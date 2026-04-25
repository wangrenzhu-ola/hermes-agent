---
name: codex-pmo-ledger-runner
description: Run a ledger-first PMO loop that dispatches child Codex tasks and records phase status, artifacts, validation, risks, and next actions.
version: 0.1.0
platforms: [linux, macos]
metadata:
  hermes:
    tags: [codex, pmo, ledger, scheduler, child-agent]
    category: software-development
---

# Codex PMO Ledger Runner

Use this skill when Hermes should observe a compound task ledger instead of
manually advancing each phase. The PMO Runner reads ledger files, dispatches a
bounded read-only child Codex task for P0-safe phases, validates the child
result contract, and writes child status, artifacts, validation, risks, and
next actions back to the ledger.

## Stable Entry Point

Run the reference CLI from the repository root:

```bash
python3.11 skills/codex-pmo-ledger-runner/references/cli.py init --task-id DEM-013 --title "Codex PMO Ledger Runner"
python3.11 skills/codex-pmo-ledger-runner/references/cli.py status DEM-013
python3.11 skills/codex-pmo-ledger-runner/references/cli.py list
python3.11 skills/codex-pmo-ledger-runner/references/cli.py validate DEM-013
python3.11 skills/codex-pmo-ledger-runner/references/cli.py run-once --executor fake --concurrency-limit 1
```

Use the project venv Python when available. This repository requires Python
3.11+; on machines where `python3` is 3.9, use `python3.11` or
`.venv/bin/python`.

Runtime ledgers default to `get_hermes_home()/pmo/ledgers`. Repository
`docs/ledgers/` files are examples or review snapshots; pass `--ledger-dir
docs/ledgers` when you intentionally want to inspect or update a docs snapshot.

## P0 Boundary

- The PMO owns scheduling and ledger writes.
- Hermes and the user observe `status`, `list`, validation errors, risks, and
  decisions.
- P0 child phases are read-only only: `ledger_validation_smoke` and
  `document_review_smoke`.
- `run-once` can use `--executor fake` for tests and `--executor codex-bridge`
  for a real read-only Codex Bridge smoke.
- Child results must satisfy the structured contract before the PMO records
  them as successful.
- The PMO observes child completion events, structured status, ledger fields,
  artifact paths, validation summaries, and risks. It must not stream, tail, or
  repeatedly poll raw child logs/transcripts as its coordination mechanism.

## Never Do

- Do not enter the `work` phase unless document review has passed and the
  later write-phase design is active.
- Do not start workspace-write children in P0.
- Do not use `danger-full-access`.
- Do not use `approval_policy=never`.
- Do not commit, push, or open a PR from this skill.
- Do not use mailbox, inbox, or outbox as the primary child communication path.
- Do not waste PMO or Hermes context by watching raw child logs. Use completion
  events, status summaries, artifact checks, validation results, and ledger
  deltas instead.
