"""Agent-Native Credential Capability Router.

Upgrades credential pool selection from availability-based failover to
capability-aware routing with:
- Capability manifest per credential (model family, context cap, tools, entitlements)
- Entitlement isolation (e.g. weixin-pro-exclusive hard boundary)
- Capability parity enforcement on fallback
- Structured failure taxonomy for routing decisions
- Redacted audit trace (no secrets exposed)

Designed to layer on top of the existing CredentialPool without breaking
backward compatibility — credentials without manifests get a permissive
default manifest that preserves existing behavior.
"""

from __future__ import annotations

import enum
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ── Capability Manifest ─────────────────────────────────────────────────


@dataclass(frozen=True)
class CapabilityManifest:
    """Machine-readable capability declaration for a credential.

    Credentials without an explicit manifest get DEFAULT_MANIFEST which
    is maximally permissive — preserving existing pool behavior.
    """

    # Provider / model constraints
    provider: str = ""
    model_families: FrozenSet[str] = frozenset()  # e.g. {"gpt-4", "gpt-4o"}
    api_modes: FrozenSet[str] = frozenset()  # e.g. {"chat_completions", "responses"}

    # Capacity
    context_cap: int = 0  # 0 = unknown/unlimited
    output_cap: int = 0

    # Tool / feature support
    tool_support: bool = True
    vision_support: bool = True
    streaming_support: bool = True

    # Channel entitlements — which platforms/entry points may use this credential
    channel_entitlements: FrozenSet[str] = frozenset()  # empty = unrestricted
    # Exclusive entitlements — ONLY these channels may use; others are denied
    exclusive_entitlements: FrozenSet[str] = frozenset()  # empty = not exclusive

    # Capability parity class — credentials in the same class are interchangeable
    parity_class: str = ""  # empty = unique / no parity group

    # Cost / risk tier
    cost_tier: str = "standard"  # "free", "standard", "premium"
    risk_tier: str = "standard"  # "low", "standard", "high"

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "CapabilityManifest":
        """Parse manifest from credential's extra or config dict."""
        if not data:
            return DEFAULT_MANIFEST

        def _frozen_set(val: Any) -> FrozenSet[str]:
            if isinstance(val, (list, tuple, set, frozenset)):
                return frozenset(str(x) for x in val)
            if isinstance(val, str) and val:
                return frozenset(val.split(","))
            return frozenset()

        return cls(
            provider=str(data.get("provider", "") or ""),
            model_families=_frozen_set(data.get("model_families")),
            api_modes=_frozen_set(data.get("api_modes")),
            context_cap=int(data.get("context_cap", 0) or 0),
            output_cap=int(data.get("output_cap", 0) or 0),
            tool_support=bool(data.get("tool_support", True)),
            vision_support=bool(data.get("vision_support", True)),
            streaming_support=bool(data.get("streaming_support", True)),
            channel_entitlements=_frozen_set(data.get("channel_entitlements")),
            exclusive_entitlements=_frozen_set(data.get("exclusive_entitlements")),
            parity_class=str(data.get("parity_class", "") or ""),
            cost_tier=str(data.get("cost_tier", "standard") or "standard"),
            risk_tier=str(data.get("risk_tier", "standard") or "standard"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to JSON-safe dict for persistence."""
        return {
            "provider": self.provider,
            "model_families": sorted(self.model_families) if self.model_families else [],
            "api_modes": sorted(self.api_modes) if self.api_modes else [],
            "context_cap": self.context_cap,
            "output_cap": self.output_cap,
            "tool_support": self.tool_support,
            "vision_support": self.vision_support,
            "streaming_support": self.streaming_support,
            "channel_entitlements": sorted(self.channel_entitlements) if self.channel_entitlements else [],
            "exclusive_entitlements": sorted(self.exclusive_entitlements) if self.exclusive_entitlements else [],
            "parity_class": self.parity_class,
            "cost_tier": self.cost_tier,
            "risk_tier": self.risk_tier,
        }


# Default manifest — maximally permissive, preserves backward compat
DEFAULT_MANIFEST = CapabilityManifest()


# ── Route Request ───────────────────────────────────────────────────────


@dataclass
class RouteRequest:
    """Describes what capabilities are needed for a routing decision."""

    # Source context
    platform: str = ""  # e.g. "weixin", "telegram", "cli"
    channel: str = ""  # e.g. "weixin-pro", "feishu-standard"
    entitlement: str = ""  # specific entitlement claim, e.g. "weixin-pro-exclusive"

    # Required capabilities
    provider: str = ""
    model_family: str = ""
    api_mode: str = ""
    min_context: int = 0
    requires_tools: bool = False
    requires_vision: bool = False
    requires_streaming: bool = False

    # Parity constraint — if set, fallback must be in same parity class
    required_parity_class: str = ""


# ── Routing Failure Taxonomy ────────────────────────────────────────────


class RoutingFailureReason(enum.Enum):
    """Why a credential was skipped or route failed."""

    # Entitlement violations
    entitlement_denied = "entitlement_denied"  # request lacks required entitlement
    exclusive_violation = "exclusive_violation"  # credential is exclusive to other channels

    # Capability mismatches
    provider_mismatch = "provider_mismatch"
    model_family_mismatch = "model_family_mismatch"
    api_mode_mismatch = "api_mode_mismatch"
    context_cap_insufficient = "context_cap_insufficient"
    tool_support_missing = "tool_support_missing"
    vision_support_missing = "vision_support_missing"
    streaming_support_missing = "streaming_support_missing"

    # Parity violations
    parity_mismatch = "parity_mismatch"  # fallback not in same parity class

    # Availability (from existing pool)
    exhausted = "exhausted"  # credential in cooldown
    no_candidates = "no_candidates"  # pool empty after filtering

    # Composite
    all_filtered = "all_filtered"  # every candidate was filtered out


# ── Routing Verdict ─────────────────────────────────────────────────────


class RoutingVerdict(enum.Enum):
    """Outcome of a routing decision."""

    selected = "selected"  # credential selected, proceed
    downgrade = "downgrade"  # fallback with lesser capabilities (requires confirmation)
    blocked = "blocked"  # cannot route, must abort or escalate


@dataclass
class RoutingDecision:
    """Result of a capability-aware routing decision."""

    verdict: RoutingVerdict
    credential_id: Optional[str] = None
    credential_label: Optional[str] = None

    # Why this decision was made
    reasons: List[str] = field(default_factory=list)
    skipped: List["SkippedCandidate"] = field(default_factory=list)

    # Parity status
    parity_satisfied: bool = True
    downgrade_details: Optional[str] = None

    # Timing
    timestamp: float = field(default_factory=time.time)

    def to_redacted_trace(self) -> Dict[str, Any]:
        """Generate audit trace with no secrets."""
        return {
            "verdict": self.verdict.value,
            "credential_label": self.credential_label,
            "parity_satisfied": self.parity_satisfied,
            "reasons": self.reasons,
            "skipped_count": len(self.skipped),
            "skipped_reasons": [s.to_redacted() for s in self.skipped],
            "downgrade_details": self.downgrade_details,
            "timestamp": self.timestamp,
        }


@dataclass
class SkippedCandidate:
    """Why a specific credential was not selected."""

    credential_label: str  # redacted label, never the actual token
    reason: RoutingFailureReason
    detail: str = ""

    def to_redacted(self) -> Dict[str, str]:
        return {
            "label": self.credential_label,
            "reason": self.reason.value,
            "detail": self.detail,
        }


# ── Capability Router ───────────────────────────────────────────────────


def get_credential_manifest(credential) -> CapabilityManifest:
    """Extract capability manifest from a PooledCredential.

    Looks for 'capability_manifest' in the credential's extra dict.
    Returns DEFAULT_MANIFEST if not present (backward compatible).
    """
    extra = getattr(credential, "extra", None) or {}
    manifest_data = extra.get("capability_manifest")
    if manifest_data:
        return CapabilityManifest.from_dict(manifest_data)
    return DEFAULT_MANIFEST


def route_with_capabilities(
    entries: List[Any],  # List[PooledCredential]
    request: RouteRequest,
    *,
    allow_downgrade: bool = False,
) -> RoutingDecision:
    """Route a request to the best capability-matched credential.

    Args:
        entries: Available (non-exhausted) PooledCredential list.
        request: What capabilities the caller needs.
        allow_downgrade: If True, may return a downgrade verdict instead of blocked.

    Returns:
        RoutingDecision with verdict, selected credential, and trace.
    """
    if not entries:
        return RoutingDecision(
            verdict=RoutingVerdict.blocked,
            reasons=["no credentials available in pool"],
        )

    candidates: List[Any] = []
    skipped: List[SkippedCandidate] = []

    for entry in entries:
        manifest = get_credential_manifest(entry)
        skip_reason = _check_entry_eligibility(entry, manifest, request)
        if skip_reason:
            skipped.append(skip_reason)
        else:
            candidates.append(entry)

    if not candidates:
        # Check if we can offer a downgrade
        if allow_downgrade and skipped:
            # Find the least-bad candidate (parity mismatch preferred over entitlement denial)
            downgradeable = [
                s for s in skipped
                if s.reason == RoutingFailureReason.parity_mismatch
            ]
            if downgradeable:
                return RoutingDecision(
                    verdict=RoutingVerdict.downgrade,
                    reasons=["no parity-equivalent credential available"],
                    skipped=skipped,
                    parity_satisfied=False,
                    downgrade_details=f"best candidate ({downgradeable[0].credential_label}) "
                                     f"does not satisfy parity class requirement",
                )

        # Determine the primary blocking reason
        primary_reasons = _summarize_skip_reasons(skipped)
        return RoutingDecision(
            verdict=RoutingVerdict.blocked,
            reasons=primary_reasons,
            skipped=skipped,
            parity_satisfied=False,
        )

    # Select best from candidates (preserve existing priority order)
    selected = candidates[0]
    label = getattr(selected, "label", None) or getattr(selected, "id", "unknown")[:8]

    return RoutingDecision(
        verdict=RoutingVerdict.selected,
        credential_id=getattr(selected, "id", None),
        credential_label=label,
        reasons=[f"capability match: {label}"],
        skipped=skipped,
        parity_satisfied=True,
    )


def _check_entry_eligibility(
    entry: Any,
    manifest: CapabilityManifest,
    request: RouteRequest,
) -> Optional[SkippedCandidate]:
    """Check if a credential entry satisfies the route request.

    Returns None if eligible, or a SkippedCandidate explaining why not.
    """
    label = getattr(entry, "label", None) or getattr(entry, "id", "unknown")[:8]

    # --- Entitlement isolation (HARD boundary) ---

    # If credential has exclusive_entitlements, request must match one
    if manifest.exclusive_entitlements:
        request_channels = _request_entitlement_set(request)
        if not (manifest.exclusive_entitlements & request_channels):
            return SkippedCandidate(
                credential_label=label,
                reason=RoutingFailureReason.exclusive_violation,
                detail=f"credential is exclusive to {sorted(manifest.exclusive_entitlements)}; "
                       f"request from '{request.channel or request.platform}' denied",
            )

    # If request has a specific entitlement, credential must explicitly allow it.
    # A credential with no entitlement metadata is backward-compatible only for
    # generic requests; it must not satisfy protected entitlement requests.
    if request.entitlement:
        allowed_entitlements = manifest.exclusive_entitlements | manifest.channel_entitlements
        if request.entitlement not in allowed_entitlements:
            if manifest.exclusive_entitlements:
                detail = (f"request requires '{request.entitlement}' but credential "
                          f"is exclusive to {sorted(manifest.exclusive_entitlements)}")
            elif manifest.channel_entitlements:
                detail = f"request requires '{request.entitlement}' not in credential entitlements"
            else:
                detail = f"request requires protected entitlement '{request.entitlement}' but credential declares none"
            return SkippedCandidate(
                credential_label=label,
                reason=RoutingFailureReason.entitlement_denied,
                detail=detail,
            )

    # --- Provider match ---
    if request.provider and manifest.provider:
        if manifest.provider != request.provider:
            return SkippedCandidate(
                credential_label=label,
                reason=RoutingFailureReason.provider_mismatch,
                detail=f"need {request.provider}, have {manifest.provider}",
            )

    # --- Model family match ---
    if request.model_family and manifest.model_families:
        if request.model_family not in manifest.model_families:
            return SkippedCandidate(
                credential_label=label,
                reason=RoutingFailureReason.model_family_mismatch,
                detail=f"need {request.model_family}, "
                       f"have {sorted(manifest.model_families)}",
            )

    # --- API mode match ---
    if request.api_mode and manifest.api_modes:
        if request.api_mode not in manifest.api_modes:
            return SkippedCandidate(
                credential_label=label,
                reason=RoutingFailureReason.api_mode_mismatch,
                detail=f"need {request.api_mode}, have {sorted(manifest.api_modes)}",
            )

    # --- Context cap ---
    if request.min_context and manifest.context_cap:
        if manifest.context_cap < request.min_context:
            return SkippedCandidate(
                credential_label=label,
                reason=RoutingFailureReason.context_cap_insufficient,
                detail=f"need {request.min_context}, cap is {manifest.context_cap}",
            )

    # --- Feature support ---
    if request.requires_tools and not manifest.tool_support:
        return SkippedCandidate(
            credential_label=label,
            reason=RoutingFailureReason.tool_support_missing,
            detail="credential does not support tool calling",
        )

    if request.requires_vision and not manifest.vision_support:
        return SkippedCandidate(
            credential_label=label,
            reason=RoutingFailureReason.vision_support_missing,
            detail="credential does not support vision",
        )

    if request.requires_streaming and not manifest.streaming_support:
        return SkippedCandidate(
            credential_label=label,
            reason=RoutingFailureReason.streaming_support_missing,
            detail="credential does not support streaming",
        )

    # --- Parity class ---
    if request.required_parity_class:
        if manifest.parity_class != request.required_parity_class:
            return SkippedCandidate(
                credential_label=label,
                reason=RoutingFailureReason.parity_mismatch,
                detail=f"need parity class '{request.required_parity_class}', "
                       f"have '{manifest.parity_class or 'undeclared'}'",
            )

    return None  # Entry is eligible


def _request_entitlement_set(request: RouteRequest) -> Set[str]:
    """Collect all entitlement identifiers from a request."""
    result: Set[str] = set()
    if request.entitlement:
        result.add(request.entitlement)
    if request.channel:
        result.add(request.channel)
    if request.platform:
        result.add(request.platform)
    return result


def _summarize_skip_reasons(skipped: List[SkippedCandidate]) -> List[str]:
    """Summarize skip reasons into human-readable list."""
    if not skipped:
        return ["no candidates available"]

    reason_counts: Dict[str, int] = {}
    for s in skipped:
        key = s.reason.value
        reason_counts[key] = reason_counts.get(key, 0) + 1

    return [
        f"{reason}: {count} credential(s)"
        for reason, count in sorted(reason_counts.items())
    ]
