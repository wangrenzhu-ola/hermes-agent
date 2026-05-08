"""Tests for Agent-Native Credential Capability Router.

Covers:
- Manifest parsing and default backward compatibility
- Entitlement isolation (Weixin Pro exclusive boundary)
- Capability parity enforcement on fallback
- Failure taxonomy correctness
- Redacted trace contains reasons but no secrets
- Integration with CredentialPool.select_with_capabilities()
"""

from __future__ import annotations

import json
import time

import pytest

from agent.capability_router import (
    DEFAULT_MANIFEST,
    CapabilityManifest,
    RouteRequest,
    RoutingDecision,
    RoutingFailureReason,
    RoutingVerdict,
    SkippedCandidate,
    get_credential_manifest,
    route_with_capabilities,
)


# ── Helpers ──────────────────────────────────────────────────────────────


class FakeCredential:
    """Minimal stand-in for PooledCredential in unit tests."""

    def __init__(self, id: str, label: str, extra: dict = None):
        self.id = id
        self.label = label
        self.extra = extra or {}
        self.priority = 0


def _make_credential(id: str, label: str, manifest_data: dict = None) -> FakeCredential:
    extra = {}
    if manifest_data:
        extra["capability_manifest"] = manifest_data
    return FakeCredential(id=id, label=label, extra=extra)


# ── Manifest Parsing Tests ───────────────────────────────────────────────


class TestCapabilityManifest:
    def test_default_manifest_is_permissive(self):
        """Default manifest should allow everything (backward compat)."""
        m = DEFAULT_MANIFEST
        assert m.tool_support is True
        assert m.vision_support is True
        assert m.streaming_support is True
        assert m.channel_entitlements == frozenset()
        assert m.exclusive_entitlements == frozenset()
        assert m.context_cap == 0
        assert m.parity_class == ""

    def test_from_dict_none_returns_default(self):
        assert CapabilityManifest.from_dict(None) is DEFAULT_MANIFEST

    def test_from_dict_empty_returns_default(self):
        assert CapabilityManifest.from_dict({}) is DEFAULT_MANIFEST

    def test_from_dict_full(self):
        data = {
            "provider": "anthropic",
            "model_families": ["claude-4", "claude-3.5"],
            "api_modes": ["chat_completions"],
            "context_cap": 200000,
            "output_cap": 8192,
            "tool_support": True,
            "vision_support": True,
            "streaming_support": True,
            "channel_entitlements": ["weixin", "feishu"],
            "exclusive_entitlements": ["weixin-pro-exclusive"],
            "parity_class": "claude-pro",
            "cost_tier": "premium",
            "risk_tier": "low",
        }
        m = CapabilityManifest.from_dict(data)
        assert m.provider == "anthropic"
        assert m.model_families == frozenset({"claude-4", "claude-3.5"})
        assert m.api_modes == frozenset({"chat_completions"})
        assert m.context_cap == 200000
        assert m.output_cap == 8192
        assert m.exclusive_entitlements == frozenset({"weixin-pro-exclusive"})
        assert m.channel_entitlements == frozenset({"weixin", "feishu"})
        assert m.parity_class == "claude-pro"
        assert m.cost_tier == "premium"

    def test_from_dict_comma_separated_string(self):
        data = {"model_families": "gpt-4,gpt-4o"}
        m = CapabilityManifest.from_dict(data)
        assert m.model_families == frozenset({"gpt-4", "gpt-4o"})

    def test_to_dict_roundtrip(self):
        data = {
            "provider": "openai",
            "model_families": ["gpt-4o"],
            "api_modes": ["chat_completions", "responses"],
            "context_cap": 128000,
            "output_cap": 16384,
            "tool_support": True,
            "vision_support": True,
            "streaming_support": True,
            "channel_entitlements": [],
            "exclusive_entitlements": [],
            "parity_class": "gpt4-tier",
            "cost_tier": "standard",
            "risk_tier": "standard",
        }
        m = CapabilityManifest.from_dict(data)
        d = m.to_dict()
        m2 = CapabilityManifest.from_dict(d)
        assert m == m2

    def test_get_credential_manifest_no_extra(self):
        cred = FakeCredential(id="x", label="test", extra={})
        assert get_credential_manifest(cred) is DEFAULT_MANIFEST

    def test_get_credential_manifest_with_data(self):
        cred = FakeCredential(id="x", label="test", extra={
            "capability_manifest": {"provider": "anthropic", "context_cap": 200000}
        })
        m = get_credential_manifest(cred)
        assert m.provider == "anthropic"
        assert m.context_cap == 200000


