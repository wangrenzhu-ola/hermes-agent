import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import yaml


SKILL_REFS = Path(__file__).resolve().parents[2] / "skills" / "codex-pmo-ledger-runner" / "references"
REPO_ROOT = Path(__file__).resolve().parents[2]


def load_reference_module(name):
    module_path = SKILL_REFS / f"{name}.py"
    sys.path.insert(0, str(SKILL_REFS))
    try:
        spec = importlib.util.spec_from_file_location(f"codex_pmo_ledger_runner_{name}", module_path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        return module
    finally:
        try:
            sys.path.remove(str(SKILL_REFS))
        except ValueError:
            pass


def read_output(capsys):
    return json.loads(capsys.readouterr().out)


def test_init_uses_profile_scoped_runtime_ledger_by_default(tmp_path, monkeypatch, capsys):
    cli = load_reference_module("cli")
    hermes_home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    exit_code = cli.main(["init", "--task-id", "DEM-013", "--title", "Codex PMO Ledger Runner"])

    assert exit_code == 0
    output = read_output(capsys)
    ledger_path = hermes_home / "pmo" / "ledgers" / "DEM-013.yaml"
    assert output["path"] == str(ledger_path)
    assert ledger_path.exists()
    data = yaml.safe_load(ledger_path.read_text())
    assert data["storage"]["active_source"] == "runtime"
    assert data["policy"]["danger_full_access_allowed"] is False


def test_status_list_and_validate_contract(tmp_path, capsys):
    cli = load_reference_module("cli")
    ledger_dir = tmp_path / "ledgers"

    assert cli.main(["init", "--task-id", "DEM-001", "--title", "One", "--ledger-dir", str(ledger_dir)]) == 0
    read_output(capsys)
    assert cli.main(["init", "--task-id", "DEM-002", "--title", "Two", "--ledger-dir", str(ledger_dir)]) == 0
    read_output(capsys)

    assert cli.main(["status", "DEM-001", "--ledger-dir", str(ledger_dir)]) == 0
    status = read_output(capsys)["status"]
    for field in [
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
    ]:
        assert field in status

    assert cli.main(["list", "--ledger-dir", str(ledger_dir)]) == 0
    listed = read_output(capsys)
    assert listed["counts"]["queued"] == 2
    assert {item["task_id"] for item in listed["tasks"]} == {"DEM-001", "DEM-002"}

    assert cli.main(["validate", "DEM-001", "--ledger-dir", str(ledger_dir)]) == 0
    validation = read_output(capsys)
    assert validation["success"] is True
    assert validation["errors"] == []


def test_run_once_starts_fake_child_and_writes_ledger(tmp_path, capsys):
    cli = load_reference_module("cli")
    ledger_dir = tmp_path / "ledgers"
    assert cli.main(["init", "--task-id", "DEM-013", "--title", "PMO", "--ledger-dir", str(ledger_dir)]) == 0
    read_output(capsys)

    exit_code = cli.main(["run-once", "--ledger-dir", str(ledger_dir), "--executor", "fake"])

    assert exit_code == 0
    output = read_output(capsys)
    assert output["started"][0]["status"] == "done"
    ledger = yaml.safe_load((ledger_dir / "DEM-013.yaml").read_text())
    assert ledger["status"] == "done"
    assert ledger["tasks"][0]["status"] == "done"
    assert ledger["children"][0]["child_id"].startswith("fake-DEM-013")
    assert ledger["children"][0]["sandbox"] == "read-only"
    assert Path(ledger["children"][0]["artifacts"][0]["path"]).exists()
    assert any(item["event"] == "child_dispatch_completed" for item in ledger["audit"])


def test_cli_subprocess_smoke_emits_observer_json_contract(tmp_path):
    cli_path = SKILL_REFS / "cli.py"
    ledger_dir = tmp_path / "ledgers"

    init = subprocess.run(
        [
            sys.executable,
            str(cli_path),
            "init",
            "--task-id",
            "DEM-SMOKE",
            "--title",
            "CLI smoke",
            "--ledger-dir",
            str(ledger_dir),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert init.returncode == 0, init.stderr
    assert json.loads(init.stdout)["success"] is True

    run_once = subprocess.run(
        [sys.executable, str(cli_path), "run-once", "--ledger-dir", str(ledger_dir), "--executor", "fake"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert run_once.returncode == 0, run_once.stderr
    run_output = json.loads(run_once.stdout)
    assert run_output["success"] is True
    assert run_output["started"][0]["child_id"].startswith("fake-DEM-SMOKE")

    status = subprocess.run(
        [sys.executable, str(cli_path), "status", "DEM-SMOKE", "--ledger-dir", str(ledger_dir)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert status.returncode == 0, status.stderr
    status_output = json.loads(status.stdout)
    assert status_output["success"] is True
    assert status_output["status"]["recent_children"][0]["status"] == "done"


def test_run_once_obeys_concurrency_limit(tmp_path, capsys):
    cli = load_reference_module("cli")
    ledger_dir = tmp_path / "ledgers"
    for task_id in ["DEM-001", "DEM-002", "DEM-003"]:
        assert cli.main(["init", "--task-id", task_id, "--title", task_id, "--ledger-dir", str(ledger_dir)]) == 0
        read_output(capsys)

    assert cli.main(["run-once", "--ledger-dir", str(ledger_dir), "--executor", "fake", "--concurrency-limit", "2"]) == 0
    output = read_output(capsys)
    assert len(output["started"]) == 2
    statuses = {
        task_id: yaml.safe_load((ledger_dir / f"{task_id}.yaml").read_text())["tasks"][0]["status"]
        for task_id in ["DEM-001", "DEM-002", "DEM-003"]
    }
    assert sorted(statuses.values()) == ["done", "done", "queued"]


def test_run_once_rejects_work_when_document_review_has_not_passed(tmp_path, capsys):
    cli = load_reference_module("cli")
    ledger_dir = tmp_path / "ledgers"
    assert cli.main(["init", "--task-id", "DEM-WORK", "--title", "Work blocked", "--ledger-dir", str(ledger_dir)]) == 0
    read_output(capsys)

    path = ledger_dir / "DEM-WORK.yaml"
    ledger = yaml.safe_load(path.read_text())
    ledger["phase"] = "work"
    ledger["tasks"][0]["phase"] = "work"
    ledger["tasks"][0]["allowed_child_kind"] = "ledger_validation_smoke"
    path.write_text(yaml.safe_dump(ledger, sort_keys=False), encoding="utf-8")

    assert cli.main(["run-once", "--ledger-dir", str(ledger_dir), "--executor", "fake"]) == 0
    output = read_output(capsys)
    assert output["started"] == []
    assert output["rejected"][0]["task"] == "DEM-WORK:DEM-WORK"

    updated = yaml.safe_load(path.read_text())
    assert updated["status"] == "needs-user"
    assert updated["tasks"][0]["status"] == "needs-user"
    assert "document_review.status=done" in updated["tasks"][0]["status_reason"]
    assert updated["children"] == []


def test_validate_rejects_mailbox_primary_transport(tmp_path, capsys):
    cli = load_reference_module("cli")
    ledger_dir = tmp_path / "ledgers"
    assert cli.main(["init", "--task-id", "DEM-SAFE", "--title", "Safety", "--ledger-dir", str(ledger_dir)]) == 0
    read_output(capsys)

    path = ledger_dir / "DEM-SAFE.yaml"
    ledger = yaml.safe_load(path.read_text())
    ledger["policy"]["mailbox_as_primary_transport"] = True
    path.write_text(yaml.safe_dump(ledger, sort_keys=False), encoding="utf-8")

    assert cli.main(["validate", "DEM-SAFE", "--ledger-dir", str(ledger_dir)]) == 1
    output = read_output(capsys)
    assert "mailbox_as_primary_transport" in output["errors"][0]


def test_validate_reports_missing_required_fields(tmp_path, capsys):
    cli = load_reference_module("cli")
    ledger_dir = tmp_path / "ledgers"
    ledger_dir.mkdir()
    (ledger_dir / "BROKEN.yaml").write_text("task_id: BROKEN\n", encoding="utf-8")

    assert cli.main(["validate", "BROKEN", "--ledger-dir", str(ledger_dir)]) == 1
    output = read_output(capsys)
    assert output["success"] is False
    assert "missing required field" in output["errors"][0]
