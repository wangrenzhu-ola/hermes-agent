"""Persistent session goals — the Ralph loop for Hermes.

A goal is a free-form user objective that stays active across turns. After
each turn completes, a small judge call asks an auxiliary model "is this
goal satisfied by the assistant's last response?". If not, Hermes feeds a
continuation prompt back into the same session and keeps working until the
goal is done, turn budget is exhausted, the user pauses/clears it, or the
user sends a new message (which takes priority and pauses the goal loop).

State is persisted in SessionDB's ``state_meta`` table keyed by
``goal:<session_id>`` so ``/resume`` picks it up.

Design notes / invariants:

- The continuation prompt is just a normal user message appended to the
  session via ``run_conversation``. No system-prompt mutation, no toolset
  swap — prompt caching stays intact.
- Judge failures are fail-OPEN: ``continue``. A broken judge must not wedge
  progress; the turn budget is the backstop.
- When a real user message arrives mid-loop it preempts the continuation
  prompt and also pauses the goal loop for that turn (we still re-judge
  after, so if the user's message happens to complete the goal the judge
  will say ``done``).
- This module has zero hard dependency on ``cli.HermesCLI`` or the gateway
  runner — both wire the same ``GoalManager`` in.

Nothing in this module touches the agent's system prompt or toolset.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Constants & defaults
# ──────────────────────────────────────────────────────────────────────

DEFAULT_MAX_TURNS = 20
DEFAULT_JUDGE_TIMEOUT = 30.0
# Judge output budget. The freeform judge returns a one-line JSON verdict, but
# reasoning models (deepseek-v4, qwq, etc.) burn tokens on hidden reasoning
# before emitting the visible JSON — and the first /goal turn's prompt is
# larger than later turns, which pushes total reply length past tight caps.
# 200 tokens (the original default) reliably truncated the JSON on reasoning
# models, leaving '{"done": true, "reason": "The agent successfully' and
# triggering the auto-pause. 4096 covers reasoning + verdict on every model
# we've live-tested; override via auxiliary.goal_judge.max_tokens for
# specifically constrained setups.
DEFAULT_JUDGE_MAX_TOKENS = 4096
# Cap how much of the last response + recent messages we send to the judge.
_JUDGE_RESPONSE_SNIPPET_CHARS = 4000
# After this many consecutive judge *parse* failures (empty output / non-JSON),
# the loop auto-pauses and points the user at the goal_judge config. API /
# transport errors do NOT count toward this — those are transient. This guards
# against small models (e.g. deepseek-v4-flash) that cannot follow the strict
# JSON reply contract; without it the loop runs until the turn budget is
# exhausted with every reply shaped like `judge returned empty response` or
# `judge reply was not JSON`.
DEFAULT_MAX_CONSECUTIVE_PARSE_FAILURES = 3


CONTINUATION_PROMPT_TEMPLATE = (
    "[Continuing toward your standing goal]\n"
    "Goal: {goal}\n\n"
    "Continue working toward this goal. Take the next concrete step. "
    "If you believe the goal is complete, state so explicitly and stop. "
    "If you are blocked and need input from the user, say so clearly and stop."
)

# Used when the user has added one or more /subgoal criteria. Surfaced
# to the agent verbatim so it sees what to target on the next turn,
# and surfaced to the judge so the verdict considers them too.
CONTINUATION_PROMPT_WITH_SUBGOALS_TEMPLATE = (
    "[Continuing toward your standing goal]\n"
    "Goal: {goal}\n\n"
    "Additional criteria the user added mid-loop:\n"
    "{subgoals_block}\n\n"
    "Continue working toward the goal AND all additional criteria. Take "
    "the next concrete step. If you believe the goal and every "
    "additional criterion are complete, state so explicitly and stop. "
    "If you are blocked and need input from the user, say so clearly "
    "and stop."
)

# GCW-bound goals need stricter continuation than a normal free-form goal:
# the next turn must re-read GCW's machine state before doing more work, and
# must not let the /goal loop invent completion from chat-only progress.
GCW_CONTINUATION_EVIDENCE_BLOCK = (
    "\n\nGCW evidence-aware supervisor requirements:\n"
    "- Treat GCW status/ledger/phase artifacts as the source of truth.\n"
    "- Before continuing or declaring progress, read back the canonical issue "
    "URL, status.json, ledger-updates.jsonl, phase report/handoff paths, "
    "worker/process state, validator/closeout evidence, and missing gates.\n"
    "- Only GCW terminal state `done` plus required evidence can satisfy the "
    "goal successfully. `blocked`, `needs_user`, or `approval_required` may "
    "stop only as a truthful non-success handoff with owner input/risk "
    "acceptance named. `partial`, stale workers, missing artifacts, PR-only "
    "evidence, or missing validator/closeout gates must continue.\n"
    "- /subgoal criteria are judge-visible reminders/candidate gates unless a "
    "later GCW artifact explicitly promotes them into validator/AC gates."
)


JUDGE_SYSTEM_PROMPT = (
    "You are a strict judge evaluating whether an autonomous agent has "
    "achieved a user's stated goal. You receive the goal text and the "
    "agent's most recent response. Your only job is to decide whether "
    "the goal is fully satisfied based on that response.\n\n"
    "A goal is DONE only when:\n"
    "- The response explicitly confirms the goal was completed, OR\n"
    "- The response clearly shows the final deliverable was produced, OR\n"
    "- The response explains the goal is unachievable / blocked / needs "
    "user input (treat this as DONE with reason describing the block).\n\n"
    "Otherwise the goal is NOT done — CONTINUE.\n\n"
    "Reply ONLY with a single JSON object on one line:\n"
    '{\"done\": <true|false>, \"reason\": \"<one-sentence rationale>\"}'
)


JUDGE_USER_PROMPT_TEMPLATE = (
    "Goal:\n{goal}\n\n"
    "Agent's most recent response:\n{response}\n\n"
    "Is the goal satisfied?"
)

# Used when the user has added /subgoal criteria. The judge must
# evaluate ALL of them being met, not just the original goal.
JUDGE_USER_PROMPT_WITH_SUBGOALS_TEMPLATE = (
    "Goal:\n{goal}\n\n"
    "Additional criteria the user added mid-loop (all must also be "
    "satisfied for the goal to be DONE):\n{subgoals_block}\n\n"
    "Agent's most recent response:\n{response}\n\n"
    "Decision: For each numbered criterion above, find concrete "
    "evidence in the agent's response that the criterion is "
    "satisfied. Do not accept generic phrases like 'all requirements "
    "met' or 'implying it was done' — require specific evidence (a "
    "file contents excerpt, an output line, a command result). If "
    "ANY criterion lacks specific evidence in the response, the goal "
    "is NOT done — return CONTINUE.\n\n"
    "Is the goal AND every additional criterion satisfied?"
)

GCW_JUDGE_EVIDENCE_BLOCK = (
    "\n\nGCW-bound goal rule: If this goal involves GCW, /gcw, GaleHarness, "
    "status.json, ledger-updates.jsonl, phase reports/handoffs, or GitHub "
    "Issue closeout, require a concrete evidence summary in the agent's "
    "response. The summary must identify the issue/run, GCW status/phase, "
    "ledger/status readback, worker/process or terminal artifact evidence, "
    "validator/closeout state, missing gates, terminal candidate, and evidence "
    "links/paths. Mark DONE as successful only when the response shows GCW "
    "terminal state `done` and required evidence. Also mark DONE for a "
    "truthful terminal non-success handoff when the response explicitly reports "
    "`blocked`, `needs_user`, or `approval_required` and identifies the owner "
    "input/risk acceptance required. A `partial` state may stop only when the "
    "response cites GCW artifact evidence that defines it as an owner-facing "
    "final handoff; otherwise partial must continue. The reason for any "
    "non-success stop must say it is blocked/needs user/partial handoff, not "
    "completed. If it reports ordinary `partial`, stale worker, missing "
    "report/handoff, PR-only, issue-only, local-only evidence, or any missing "
    "validator/closeout gate, return CONTINUE."
)


# ──────────────────────────────────────────────────────────────────────
# Dataclass
# ──────────────────────────────────────────────────────────────────────


@dataclass
class GoalState:
    """Serializable goal state stored per session."""

    goal: str
    status: str = "active"          # active | paused | done | cleared
    turns_used: int = 0
    max_turns: int = DEFAULT_MAX_TURNS
    created_at: float = 0.0
    last_turn_at: float = 0.0
    last_verdict: Optional[str] = None        # "done" | "continue" | "skipped"
    last_reason: Optional[str] = None
    paused_reason: Optional[str] = None       # why we auto-paused (budget, etc.)
    consecutive_parse_failures: int = 0       # judge-output parse failures in a row
    # User-added criteria appended mid-loop via the /subgoal command.
    # When non-empty the judge prompt and continuation prompt both
    # include them so the agent works toward them and the judge factors
    # them into the verdict. Backwards-compatible: defaults to empty so
    # old state_meta rows load unchanged.
    subgoals: List[str] = field(default_factory=list)
    # Machine-readable GCW supervisor binding. Empty for ordinary goals.
    # When present, it binds /goal continuation to a canonical issue/run
    # and records evidence/gate state without making /goal the closeout authority.
    gcw_binding: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "GoalState":
        data = json.loads(raw)
        raw_subgoals = data.get("subgoals") or []
        subgoals: List[str] = []
        if isinstance(raw_subgoals, list):
            subgoals = [str(s).strip() for s in raw_subgoals if str(s).strip()]
        raw_binding = data.get("gcw_binding") or {}
        gcw_binding: Dict[str, Any] = raw_binding if isinstance(raw_binding, dict) else {}
        return cls(
            goal=data.get("goal", ""),
            status=data.get("status", "active"),
            turns_used=int(data.get("turns_used", 0) or 0),
            max_turns=int(data.get("max_turns", DEFAULT_MAX_TURNS) or DEFAULT_MAX_TURNS),
            created_at=float(data.get("created_at", 0.0) or 0.0),
            last_turn_at=float(data.get("last_turn_at", 0.0) or 0.0),
            last_verdict=data.get("last_verdict"),
            last_reason=data.get("last_reason"),
            paused_reason=data.get("paused_reason"),
            consecutive_parse_failures=int(data.get("consecutive_parse_failures", 0) or 0),
            subgoals=subgoals,
            gcw_binding=gcw_binding,
        )

    # --- subgoals helpers -------------------------------------------------

    def render_subgoals_block(self) -> str:
        """Render the subgoals as a numbered ``- N. text`` block. Empty
        when no subgoals exist."""
        if not self.subgoals:
            return ""
        return "\n".join(f"- {i}. {text}" for i, text in enumerate(self.subgoals, start=1))


# ──────────────────────────────────────────────────────────────────────
# Persistence (SessionDB state_meta)
# ──────────────────────────────────────────────────────────────────────


def _meta_key(session_id: str) -> str:
    return f"goal:{session_id}"


_DB_CACHE: Dict[str, Any] = {}


def _get_session_db() -> Optional[Any]:
    """Return a SessionDB instance for the current HERMES_HOME.

    SessionDB has no built-in singleton, but opening a new connection per
    /goal call would thrash the file. We cache one instance per
    ``hermes_home`` path so profile switches still pick up the right DB.
    Defensive against import/instantiation failures so tests and
    non-standard launchers can still use the GoalManager.
    """
    try:
        from hermes_constants import get_hermes_home
        from hermes_state import SessionDB

        home = str(get_hermes_home())
    except Exception as exc:  # pragma: no cover
        logger.debug("GoalManager: SessionDB bootstrap failed (%s)", exc)
        return None

    cached = _DB_CACHE.get(home)
    if cached is not None:
        return cached
    try:
        db = SessionDB()
    except Exception as exc:  # pragma: no cover
        logger.debug("GoalManager: SessionDB() raised (%s)", exc)
        return None
    _DB_CACHE[home] = db
    return db


def load_goal(session_id: str) -> Optional[GoalState]:
    """Load the goal for a session, or None if none exists."""
    if not session_id:
        return None
    db = _get_session_db()
    if db is None:
        return None
    try:
        raw = db.get_meta(_meta_key(session_id))
    except Exception as exc:
        logger.debug("GoalManager: get_meta failed: %s", exc)
        return None
    if not raw:
        return None
    try:
        return GoalState.from_json(raw)
    except Exception as exc:
        logger.warning("GoalManager: could not parse stored goal for %s: %s", session_id, exc)
        return None


def save_goal(session_id: str, state: GoalState) -> None:
    """Persist a goal to SessionDB. No-op if DB unavailable."""
    if not session_id:
        return
    db = _get_session_db()
    if db is None:
        return
    try:
        db.set_meta(_meta_key(session_id), state.to_json())
    except Exception as exc:
        logger.debug("GoalManager: set_meta failed: %s", exc)


def clear_goal(session_id: str) -> None:
    """Mark a goal cleared in the DB (preserved for audit, status=cleared)."""
    state = load_goal(session_id)
    if state is None:
        return
    state.status = "cleared"
    save_goal(session_id, state)


# ──────────────────────────────────────────────────────────────────────
# Judge
# ──────────────────────────────────────────────────────────────────────


def _truncate(text: str, limit: int) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "… [truncated]"


_GCW_GOAL_RE = re.compile(
    r"(\bgcw\b|/gcw|galeharness|status\.json|ledger-updates\.jsonl|"
    r"phase report|handoff|completion guard|github\.com/.+/issues/\d+)",
    re.IGNORECASE,
)

_ISSUE_URL_RE = re.compile(
    r"https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/issues/(?P<number>\d+)",
    re.IGNORECASE,
)


def _extract_issue_url(text: str) -> Optional[str]:
    match = _ISSUE_URL_RE.search(text or "")
    return match.group(0) if match else None


def _issue_ref(issue_url: str) -> str:
    match = _ISSUE_URL_RE.search(issue_url or "")
    return f"#{match.group('number')}" if match else issue_url


def _source_repo_from_issue_url(issue_url: str) -> str:
    match = _ISSUE_URL_RE.search(issue_url or "")
    if not match:
        return ""
    return f"{match.group('owner')}/{match.group('repo')}"


def _new_gcw_binding(
    *,
    issue_url: str,
    goal_id: str,
    run_id: Optional[str] = None,
    phase: Optional[str] = None,
    source_repo: Optional[str] = None,
) -> Dict[str, Any]:
    issue_url = (issue_url or "").strip()
    if not _ISSUE_URL_RE.search(issue_url):
        raise ValueError("GCW supervisor requires a canonical GitHub issue URL")
    return {
        "schema_version": "gcw-goal-binding.v1",
        "issue_url": issue_url,
        "run_id": (run_id or "").strip(),
        "goal_id": goal_id,
        "phase": (phase or "readback").strip(),
        "source_repo": (source_repo or _source_repo_from_issue_url(issue_url)).strip(),
        "terminal_candidate": "continue",
        "evidence_refs": [],
        "missing_gates": ["status_readback", "ledger_readback", "validator_closeout"],
        "formal_gates": [],
        "resume_readback_required": True,
    }


def _binding_summary(binding: Dict[str, Any]) -> str:
    if not binding:
        return ""
    missing = binding.get("missing_gates") or []
    formal_gates = binding.get("formal_gates") or []
    return (
        "\n\nGCW supervisor binding:\n"
        f"- issue_url: {binding.get('issue_url') or ''}\n"
        f"- run_id: {binding.get('run_id') or '(unknown — read back before continuing)'}\n"
        f"- goal_id: {binding.get('goal_id') or ''}\n"
        f"- source_repo: {binding.get('source_repo') or ''}\n"
        f"- current_phase: {binding.get('phase') or 'readback'}\n"
        f"- terminal_candidate: {binding.get('terminal_candidate') or 'continue'}\n"
        f"- missing_gates: {', '.join(str(x) for x in missing) if missing else '(none recorded)'}\n"
        f"- formal_gates: {len(formal_gates)} promoted gate(s) with owner/issue/ledger/readback evidence\n"
        "First action after resume: read back Issue, status.json, "
        "ledger-updates.jsonl, phase report/handoff, worker/process state, "
        "validator/completion guard/closeout evidence, and missing gates "
        "before launching new work or reporting progress."
    )


def _is_gcw_bound_goal(goal: str, subgoals: Optional[List[str]] = None) -> bool:
    """Heuristic: should /goal apply the GCW evidence-aware contract?"""
    text = "\n".join([goal or "", *[s or "" for s in (subgoals or [])]])
    return bool(_GCW_GOAL_RE.search(text))


_JSON_OBJECT_RE = re.compile(r"\{.*?\}", re.DOTALL)


def _goal_judge_max_tokens() -> int:
    """Resolve auxiliary.goal_judge.max_tokens, falling back to the default.

    ``load_config()`` is cached on the config file's (mtime, size), so calling
    this once per judge turn is cheap. A non-positive or non-int value falls
    back to the default rather than crashing the goal loop.
    """
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
        value = (
            (cfg.get("auxiliary") or {})
            .get("goal_judge", {})
            .get("max_tokens", DEFAULT_JUDGE_MAX_TOKENS)
        )
        value = int(value)
        if value > 0:
            return value
    except Exception:
        pass
    return DEFAULT_JUDGE_MAX_TOKENS


def _parse_judge_response(raw: str) -> Tuple[bool, str, bool]:
    """Parse the judge's reply. Fail-open to ``(False, "<reason>", parse_failed)``.

    Returns ``(done, reason, parse_failed)``. ``parse_failed`` is True when the
    judge returned output that couldn't be interpreted as the expected JSON
    verdict (empty body, prose, malformed JSON). Callers use that flag to
    auto-pause after N consecutive parse failures so a weak judge model
    doesn't silently burn the turn budget.
    """
    if not raw:
        return False, "judge returned empty response", True

    text = raw.strip()

    # Strip markdown code fences the model may wrap JSON in.
    if text.startswith("```"):
        text = text.strip("`")
        # Peel off leading json/JSON/etc tag
        nl = text.find("\n")
        if nl != -1:
            text = text[nl + 1:]

    # First try: parse the whole blob.
    data: Optional[Dict[str, Any]] = None
    try:
        data = json.loads(text)
    except Exception:
        # Second try: pull the first JSON object out.
        match = _JSON_OBJECT_RE.search(text)
        if match:
            try:
                data = json.loads(match.group(0))
            except Exception:
                data = None

    if not isinstance(data, dict):
        return False, f"judge reply was not JSON: {_truncate(raw, 200)!r}", True

    done_val = data.get("done")
    if isinstance(done_val, str):
        done = done_val.strip().lower() in {"true", "yes", "1", "done"}
    else:
        done = bool(done_val)
    reason = str(data.get("reason") or "").strip()
    if not reason:
        reason = "no reason provided"
    return done, reason, False


def judge_goal(
    goal: str,
    last_response: str,
    *,
    timeout: float = DEFAULT_JUDGE_TIMEOUT,
    subgoals: Optional[List[str]] = None,
) -> Tuple[str, str, bool]:
    """Ask the auxiliary model whether the goal is satisfied.

    Returns ``(verdict, reason, parse_failed)`` where verdict is ``"done"``,
    ``"continue"``, or ``"skipped"`` (when the judge couldn't be reached).

    ``parse_failed`` is True only when the judge call succeeded but its output
    was unusable (empty or non-JSON). API/transport errors return False — they
    are transient and should fail-open silently. Callers use this flag to
    auto-pause after N consecutive parse failures (see
    ``DEFAULT_MAX_CONSECUTIVE_PARSE_FAILURES``).

    ``subgoals`` is an optional list of user-added criteria (from
    ``/subgoal``) that the judge must also factor into its DONE/CONTINUE
    decision. When non-empty the prompt switches to the with-subgoals
    template; otherwise behavior is identical to the original judge.

    This is deliberately fail-open: any error returns ``("continue", "...", False)``
    so a broken judge doesn't wedge progress — the turn budget and the
    consecutive-parse-failures auto-pause are the backstops.
    """
    if not goal.strip():
        return "skipped", "empty goal", False
    if not last_response.strip():
        # No substantive reply this turn — almost certainly not done yet.
        return "continue", "empty response (nothing to evaluate)", False

    try:
        from agent.auxiliary_client import get_auxiliary_extra_body, get_text_auxiliary_client
    except Exception as exc:
        logger.debug("goal judge: auxiliary client import failed: %s", exc)
        return "continue", "auxiliary client unavailable", False

    try:
        client, model = get_text_auxiliary_client("goal_judge")
    except Exception as exc:
        logger.debug("goal judge: get_text_auxiliary_client failed: %s", exc)
        return "continue", "auxiliary client unavailable", False

    if client is None or not model:
        return "continue", "no auxiliary client configured", False

    # Build the prompt — pick the with-subgoals variant when applicable.
    clean_subgoals = [s.strip() for s in (subgoals or []) if s and s.strip()]
    if clean_subgoals:
        subgoals_block = "\n".join(
            f"- {i}. {text}" for i, text in enumerate(clean_subgoals, start=1)
        )
        prompt = JUDGE_USER_PROMPT_WITH_SUBGOALS_TEMPLATE.format(
            goal=_truncate(goal, 2000),
            subgoals_block=_truncate(subgoals_block, 2000),
            response=_truncate(last_response, _JUDGE_RESPONSE_SNIPPET_CHARS),
        )
    else:
        prompt = JUDGE_USER_PROMPT_TEMPLATE.format(
            goal=_truncate(goal, 2000),
            response=_truncate(last_response, _JUDGE_RESPONSE_SNIPPET_CHARS),
        )
    if _is_gcw_bound_goal(goal, clean_subgoals):
        prompt += GCW_JUDGE_EVIDENCE_BLOCK

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=_goal_judge_max_tokens(),
            timeout=timeout,
            extra_body=get_auxiliary_extra_body() or None,
        )
    except Exception as exc:
        logger.info("goal judge: API call failed (%s) — falling through to continue", exc)
        return "continue", f"judge error: {type(exc).__name__}", False

    try:
        raw = resp.choices[0].message.content or ""
    except Exception:
        raw = ""

    done, reason, parse_failed = _parse_judge_response(raw)
    verdict = "done" if done else "continue"
    logger.info("goal judge: verdict=%s reason=%s", verdict, _truncate(reason, 120))
    return verdict, reason, parse_failed


# ──────────────────────────────────────────────────────────────────────
# GoalManager — the orchestration surface CLI + gateway talk to
# ──────────────────────────────────────────────────────────────────────


class GoalManager:
    """Per-session goal state + continuation decisions.

    The CLI and gateway each hold one ``GoalManager`` per live session.

    Methods:

    - ``set(goal)`` — start a new standing goal.
    - ``clear()`` — remove the active goal.
    - ``pause()`` / ``resume()`` — explicit user controls.
    - ``status()`` — printable one-liner.
    - ``evaluate_after_turn(last_response)`` — call the judge, update state,
      and return a decision dict the caller uses to drive the next turn.
    - ``next_continuation_prompt()`` — the canonical user-role message to
      feed back into ``run_conversation``.
    """

    def __init__(self, session_id: str, *, default_max_turns: int = DEFAULT_MAX_TURNS):
        self.session_id = session_id
        self.default_max_turns = int(default_max_turns or DEFAULT_MAX_TURNS)
        self._state: Optional[GoalState] = load_goal(session_id)

    # --- introspection ------------------------------------------------

    @property
    def state(self) -> Optional[GoalState]:
        return self._state

    def is_active(self) -> bool:
        return self._state is not None and self._state.status == "active"

    def has_goal(self) -> bool:
        return self._state is not None and self._state.status in {"active", "paused"}

    def status_line(self) -> str:
        s = self._state
        if s is None or s.status in {"cleared",}:
            return "No active goal. Set one with /goal <text>."
        turns = f"{s.turns_used}/{s.max_turns} turns"
        sub = f", {len(s.subgoals)} subgoal{'s' if len(s.subgoals) != 1 else ''}" if s.subgoals else ""
        gcw = ""
        if s.gcw_binding:
            ref = _issue_ref(str(s.gcw_binding.get("issue_url") or ""))
            phase = s.gcw_binding.get("phase") or "readback"
            terminal = s.gcw_binding.get("terminal_candidate") or "continue"
            gcw = f", GCW {ref} phase={phase} terminal={terminal}"
        if s.status == "active":
            return f"⊙ Goal (active, {turns}{sub}{gcw}): {s.goal}"
        if s.status == "paused":
            extra = f" — {s.paused_reason}" if s.paused_reason else ""
            return f"⏸ Goal (paused, {turns}{sub}{gcw}{extra}): {s.goal}"
        if s.status == "done":
            return f"✓ Goal done ({turns}{sub}{gcw}): {s.goal}"
        return f"Goal ({s.status}, {turns}{sub}): {s.goal}"

    # --- mutation -----------------------------------------------------

    def set(self, goal: str, *, max_turns: Optional[int] = None) -> GoalState:
        goal = (goal or "").strip()
        if not goal:
            raise ValueError("goal text is empty")
        state = GoalState(
            goal=goal,
            status="active",
            turns_used=0,
            max_turns=int(max_turns) if max_turns else self.default_max_turns,
            created_at=time.time(),
            last_turn_at=0.0,
        )
        self._state = state
        save_goal(self.session_id, state)
        return state

    def set_gcw_supervisor(
        self,
        *,
        issue_url: Optional[str] = None,
        goal: Optional[str] = None,
        run_id: Optional[str] = None,
        phase: Optional[str] = None,
        source_repo: Optional[str] = None,
        max_turns: Optional[int] = None,
    ) -> GoalState:
        """Start an issue-bound GCW supervisor goal.

        This is the machine-readable bridge for GCW integrations: it keeps
        ordinary /goal free-form, while GCW work is explicitly bound to a
        canonical Issue/run and always resumes through a status/ledger
        readback turn before executing more work.
        """
        issue_url = (issue_url or _extract_issue_url(goal or "") or "").strip()
        if not issue_url:
            raise ValueError("GCW supervisor requires a canonical GitHub issue URL")
        if not goal:
            goal = f"Continue GCW supervisor for {issue_url} until terminal closeout evidence is reached"
        state = self.set(goal, max_turns=max_turns)
        state.gcw_binding = _new_gcw_binding(
            issue_url=issue_url,
            goal_id=self.session_id,
            run_id=run_id,
            phase=phase,
            source_repo=source_repo,
        )
        save_goal(self.session_id, state)
        return state

    def bind_gcw_supervisor(
        self,
        *,
        issue_url: str,
        run_id: Optional[str] = None,
        phase: Optional[str] = None,
        source_repo: Optional[str] = None,
    ) -> GoalState:
        """Bind an existing active/paused goal to a GCW issue/run."""
        if not self._state or not self.has_goal():
            raise RuntimeError("no active goal")
        self._state.gcw_binding = _new_gcw_binding(
            issue_url=issue_url,
            goal_id=self.session_id,
            run_id=run_id,
            phase=phase,
            source_repo=source_repo,
        )
        save_goal(self.session_id, self._state)
        return self._state

    def update_gcw_binding(self, **updates: Any) -> Optional[GoalState]:
        """Update machine-readable GCW readback fields without clearing history."""
        if not self._state or not self._state.gcw_binding:
            return None
        allowed = {
            "run_id", "phase", "terminal_candidate", "evidence_refs",
            "missing_gates", "resume_readback_required", "source_repo",
        }
        for key, value in updates.items():
            if key in allowed:
                self._state.gcw_binding[key] = value
        save_goal(self.session_id, self._state)
        return self._state

    def pause(self, reason: str = "user-paused") -> Optional[GoalState]:
        if not self._state:
            return None
        self._state.status = "paused"
        self._state.paused_reason = reason
        save_goal(self.session_id, self._state)
        return self._state

    def resume(self, *, reset_budget: bool = True) -> Optional[GoalState]:
        if not self._state:
            return None
        self._state.status = "active"
        self._state.paused_reason = None
        if reset_budget:
            self._state.turns_used = 0
        if self._state.gcw_binding:
            self._state.gcw_binding["resume_readback_required"] = True
        save_goal(self.session_id, self._state)
        return self._state

    def clear(self) -> None:
        if self._state is None:
            return
        self._state.status = "cleared"
        save_goal(self.session_id, self._state)
        self._state = None

    def mark_done(self, reason: str) -> None:
        if not self._state:
            return
        self._state.status = "done"
        self._state.last_verdict = "done"
        self._state.last_reason = reason
        save_goal(self.session_id, self._state)

    # --- /subgoal user controls ---------------------------------------

    def add_subgoal(self, text: str) -> str:
        """Append a user-added criterion to the active goal. Requires
        ``has_goal()``; raises ``RuntimeError`` otherwise.

        Returns the cleaned text so the caller can show it back to the user.
        """
        if self._state is None or not self.has_goal():
            raise RuntimeError("no active goal")
        text = (text or "").strip()
        if not text:
            raise ValueError("subgoal text is empty")
        self._state.subgoals.append(text)
        if self._state.gcw_binding:
            self._state.gcw_binding.setdefault("formal_gates", [])
        save_goal(self.session_id, self._state)
        return text

    def promote_subgoal_to_gcw_gate(
        self,
        index_1based: int,
        *,
        owner_evidence: Optional[str] = None,
        issue_comment: Optional[str] = None,
        ledger_event: Optional[str] = None,
        readback: Optional[str] = None,
    ) -> Dict[str, str]:
        """Explicitly promote a /subgoal into a formal GCW gate.

        Promotion is intentionally strict: all evidence channels must be
        present so a chat-only /subgoal cannot silently mutate validator/AC
        gates. The returned dict is stored under gcw_binding.formal_gates for
        GCW PMO/validator readback.
        """
        if self._state is None or not self.has_goal():
            raise RuntimeError("no active goal")
        if not self._state.gcw_binding:
            raise RuntimeError("goal is not GCW-bound")
        idx = int(index_1based) - 1
        if idx < 0 or idx >= len(self._state.subgoals):
            raise IndexError(f"index out of range (1..{len(self._state.subgoals)})")
        required = {
            "owner_evidence": owner_evidence,
            "issue_comment": issue_comment,
            "ledger_event": ledger_event,
            "readback": readback,
        }
        missing = [name for name, value in required.items() if not str(value or "").strip()]
        if missing:
            raise ValueError("GCW gate promotion requires " + ", ".join(missing))
        gate = {
            "subgoal_index": str(index_1based),
            "text": self._state.subgoals[idx],
            "owner_evidence": str(owner_evidence).strip(),
            "issue_comment": str(issue_comment).strip(),
            "ledger_event": str(ledger_event).strip(),
            "readback": str(readback).strip(),
        }
        self._state.gcw_binding.setdefault("formal_gates", []).append(gate)
        save_goal(self.session_id, self._state)
        return gate

    def remove_subgoal(self, index_1based: int) -> str:
        """Remove a subgoal by 1-based index. Returns the removed text."""
        if self._state is None or not self.has_goal():
            raise RuntimeError("no active goal")
        idx = int(index_1based) - 1
        if idx < 0 or idx >= len(self._state.subgoals):
            raise IndexError(
                f"index out of range (1..{len(self._state.subgoals)})"
            )
        removed = self._state.subgoals.pop(idx)
        save_goal(self.session_id, self._state)
        return removed

    def clear_subgoals(self) -> int:
        """Wipe all subgoals. Returns the previous count."""
        if self._state is None or not self.has_goal():
            raise RuntimeError("no active goal")
        prev = len(self._state.subgoals)
        self._state.subgoals = []
        save_goal(self.session_id, self._state)
        return prev

    def render_subgoals(self) -> str:
        """Public helper for the /subgoal slash command."""
        if self._state is None:
            return "(no active goal)"
        if not self._state.subgoals:
            return "(no subgoals — use /subgoal <text> to add criteria)"
        return self._state.render_subgoals_block()

    # --- the main entry point called after every turn -----------------

    def evaluate_after_turn(
        self,
        last_response: str,
        *,
        user_initiated: bool = True,
    ) -> Dict[str, Any]:
        """Run the judge and update state. Return a decision dict.

        ``user_initiated`` distinguishes a real user prompt (True) from a
        continuation prompt we fed ourselves (False). Both increment
        ``turns_used`` because both consume model budget.

        Decision keys:
          - ``status``: current goal status after update
          - ``should_continue``: bool — caller should fire another turn
          - ``continuation_prompt``: str or None
          - ``verdict``: "done" | "continue" | "skipped" | "inactive"
          - ``reason``: str
          - ``message``: user-visible one-liner to print/send
        """
        state = self._state
        if state is None or state.status != "active":
            return {
                "status": state.status if state else None,
                "should_continue": False,
                "continuation_prompt": None,
                "verdict": "inactive",
                "reason": "no active goal",
                "message": "",
            }

        # Count the turn that just finished.
        state.turns_used += 1
        state.last_turn_at = time.time()

        verdict, reason, parse_failed = judge_goal(
            state.goal, last_response, subgoals=state.subgoals or None
        )
        state.last_verdict = verdict
        state.last_reason = reason

        # Track consecutive judge parse failures. Reset on any usable reply,
        # including API / transport errors (parse_failed=False) so a flaky
        # network doesn't trip the auto-pause meant for bad judge models.
        if parse_failed:
            state.consecutive_parse_failures += 1
        else:
            state.consecutive_parse_failures = 0

        if verdict == "done":
            state.status = "done"
            save_goal(self.session_id, state)
            return {
                "status": "done",
                "should_continue": False,
                "continuation_prompt": None,
                "verdict": "done",
                "reason": reason,
                "message": f"✓ Goal achieved: {reason}",
            }

        # Auto-pause when the judge model can't produce the expected JSON
        # verdict N turns in a row. Points the user at the goal_judge config
        # so they can route this side task to a model that follows the
        # contract (e.g. google/gemini-3-flash-preview). Without this guard,
        # weak judge models burn the entire turn budget returning prose or
        # empty strings.
        if state.consecutive_parse_failures >= DEFAULT_MAX_CONSECUTIVE_PARSE_FAILURES:
            state.status = "paused"
            state.paused_reason = (
                f"judge model returned unparseable output {state.consecutive_parse_failures} turns in a row"
            )
            save_goal(self.session_id, state)
            return {
                "status": "paused",
                "should_continue": False,
                "continuation_prompt": None,
                "verdict": "continue",
                "reason": reason,
                "message": (
                    f"⏸ Goal paused — the judge model ({state.consecutive_parse_failures} turns) "
                    "isn't returning the required JSON verdict. Route the judge to a stricter "
                    "model in ~/.hermes/config.yaml:\n"
                    "  auxiliary:\n"
                    "    goal_judge:\n"
                    "      provider: openrouter\n"
                    "      model: google/gemini-3-flash-preview\n"
                    "Then /goal resume to continue."
                ),
            }

        if state.turns_used >= state.max_turns:
            state.status = "paused"
            state.paused_reason = f"turn budget exhausted ({state.turns_used}/{state.max_turns})"
            save_goal(self.session_id, state)
            return {
                "status": "paused",
                "should_continue": False,
                "continuation_prompt": None,
                "verdict": "continue",
                "reason": reason,
                "message": (
                    f"⏸ Goal paused — {state.turns_used}/{state.max_turns} turns used. "
                    "Use /goal resume to keep going, or /goal clear to stop."
                ),
            }

        save_goal(self.session_id, state)
        return {
            "status": "active",
            "should_continue": True,
            "continuation_prompt": self.next_continuation_prompt(),
            "verdict": "continue",
            "reason": reason,
            "message": (
                f"↻ Continuing toward goal ({state.turns_used}/{state.max_turns}): {reason}"
            ),
        }

    def next_continuation_prompt(self) -> Optional[str]:
        if not self._state or self._state.status != "active":
            return None
        if self._state.subgoals:
            prompt = CONTINUATION_PROMPT_WITH_SUBGOALS_TEMPLATE.format(
                goal=self._state.goal,
                subgoals_block=self._state.render_subgoals_block(),
            )
        else:
            prompt = CONTINUATION_PROMPT_TEMPLATE.format(goal=self._state.goal)
        if self._state.gcw_binding:
            if self._state.subgoals:
                prompt += (
                    "\n\nCurrent /subgoal items are judge-visible GCW candidate gates "
                    "and PMO reminders, not yet formal validator gates unless "
                    "listed in gcw_binding.formal_gates. Explicit promotion "
                    "requires owner evidence, issue comment, ledger event, and readback."
                )
            prompt += _binding_summary(self._state.gcw_binding)
            prompt += GCW_CONTINUATION_EVIDENCE_BLOCK
        elif _is_gcw_bound_goal(self._state.goal, self._state.subgoals):
            prompt += GCW_CONTINUATION_EVIDENCE_BLOCK
        return prompt


__all__ = [
    "GoalState",
    "GoalManager",
    "CONTINUATION_PROMPT_TEMPLATE",
    "CONTINUATION_PROMPT_WITH_SUBGOALS_TEMPLATE",
    "JUDGE_USER_PROMPT_TEMPLATE",
    "JUDGE_USER_PROMPT_WITH_SUBGOALS_TEMPLATE",
    "GCW_CONTINUATION_EVIDENCE_BLOCK",
    "GCW_JUDGE_EVIDENCE_BLOCK",
    "DEFAULT_MAX_TURNS",
    "load_goal",
    "save_goal",
    "clear_goal",
    "judge_goal",
]
