"""Prompt-size observability and diagnostics for Hermes context payloads."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

# Compatibility export for the original ``hermes prompt-size`` diagnostic tests.
_SKILLS_BLOCK_RE = re.compile(r"<available_skills>.*?</available_skills>", re.DOTALL)


def _json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False))


def _bytes(s: str) -> int:
    return len(s.encode("utf-8"))


def _history_buckets(history: list[dict[str, Any]] | None) -> dict[str, Any]:
    history = history or []
    tool_output_chars = 0
    tool_messages = 0
    for msg in history:
        if not isinstance(msg, dict):
            continue
        if msg.get("role") == "tool":
            tool_messages += 1
            tool_output_chars += len(str(msg.get("content") or ""))
    return {
        "chars": _json_size(history),
        "messages": len(history),
        "tool_messages": tool_messages,
        "tool_output_chars": tool_output_chars,
    }


def _memory_file_text(filename: str) -> str:
    home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
    path = home / "memories" / filename
    try:
        return path.read_text(encoding="utf-8") if path.exists() else ""
    except OSError:
        return ""


def compute_prompt_breakdown(
    platform: str = "weixin",
    *,
    message: str = "hello",
    history: list[dict[str, Any]] | None = None,
    top_n: int = 10,
    include_context_files: bool = False,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a bucketed prompt-size estimate for a fresh Hermes turn.

    The primary shape is the progressive-disclosure ``buckets`` map. For
    backward compatibility with the older ``hermes prompt-size`` command/tests,
    the return value also includes ``system_prompt``, ``memory``,
    ``user_profile``, ``tools``, and ``sections`` summary keys.
    """
    from hermes_cli.config import load_config
    from hermes_cli.tools_config import _get_platform_tools
    from model_tools import get_tool_definitions
    from agent.context_policy import (
        filter_progressive_tool_schemas,
        resolve_progressive_toolsets,
        should_prefetch_memory,
        tool_schema_size,
    )
    from agent.prompt_builder import build_skills_system_prompt
    from agent.system_prompt import build_system_prompt_parts

    cfg = config if config is not None else load_config()
    platform_key = (platform or "cli").strip().lower()
    base_toolsets = sorted(_get_platform_tools(cfg, platform_key))
    enabled_toolsets = resolve_progressive_toolsets(
        cfg,
        platform_key,
        message,
        base_toolsets,
    )
    tools = get_tool_definitions(enabled_toolsets=enabled_toolsets, quiet_mode=True)
    tools = filter_progressive_tool_schemas(
        tools,
        config=cfg,
        platform=platform_key,
        enabled_toolsets=enabled_toolsets,
    ) or []
    valid = {t.get("function", {}).get("name", "") for t in tools}
    avail_toolsets = set(enabled_toolsets)
    skills_prompt = build_skills_system_prompt(
        available_tools=valid,
        available_toolsets=avail_toolsets,
    )
    agent = SimpleNamespace(
        load_soul_identity=False,
        skip_context_files=not include_context_files,
        valid_tool_names=valid,
        _kanban_worker_guidance=False,
        _tool_use_enforcement=(cfg.get("agent") or {}).get(
            "tool_use_enforcement",
            "auto",
        ),
        model=(cfg.get("model") or {}).get("model", "gpt-5.5") if isinstance(cfg.get("model"), dict) else "gpt-5.5",
        provider=(cfg.get("model") or {}).get("provider", "openai") if isinstance(cfg.get("model"), dict) else "openai",
        platform=platform_key,
        _memory_store=None,
        _memory_enabled=True,
        _user_profile_enabled=True,
        _memory_manager=None,
        pass_session_id=False,
        session_id="prompt-size",
        tools=tools,
    )
    parts = build_system_prompt_parts(agent)
    stable = parts.get("stable", "")
    context = parts.get("context", "")
    volatile = parts.get("volatile", "")
    stable_chars = len(stable)
    skills_chars = len(skills_prompt)
    system_stable_chars = (
        stable_chars - skills_chars
        if skills_prompt and skills_prompt in stable
        else stable_chars
    )
    tool_sizes = [
        {
            "name": t.get("function", {}).get("name", ""),
            "chars": tool_schema_size(t),
        }
        for t in tools
    ]
    tool_sizes.sort(key=lambda item: item["chars"], reverse=True)
    memory_allowed, memory_reason = should_prefetch_memory(
        message,
        config=cfg,
        platform=platform_key,
    )
    buckets = {
        "system_stable": {"chars": max(system_stable_chars, 0)},
        "skills_index": {"chars": skills_chars},
        "memory_user": {"chars": len(volatile)},
        "enterprise_recall": {
            "chars": 0,
            "gate_allowed": memory_allowed,
            "gate_reason": memory_reason,
        },
        "project_context_files": {"chars": len(context)},
        "tool_schemas": {
            "chars": _json_size(tools),
            "count": len(tools),
            "top": tool_sizes[:top_n],
        },
        "history_tool_outputs": _history_buckets(history),
    }

    total_chars = sum(bucket.get("chars", 0) for bucket in buckets.values())
    memory_text = _memory_file_text("MEMORY.md")
    user_text = _memory_file_text("USER.md")
    tools_json_bytes = _bytes(json.dumps(tools, ensure_ascii=False))
    sections = [
        ("stable (identity/guidance/skills)", len(stable), _bytes(stable)),
        ("context (AGENTS.md/cwd files)", len(context), _bytes(context)),
        ("volatile (memory/profile/timestamp)", len(volatile), _bytes(volatile)),
    ]
    return {
        "platform": platform_key,
        "model": getattr(agent, "model", "") or "",
        "message_preview": str(message or "")[:120],
        "enabled_toolsets": enabled_toolsets,
        "total_chars": total_chars,
        "buckets": buckets,
        # Backward-compatible diagnostic keys.
        "system_prompt": {"chars": len(stable) + len(context) + len(volatile), "bytes": _bytes(stable) + _bytes(context) + _bytes(volatile)},
        "skills_index": {"chars": skills_chars, "bytes": _bytes(skills_prompt)},
        "memory": {"chars": len(memory_text), "bytes": _bytes(memory_text)},
        "user_profile": {"chars": len(user_text), "bytes": _bytes(user_text)},
        "tools": {"count": len(tools), "json_bytes": tools_json_bytes},
        "sections": sections,
    }


