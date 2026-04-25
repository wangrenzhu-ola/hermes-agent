"""Child executor abstraction for Codex PMO Ledger Runner."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Mapping

try:
    from .ledger import now_iso, write_json_artifact
    from .validator import ValidationError, validate_approval_policy, validate_sandbox
except ImportError:
    from ledger import now_iso, write_json_artifact  # type: ignore
    from validator import ValidationError, validate_approval_policy, validate_sandbox  # type: ignore


class ChildExecutor:
    """Interface for one PMO-controlled child task."""

    name = "base"

    def execute(
        self,
        *,
        ledger: Mapping[str, Any],
        task: Mapping[str, Any],
        artifact_dir: Path,
        cwd: Path,
        timeout: float,
        poll_interval: float,
    ) -> dict[str, Any]:
        raise NotImplementedError


def _artifact_path(artifact_dir: Path, child_id: str) -> Path:
    return artifact_dir / f"{child_id}.json"


def _base_child_result(
    *,
    child_id: str,
    ledger: Mapping[str, Any],
    task: Mapping[str, Any],
    started_at: str,
    ended_at: str,
    artifact_path: Path,
    status: str = "done",
    result: str = "pass",
    summary: str,
    validation_status: str = "pass",
    executor_name: str,
    approval_policy: str = "on-request",
) -> dict[str, Any]:
    return {
        "child_id": child_id,
        "phase": task.get("phase"),
        "status": status,
        "result": result,
        "model": f"{executor_name}-executor",
        "effort": "low",
        "sandbox": "read-only",
        "approval_policy": validate_approval_policy(approval_policy),
        "started_at": started_at,
        "ended_at": ended_at,
        "artifacts": [{"path": str(artifact_path), "kind": "child_result", "status": "created"}],
        "summary": summary,
        "validation": [
            {
                "name": f"{executor_name}_child_contract",
                "status": validation_status,
                "method": executor_name,
                "checked_at": ended_at,
            }
        ],
        "risks": [],
        "next_recommendation": {
            "action": "observe_ledger",
            "reason": "P0 child smoke completed; PMO recorded the result in the ledger.",
        },
    }


class FakeChildExecutor(ChildExecutor):
    """Deterministic executor used by tests and local CLI smoke checks."""

    name = "fake"

    def execute(
        self,
        *,
        ledger: Mapping[str, Any],
        task: Mapping[str, Any],
        artifact_dir: Path,
        cwd: Path,
        timeout: float,
        poll_interval: float,
    ) -> dict[str, Any]:
        del cwd, timeout, poll_interval
        started_at = now_iso()
        child_id = f"fake-{ledger.get('task_id')}-{task.get('allowed_child_kind')}-{int(time.time() * 1000)}"
        artifact_path = _artifact_path(artifact_dir, child_id)
        ended_at = now_iso()
        result = _base_child_result(
            child_id=child_id,
            ledger=ledger,
            task=task,
            started_at=started_at,
            ended_at=ended_at,
            artifact_path=artifact_path,
            summary=f"Fake child completed {task.get('allowed_child_kind')} for {ledger.get('task_id')}.",
            executor_name=self.name,
        )
        write_json_artifact(
            artifact_path,
            {
                "executor": self.name,
                "ledger_task_id": ledger.get("task_id"),
                "task": dict(task),
                "child_result": result,
            },
        )
        return result


class CodexBridgeChildExecutor(ChildExecutor):
    """Real read-only child Codex smoke through the existing Codex Bridge tool."""

    name = "codex-bridge"

    def __init__(self, *, model: str | None = None, approval_policy: str = "on-request") -> None:
        self.model = model
        self.approval_policy = validate_approval_policy(approval_policy)

    def _call_bridge(self, action: str, **kwargs: Any) -> dict[str, Any]:
        from tools.codex_bridge_tool import codex_bridge

        raw = codex_bridge(action=action, **kwargs)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"codex_bridge returned invalid JSON for {action}: {exc.msg}") from exc
        if data.get("success") is not True:
            raise ValidationError(str(data.get("error") or f"codex_bridge {action} failed."))
        return data

    def execute(
        self,
        *,
        ledger: Mapping[str, Any],
        task: Mapping[str, Any],
        artifact_dir: Path,
        cwd: Path,
        timeout: float,
        poll_interval: float,
    ) -> dict[str, Any]:
        sandbox = validate_sandbox("read-only")
        prompt = build_read_only_prompt(ledger, task)
        started_at = now_iso()
        started = self._call_bridge(
            "start",
            prompt=prompt,
            cwd=str(cwd),
            model=self.model,
            sandbox=sandbox,
            approval_policy=self.approval_policy,
            codex_home=None,
            notify_target=None,
        )
        bridge_task = started.get("task") or {}
        child_id = str(bridge_task.get("hermes_task_id") or f"codex-bridge-{int(time.time() * 1000)}")
        deadline = time.monotonic() + timeout
        final_status: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            time.sleep(poll_interval)
            final_status = self._call_bridge("status", task_id=child_id)
            status = ((final_status.get("task") or {}).get("status") or "").lower()
            if status in {"completed", "failed", "cancelled"}:
                break
        ended_at = now_iso()
        task_status = ((final_status or {}).get("task") or {}).get("status")
        status = "done" if task_status == "completed" else "failed"
        result = "pass" if status == "done" else "failed"
        artifact_path = _artifact_path(artifact_dir, child_id)
        child_result = _base_child_result(
            child_id=child_id,
            ledger=ledger,
            task=task,
            started_at=started_at,
            ended_at=ended_at,
            artifact_path=artifact_path,
            status=status,
            result=result,
            summary=f"Codex Bridge child finished with status {task_status!r}.",
            validation_status="pass" if status == "done" else "failed",
            executor_name=self.name,
            approval_policy=self.approval_policy,
        )
        child_result["bridge"] = {"start": started, "final_status": final_status}
        write_json_artifact(artifact_path, {"child_result": child_result})
        return child_result


def build_read_only_prompt(ledger: Mapping[str, Any], task: Mapping[str, Any]) -> str:
    return (
        "You are a read-only child Codex worker under a PMO ledger runner.\n"
        "Do not modify files. Do not commit, push, or open a PR.\n"
        f"Ledger task: {ledger.get('task_id')} - {ledger.get('title')}.\n"
        f"Phase: {task.get('phase')}. Child kind: {task.get('allowed_child_kind')}.\n"
        "Inspect only enough context to confirm the ledger is readable and the P0 child dispatch smoke ran.\n"
        "Reply with a concise summary, risks if any, and the literal marker PMO_CHILD_SMOKE_OK."
    )


def get_executor(name: str, *, model: str | None = None, approval_policy: str = "on-request") -> ChildExecutor:
    if name == "fake":
        return FakeChildExecutor()
    if name == "codex-bridge":
        return CodexBridgeChildExecutor(model=model, approval_policy=approval_policy)
    raise ValidationError("executor must be one of: fake, codex-bridge.")
