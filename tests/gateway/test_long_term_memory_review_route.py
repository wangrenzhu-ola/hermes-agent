"""Tests for gateway manual long-term memory review routing."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import MessageEvent
from gateway.session import SessionSource


def _make_runner(platform: Platform = Platform.WEIXIN):
    from gateway.run import GatewayRunner

    config = GatewayConfig(platforms={platform: PlatformConfig(enabled=True)})
    runner = object.__new__(GatewayRunner)
    runner.config = config
    runner.adapters = {platform: SimpleNamespace(send=AsyncMock())}
    runner.pairing_store = MagicMock()
    runner.pairing_store.is_approved.return_value = True
    runner.pairing_store._is_rate_limited.return_value = False
    runner.session_store = MagicMock()
    runner._running_agents = {}
    runner._update_prompt_pending = {}
    return runner


def _make_event(text: str, platform: Platform = Platform.WEIXIN) -> MessageEvent:
    return MessageEvent(
        text=text,
        message_id="m-ltm",
        source=SessionSource(
            platform=platform,
            user_id="user-1",
            chat_id="chat-1",
            user_name="tester",
            chat_type="dm",
        ),
    )


@pytest.mark.asyncio
async def test_weixin_ltm_review_request_bypasses_agent_and_returns_user_message(monkeypatch):
    from gateway import run as gateway_run

    async def _agent_should_not_run(event, source, _quick_key, _run_generation):  # pragma: no cover
        raise AssertionError("agent dispatch should not run for LTM review route")

    payload = {
        "ok": True,
        "status": "success",
        "user_message": "Hermes 长期记忆整理完毕。\n\n报告留痕：\n- Markdown：`/tmp/report.md`",
        "memory_sha_unchanged": True,
        "user_sha_unchanged": True,
    }
    called = {}

    def _fake_run(*, run_id=None):
        called["run_id"] = run_id
        return payload

    monkeypatch.setattr(gateway_run, "_run_long_term_memory_review_adapter", _fake_run)
    runner = _make_runner(Platform.WEIXIN)
    runner._handle_message_with_agent = _agent_should_not_run  # noqa: SLF001

    result = await runner._handle_message(_make_event("执行长期记忆整理并给我报告"))

    assert called["run_id"].startswith("weixin-ltm-")
    assert result.startswith("Hermes 长期记忆整理完毕。")
    assert "Markdown" in result
    assert "MEMORY.md unchanged=`True`" in result
    assert "USER.md unchanged=`True`" in result


@pytest.mark.asyncio
async def test_ltm_review_apply_request_is_not_intercepted(monkeypatch):
    from gateway import run as gateway_run

    seen = {}

    async def _agent_dispatch(event, source, _quick_key, _run_generation):
        seen["text"] = event.text
        return "agent-ok"

    def _fake_run(*, run_id=None):  # pragma: no cover
        raise AssertionError("adapter should not run for explicit write/apply request")

    monkeypatch.setattr(gateway_run, "_run_long_term_memory_review_adapter", _fake_run)
    runner = _make_runner(Platform.WEIXIN)
    runner._handle_message_with_agent = _agent_dispatch  # noqa: SLF001

    result = await runner._handle_message(_make_event("按报告确认项写入长期记忆整理结果"))

    assert result == "agent-ok"
    assert seen["text"] == "按报告确认项写入长期记忆整理结果"
