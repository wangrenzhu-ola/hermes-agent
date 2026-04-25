---
title: Codex PMO Ledger Runner P0 keeps orchestration ledger-first
date: 2026-04-25
category: docs/solutions/developer-experience/
module: Codex PMO Ledger Runner
problem_type: developer_experience
component: skill
severity: medium
tags: [codex-pmo, ledger, scheduler, child-executor, skill-cli]
---

# Codex PMO Ledger Runner P0 keeps orchestration ledger-first

## Context

DEM-013 needs Hermes to stop manually carrying every compound phase. P0 cannot
be only ledger CRUD because that would still leave Hermes responsible for
starting the next worker and interpreting results. The useful minimum is a PMO
loop that reads a ledger, dispatches a bounded child, validates the result, and
writes the outcome back to the ledger.

## 问题

Hermes 在 compound 运行中仍要手工推进阶段和管理子模型执行，导致：

- 任务推进依赖个人记忆，缺少统一的结构化控制面。
- 子任务结果不统一可观测，难以作为高置信度交付依据。
- P0 仍容易越界到写阶段或危险策略，缺乏明确边界。

## 决策

- 采用 ledger-first + PMO loop（不是仅做 CRUD）。
- 仅在 P0 提供 reference CLI，不绑定 slash command/gateway/TUI，避免范围外扩散。
- 强制 P0 边界策略：`sandbox=read-only`、`approval_policy=on-request`，禁止 `danger-full-access` 与 mailbox 为主通信。
- 子任务种类仅允许 `ledger_validation_smoke` 和 `document_review_smoke`。
- 以 `fake` child executor 作为可复现验证路径，`codex-bridge` 作为真实桥接路径（不作为默认强耦合路径）。
- `status/list/validate` 为 Hermes 观察接口，`run-once` 为PMO执行接口。

## 实现

代码位置位于 `skills/codex-pmo-ledger-runner/`，核心是 CLI + ledger + validator +
scheduler + child executor。

- `references/cli.py`
  - `init`：创建任务 ledger（默认运行时路径 `get_hermes_home()/pmo/ledgers`）。
  - `status`：读取单一任务状态快照。
  - `list`：汇总目录下任务数量、状态、风险与最近 child。
  - `validate`：执行 schema 与策略校验。
  - `run-once`：扫描 queued，按并发约束调度 child。
- `references/ledger.py`
  - 运行时与文档快照路径隔离，temp-file+原子替换写回。
- `references/validator.py`
  - 强制 read-only/on-request/no mailbox/no danger policy。
  - 校验子结果、artifact、风险和审计字段。
- `references/scheduler.py`
  - 只扫描 `queued`。
  - 阶段与策略前置门禁，未通过 document-review 的 work 直接 reject。
- `references/child_executor.py`
  - 提供 fake/codex-bridge 执行适配。
  - child 写回结构化记录，包含 `actual_approval_policy`。

当前实现不进行 raw child 日志 tail、transcript 拼接或人工上下文注入；PMO 的控制逻辑基于 ledger 的
child 结果、验证、风险与审计事件。

## 测试

Hermes 验证链已在 `python3.11` 下通过：

- `python3.11 -m py_compile skills/codex-pmo-ledger-runner/references/*.py`
- `python3.11 -m pytest -q -o addopts='' tests/skills/test_codex_pmo_ledger_runner_contract.py`
- `git diff --check`

Contract tests 覆盖：

- init/status/list/validate 合约字段。
- fake child dispatch 写回（sandbox、artifact、children、audit 事件）。
- 并发限制。
- work 阶段拒绝策略（document review 未通过）。
- mailbox 安全策略拒绝。
- 缺失字段校验。
- subprocess CLI smoke（输出可作为 Hermes observer JSON contract）。

## ledger / PMO 控制面

- PMO 控制面只关注结构化记录与决策态，不关注 child 原始 transcript。
- 关键字段：`phase/status/result/next_action`、`tasks`、`children`、`validation`、`risks`、`audit`。
- 风险、决策与审计记录都回写至 ledger，便于 Hermes/User 做复核而非人工轮询日志。
- 允许的观测动作：查看 status/list、读取 validate 结果、确认是否进入下一阶段。

## workflow source

- Workflow source of truth: `galeharness-compound-workflow`
- 路径: `/Users/wangrenzhu/.hermes/skills/software-development/galeharness-compound-workflow/`
- PMO 与子执行由 `codex-pmo-ledger-runner` 编排；Hermes 侧以控制面观察与决策为主。

## 下一步（P1 / P2 / P3）

- P1：补齐决策门控可观测性（user pause/state transition 追踪），完善 high-risk 的可回溯字段。
- P2：接入 work/write 阶段的受控调度与审批增强（仍保留 ledger-first 与最小职责）。
- P3：与 Hermes 运行面更深集成（可选 slash/命令入口、可视化聚合、跨 repo 自动化）。
