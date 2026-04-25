"""Ledger storage and status contracts for Codex PMO Ledger Runner."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]

try:
    from hermes_constants import display_hermes_home, get_hermes_home
except ImportError:
    import sys

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from hermes_constants import display_hermes_home, get_hermes_home  # type: ignore

try:
    from .validator import RUNNER_VERSION, STATUS_CONTRACT_FIELDS, validate_status_summary
except ImportError:
    from validator import RUNNER_VERSION, STATUS_CONTRACT_FIELDS, validate_status_summary  # type: ignore


class _NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data: Any) -> bool:
        return True


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def runtime_ledger_dir() -> Path:
    return get_hermes_home() / "pmo" / "ledgers"


def normalize_task_id(task_id: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in task_id.strip())
    return safe or "task"


def ledger_path(ledger_dir: Path, task_id: str) -> Path:
    return ledger_dir / f"{normalize_task_id(task_id)}.yaml"


def load_ledger(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"ledger must be a YAML object: {path}")
    return data


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def save_ledger(path: Path, ledger: Mapping[str, Any]) -> None:
    data = dict(ledger)
    data["updated_at"] = now_iso()
    content = yaml.dump(data, Dumper=_NoAliasDumper, sort_keys=False, allow_unicode=True)
    atomic_write_text(path, content)


def write_json_artifact(path: Path, payload: Mapping[str, Any]) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def default_ledger(task_id: str, title: str, *, ledger_dir: Path, docs_snapshot_path: str | None = None) -> dict[str, Any]:
    timestamp = now_iso()
    path = ledger_path(ledger_dir, task_id)
    display_runtime = str(path)
    try:
        home = get_hermes_home()
        display_runtime = str(Path(display_hermes_home()) / path.relative_to(home))
    except ValueError:
        pass
    return {
        "schema_version": 1,
        "runner_version": RUNNER_VERSION,
        "task_id": task_id,
        "title": title,
        "created_at": timestamp,
        "updated_at": timestamp,
        "phase": "document_review",
        "status": "queued",
        "repo": {
            "root": ".",
            "current_branch": None,
            "base_branch": "main",
            "task_branch": None,
            "worktree": ".",
            "repo_lock_key": "hermes-agent",
            "repo_write_slot": None,
        },
        "storage": {
            "mode": "hybrid_docs_examples_runtime_state",
            "runtime_path": display_runtime,
            "docs_snapshot_path": docs_snapshot_path,
            "active_source": "runtime",
        },
        "policy": {
            "child_depth_limit": 1,
            "default_sandbox": "read-only",
            "work_sandbox": "workspace-write",
            "approval_policy": "on-request",
            "work_requires_document_review_pass": True,
            "danger_full_access_allowed": False,
            "approval_policy_never_allowed": False,
            "mailbox_as_primary_transport": False,
            "user_decisions_pause_runner": True,
        },
        "scheduler": {
            "status": "ready",
            "concurrency_limit": 1,
            "read_only_child_limit": 1,
            "work_child_limit_per_repo": 0,
            "scan_statuses": ["queued"],
            "p0_supported_task_kinds": ["document_review_smoke", "ledger_validation_smoke"],
        },
        "tasks": [
            {
                "task_id": task_id,
                "title": title,
                "phase": "document_review",
                "status": "queued",
                "next_action": "run_ledger_validation_smoke",
                "allowed_child_kind": "ledger_validation_smoke",
                "sandbox": "read-only",
            }
        ],
        "phases": {
            "brainstorm_plan": {"status": "queued", "result": None, "artifacts": []},
            "document_review": {
                "status": "queued",
                "result": None,
                "transition_guard": {"work_requires_result": "pass"},
                "artifacts": [],
            },
            "work": {"status": "queued", "blocked_by": ["document_review"], "artifacts": []},
            "review": {"status": "queued", "artifacts": []},
            "compound": {"status": "queued", "artifacts": []},
        },
        "children": [],
        "pmo_activity": [],
        "artifacts": [],
        "validation": [],
        "risks": [],
        "decisions_needed": [],
        "next_action": {
            "type": "run_ledger_validation_smoke",
            "owner": "codex_pmo",
            "status": "ready",
            "description": "Run one P0 read-only child smoke and write the result back to the ledger.",
        },
        "locks": {
            "ledger": {
                "status": "unlocked",
                "owner": None,
                "acquired_at": None,
                "heartbeat_at": None,
                "lease_ttl_seconds": 300,
            },
            "repo": {
                "status": "not_requested",
                "key": "hermes-agent",
                "owner": None,
                "acquired_at": None,
                "heartbeat_at": None,
                "lease_ttl_seconds": 900,
            },
        },
        "status_contract": {"version": 1, "required_fields": STATUS_CONTRACT_FIELDS},
        "budget": {
            "pmo_model": "codex",
            "pmo_effort": "medium",
            "children_started": 0,
            "max_child_depth": 1,
            "elapsed_seconds": None,
            "token_usage": {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None},
            "budget_warnings": [],
        },
        "audit": [
            {
                "at": timestamp,
                "actor": "codex_pmo",
                "event": "ledger_initialized",
                "details": "Created runtime PMO ledger.",
            }
        ],
    }


def append_audit(ledger: dict[str, Any], event: str, details: str, *, actor: str = "codex_pmo") -> None:
    ledger.setdefault("audit", []).append({"at": now_iso(), "actor": actor, "event": event, "details": details})


def task_result(ledger: Mapping[str, Any]) -> Any:
    phase = ledger.get("phase")
    phases = ledger.get("phases")
    if isinstance(phases, Mapping) and isinstance(phases.get(phase), Mapping):
        return phases[phase].get("result")  # type: ignore[index]
    return ledger.get("result")


def status_summary(ledger: Mapping[str, Any]) -> dict[str, Any]:
    decisions = [
        decision
        for decision in ledger.get("decisions_needed", [])
        if isinstance(decision, Mapping) and decision.get("status") == "open"
    ]
    risks = [
        risk
        for risk in ledger.get("risks", [])
        if isinstance(risk, Mapping) and risk.get("severity") == "high" and risk.get("status") not in {"closed", "mitigated"}
    ]
    validation = [item for item in ledger.get("validation", []) if isinstance(item, Mapping)]
    passed = sum(1 for item in validation if item.get("status") == "pass")
    failed = sum(1 for item in validation if item.get("status") in {"fail", "failed"})
    summary = {
        "task_id": ledger.get("task_id"),
        "title": ledger.get("title"),
        "phase": ledger.get("phase"),
        "status": ledger.get("status"),
        "result": task_result(ledger),
        "next_action": ledger.get("next_action"),
        "blocking_decisions": decisions,
        "high_risks": risks,
        "recent_children": list(ledger.get("children", []))[-5:],
        "artifacts": ledger.get("artifacts", []),
        "validation_summary": {
            "total": len(validation),
            "pass": passed,
            "failed": failed,
            "recent": validation[-5:],
        },
        "budget_summary": ledger.get("budget", {}),
        "locks": ledger.get("locks", {}),
        "audit_tail": list(ledger.get("audit", []))[-10:],
    }
    validate_status_summary(summary)
    return summary


def list_ledger_summaries(ledger_dir: Path) -> list[dict[str, Any]]:
    if not ledger_dir.exists():
        return []
    summaries = []
    for path in sorted(ledger_dir.glob("*.yaml")):
        ledger = load_ledger(path)
        recent_children = ledger.get("children", [])
        summaries.append(
            {
                "task_id": ledger.get("task_id"),
                "title": ledger.get("title"),
                "phase": ledger.get("phase"),
                "status": ledger.get("status"),
                "next_action": ledger.get("next_action"),
                "recent_child": recent_children[-1] if recent_children else None,
                "high_risks": [
                    risk
                    for risk in ledger.get("risks", [])
                    if isinstance(risk, Mapping)
                    and risk.get("severity") == "high"
                    and risk.get("status") not in {"closed", "mitigated"}
                ],
                "path": str(path),
            }
        )
    return summaries
