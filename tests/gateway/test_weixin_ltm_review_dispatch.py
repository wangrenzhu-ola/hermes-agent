from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import asyncio
import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import MessageEvent
from gateway.session import SessionEntry, SessionSource, build_session_key


def _make_source(*, chat_type: str = "dm") -> SessionSource:
    return SessionSource(
        platform=Platform.WEIXIN,
        user_id="wx-user-1",
        chat_id="wx-chat-1",
        user_name="tester",
        chat_type=chat_type,
    )


def _make_event(text: str, *, chat_type: str = "dm") -> MessageEvent:
    return MessageEvent(
        text=text,
        source=_make_source(chat_type=chat_type),
        message_id="msg-1",
    )


def _make_runner():
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(
        platforms={Platform.WEIXIN: PlatformConfig(enabled=True, token="***")}
    )
    adapter = MagicMock()
    adapter.send = AsyncMock()
    runner.adapters = {Platform.WEIXIN: adapter}
    runner._voice_mode = {}
    runner.hooks = SimpleNamespace(
        emit=AsyncMock(),
        emit_collect=AsyncMock(return_value=[]),
        loaded_hooks=False,
    )

    session_entry = SessionEntry(
        session_key=build_session_key(_make_source()),
        session_id="sess-1",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        platform=Platform.WEIXIN,
        chat_type="dm",
    )
    runner.session_store = MagicMock()
    runner.session_store.get_or_create_session.return_value = session_entry
    runner.session_store.load_transcript.return_value = []
    runner.session_store.has_any_sessions.return_value = True
    runner.session_store.append_to_transcript = MagicMock()
    runner.session_store.rewrite_transcript = MagicMock()
    runner.session_store.update_session = MagicMock()
    runner._running_agents = {}
    runner._running_agents_ts = {}
    runner._pending_messages = {}
    runner._pending_approvals = {}
    runner._session_db = None
    runner._reasoning_config = None
    runner._provider_routing = {}
    runner._fallback_model = None
    runner._show_reasoning = False
    runner._draining = False
    runner._is_user_authorized = lambda _source: True
    runner._set_session_env = lambda _context: None
    runner._should_send_voice_reply = lambda *_args, **_kwargs: False
    runner._send_voice_reply = AsyncMock()
    runner._capture_gateway_honcho_if_configured = lambda *args, **kwargs: None
    runner._emit_gateway_run_progress = AsyncMock()
    runner._session_key_for_source = lambda source: build_session_key(source)
    runner._begin_session_run_generation = MagicMock(return_value=1)
    runner._handle_message_with_agent = AsyncMock(return_value="agent path")
    return runner


