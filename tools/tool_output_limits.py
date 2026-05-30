"""Configurable tool-output truncation limits.

Ported from anomalyco/opencode PR #23770 (``feat(truncate): allow
configuring tool output truncation limits``).

OpenCode hardcoded ``MAX_LINES = 2000`` and ``MAX_BYTES = 50 * 1024``
as tool-output truncation thresholds. Hermes-agent had the same
hardcoded constants in two places:

* ``tools/terminal_tool.py`` — ``MAX_OUTPUT_CHARS = 50000`` (terminal
  stdout/stderr cap)
* ``tools/file_operations.py`` — ``MAX_LINES = 2000`` /
  ``MAX_LINE_LENGTH = 2000`` (read_file pagination cap + per-line cap)

This module centralises those values behind a single config section
(``tool_output`` in ``config.yaml``) so power users can tune them
without patching the source. The existing hardcoded numbers remain as
defaults, so behaviour is unchanged when the config key is absent.

Example ``config.yaml``::

    tool_output:
      max_bytes: 100000        # terminal output cap (chars)
      max_lines: 5000          # read_file pagination + truncation cap
      max_line_length: 2000    # per-line length cap before '... [truncated]'

The limits reader is defensive: any error (missing config file, invalid
value type, etc.) falls back to the built-in defaults so tools never
fail because of a malformed config.
"""

from __future__ import annotations

import re
from typing import Any, Dict

# Hardcoded defaults — these match the pre-existing values, so adding
# this module is behaviour-preserving for users who don't set
# ``tool_output`` in config.yaml.
DEFAULT_MAX_BYTES = 50_000       # terminal_tool.MAX_OUTPUT_CHARS
DEFAULT_MAX_LINES = 2000         # file_operations.MAX_LINES
DEFAULT_MAX_LINE_LENGTH = 2000   # file_operations.MAX_LINE_LENGTH
DEFAULT_CONTEXT_SAFE_MAX_CHARS = 12_000
DEFAULT_ARGV_REDACTION_LIMIT = 320

_PROMPT_ARG_RE = re.compile(
    r"(?P<cmd>\b(?:claude|codex)\b(?:[^\n]*?\s-(?:p|-prompt)(?:=|\s+)))"
    r"(?P<prompt>[^\n]*)",
    re.IGNORECASE,
)


def _coerce_positive_int(value: Any, default: int) -> int:
    """Return ``value`` as a positive int, or ``default`` on any issue."""
    try:
        iv = int(value)
    except (TypeError, ValueError):
        return default
    if iv <= 0:
        return default
    return iv


def get_tool_output_limits() -> Dict[str, int]:
    """Return resolved tool-output limits, reading ``tool_output`` from config.

    Keys: ``max_bytes``, ``max_lines``, ``max_line_length``. Missing or
    invalid entries fall through to the ``DEFAULT_*`` constants. This
    function NEVER raises.
    """
    try:
        from hermes_cli.config import load_config
        cfg = load_config() or {}
        section = cfg.get("tool_output") if isinstance(cfg, dict) else None
        if not isinstance(section, dict):
            section = {}
    except Exception:
        section = {}

    return {
        "max_bytes": _coerce_positive_int(section.get("max_bytes"), DEFAULT_MAX_BYTES),
        "max_lines": _coerce_positive_int(section.get("max_lines"), DEFAULT_MAX_LINES),
        "max_line_length": _coerce_positive_int(
            section.get("max_line_length"), DEFAULT_MAX_LINE_LENGTH
        ),
        "context_safe_max_chars": _coerce_positive_int(
            section.get("context_safe_max_chars"), DEFAULT_CONTEXT_SAFE_MAX_CHARS
        ),
    }


def get_max_bytes() -> int:
    """Shortcut for terminal-tool callers that only need the byte cap."""
    return get_tool_output_limits()["max_bytes"]


def get_max_lines() -> int:
    """Shortcut for file-ops callers that only need the line cap."""
    return get_tool_output_limits()["max_lines"]


def get_max_line_length() -> int:
    """Shortcut for file-ops callers that only need the per-line cap."""
    return get_tool_output_limits()["max_line_length"]


def get_context_safe_max_chars() -> int:
    """Shortcut for the final per-tool-message context cap."""
    return get_tool_output_limits()["context_safe_max_chars"]


def redact_prompt_argv(text: str, *, prompt_limit: int = DEFAULT_ARGV_REDACTION_LIMIT) -> str:
    """Redact long ``claude -p`` / ``codex -p`` prompt argv fragments.

    Process listings (for example ``ps aux``) can echo an entire generated
    prompt in a command line. Keep the command shape visible but replace
    oversized prompt payloads before the text is persisted or injected into
    model context.
    """
    if not text or ("claude" not in text.lower() and "codex" not in text.lower()):
        return text

    def _replace(match: re.Match[str]) -> str:
        prompt = match.group("prompt") or ""
        if len(prompt) <= prompt_limit:
            return match.group(0)
        return (
            f"{match.group('cmd')}[REDACTED_PROMPT_ARG: "
            f"{len(prompt):,} chars omitted]"
        )

    return _PROMPT_ARG_RE.sub(_replace, text)


def middle_truncate_text(
    text: str,
    *,
    max_chars: int = DEFAULT_CONTEXT_SAFE_MAX_CHARS,
    notice: str = "CONTENT TRUNCATED",
) -> str:
    """Bound text by keeping head and tail with an explicit omission marker."""
    if not text or len(text) <= max_chars:
        return text

    marker = (
        f"\n\n... [{notice} - "
        f"{len(text) - max_chars:,}+ chars omitted from {len(text):,} total] ...\n\n"
    )
    if len(marker) >= max_chars:
        # Extremely small user-configured caps should remain hard caps even
        # when the explanatory marker itself would exceed the budget.
        return marker[:max_chars]

    available = max_chars - len(marker)
    head_chars = max(1, int(available * 0.4))
    tail_chars = max(1, available - head_chars)
    return text[:head_chars] + marker + text[-tail_chars:]


def sanitize_context_text(
    text: str,
    *,
    max_chars: int | None = None,
    notice: str = "CONTENT TRUNCATED",
) -> str:
    """Apply context-hygiene redactions and a hard middle-truncation cap."""
    if not isinstance(text, str):
        text = str(text)
    text = redact_prompt_argv(text)
    cap = max_chars if max_chars is not None else get_context_safe_max_chars()
    return middle_truncate_text(text, max_chars=cap, notice=notice)
