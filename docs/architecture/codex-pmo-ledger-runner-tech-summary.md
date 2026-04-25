# DEM-013 Codex PMO Ledger Runner 技术方案摘要

## 当前结论

P0 已经具备“Codex PMO 可以调度 child 并写回 ledger”的最小闭环，但还不是完整自动 compound PMO。

当前能做：

- 初始化 runtime ledger；
- status/list/validate；
- run-once 扫描 queued/runnable task；
- concurrency limit；
- fake child executor 调度；
- child result artifact 写入；
- ledger 写回 children/artifacts/validation/audit/next_action；
- document-review 未 pass 时拒绝进入 work；
- P0 安全默认：read-only、on-request、禁止 danger-full-access、禁止 mailbox 主路径。

还不能做：

- 自动跑完整 brainstorm -> plan -> document-review -> work -> review -> compound -> PR；
- 多任务长期 scheduler daemon；
- 真实 Codex Bridge child 的完整生产闭环；
- worktree write lock 下的代码实现阶段；
- dashboard/TUI/gateway 查询入口。

## Skill 名称

`codex-pmo-ledger-runner`

路径：

`skills/codex-pmo-ledger-runner/`

稳定 CLI 入口：

```bash
python3.11 skills/codex-pmo-ledger-runner/references/cli.py init --task-id DEM-013 --title "Codex PMO Ledger Runner"
python3.11 skills/codex-pmo-ledger-runner/references/cli.py status DEM-013
python3.11 skills/codex-pmo-ledger-runner/references/cli.py list
python3.11 skills/codex-pmo-ledger-runner/references/cli.py validate DEM-013
python3.11 skills/codex-pmo-ledger-runner/references/cli.py run-once --executor fake --concurrency-limit 1
```

## 文件结构

```text
skills/codex-pmo-ledger-runner/
├── SKILL.md
└── references/
    ├── cli.py
    ├── ledger.py
    ├── scheduler.py
    ├── child_executor.py
    └── validator.py

tests/skills/test_codex_pmo_ledger_runner_contract.py

docs/brainstorms/2026-04-25-codex-pmo-ledger-runner-requirements.md
docs/plans/2026-04-25-codex-pmo-ledger-runner-plan.md
docs/ledgers/codex-pmo-ledger-runner-ledger.yaml
docs/solutions/developer-experience/codex-pmo-ledger-runner-p0-2026-04-25.md
```

## Ledger 核心字段

```yaml
schema_version:
runner_version:
task_id:
title:
phase:
status:
repo:
storage:
policy:
scheduler:
tasks:
phases:
children:
artifacts:
validation:
risks:
decisions_needed:
next_action:
audit:
```

## Child result contract

Child 必须返回结构化结果，PMO 才能推进：

```yaml
child_id:
phase:
status:
result:
model:
effort:
sandbox:
approval_policy:
started_at:
ended_at:
artifacts:
summary:
validation:
risks:
next_recommendation:
```

缺字段则标记 invalid，不推进 phase。

## Roadmap

### P0 已实现

PMO -> child dispatch MVP + ledger/status/validate。

### P1 下一步

让 PMO 自动推进只读阶段：

```text
brainstorm -> plan -> document-review
```

每个阶段都是 child Codex，PMO 只写 ledger。

### P2

接入 write phase：

```text
work -> review -> compound -> PR
```

要求独立 worktree、repo write lock、workspace-write 审计。

### P3

多任务 scheduler / dashboard / gateway 查询入口。

## 验证结果

已验证：

```bash
python3.11 -m py_compile skills/codex-pmo-ledger-runner/references/*.py
python3.11 -m pytest -q -o addopts='' tests/skills/test_codex_pmo_ledger_runner_contract.py
git diff --check
```

结果：

```text
8 passed
```

## 关键边界

- Codex Bridge 是底层 transport；PMO Runner 是上层 compound 编排。
- 不用 mailbox 作为 Codex 主路径。
- PMO 不盯 raw child logs/transcripts。
- Hermes/User 只关注 ledger、完成事件、产物、验证、风险。
