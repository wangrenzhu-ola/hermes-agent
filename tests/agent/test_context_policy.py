from types import SimpleNamespace

from agent.context_policy import (
    base_progressive_toolsets,
    direct_openai_responses_compaction_status,
    filter_progressive_tool_schemas,
    prune_provider_replay_messages,
    resolve_progressive_toolsets,
    should_prefetch_memory,
)


def _tool(name):
    return {"type": "function", "function": {"name": name, "description": name}}


def test_weixin_progressive_defaults_are_compact():
    config = {}

    toolsets = base_progressive_toolsets(config, "weixin")

    assert toolsets is not None
    assert "web" in toolsets
    assert "terminal" not in toolsets
    assert "cronjob" not in toolsets


def test_progressive_defaults_can_respect_explicit_platform_toolsets():
    config = {
        "platform_toolsets": {"weixin": ["hermes-weixin"]},
        "context": {
            "progressive_tools": {
                "enabled": True,
                "respect_explicit_platform_toolsets": True,
            }
        },
    }

    assert base_progressive_toolsets(config, "weixin") is None


def test_progressive_defaults_preserve_no_mcp_sentinel():
    config = {
        "platform_toolsets": {"api_server": ["web", "terminal", "no_mcp"]},
    }

    assert base_progressive_toolsets(config, "api_server") is None


def test_progressive_toolsets_expand_for_coding_intent():
    toolsets = resolve_progressive_toolsets(
        {},
        "weixin",
        "please debug this github issue and patch the repo",
        ["web", "skills"],
    )

    assert "terminal" in toolsets
    assert "file" in toolsets
    assert "code_execution" in toolsets


def test_progressive_toolsets_expand_for_chinese_coding_intent():
    toolsets = resolve_progressive_toolsets(
        {},
        "weixin",
        "帮我改代码，跑测试，开PR",
        ["web", "skills"],
    )

    assert "terminal" in toolsets
    assert "file" in toolsets
    assert "code_execution" in toolsets


def test_progressive_schema_filter_removes_heavy_base_tools():
    tools = [_tool("web_search"), _tool("terminal"), _tool("cronjob"), _tool("skill_manage"), _tool("skill_view")]

    filtered = filter_progressive_tool_schemas(
        tools,
        config={},
        platform="weixin",
        enabled_toolsets=["web", "skills"],
    )

    names = {tool["function"]["name"] for tool in filtered}
    assert "web_search" in names
    assert "skill_view" in names
    assert "terminal" not in names
    assert "cronjob" not in names
    assert "skill_manage" not in names


def test_memory_recall_gate_skips_low_signal_and_meta_research():
    assert should_prefetch_memory("hi", config={}, platform="weixin") == (False, "low_signal")
    assert should_prefetch_memory(
        "show prompt context overhead for OpenClaw",
        config={},
        platform="weixin",
    ) == (False, "meta_or_external_research")
    assert should_prefetch_memory(
        "what did we decide about the launch plan last week?",
        config={},
        platform="weixin",
    ) == (True, "allowed")


def test_provider_replay_pruning_does_not_mutate_raw_transcript():
    large = "A" * 50
    messages = [
        {"role": "user", "content": "start"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1"}]},
        {"role": "tool", "tool_call_id": "call_1", "content": large},
        {"role": "user", "content": "next"},
    ]

    replay, stats = prune_provider_replay_messages(
        messages,
        config={
            "context": {
                "replay_pruning": {
                    "enabled": True,
                    "keep_recent_messages": 1,
                    "tool_output_threshold_chars": 10,
                    "head_chars": 4,
                    "tail_chars": 4,
                }
            }
        },
    )

    assert messages[2]["content"] == large
    assert replay[2]["content"] != large
    assert "raw transcript is unchanged" in replay[2]["content"]
    assert stats.pruned_messages == 1


def test_responses_compaction_status_is_direct_openai_only():
    cfg = {"context": {"openai_responses_compaction": {"enabled": True, "threshold": 0.75}}}

    direct = SimpleNamespace(api_mode="codex_responses", provider="openai", base_url="https://api.openai.com/v1")
    codex_app = SimpleNamespace(api_mode="codex_responses", provider="openai-codex", base_url="https://chatgpt.com/backend-api/codex")

    assert direct_openai_responses_compaction_status(direct, config=cfg)["applicable"] is True
    assert direct_openai_responses_compaction_status(codex_app, config=cfg)["applicable"] is False