def _fmt_kb(n: int) -> str:
    return f"{n / 1024:.1f} KB"


def render_breakdown(data: dict[str, Any]) -> str:
    """Render the legacy byte-oriented prompt-size breakdown."""
    sp = data.get("system_prompt") or {"bytes": 0, "chars": 0}
    lines = [
        f"Prompt-size breakdown (platform={data.get('platform')}, model={data.get('model') or 'unset'})",
        "",
        f"  System prompt total : {sp.get('bytes', 0):>8,} B  ({_fmt_kb(int(sp.get('bytes', 0)))}, {sp.get('chars', 0):,} chars)",
        "",
        "  Major blocks:",
    ]
    si = data.get("skills_index") or {"bytes": 0}
    mem = data.get("memory") or {"bytes": 0}
    up = data.get("user_profile") or {"bytes": 0}
    lines.append(f"    skills index       : {si.get('bytes', 0):>8,} B  ({_fmt_kb(int(si.get('bytes', 0)))})")
    lines.append(f"    memory             : {mem.get('bytes', 0):>8,} B  ({_fmt_kb(int(mem.get('bytes', 0)))})")
    lines.append(f"    user profile       : {up.get('bytes', 0):>8,} B  ({_fmt_kb(int(up.get('bytes', 0)))})")
    lines.append("")
    lines.append("  Prompt tiers:")
    for label, _chars, byts in data.get("sections", []):
        lines.append(f"    {label:<36}: {byts:>8,} B  ({_fmt_kb(int(byts))})")
    lines.append("")
    tools = data.get("tools") or {"json_bytes": 0, "count": 0}
    lines.append(f"  Tool schemas         : {tools.get('json_bytes', 0):>8,} B  ({_fmt_kb(int(tools.get('json_bytes', 0)))}, {tools.get('count', 0)} tools)")
    return "\n".join(lines)


def format_prompt_breakdown(
    breakdown: dict[str, Any],
    *,
    mode: str = "list",
    as_json: bool = False,
) -> str:
    if as_json:
        return json.dumps(breakdown, ensure_ascii=False, indent=2)

    buckets = breakdown.get("buckets") or {}
    if mode == "map":
        lines = [
            (
                f"context map for {breakdown.get('platform')} "
                f"({breakdown.get('total_chars', 0):,} chars)"
            ),
            (
                "system_stable -> skills_index -> memory_user -> "
                "enterprise_recall -> project_context_files -> "
                "tool_schemas -> history_tool_outputs"
            ),
        ]
        return "\n".join(lines)

    lines = [
        (
            f"context {mode} for {breakdown.get('platform')} "
            f"({breakdown.get('total_chars', 0):,} chars)"
        ),
    ]
    for name, data in buckets.items():
        lines.append(f"- {name}: {int(data.get('chars', 0)):,} chars")
        if mode == "detail" and name == "tool_schemas":
            for item in data.get("top", []):
                lines.append(f"  - {item['name']}: {item['chars']:,}")
        if mode == "detail" and name == "enterprise_recall":
            lines.append(
                f"  - gate: {data.get('gate_reason')} "
                f"({'allowed' if data.get('gate_allowed') else 'skipped'})"
            )
    return "\n".join(lines)


def cmd_prompt_size(args: Any) -> None:
    """Entry point for ``hermes prompt-size``."""
    platform = getattr(args, "platform", "cli") or "cli"
    as_json = getattr(args, "json", False)
    mode = getattr(args, "mode", None)
    try:
        data = compute_prompt_breakdown(platform=platform)
    except Exception as e:
        print(f"Could not compute prompt-size breakdown: {e}")
        return
    if mode in {"list", "detail", "map"}:
        print(format_prompt_breakdown(data, mode=mode, as_json=as_json))
    elif as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(render_breakdown(data))


def handle_context_command(args: str = "", *, default_platform: str = "weixin") -> str:
    tokens = [tok for tok in str(args or "").split() if tok]
    mode = "list"
    as_json = False
    platform = default_platform
    message = "hello"
    for tok in tokens:
        if tok in {"list", "detail", "map"}:
            mode = tok
        elif tok == "--json":
            as_json = True
        elif tok.startswith("--platform="):
            platform = tok.split("=", 1)[1] or platform
        elif tok.startswith("--message="):
            message = tok.split("=", 1)[1]
    breakdown = compute_prompt_breakdown(platform=platform, message=message)
    return format_prompt_breakdown(breakdown, mode=mode, as_json=as_json)


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect Hermes prompt-size buckets.")
    parser.add_argument(
        "mode",
        nargs="?",
        default="list",
        choices=("list", "detail", "map"),
    )
    parser.add_argument("--platform", default="weixin")
    parser.add_argument("--message", default="hello")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    breakdown = compute_prompt_breakdown(platform=args.platform, message=args.message)
    print(format_prompt_breakdown(breakdown, mode=args.mode, as_json=args.json))


if __name__ == "__main__":
    main()