# ── Entitlement Isolation Tests (Weixin Pro) ─────────────────────────────


class TestWeixinProIsolation:
    """Tests for hard isolation: non-Weixin-Pro cannot use Weixin-Pro-exclusive credential."""

    def _weixin_pro_credential(self):
        return _make_credential("pro-1", "weixin-pro-cred", {
            "provider": "anthropic",
            "exclusive_entitlements": ["weixin-pro-exclusive"],
            "parity_class": "claude-pro",
            "context_cap": 200000,
        })

    def _standard_credential(self):
        return _make_credential("std-1", "standard-cred", {
            "provider": "anthropic",
            "channel_entitlements": ["weixin", "feishu", "telegram"],
            "parity_class": "claude-standard",
            "context_cap": 200000,
        })

    def test_non_weixin_pro_cannot_use_exclusive_credential(self):
        """Non-Weixin-Pro entry must not consume Weixin-Pro-exclusive credentials."""
        entries = [self._weixin_pro_credential()]
        request = RouteRequest(
            platform="telegram",
            channel="telegram-standard",
            provider="anthropic",
        )
        decision = route_with_capabilities(entries, request)
        assert decision.verdict == RoutingVerdict.blocked
        assert len(decision.skipped) == 1
        assert decision.skipped[0].reason == RoutingFailureReason.exclusive_violation

    def test_feishu_cannot_use_weixin_pro_exclusive(self):
        """Feishu platform must not consume Weixin-Pro-exclusive credentials."""
        entries = [self._weixin_pro_credential()]
        request = RouteRequest(
            platform="feishu",
            channel="feishu-standard",
            provider="anthropic",
        )
        decision = route_with_capabilities(entries, request)
        assert decision.verdict == RoutingVerdict.blocked
        assert decision.skipped[0].reason == RoutingFailureReason.exclusive_violation

    def test_weixin_pro_can_use_exclusive_credential(self):
        """Weixin-Pro entry should successfully use its exclusive credential."""
        entries = [self._weixin_pro_credential()]
        request = RouteRequest(
            platform="weixin",
            channel="weixin-pro-exclusive",
            entitlement="weixin-pro-exclusive",
            provider="anthropic",
        )
        decision = route_with_capabilities(entries, request)
        assert decision.verdict == RoutingVerdict.selected
        assert decision.credential_id == "pro-1"
        assert decision.parity_satisfied is True

    def test_weixin_pro_not_silently_replaced_by_non_pro(self):
        """Weixin-Pro request must not silently fallback to non-Pro credential
        without explicit block/downgrade verdict."""
        entries = [self._standard_credential()]
        request = RouteRequest(
            platform="weixin",
            channel="weixin-pro-exclusive",
            entitlement="weixin-pro-exclusive",
            provider="anthropic",
            required_parity_class="claude-pro",
        )
        decision = route_with_capabilities(entries, request)
        # Standard credential has parity_class="claude-standard" != "claude-pro"
        assert decision.verdict == RoutingVerdict.blocked
        assert decision.parity_satisfied is False

    def test_weixin_pro_downgrade_requires_explicit_verdict(self):
        """With allow_downgrade=True, an entitled but non-parity credential
        returns downgrade verdict rather than silently selecting."""
        cred = _make_credential("weak-pro", "weak-pro-cred", {
            "provider": "anthropic",
            "channel_entitlements": ["weixin-pro-exclusive"],
            "parity_class": "claude-standard",
        })
        entries = [cred]
        request = RouteRequest(
            platform="weixin",
            channel="weixin-pro-exclusive",
            entitlement="weixin-pro-exclusive",
            provider="anthropic",
            required_parity_class="claude-pro",
        )
        decision = route_with_capabilities(entries, request, allow_downgrade=True)
        assert decision.verdict == RoutingVerdict.downgrade
        assert decision.parity_satisfied is False
        assert decision.downgrade_details is not None

    def test_weixin_pro_request_blocks_legacy_credential_without_entitlement(self):
        """Legacy/no-manifest credentials must not satisfy protected Pro requests."""
        legacy = FakeCredential(id="legacy-1", label="legacy-cred", extra={})
        request = RouteRequest(
            platform="weixin",
            channel="weixin-pro-exclusive",
            entitlement="weixin-pro-exclusive",
            provider="anthropic",
        )
        decision = route_with_capabilities([legacy], request)
        assert decision.verdict == RoutingVerdict.blocked
        assert decision.skipped[0].reason == RoutingFailureReason.entitlement_denied

    def test_mixed_pool_routes_correctly(self):
        """Pool with both Pro-exclusive and standard credentials:
        - Pro request gets Pro credential
        - Standard request gets standard credential
        """
        pro_cred = self._weixin_pro_credential()
        std_cred = self._standard_credential()
        entries = [pro_cred, std_cred]

        # Pro request
        pro_request = RouteRequest(
            platform="weixin",
            channel="weixin-pro-exclusive",
            entitlement="weixin-pro-exclusive",
            provider="anthropic",
        )
        decision = route_with_capabilities(entries, pro_request)
        assert decision.verdict == RoutingVerdict.selected
        assert decision.credential_id == "pro-1"

        # Standard request — should skip pro, pick standard
        std_request = RouteRequest(
            platform="telegram",
            channel="telegram-standard",
            provider="anthropic",
        )
        decision = route_with_capabilities(entries, std_request)
        assert decision.verdict == RoutingVerdict.selected
        assert decision.credential_id == "std-1"
        assert len(decision.skipped) == 1
        assert decision.skipped[0].reason == RoutingFailureReason.exclusive_violation


