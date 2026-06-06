"""Context progressive-disclosure policy helpers.

The helpers in this module are intentionally pure and conservative. They
decide what Hermes sends to a provider for a turn, without mutating the raw
transcript or the user's persisted tool/platform configuration.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


PROGRESSIVE_PLATFORMS = frozenset({"weixin", "feishu", "api_server"})
PROGRESSIVE_BASE_TOOLSETS = (
    "web",
    "vision",
    "image_gen",
    "memory",
    "session_search",
    "skills",
    "clarify",
    "todo",
    "messaging",
)
PROGRESSIVE_CODING_TOOLSETS = (
    "terminal",
    "file",
    "code_execution",
    "delegation",
)
PROGRESSIVE_RESEARCH_TOOLSETS = ("web", "browser")
PROGRESSIVE_ENTERPRISE_TOOLSETS = ("feishu_doc", "feishu_drive")
PROGRESSIVE_BLOCKED_BASE_TOOLS = frozenset({
    "cronjob",
    "delegate_task",
    "terminal",
    "process",
    "execute_code",
    "read_file",
    "write_file",
    "patch",
    "search_files",
    "skill_manage",
})

_CODING_RE = re.compile(
    r"(\b("
    r"code|coding|repo|repository|git|github|issue|pr|pull request|"
    r"bug|debug|traceback|stack trace|test|pytest|build|lint|typecheck|"
    r"file|patch|diff|implement|refactor|terminal|shell|command"
    r")\b|"
    r"代码|仓库|问题|议题|开PR|PR|拉取请求|改代码|实现|修复|调试|报错|"
    r"测试|构建|编译|补丁|差异|重构|终端|命令|跑测试|提交|分支)",
    re.IGNORECASE,
)
_RESEARCH_RE = re.compile(
    r"(\b("
    r"research|search|lookup|look up|web|internet|docs|documentation|"
    r"openclaw|reference|source|latest|current"
    r")\b|"
    r"研究|搜索|查找|查询|资料|文档|参考|来源|最新|当前|业内)",
    re.IGNORECASE,
)
_ENTERPRISE_RE = re.compile(
    r"(\b(feishu|lark|doc|document|comment|drive|sheet|wiki)\b|"
    r"飞书|文档|评论|云文档|表格|知识库)",
    re.IGNORECASE,
)
_LOW_SIGNAL_RE = re.compile(
    r"^\s*(hi|hello|hey|ok|okay|thanks|thank you|ping|test|"
    r"收到|好的|谢谢|在吗|好了|好了吗|hi[!.]?)\s*$",
    re.IGNORECASE,
)
_META_RECALL_RE = re.compile(
    r"(\b(context|prompt|token|schema|tool schema|memory|hktmemory|"
    r"diagnostic|breakdown|overhead|openclaw|competitor|external research)\b|"
    r"上下文|提示词|令牌|工具 schema|工具模式|记忆|诊断|占用|分布|开销|竞品|外部研究)",
    re.IGNORECASE,
)


def _context_cfg(config: dict[str, Any] | None) -> dict[str, Any]:
    cfg = (config or {}).get("context") or {}
    return cfg if isinstance(cfg, dict) else {}


def progressive_tools_config(config: dict[str, Any] | None) -> dict[str, Any]:
    ctx = _context_cfg(config)
    cfg = ctx.get("progressive_tools") or {}
    if not isinstance(cfg, dict):
        cfg = {}
    return cfg


def progressive_tools_enabled(config: dict[str, Any] | None, platform: str) -> bool:
    cfg = progressive_tools_config(config)
    if cfg.get("enabled", True) is False:
        return False
    platforms = cfg.get("platforms") or sorted(PROGRESSIVE_PLATFORMS)
    return (platform or "").lower() in {str(p).lower() for p in platforms}


def has_explicit_platform_toolsets(config: dict[str, Any] | None, platform: str) -> bool:
    platform_toolsets = (config or {}).get("platform_toolsets") or {}
    return isinstance(platform_toolsets.get(platform), list)


def explicit_platform_toolsets(config: dict[str, Any] | None, platform: str) -> list[str]:
    platform_toolsets = (config or {}).get("platform_toolsets") or {}
    values = platform_toolsets.get(platform)
    if not isinstance(values, list):
        return []
    return [str(value) for value in values]


def base_progressive_toolsets(config: dict[str, Any] | None, platform: str) -> list[str] | None:
    """Return default low-overhead toolsets for an unconfigured platform."""
    if not progressive_tools_enabled(config, platform):
        return None
    cfg = progressive_tools_config(config)
    explicit_toolsets = explicit_platform_toolsets(config, platform)
    if "no_mcp" in explicit_toolsets:
        return None
    if (
        has_explicit_platform_toolsets(config, platform)
        and cfg.get("respect_explicit_platform_toolsets", False)
    ):
        return None
    per_platform = cfg.get("base_toolsets_by_platform") or {}
    if isinstance(per_platform, dict) and isinstance(per_platform.get(platform), list):
        return [str(x) for x in per_platform[platform]]
    base = cfg.get("base_toolsets")
    if isinstance(base, list):
        return [str(x) for x in base]
    if platform == "api_server":
        return [ts for ts in PROGRESSIVE_BASE_TOOLSETS if ts != "messaging"]
    return list(PROGRESSIVE_BASE_TOOLSETS)


def classify_turn_intents(message: str | None, platform: str = "") -> set[str]:
    text = str(message or "")
    intents: set[str] = set()
    if _CODING_RE.search(text):
        intents.add("coding")
    if _RESEARCH_RE.search(text):
        intents.add("research")
    if platform == "feishu" and _ENTERPRISE_RE.search(text):
        intents.add("enterprise")
    return intents


def resolve_progressive_toolsets(
    config: dict[str, Any] | None,
    platform: str,
    message: str | None,
    enabled_toolsets: Iterable[str] | None,
) -> list[str]:
    """Apply per-turn progressive-disclosure expansion.

    Explicit platform tool configuration remains authoritative. For default
    Weixin/Feishu/API turns, Hermes starts from a compact toolset and adds
    heavier toolsets only when the user's message signals that intent.
    """
    existing = list(enabled_toolsets or [])
    if not progressive_tools_enabled(config, platform):
        return existing

    base = base_progressive_toolsets(config, platform)
    if base is None:
        base = existing

    result = list(dict.fromkeys(str(x) for x in base))
    intents = classify_turn_intents(message, platform)
    if "coding" in intents:
        result.extend(PROGRESSIVE_CODING_TOOLSETS)
    if "research" in intents:
        result.extend(PROGRESSIVE_RESEARCH_TOOLSETS)
    if "enterprise" in intents:
        result.extend(PROGRESSIVE_ENTERPRISE_TOOLSETS)

    cfg = progressive_tools_config(config)
    intent_toolsets = cfg.get("intent_toolsets") or {}
    if isinstance(intent_toolsets, dict):
        for intent in sorted(intents):
            extra = intent_toolsets.get(intent)
            if isinstance(extra, list):
                result.extend(str(x) for x in extra)

    return sorted(dict.fromkeys(result))


def filter_progressive_tool_schemas(
    tools: list[dict[str, Any]] | None,
    *,
    config: dict[str, Any] | None,
    platform: str,
    enabled_toolsets: Iterable[str] | None = None,
) -> list[dict[str, Any]] | None:
    """Remove heavy base schemas for progressive default platform turns."""
    if not tools or not progressive_tools_enabled(config, platform):
        return tools
    enabled = set(str(x) for x in (enabled_toolsets or []))
    heavy_enabled = (
        enabled & set(PROGRESSIVE_CODING_TOOLSETS)
        | {"cronjob"} & enabled
    )
    blocked = set(PROGRESSIVE_BLOCKED_BASE_TOOLS)
    if heavy_enabled:
        blocked -= {
            "delegate_task",
            "terminal",
            "process",
            "execute_code",
            "read_file",
            "write_file",
            "patch",
            "search_files",
        }
    if "cronjob" in enabled:
        blocked.discard("cronjob")

    filtered = [
        t for t in tools
        if t.get("function", {}).get("name") not in blocked
    ]
    return filtered


def memory_recall_gate_config(config: dict[str, Any] | None) -> dict[str, Any]:
    ctx = _context_cfg(config)
    cfg = ctx.get("memory_recall_gate") or {}
    return cfg if isinstance(cfg, dict) else {}


def should_prefetch_memory(
    query: str | None,
    *,
    config: dict[str, Any] | None,
    platform: str = "",
) -> tuple[bool, str]:
    cfg = memory_recall_gate_config(config)
    if cfg.get("enabled", True) is False:
        return True, "disabled"
    text = str(query or "").strip()
    min_chars = int(cfg.get("min_query_chars", 12) or 12)
    if not text or len(text) < min_chars or _LOW_SIGNAL_RE.match(text):
        return False, "low_signal"
    if _META_RECALL_RE.search(text):
        return False, "meta_or_external_research"
    return True, "allowed"


@dataclass(frozen=True)
class ReplayPruneStats:
    pruned_messages: int = 0
    original_chars: int = 0
    replay_chars: int = 0


def replay_pruning_config(config: dict[str, Any] | None) -> dict[str, Any]:
    ctx = _context_cfg(config)
    cfg = ctx.get("replay_pruning") or {}
    return cfg if isinstance(cfg, dict) else {}


def _head_tail(text: str, *, head_chars: int, tail_chars: int) -> str:
    if len(text) <= head_chars + tail_chars:
        return text
    head = text[:head_chars]
    tail = text[-tail_chars:] if tail_chars > 0 else ""
    return (
        f"{head}\n\n"
        f"[... {len(text) - len(head) - len(tail):,} chars pruned from old tool output "
        f"for provider replay; raw transcript is unchanged ...]\n\n"
        f"{tail}"
    ).strip()


def prune_provider_replay_messages(
    messages: list[dict[str, Any]],
    *,
    config: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], ReplayPruneStats]:
    """Prune old large tool outputs in the provider-call copy only."""
    cfg = replay_pruning_config(config)
    if cfg.get("enabled", True) is False or not messages:
        return messages, ReplayPruneStats(replay_chars=sum(len(str(m)) for m in messages))

    keep_recent = int(cfg.get("keep_recent_messages", 12) or 12)
    threshold = int(cfg.get("tool_output_threshold_chars", 8000) or 8000)
    head_chars = int(cfg.get("head_chars", 1200) or 1200)
    tail_chars = int(cfg.get("tail_chars", 800) or 800)
    cutoff = max(0, len(messages) - keep_recent)
    changed = False
    pruned = 0
    original_chars = 0
    replay_chars = 0
    out: list[dict[str, Any]] = []
    for idx, msg in enumerate(messages):
        new_msg = msg
        content = msg.get("content") if isinstance(msg, dict) else None
        if (
            idx < cutoff
            and isinstance(msg, dict)
            and msg.get("role") == "tool"
            and isinstance(content, str)
            and len(content) > threshold
        ):
            changed = True
            pruned += 1
            original_chars += len(content)
            new_msg = dict(msg)
            new_msg["content"] = _head_tail(
                content,
                head_chars=head_chars,
                tail_chars=tail_chars,
            )
        replay_chars += len(str(new_msg))
        out.append(new_msg)
    if not changed:
        original_chars = sum(len(str(m)) for m in messages)
    return out, ReplayPruneStats(
        pruned_messages=pruned,
        original_chars=original_chars,
        replay_chars=replay_chars,
    )


def tool_schema_size(tool: dict[str, Any]) -> int:
    return len(json.dumps(tool, ensure_ascii=False))


def direct_openai_responses_compaction_status(
    agent: Any,
    *,
    config: dict[str, Any] | None,
) -> dict[str, Any]:
    """Report whether OpenAI Responses compaction is applicable.

    OpenAI documents compaction as the `/v1/responses/compact` endpoint. This
    helper deliberately does not enable anything for ChatGPT/Codex app-server
    routes, xAI, GitHub/Copilot, or non-Responses modes.
    """
    ctx = _context_cfg(config)
    cfg = ctx.get("openai_responses_compaction") or {}
    if not isinstance(cfg, dict):
        cfg = {}
    enabled = bool(cfg.get("enabled", False))
    api_mode = getattr(agent, "api_mode", "") or ""
    provider = (getattr(agent, "provider", "") or "").strip().lower()
    base_url = (getattr(agent, "base_url", "") or "").strip()
    host = urlparse(base_url).hostname or ""
    direct_openai = provider == "openai" or host in {"api.openai.com", ""}
    excluded = provider in {"openai-codex", "xai", "xai-oauth"} or "chatgpt.com" in host
    applicable = enabled and api_mode == "codex_responses" and direct_openai and not excluded
    return {
        "enabled": enabled,
        "applicable": applicable,
        "mode": "responses_compact_endpoint",
        "reason": (
            "direct_openai_responses" if applicable else
            "disabled" if not enabled else
            "not_direct_openai_responses"
        ),
        "threshold": cfg.get("threshold", 0.8),
    }