def _install_fake_adapter(hermes_home, *, mutate_memory: bool = False, stderr_text: str = ""):
    adapter = hermes_home / "skills" / "infra-sleep-skill" / "references" / "long_term_memory_review.py"
    adapter.parent.mkdir(parents=True)
    adapter.write_text(
        "\n".join(
            [
                "import argparse, json",
                "from pathlib import Path",
                "ap = argparse.ArgumentParser()",
                "ap.add_argument('--memory-path')",
                "ap.add_argument('--user-profile-path')",
                "ap.add_argument('--skills-root', action='append', default=[])",
                "ap.add_argument('--output-dir', required=True)",
                "ap.add_argument('--run-id', required=True)",
                "ap.add_argument('--pretty', action='store_true')",
                "args = ap.parse_args()",
                "out = Path(args.output_dir)",
                "out.mkdir(parents=True, exist_ok=True)",
                "msg = out / f'long-term-memory-review-{args.run_id}-user-message.md'",
                "msg.write_text('Hermes 长期记忆整理完毕。\\n', encoding='utf-8')",
                (
                    "import sys; print(%r, file=sys.stderr)" % stderr_text
                    if stderr_text
                    else ""
                ),
                (
                    "Path(args.memory_path).write_text('mutated\\n', encoding='utf-8')"
                    if mutate_memory
                    else "Path(args.memory_path).read_text(encoding='utf-8')"
                ),
                "print(json.dumps({'user_message_path': str(msg)}))",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return adapter


def _prepare_hermes_home(tmp_path, *, mutate_memory: bool = False, stderr_text: str = ""):
    hermes_home = tmp_path / "hermes"
    memories = hermes_home / "memories"
    memories.mkdir(parents=True)
    (memories / "MEMORY.md").write_text("stable memory\n", encoding="utf-8")
    (memories / "USER.md").write_text("stable user\n", encoding="utf-8")
    (hermes_home / "skills").mkdir(exist_ok=True)
    _install_fake_adapter(
        hermes_home,
        mutate_memory=mutate_memory,
        stderr_text=stderr_text,
    )
    return hermes_home


@pytest.mark.asyncio
async def test_authorized_weixin_private_ltm_review_intent_uses_deterministic_handler():
    runner = _make_runner()
    runner._handle_weixin_ltm_review = AsyncMock(return_value="Hermes 长期记忆整理完毕。\n")

    result = await runner._handle_message(_make_event("执行长期记忆整理并给我报告"))

    assert result == "Hermes 长期记忆整理完毕.\n" or result == "Hermes 长期记忆整理完毕。\n"
    runner._handle_weixin_ltm_review.assert_awaited_once()
    runner._handle_message_with_agent.assert_not_called()


@pytest.mark.asyncio
async def test_weixin_unrelated_memory_text_falls_through_to_agent_path():
    runner = _make_runner()
    runner._handle_weixin_ltm_review = AsyncMock(return_value="should not run")

    result = await runner._handle_message(_make_event("我刚才说的记忆还在吗"))

    assert result == "agent path"
    runner._handle_weixin_ltm_review.assert_not_called()
    runner._handle_message_with_agent.assert_awaited_once()


@pytest.mark.asyncio
async def test_weixin_group_ltm_review_text_does_not_use_private_handler():
    runner = _make_runner()
    runner._handle_weixin_ltm_review = AsyncMock(return_value="should not run")

    result = await runner._handle_message(
        _make_event("跑一下 Hermes 长期记忆整理，整理完给我报告", chat_type="group")
    )

    assert result == "agent path"
    runner._handle_weixin_ltm_review.assert_not_called()
    runner._handle_message_with_agent.assert_awaited_once()


@pytest.mark.asyncio
async def test_weixin_ltm_review_handler_returns_report_when_memory_sha_is_unchanged(tmp_path, monkeypatch):
    import gateway.run as gateway_run

    hermes_home = _prepare_hermes_home(tmp_path)
    monkeypatch.setattr(gateway_run, "_hermes_home", hermes_home)
    runner = _make_runner()

    result = await runner._handle_weixin_ltm_review(_make_event("执行长期记忆整理并给我报告"))

    assert result == "Hermes 长期记忆整理完毕。\n"
    assert (hermes_home / "memories" / "MEMORY.md").read_text(encoding="utf-8") == "stable memory\n"
    assert (hermes_home / "memories" / "USER.md").read_text(encoding="utf-8") == "stable user\n"


@pytest.mark.asyncio
async def test_weixin_ltm_review_reply_does_not_leak_reasoning_text(tmp_path, monkeypatch):
    import gateway.run as gateway_run

    hermes_home = _prepare_hermes_home(
        tmp_path,
        stderr_text="Reasoning: hidden adapter diagnostic that must stay server-side",
    )
    monkeypatch.setattr(gateway_run, "_hermes_home", hermes_home)
    runner = _make_runner()
    runner._handle_message_with_agent = AsyncMock(
        return_value="Reasoning: hidden agent chain of thought\nHermes 长期记忆整理完毕。\n"
    )

    result = await runner._handle_message(_make_event("执行长期记忆整理并给我报告"))

    assert result == "Hermes 长期记忆整理完毕。\n"
    assert "Reasoning" not in result
    assert "hidden" not in result
    runner._handle_message_with_agent.assert_not_called()


@pytest.mark.asyncio
async def test_weixin_ltm_review_handler_blocks_report_when_memory_sha_changes(tmp_path, monkeypatch):
    import gateway.run as gateway_run

    hermes_home = _prepare_hermes_home(tmp_path, mutate_memory=True)
    monkeypatch.setattr(gateway_run, "_hermes_home", hermes_home)
    runner = _make_runner()

    result = await runner._handle_weixin_ltm_review(_make_event("执行长期记忆整理并给我报告"))

    assert "长期记忆整理安全校验失败" in result
    assert "MEMORY.md" in result


@pytest.mark.asyncio
async def test_weixin_ltm_review_timeout_terminates_adapter_process(tmp_path, monkeypatch):
    import gateway.run as gateway_run

    hermes_home = _prepare_hermes_home(tmp_path)
    monkeypatch.setattr(gateway_run, "_hermes_home", hermes_home)

    proc = SimpleNamespace(
        returncode=None,
        communicate=MagicMock(),
        wait=MagicMock(),
        terminate=MagicMock(),
        kill=MagicMock(),
    )

    async def communicate():
        return b"", b""

    async def wait():
        proc.returncode = -15
        return proc.returncode

    proc.communicate.return_value = communicate()
    proc.wait.return_value = wait()

    async def create_subprocess_exec(*_args, **_kwargs):
        return proc

    async def wait_for(awaitable, timeout):
        if timeout == 180:
            awaitable.close()
            raise asyncio.TimeoutError
        return await awaitable

    monkeypatch.setattr(gateway_run.asyncio, "create_subprocess_exec", create_subprocess_exec)
    monkeypatch.setattr(gateway_run.asyncio, "wait_for", wait_for)

    runner = _make_runner()

    result = await runner._handle_weixin_ltm_review(_make_event("执行长期记忆整理并给我报告"))

    assert result == "长期记忆整理超时，未生成报告。"
    proc.terminate.assert_called_once()
    proc.wait.assert_called_once()
    proc.kill.assert_not_called()
