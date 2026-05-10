"""Focused tests for gateway runtime credential fallback routing."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from hermes_cli.auth import AuthError


def _source(platform: str = "weixin", chat_id: str = "chat-1", user_id: str = "user-1"):
    return SimpleNamespace(platform=platform, chat_id=chat_id, user_id=user_id)


def test_strict_gateway_route_fails_closed_without_fallback(monkeypatch):
    """A matched strict route must not silently fall back after primary auth failure."""
    import gateway.run as run

    monkeypatch.setenv("HERMES_INFERENCE_PROVIDER", "openai-codex")
    cfg = {
        "gateway_credential_routing": {
            "rules": [
                {
                    "platform": "weixin",
                    "chat_id": "chat-1",
                    "provider": "openai-codex",
                    "exclusive": True,
                }
            ]
        }
    }

    with patch("hermes_cli.runtime_provider.resolve_runtime_provider", side_effect=AuthError("expired", provider="openai-codex")), \
        patch.object(run, "_load_gateway_config", return_value=cfg), \
        patch.object(run, "_try_resolve_fallback_provider") as fallback:
        with pytest.raises(RuntimeError, match="fallback is disabled"):
            run._resolve_runtime_agent_kwargs(source=_source())

    fallback.assert_not_called()


def test_non_strict_gateway_route_uses_fallback_with_metadata(monkeypatch):
    """Non-strict routes retain existing fallback behavior and expose fallback metadata."""
    import gateway.run as run

    monkeypatch.setenv("HERMES_INFERENCE_PROVIDER", "openai-codex")
    fallback_config = {
        "api_key": "fb-key",
        "base_url": "https://fallback.example/v1",
        "provider": "openrouter",
        "model": "anthropic/claude-sonnet-4",
        "fallback_used": True,
        "fallback_reason": "expired",
        "primary_provider": "openai-codex",
    }

    with patch("hermes_cli.runtime_provider.resolve_runtime_provider", side_effect=AuthError("expired", provider="openai-codex")), \
        patch.object(run, "_load_gateway_config", return_value={}), \
        patch.object(run, "_try_resolve_fallback_provider", return_value=fallback_config) as fallback:
        resolved = run._resolve_runtime_agent_kwargs(source=_source())

    assert resolved is fallback_config
    fallback.assert_called_once_with(primary_error="expired", primary_provider="openai-codex")


def test_runtime_footer_shows_fallback_warning_when_enabled():
    """Footer-enabled gateways should visibly warn when a fallback runtime handled the turn."""
    from gateway.runtime_footer import build_footer_line

    line = build_footer_line(
        user_config={
            "display": {
                "runtime_footer": {
                    "enabled": True,
                    "fields": ["model", "provider", "credential"],
                }
            }
        },
        platform_key="weixin",
        model="anthropic/claude-sonnet-4",
        context_tokens=0,
        context_length=None,
        cwd="",
        provider="openrouter",
        credential_label="fallback-key",
        fallback_used=True,
        fallback_reason="expired primary token",
    )

    assert line.startswith("⚠ fallback:")
    assert "claude-sonnet-4" in line
    assert "openrouter" in line
    assert "fallback-key" in line
    assert "expired primary token" in line
