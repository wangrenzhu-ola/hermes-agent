#!/usr/bin/env python3
"""Productized CLI for the Codex PMO Ledger Runner skill."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from .child_executor import get_executor
    from .ledger import default_ledger, ledger_path, list_ledger_summaries, load_ledger, runtime_ledger_dir, save_ledger, status_summary
    from .scheduler import run_once
    from .validator import ValidationError, collect_ledger_errors, validate_ledger
except ImportError:
    from child_executor import get_executor  # type: ignore
    from ledger import default_ledger, ledger_path, list_ledger_summaries, load_ledger, runtime_ledger_dir, save_ledger, status_summary  # type: ignore
    from scheduler import run_once  # type: ignore
    from validator import ValidationError, collect_ledger_errors, validate_ledger  # type: ignore


def emit(data: dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=False, sort_keys=True))


def resolve_ledger_dir(value: str | None) -> Path:
    return Path(value).expanduser() if value else runtime_ledger_dir()


def load_task_ledger(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    ledger_dir = resolve_ledger_dir(args.ledger_dir)
    path = Path(args.ledger).expanduser() if getattr(args, "ledger", None) else ledger_path(ledger_dir, args.task_id)
    if not path.exists():
        raise ValidationError(f"ledger not found: {path}")
    return path, load_ledger(path)


def cmd_init(args: argparse.Namespace) -> dict[str, Any]:
    ledger_dir = resolve_ledger_dir(args.ledger_dir)
    path = ledger_path(ledger_dir, args.task_id)
    if path.exists() and not args.force:
        raise ValidationError(f"ledger already exists: {path}. Use --force to replace it.")
    ledger = default_ledger(
        args.task_id,
        args.title or args.task_id,
        ledger_dir=ledger_dir,
        docs_snapshot_path=args.docs_snapshot_path,
    )
    save_ledger(path, ledger)
    return {"success": True, "task_id": args.task_id, "path": str(path), "ledger": status_summary(ledger)}


def cmd_status(args: argparse.Namespace) -> dict[str, Any]:
    path, ledger = load_task_ledger(args)
    return {"success": True, "path": str(path), "status": status_summary(ledger)}


def cmd_list(args: argparse.Namespace) -> dict[str, Any]:
    ledger_dir = resolve_ledger_dir(args.ledger_dir)
    tasks = list_ledger_summaries(ledger_dir)
    counts: dict[str, int] = {}
    for item in tasks:
        status = str(item.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return {"success": True, "ledger_dir": str(ledger_dir), "counts": counts, "tasks": tasks}


def cmd_validate(args: argparse.Namespace) -> dict[str, Any]:
    path, ledger = load_task_ledger(args)
    errors = collect_ledger_errors(ledger, artifact_base=Path.cwd())
    return {"success": not errors, "path": str(path), "errors": errors}


def cmd_run_once(args: argparse.Namespace) -> dict[str, Any]:
    ledger_dir = resolve_ledger_dir(args.ledger_dir)
    if args.concurrency_limit < 1:
        raise ValidationError("concurrency-limit must be >= 1.")
    executor = get_executor(args.executor, model=args.model, approval_policy=args.approval_policy)
    return run_once(
        ledger_dir=ledger_dir,
        executor=executor,
        concurrency_limit=args.concurrency_limit,
        cwd=Path(args.cwd).expanduser(),
        timeout=args.timeout,
        poll_interval=args.poll_interval,
        only_task_id=args.task_id,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Codex PMO Ledger Runner skill CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Create a runtime or explicit docs ledger.")
    init.add_argument("--task-id", required=True)
    init.add_argument("--title", required=True)
    init.add_argument("--ledger-dir", default=None, help="Defaults to get_hermes_home()/pmo/ledgers.")
    init.add_argument("--docs-snapshot-path", default=None)
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init)

    status = subparsers.add_parser("status", help="Output one ledger status summary JSON.")
    status.add_argument("task_id")
    status.add_argument("--ledger-dir", default=None)
    status.add_argument("--ledger", default=None, help="Explicit ledger YAML path.")
    status.set_defaults(func=cmd_status)

    list_parser = subparsers.add_parser("list", help="List ledgers in a directory.")
    list_parser.add_argument("--ledger-dir", default=None)
    list_parser.set_defaults(func=cmd_list)

    validate = subparsers.add_parser("validate", help="Validate ledger schema, phase gate, and required fields.")
    validate.add_argument("task_id")
    validate.add_argument("--ledger-dir", default=None)
    validate.add_argument("--ledger", default=None, help="Explicit ledger YAML path.")
    validate.set_defaults(func=cmd_validate)

    run = subparsers.add_parser("run-once", help="Run one PMO scheduling pass and dispatch P0-safe child tasks.")
    run.add_argument("--ledger-dir", default=None)
    run.add_argument("--task-id", default=None, help="Optional single ledger task id filter.")
    run.add_argument("--concurrency-limit", type=int, default=1)
    run.add_argument("--executor", choices=["fake", "codex-bridge"], default="fake")
    run.add_argument("--cwd", default=str(Path.cwd()))
    run.add_argument("--timeout", type=float, default=60.0)
    run.add_argument("--poll-interval", type=float, default=2.0)
    run.add_argument("--model", default=None)
    run.add_argument("--approval-policy", choices=["untrusted", "on-request"], default="on-request")
    run.set_defaults(func=cmd_run_once)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        result = args.func(args)
        emit(result)
        return 0 if result.get("success") is True else 1
    except ValidationError as exc:
        emit({"success": False, "error": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
