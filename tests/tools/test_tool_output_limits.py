"""Tests for tools.tool_output_limits.

Covers:
1. Default values when no config is provided.
2. Config override picks up user-supplied max_bytes / max_lines /
   max_line_length.
3. Malformed values (None, negative, wrong type) fall back to defaults
   rather than raising.
4. Integration: the helpers return what the terminal_tool and
   file_operations call paths will actually consume.

Port-tracking: anomalyco/opencode PR #23770
(feat(truncate): allow configuring tool output truncation limits).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from tools import tool_output_limits as tol


@pytest.fixture(autouse=True)
def _reset_limits_cache():
    """get_tool_output_limits() now memoizes its result for the process
    lifetime, so each test must start from a clean cache to observe the
    config value it patches in."""
    tol._reset_tool_output_limits_cache()
    yield
    tol._reset_tool_output_limits_cache()


class TestDefaults:
    def test_defaults_match_previous_hardcoded_values(self):
        assert tol.DEFAULT_MAX_BYTES == 50_000
        assert tol.DEFAULT_MAX_LINES == 2000
        assert tol.DEFAULT_MAX_LINE_LENGTH == 2000

    def test_get_limits_returns_defaults_when_config_missing(self):
        with patch("hermes_cli.config.load_config", return_value={}):
            limits = tol.get_tool_output_limits()
        assert limits == {
            "max_bytes": tol.DEFAULT_MAX_BYTES,
            "max_lines": tol.DEFAULT_MAX_LINES,
            "max_line_length": tol.DEFAULT_MAX_LINE_LENGTH,
            "context_safe_max_chars": tol.DEFAULT_CONTEXT_SAFE_MAX_CHARS,
        }

    def test_get_limits_returns_defaults_when_config_not_a_dict(self):
        # load_config should always return a dict but be defensive anyway.
        with patch("hermes_cli.config.load_config", return_value="not a dict"):
            limits = tol.get_tool_output_limits()
        assert limits["max_bytes"] == tol.DEFAULT_MAX_BYTES

    def test_get_limits_returns_defaults_when_load_config_raises(self):
        def _boom():
            raise RuntimeError("boom")

        with patch("hermes_cli.config.load_config", side_effect=_boom):
            limits = tol.get_tool_output_limits()
        assert limits["max_lines"] == tol.DEFAULT_MAX_LINES


class TestOverrides:
    def test_user_config_overrides_all_limits(self):
        cfg = {
            "tool_output": {
                "max_bytes": 100_000,
                "max_lines": 5000,
                "max_line_length": 4096,
                "context_safe_max_chars": 12_345,
            }
        }
        with patch("hermes_cli.config.load_config", return_value=cfg):
            limits = tol.get_tool_output_limits()
        assert limits == {
            "max_bytes": 100_000,
            "max_lines": 5000,
            "max_line_length": 4096,
            "context_safe_max_chars": 12_345,
        }

    def test_partial_override_preserves_other_defaults(self):
        cfg = {"tool_output": {"max_bytes": 200_000}}
        with patch("hermes_cli.config.load_config", return_value=cfg):
            limits = tol.get_tool_output_limits()
        assert limits["max_bytes"] == 200_000
        assert limits["max_lines"] == tol.DEFAULT_MAX_LINES
        assert limits["max_line_length"] == tol.DEFAULT_MAX_LINE_LENGTH

    def test_section_not_a_dict_falls_back(self):
        cfg = {"tool_output": "nonsense"}
        with patch("hermes_cli.config.load_config", return_value=cfg):
            limits = tol.get_tool_output_limits()
        assert limits["max_bytes"] == tol.DEFAULT_MAX_BYTES


class TestCoercion:
    @pytest.mark.parametrize("bad", [None, "not a number", -1, 0, [], {}])
    def test_invalid_values_fall_back_to_defaults(self, bad):
        cfg = {"tool_output": {"max_bytes": bad, "max_lines": bad, "max_line_length": bad}}
        with patch("hermes_cli.config.load_config", return_value=cfg):
            limits = tol.get_tool_output_limits()
        assert limits["max_bytes"] == tol.DEFAULT_MAX_BYTES
        assert limits["max_lines"] == tol.DEFAULT_MAX_LINES
        assert limits["max_line_length"] == tol.DEFAULT_MAX_LINE_LENGTH

    def test_string_integer_is_coerced(self):
        cfg = {"tool_output": {"max_bytes": "75000"}}
        with patch("hermes_cli.config.load_config", return_value=cfg):
            limits = tol.get_tool_output_limits()
        assert limits["max_bytes"] == 75_000


class TestShortcuts:
    def test_individual_accessors_delegate_to_get_tool_output_limits(self):
        cfg = {
            "tool_output": {
                "max_bytes": 111,
                "max_lines": 222,
                "max_line_length": 333,
                "context_safe_max_chars": 444,
            }
        }
        with patch("hermes_cli.config.load_config", return_value=cfg):
            assert tol.get_max_bytes() == 111
            assert tol.get_max_lines() == 222
            assert tol.get_max_line_length() == 333
            assert tol.get_context_safe_max_chars() == 444


class TestDefaultConfigHasSection:
    """The DEFAULT_CONFIG in hermes_cli.config must expose tool_output so
    that ``hermes setup`` and default installs stay in sync with the
    helpers here."""

    def test_default_config_contains_tool_output_section(self):
        from hermes_cli.config import DEFAULT_CONFIG
        assert "tool_output" in DEFAULT_CONFIG
        section = DEFAULT_CONFIG["tool_output"]
        assert isinstance(section, dict)
        assert section["max_bytes"] == tol.DEFAULT_MAX_BYTES
        assert section["max_lines"] == tol.DEFAULT_MAX_LINES
        assert section["max_line_length"] == tol.DEFAULT_MAX_LINE_LENGTH
        assert section["context_safe_max_chars"] == tol.DEFAULT_CONTEXT_SAFE_MAX_CHARS


class TestIntegrationReadPagination:
    """normalize_read_pagination uses get_max_lines() — verify the plumbing."""

    def test_pagination_limit_clamped_by_config_value(self):
        from tools.file_operations import normalize_read_pagination
        cfg = {"tool_output": {"max_lines": 50}}
        with patch("hermes_cli.config.load_config", return_value=cfg):
            offset, limit = normalize_read_pagination(offset=1, limit=1000)
        # limit should have been clamped to 50 (the configured max_lines)
        assert limit == 50
        assert offset == 1

    def test_pagination_default_when_config_missing(self):
        from tools.file_operations import normalize_read_pagination
        with patch("hermes_cli.config.load_config", return_value={}):
            offset, limit = normalize_read_pagination(offset=10, limit=100000)
        # Clamped to default MAX_LINES (2000).
        assert limit == tol.DEFAULT_MAX_LINES
        assert offset == 10


class TestContextHygiene:
    def test_redacts_huge_claude_prompt_argv_from_process_listing(self):
        huge_prompt = "x" * 80_000
        line = f"123 ?? claude -p {huge_prompt} --dangerously-skip-permissions"
        redacted = tol.redact_prompt_argv(line)
        assert len(redacted) < 1_000
        assert "[REDACTED_PROMPT_ARG:" in redacted
        assert huge_prompt[:100] not in redacted

    def test_sanitize_context_text_middle_truncates_large_tool_output(self):
        text = "HEAD" + ("x" * 50_000) + "TAIL"
        sanitized = tol.sanitize_context_text(text, max_chars=2_000, notice="TEST TRUNCATED")
        assert len(sanitized) <= 2_000
        assert sanitized.startswith("HEAD")
        assert sanitized.endswith("TAIL")
        assert "TEST TRUNCATED" in sanitized

    def test_middle_truncate_text_keeps_tiny_caps_strict(self):
        sanitized = tol.middle_truncate_text("x" * 1_000, max_chars=10, notice="TEST TRUNCATED")
        assert len(sanitized) <= 10
        assert sanitized

    def test_make_tool_result_message_caps_string_content_before_context_injection(self):
        from agent.tool_dispatch_helpers import make_tool_result_message

        huge = "A" * (tol.DEFAULT_CONTEXT_SAFE_MAX_CHARS + 20_000)
        msg = make_tool_result_message("terminal", huge, "call_1")
        assert len(msg["content"]) <= tol.DEFAULT_CONTEXT_SAFE_MAX_CHARS
        assert "terminal TOOL RESULT TRUNCATED" in msg["content"]

    def test_make_tool_result_message_redacts_prompt_argv_before_context_injection(self):
        from agent.tool_dispatch_helpers import make_tool_result_message

        huge_prompt = "secret-ish prompt " * 5_000
        output = f"wang 1 0.0 claude -p {huge_prompt}\n"
        msg = make_tool_result_message("terminal", output, "call_2")
        assert len(msg["content"]) < 2_000
        assert "[REDACTED_PROMPT_ARG:" in msg["content"]
        assert "secret-ish prompt secret-ish prompt" not in msg["content"]

    def test_make_tool_result_message_redacts_nested_dict_output(self):
        from agent.tool_dispatch_helpers import make_tool_result_message

        output = "wang 123 0.0 claude -p " + ("X" * 30_000)
        msg = make_tool_result_message(
            "terminal",
            {"output": output, "exit_code": 0, "nested": [{"stderr": output}]},
            "call_3",
        )
        assert "[REDACTED_PROMPT_ARG:" in msg["content"]["output"]
        assert "X" * 500 not in msg["content"]["output"]
        assert "[REDACTED_PROMPT_ARG:" in msg["content"]["nested"][0]["stderr"]
        assert "X" * 500 not in msg["content"]["nested"][0]["stderr"]

    def test_terminal_tool_exact_context_hygiene_repro_is_redacted(self):
        import json
        from tools.terminal_tool import terminal_tool

        command = "python3 - <<'PY'\nprint('wang 123 0.0 claude -p ' + 'X'*30000)\nPY"
        result = json.loads(terminal_tool(command, timeout=30))
        output = result["output"]
        assert len(output) < 1_000
        assert "[REDACTED_PROMPT_ARG:" in output
        assert "X" * 500 not in output
        assert result["exit_code"] == 0