# ── Capability Parity Tests ──────────────────────────────────────────────


class TestCapabilityParity:
    def test_parity_mismatch_blocks_fallback(self):
        """Fallback must satisfy capability parity — mismatch blocks."""
        cred = _make_credential("fallback-1", "weaker-cred", {
            "provider": "anthropic",
            "parity_class": "claude-haiku",
        })
        request = RouteRequest(
            provider="anthropic",
            required_parity_class="claude-sonnet",
        )
        decision = route_with_capabilities([cred], request)
        assert decision.verdict == RoutingVerdict.blocked
        assert any(
            s.reason == RoutingFailureReason.parity_mismatch
            for s in decision.skipped
        )

    def test_parity_match_allows_selection(self):
        cred = _make_credential("match-1", "sonnet-cred", {
            "provider": "anthropic",
            "parity_class": "claude-sonnet",
        })
        request = RouteRequest(
            provider="anthropic",
            required_parity_class="claude-sonnet",
        )
        decision = route_with_capabilities([cred], request)
        assert decision.verdict == RoutingVerdict.selected
        assert decision.credential_id == "match-1"

    def test_no_parity_requirement_accepts_any(self):
        """When request doesn't specify parity_class, any credential works."""
        cred = _make_credential("any-1", "any-cred", {
            "provider": "openai",
            "parity_class": "gpt4-tier",
        })
        request = RouteRequest(provider="openai")
        decision = route_with_capabilities([cred], request)
        assert decision.verdict == RoutingVerdict.selected

    def test_credential_without_parity_class_blocks_when_parity_required(self):
        """Protected fallback requests require an explicit matching parity class."""
        cred = _make_credential("legacy-1", "legacy-cred", {
            "provider": "anthropic",
            # No parity_class specified
        })
        request = RouteRequest(
            provider="anthropic",
            required_parity_class="claude-sonnet",
        )
        decision = route_with_capabilities([cred], request)
        assert decision.verdict == RoutingVerdict.blocked
        assert decision.skipped[0].reason == RoutingFailureReason.parity_mismatch


# ── Feature Requirement Tests ────────────────────────────────────────────


class TestFeatureRequirements:
    def test_tool_support_missing_blocks(self):
        cred = _make_credential("no-tools", "basic-cred", {
            "tool_support": False,
        })
        request = RouteRequest(requires_tools=True)
        decision = route_with_capabilities([cred], request)
        assert decision.verdict == RoutingVerdict.blocked
        assert decision.skipped[0].reason == RoutingFailureReason.tool_support_missing

    def test_vision_support_missing_blocks(self):
        cred = _make_credential("no-vision", "text-only", {
            "vision_support": False,
        })
        request = RouteRequest(requires_vision=True)
        decision = route_with_capabilities([cred], request)
        assert decision.verdict == RoutingVerdict.blocked
        assert decision.skipped[0].reason == RoutingFailureReason.vision_support_missing

    def test_context_cap_insufficient_blocks(self):
        cred = _make_credential("small-ctx", "small-context", {
            "context_cap": 32000,
        })
        request = RouteRequest(min_context=128000)
        decision = route_with_capabilities([cred], request)
        assert decision.verdict == RoutingVerdict.blocked
        assert decision.skipped[0].reason == RoutingFailureReason.context_cap_insufficient

    def test_context_cap_zero_means_unlimited(self):
        """Credential with context_cap=0 (unknown) passes any min_context check."""
        cred = _make_credential("unlimited", "unlimited-cred", {
            "context_cap": 0,
        })
        request = RouteRequest(min_context=200000)
        decision = route_with_capabilities([cred], request)
        assert decision.verdict == RoutingVerdict.selected

    def test_model_family_mismatch_blocks(self):
        cred = _make_credential("wrong-model", "gpt-cred", {
            "model_families": ["gpt-4", "gpt-4o"],
        })
        request = RouteRequest(model_family="claude-4")
        decision = route_with_capabilities([cred], request)
        assert decision.verdict == RoutingVerdict.blocked
        assert decision.skipped[0].reason == RoutingFailureReason.model_family_mismatch

    def test_api_mode_mismatch_blocks(self):
        cred = _make_credential("chat-only", "chat-cred", {
            "api_modes": ["chat_completions"],
        })
        request = RouteRequest(api_mode="codex_responses")
        decision = route_with_capabilities([cred], request)
        assert decision.verdict == RoutingVerdict.blocked
        assert decision.skipped[0].reason == RoutingFailureReason.api_mode_mismatch


