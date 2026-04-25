"""Validation helpers for the Codex PMO Ledger Runner reference CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


RUNNER_VERSION = "0.1.0"
ALLOWED_LEDGER_STATUSES = {"queued", "running", "needs-user", "blocked", "failed", "done"}
ALLOWED_PHASES = {"brainstorm_plan", "document_review", "work", "review", "compound", "done"}
P0_READ_ONLY_PHASES = {"brainstorm_plan", "document_review", "review"}
P0_SUPPORTED_TASK_KINDS = {"document_review_smoke", "ledger_validation_smoke"}
ALLOWED_CHILD_STATUSES = {"done", "failed", "blocked", "needs-user", "invalid_output"}
ALLOWED_SANDBOXES = {"read-only", "workspace-write"}
ALLOWED_APPROVAL_POLICIES = {"untrusted", "on-request"}
STATUS_CONTRACT_FIELDS = [
    "task_id",
    "title",
    "phase",
    "status",
    "result",
    "next_action",
    "blocking_decisions",
    "high_risks",
    "recent_children",
    "artifacts",
    "validation_summary",
    "budget_summary",
    "locks",
    "audit_tail",
]
CHILD_RESULT_REQUIRED_FIELDS = [
    "child_id",
    "phase",
    "status",
    "result",
    "model",
    "effort",
    "sandbox",
    "approval_policy",
    "started_at",
    "ended_at",
    "artifacts",
    "summary",
    "validation",
    "risks",
    "next_recommendation",
]


class ValidationError(ValueError):
    """Raised when a ledger, command input, or child output is invalid."""


def _require_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError(f"{field} must be an object.")
    return value


def _require_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValidationError(f"{field} must be a list.")
    return value


def validate_sandbox(sandbox: str) -> str:
    if sandbox == "danger-full-access":
        raise ValidationError("danger-full-access is not allowed for PMO child tasks.")
    if sandbox not in ALLOWED_SANDBOXES:
        allowed = ", ".join(sorted(ALLOWED_SANDBOXES))
        raise ValidationError(f"sandbox must be one of: {allowed}.")
    return sandbox


def validate_approval_policy(approval_policy: str) -> str:
    if approval_policy == "never":
        raise ValidationError("approval_policy=never is not allowed for PMO child tasks.")
    if approval_policy not in ALLOWED_APPROVAL_POLICIES:
        allowed = ", ".join(sorted(ALLOWED_APPROVAL_POLICIES))
        raise ValidationError(f"approval_policy must be one of: {allowed}.")
    return approval_policy


def document_review_passed(ledger: Mapping[str, Any]) -> bool:
    phases = _require_mapping(ledger.get("phases"), "phases")
    document_review = _require_mapping(phases.get("document_review"), "phases.document_review")
    return document_review.get("status") == "done" and document_review.get("result") == "pass"


def validate_work_gate(ledger: Mapping[str, Any]) -> None:
    phase = ledger.get("phase")
    tasks = ledger.get("tasks") or []
    wants_work = phase == "work" or any(isinstance(task, Mapping) and task.get("phase") == "work" for task in tasks)
    if wants_work and not document_review_passed(ledger):
        raise ValidationError("work phase is blocked until document_review.status=done and result=pass.")


def validate_p0_task(task: Mapping[str, Any]) -> None:
    phase = task.get("phase")
    kind = task.get("allowed_child_kind")
    sandbox = task.get("sandbox", "read-only")
    if phase == "work":
        raise ValidationError("P0 run-once cannot launch work phase tasks.")
    if phase not in P0_READ_ONLY_PHASES:
        raise ValidationError(f"P0 task phase must be read-only, got {phase!r}.")
    if kind not in P0_SUPPORTED_TASK_KINDS:
        allowed = ", ".join(sorted(P0_SUPPORTED_TASK_KINDS))
        raise ValidationError(f"P0 task allowed_child_kind must be one of: {allowed}.")
    if sandbox != "read-only":
        raise ValidationError("P0 child task sandbox must be read-only.")


def validate_ledger(ledger: Mapping[str, Any], *, artifact_base: Path | None = None) -> None:
    required = [
        "schema_version",
        "runner_version",
        "task_id",
        "title",
        "phase",
        "status",
        "repo",
        "storage",
        "policy",
        "scheduler",
        "tasks",
        "phases",
        "children",
        "artifacts",
        "validation",
        "risks",
        "decisions_needed",
        "next_action",
        "locks",
        "audit",
    ]
    for field in required:
        if field not in ledger:
            raise ValidationError(f"ledger missing required field: {field}.")

    if ledger.get("schema_version") != 1:
        raise ValidationError("schema_version must be 1.")
    if ledger.get("phase") not in ALLOWED_PHASES:
        raise ValidationError(f"phase must be one of: {', '.join(sorted(ALLOWED_PHASES))}.")
    if ledger.get("status") not in ALLOWED_LEDGER_STATUSES:
        raise ValidationError(f"status must be one of: {', '.join(sorted(ALLOWED_LEDGER_STATUSES))}.")

    policy = _require_mapping(ledger.get("policy"), "policy")
    default_sandbox = validate_sandbox(str(policy.get("default_sandbox", "")))
    if default_sandbox != "read-only":
        raise ValidationError("policy.default_sandbox must be read-only for P0.")
    approval_policy = validate_approval_policy(str(policy.get("approval_policy", "")))
    if approval_policy != "on-request":
        raise ValidationError("policy.approval_policy must default to on-request for P0.")
    if policy.get("danger_full_access_allowed") is not False:
        raise ValidationError("policy.danger_full_access_allowed must be false.")
    if policy.get("approval_policy_never_allowed") is not False:
        raise ValidationError("policy.approval_policy_never_allowed must be false.")
    if policy.get("mailbox_as_primary_transport") is not False:
        raise ValidationError("policy.mailbox_as_primary_transport must be false.")

    _require_mapping(ledger.get("repo"), "repo")
    _require_mapping(ledger.get("storage"), "storage")
    _require_mapping(ledger.get("scheduler"), "scheduler")
    _require_mapping(ledger.get("phases"), "phases")
    _require_mapping(ledger.get("locks"), "locks")
    _require_list(ledger.get("tasks"), "tasks")
    _require_list(ledger.get("children"), "children")
    _require_list(ledger.get("artifacts"), "artifacts")
    _require_list(ledger.get("validation"), "validation")
    _require_list(ledger.get("risks"), "risks")
    _require_list(ledger.get("decisions_needed"), "decisions_needed")
    _require_list(ledger.get("audit"), "audit")

    validate_work_gate(ledger)

    base = artifact_base or Path.cwd()
    for artifact in ledger.get("artifacts") or []:
        if not isinstance(artifact, Mapping) or not artifact.get("path"):
            continue
        path = Path(str(artifact["path"]))
        if not path.is_absolute():
            path = base / path
        if artifact.get("status") in {None, "created", "done", "pass"} and not path.exists():
            raise ValidationError(f"artifact path does not exist: {artifact['path']}.")


def collect_ledger_errors(ledger: Mapping[str, Any], *, artifact_base: Path | None = None) -> list[str]:
    try:
        validate_ledger(ledger, artifact_base=artifact_base)
    except ValidationError as exc:
        return [str(exc)]
    return []


def validate_status_summary(summary: Mapping[str, Any]) -> None:
    for field in STATUS_CONTRACT_FIELDS:
        if field not in summary:
            raise ValidationError(f"status summary missing required field: {field}.")


def validate_child_result(result: Mapping[str, Any], *, artifact_base: Path | None = None) -> None:
    for field in CHILD_RESULT_REQUIRED_FIELDS:
        if field not in result:
            raise ValidationError(f"child result missing required field: {field}.")
    if result.get("status") not in ALLOWED_CHILD_STATUSES:
        raise ValidationError("child result status is not allowed.")
    if result.get("phase") == "work":
        raise ValidationError("P0 child result cannot be for work phase.")
    if result.get("sandbox") != "read-only":
        raise ValidationError("P0 child result sandbox must be read-only.")
    validate_approval_policy(str(result.get("approval_policy")))

    artifacts = _require_list(result.get("artifacts"), "child result artifacts")
    if not artifacts:
        raise ValidationError("child result must include at least one artifact.")
    base = artifact_base or Path.cwd()
    for artifact in artifacts:
        if isinstance(artifact, Mapping):
            raw_path = artifact.get("path")
        else:
            raw_path = artifact
        if not raw_path:
            raise ValidationError("child result artifact missing path.")
        path = Path(str(raw_path))
        if not path.is_absolute():
            path = base / path
        if not path.exists():
            raise ValidationError(f"child result artifact does not exist: {raw_path}.")

    _require_list(result.get("validation"), "child result validation")
    _require_list(result.get("risks"), "child result risks")
    _require_mapping(result.get("next_recommendation"), "child result next_recommendation")
