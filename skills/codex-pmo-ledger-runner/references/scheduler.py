"""One-shot scheduler for P0 PMO child dispatch."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

try:
    from .child_executor import ChildExecutor
    from .ledger import append_audit, load_ledger, now_iso, save_ledger
    from .validator import ValidationError, validate_child_result, validate_p0_task, validate_work_gate
except ImportError:
    from child_executor import ChildExecutor  # type: ignore
    from ledger import append_audit, load_ledger, now_iso, save_ledger  # type: ignore
    from validator import ValidationError, validate_child_result, validate_p0_task, validate_work_gate  # type: ignore


def _running_count(ledgers: list[Mapping[str, Any]]) -> int:
    total = 0
    for ledger in ledgers:
        for task in ledger.get("tasks", []) or []:
            if isinstance(task, Mapping) and task.get("status") == "running":
                total += 1
        for child in ledger.get("children", []) or []:
            if isinstance(child, Mapping) and child.get("status") == "running":
                total += 1
    return total


def _task_key(ledger: Mapping[str, Any], task: Mapping[str, Any]) -> str:
    return f"{ledger.get('task_id')}:{task.get('task_id') or task.get('allowed_child_kind')}"


def _append_child_outputs(ledger: dict[str, Any], child_result: Mapping[str, Any]) -> None:
    ledger.setdefault("children", []).append(dict(child_result))
    ledger.setdefault("validation", []).extend(child_result.get("validation") or [])
    for artifact in child_result.get("artifacts") or []:
        if isinstance(artifact, Mapping):
            ledger.setdefault("artifacts", []).append(dict(artifact))
    for risk in child_result.get("risks") or []:
        if isinstance(risk, Mapping):
            ledger.setdefault("risks", []).append(dict(risk))
    ledger["next_action"] = child_result.get("next_recommendation")
    budget = ledger.setdefault("budget", {})
    budget["children_started"] = int(budget.get("children_started") or 0) + 1


def _set_task_status(task: dict[str, Any], status: str, *, reason: str | None = None) -> None:
    task["status"] = status
    if status == "running":
        task["started_at"] = now_iso()
    if status in {"done", "failed", "blocked", "needs-user"}:
        task["ended_at"] = now_iso()
    if reason:
        task["status_reason"] = reason


def _refresh_ledger_status(ledger: dict[str, Any]) -> None:
    tasks = [task for task in ledger.get("tasks", []) or [] if isinstance(task, Mapping)]
    if any(task.get("status") == "needs-user" for task in tasks):
        ledger["status"] = "needs-user"
        return
    if any(task.get("status") == "failed" for task in tasks):
        ledger["status"] = "failed"
        return
    if any(task.get("status") == "running" for task in tasks):
        ledger["status"] = "running"
        return
    if tasks and all(task.get("status") == "done" for task in tasks):
        ledger["status"] = "done"


def run_once(
    *,
    ledger_dir: Path,
    executor: ChildExecutor,
    concurrency_limit: int,
    cwd: Path,
    timeout: float,
    poll_interval: float,
    only_task_id: str | None = None,
) -> dict[str, Any]:
    ledger_paths = sorted(ledger_dir.glob("*.yaml")) if ledger_dir.exists() else []
    loaded = [(path, load_ledger(path)) for path in ledger_paths]
    all_ledgers = [ledger for _, ledger in loaded]
    running = _running_count(all_ledgers)
    slots = max(0, concurrency_limit - running)
    started: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for path, ledger in loaded:
        if slots <= 0:
            break
        if only_task_id and ledger.get("task_id") != only_task_id:
            continue
        tasks = ledger.get("tasks") or []
        for task in tasks:
            if slots <= 0:
                break
            if not isinstance(task, dict) or task.get("status") != "queued":
                continue
            key = _task_key(ledger, task)
            try:
                validate_work_gate(ledger)
                validate_p0_task(task)
            except ValidationError as exc:
                _set_task_status(task, "needs-user", reason=str(exc))
                ledger["status"] = "needs-user"
                append_audit(ledger, "p0_task_rejected", f"{key}: {exc}")
                save_ledger(path, ledger)
                rejected.append({"task": key, "error": str(exc)})
                continue

            artifact_dir = path.parent / "artifacts" / str(ledger.get("task_id"))
            _set_task_status(task, "running")
            ledger["status"] = "running"
            append_audit(ledger, "child_dispatch_started", f"{key} via executor {executor.name}.")
            save_ledger(path, ledger)

            try:
                child_result = executor.execute(
                    ledger=ledger,
                    task=task,
                    artifact_dir=artifact_dir,
                    cwd=cwd,
                    timeout=timeout,
                    poll_interval=poll_interval,
                )
                validate_child_result(child_result, artifact_base=Path.cwd())
            except Exception as exc:
                _set_task_status(task, "failed", reason=str(exc))
                ledger["status"] = "failed"
                append_audit(ledger, "child_dispatch_failed", f"{key}: {exc}")
                save_ledger(path, ledger)
                started.append({"task": key, "status": "failed", "error": str(exc)})
                slots -= 1
                continue

            _append_child_outputs(ledger, child_result)
            _set_task_status(task, "done")
            append_audit(ledger, "child_dispatch_completed", f"{key}: {child_result.get('child_id')}")
            _refresh_ledger_status(ledger)
            save_ledger(path, ledger)
            started.append({"task": key, "status": "done", "child_id": child_result.get("child_id")})
            slots -= 1

    for path, ledger in loaded:
        if only_task_id and ledger.get("task_id") != only_task_id:
            continue
        for task in ledger.get("tasks") or []:
            if isinstance(task, Mapping) and task.get("status") == "queued":
                skipped.append({"task": _task_key(ledger, task), "reason": "not selected or concurrency limit reached"})

    return {
        "success": True,
        "ledger_dir": str(ledger_dir),
        "executor": executor.name,
        "concurrency_limit": concurrency_limit,
        "running_at_start": running,
        "started": started,
        "rejected": rejected,
        "skipped": skipped,
    }