# ── Failure Taxonomy Tests ───────────────────────────────────────────────


class TestFailureTaxonomy:
    def test_empty_pool_returns_blocked(self):
        decision = route_with_capabilities([], RouteRequest())
        assert decision.verdict == RoutingVerdict.blocked
        assert "no credentials available" in decision.reasons[0]

    def test_all_filtered_reports_reason_summary(self):
        """When all candidates are filtered, reasons summarize why."""
        creds = [
            _make_credential("a", "cred-a", {"tool_support": False}),
            _make_credential("b", "cred-b", {"vision_support": False}),
        ]
        request = RouteRequest(requires_tools=True, requires_vision=True)
        decision = route_with_capabilities(creds, request)
        assert decision.verdict == RoutingVerdict.blocked
        # Should have 2 skipped entries
        assert len(decision.skipped) == 2

    def test_downgrade_verdict_when_parity_mismatch_and_allowed(self):
        cred = _make_credential("lesser", "lesser-cred", {
            "parity_class": "basic-tier",
        })
        request = RouteRequest(required_parity_class="pro-tier")
        decision = route_with_capabilities([cred], request, allow_downgrade=True)
        assert decision.verdict == RoutingVerdict.downgrade
        assert decision.parity_satisfied is False


# ── Redacted Trace Tests ─────────────────────────────────────────────────


class TestRedactedTrace:
    def test_trace_contains_no_secrets(self):
        """Redacted trace must not contain actual tokens or credentials."""
        cred = FakeCredential(
            id="secret-id-123",
            label="my-cred",
            extra={
                "capability_manifest": {"provider": "anthropic"},
                "access_token": "sk-super-secret-key-12345",
            },
        )
        request = RouteRequest(platform="cli", provider="anthropic")
        decision = route_with_capabilities([cred], request)
        trace = decision.to_redacted_trace()

        trace_str = json.dumps(trace)
        assert "sk-super-secret" not in trace_str
        assert "super-secret-key" not in trace_str
        # But label and reasons should be present
        assert "my-cred" in trace_str
        assert trace["verdict"] == "selected"

    def test_trace_contains_skip_reasons(self):
        cred = _make_credential("pro-only", "weixin-pro", {
            "exclusive_entitlements": ["weixin-pro-exclusive"],
        })
        request = RouteRequest(platform="telegram")
        decision = route_with_capabilities([cred], request)
        trace = decision.to_redacted_trace()

        assert trace["verdict"] == "blocked"
        assert trace["skipped_count"] == 1
        assert trace["skipped_reasons"][0]["reason"] == "exclusive_violation"
        assert "weixin-pro" in trace["skipped_reasons"][0]["label"]

    def test_trace_has_timestamp(self):
        decision = route_with_capabilities([], RouteRequest())
        trace = decision.to_redacted_trace()
        assert "timestamp" in trace
        assert isinstance(trace["timestamp"], float)


# ── Integration with CredentialPool ──────────────────────────────────────


def _write_auth_store(tmp_path, payload: dict) -> None:
    hermes_home = tmp_path / "hermes"
    hermes_home.mkdir(parents=True, exist_ok=True)
    (hermes_home / "auth.json").write_text(json.dumps(payload, indent=2))


