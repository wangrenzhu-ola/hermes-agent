from gateway.run import (
    _extract_gateway_display_reasoning,
    _format_gateway_code_change_snippet,
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


def test_format_gateway_code_change_snippet_diff_truncates_and_redacts():
    diff = "\n".join(
        [
            "--- a/app.py",
            "+++ b/app.py",
            "@@",
            "-old = 1",
            "+api_key = sk-testsecret1234567890",
            "+new = 2",
            "+extra = 3",
        ]
    )

    rendered = _format_gateway_code_change_snippet(
        "patch",
        {
            "success": True,
            "diff": diff,
            "files_modified": ["app.py"],
        },
        max_lines=5,
        max_chars=1000,
    )

    assert rendered.startswith("📝 代码变更\n- app.py\n```diff")
    assert "[REDACTED]" in rendered
    assert "extra = 3" not in rendered
    assert "more lines" in rendered


def test_format_gateway_code_change_snippet_write_file_summarizes_without_content():
    rendered = _format_gateway_code_change_snippet(
        "write_file",
        {
            "bytes_written": 123,
            "files_modified": ["/tmp/app.py"],
            "content": "full file content should not be shown",
        },
    )

    assert rendered == "📝 文件已修改\n- /tmp/app.py\nBytes written: 123"


def test_format_gateway_code_change_snippet_ignores_non_mutating_tools():
    assert (
        _format_gateway_code_change_snippet(
            "read_file",
            {"diff": "--- a\n+++ b\n"},
        )
        is None
    )
