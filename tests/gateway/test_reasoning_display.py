from gateway.run import (
    _extract_gateway_display_reasoning,
    _format_gateway_reasoning_prefix,
)


def test_extract_gateway_display_reasoning_prefers_last_reasoning():
    result = {
        "last_reasoning": " direct reasoning ",
        "messages": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "reasoning": "older"},
        ],
    }

    assert _extract_gateway_display_reasoning(result) == "direct reasoning"


def test_extract_gateway_display_reasoning_falls_back_to_same_turn_messages():
    result = {
        "last_reasoning": None,
        "messages": [
            {"role": "user", "content": "previous"},
            {"role": "assistant", "reasoning": "stale reasoning"},
            {"role": "assistant", "content": "previous answer"},
            {"role": "user", "content": "current"},
            {"role": "assistant", "reasoning_content": "current hidden summary"},
            {"role": "tool", "content": "tool output"},
            {"role": "assistant", "content": "final answer without reasoning"},
        ],
    }

    assert _extract_gateway_display_reasoning(result) == "current hidden summary"


def test_extract_gateway_display_reasoning_does_not_cross_user_turn_boundary():
    result = {
        "messages": [
            {"role": "assistant", "reasoning": "stale reasoning"},
            {"role": "user", "content": "current"},
            {"role": "assistant", "content": "final answer without reasoning"},
        ]
    }

    assert _extract_gateway_display_reasoning(result) is None


def test_format_gateway_reasoning_prefix_compacts_feishu_and_redacts_secrets():
    reasoning = "\n".join(["first", "sk-testsecret1234567890", *[f"line {i}" for i in range(20)]])

    rendered = _format_gateway_reasoning_prefix("feishu", reasoning)

    assert rendered.startswith("🧠 **思考过程**")
    assert "[REDACTED]" in rendered
    assert "***" not in rendered
    assert "more lines" in rendered
    assert "line 19" not in rendered


def test_format_gateway_reasoning_prefix_compacts_weixin_more_aggressively():
    reasoning = "\n".join([f"line {i}" for i in range(12)])

    rendered = _format_gateway_reasoning_prefix("weixin", reasoning)

    assert rendered.startswith("🧠 **思考过程**")
    assert "line 7" in rendered
    assert "line 8" not in rendered
    assert "4 more lines" in rendered


def test_format_gateway_reasoning_prefix_keeps_other_platform_reasoning_label():
    rendered = _format_gateway_reasoning_prefix("telegram", "reasoning")

    assert rendered.startswith("💭 **Reasoning:**")
    assert "reasoning" in rendered