class TestCredentialPoolIntegration:
    def test_select_with_capabilities_backward_compat(self, tmp_path, monkeypatch):
        """Credentials without manifests still work via default permissive manifest."""
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
        _write_auth_store(tmp_path, {
            "version": 1,
            "credential_pool": {
                "anthropic": [
                    {
                        "id": "legacy-1",
                        "label": "legacy-key",
                        "auth_type": "api_key",
                        "priority": 0,
                        "source": "manual",
                        "access_token": "***",
                        "last_status": "ok",
                    }
                ]
            },
        })
        from agent.credential_pool import load_pool

        pool = load_pool("anthropic")
        request = RouteRequest(provider="anthropic", requires_tools=True)
        entry, decision = pool.select_with_capabilities(request)

        assert entry is not None
        assert entry.id == "legacy-1"
        assert decision.verdict == RoutingVerdict.selected
        assert decision.parity_satisfied is True

    def test_select_with_capabilities_entitlement_isolation(self, tmp_path, monkeypatch):
        """Integration: pool with manifest enforces entitlement isolation."""
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
        _write_auth_store(tmp_path, {
            "version": 1,
            "credential_pool": {
                "anthropic": [
                    {
                        "id": "pro-1",
                        "label": "weixin-pro",
                        "auth_type": "api_key",
                        "priority": 0,
                        "source": "manual",
                        "access_token": "***",
                        "last_status": "ok",
                        "capability_manifest": {
                            "provider": "anthropic",
                            "exclusive_entitlements": ["weixin-pro-exclusive"],
                            "parity_class": "claude-pro",
                        },
                    },
                    {
                        "id": "std-1",
                        "label": "standard",
                        "auth_type": "api_key",
                        "priority": 1,
                        "source": "manual",
                        "access_token": "***",
                        "last_status": "ok",
                    },
                ]
            },
        })
        from agent.credential_pool import load_pool

        pool = load_pool("anthropic")

        # Telegram request should NOT get the pro credential
        telegram_request = RouteRequest(
            platform="telegram",
            channel="telegram-standard",
            provider="anthropic",
        )
        entry, decision = pool.select_with_capabilities(telegram_request)
        assert entry is not None
        assert entry.id == "std-1"  # Gets standard, not pro
        assert decision.verdict == RoutingVerdict.selected

        # Weixin Pro request should get the pro credential
        pro_request = RouteRequest(
            platform="weixin",
            channel="weixin-pro-exclusive",
            entitlement="weixin-pro-exclusive",
            provider="anthropic",
        )
        entry, decision = pool.select_with_capabilities(pro_request)
        assert entry is not None
        assert entry.id == "pro-1"
        assert decision.verdict == RoutingVerdict.selected

    def test_select_with_capabilities_exhausted_pool(self, tmp_path, monkeypatch):
        """Integration: all entries exhausted returns blocked decision."""
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
        _write_auth_store(tmp_path, {
            "version": 1,
            "credential_pool": {
                "anthropic": [
                    {
                        "id": "exhausted-1",
                        "label": "tired-cred",
                        "auth_type": "api_key",
                        "priority": 0,
                        "source": "manual",
                        "access_token": "***",
                        "last_status": "exhausted",
                        "last_status_at": time.time(),
                        "last_error_code": 429,
                    }
                ]
            },
        })
        from agent.credential_pool import load_pool

        pool = load_pool("anthropic")
        request = RouteRequest(provider="anthropic")
        entry, decision = pool.select_with_capabilities(request)

        assert entry is None
        assert decision.verdict == RoutingVerdict.blocked
        assert "exhausted or empty" in decision.reasons[0]

    def test_capability_manifest_persists_in_auth_json(self, tmp_path, monkeypatch):
        """Manifest stored in credential extra round-trips through auth.json."""
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
        manifest_data = {
            "provider": "anthropic",
            "exclusive_entitlements": ["weixin-pro-exclusive"],
            "parity_class": "claude-pro",
            "context_cap": 200000,
        }
        _write_auth_store(tmp_path, {
            "version": 1,
            "credential_pool": {
                "anthropic": [
                    {
                        "id": "persist-1",
                        "label": "persist-test",
                        "auth_type": "api_key",
                        "priority": 0,
                        "source": "manual",
                        "access_token": "***",
                        "last_status": "ok",
                        "capability_manifest": manifest_data,
                    }
                ]
            },
        })
        from agent.credential_pool import load_pool

        pool = load_pool("anthropic")
        entry = pool.select()
        assert entry is not None

        # Check manifest is accessible
        manifest = get_credential_manifest(entry)
        assert manifest.provider == "anthropic"
        assert manifest.exclusive_entitlements == frozenset({"weixin-pro-exclusive"})
        assert manifest.parity_class == "claude-pro"
        assert manifest.context_cap == 200000

        # Verify it persists in to_dict()
        d = entry.to_dict()
        assert "capability_manifest" in d
        assert d["capability_manifest"]["provider"] == "anthropic"
