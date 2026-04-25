---
title: Codex PMO Ledger Runner 需求
date: 2026-04-25
status: draft
scope: deep
dem: DEM-013
---

# Codex PMO Ledger Runner 需求

## Problem Frame

完整 compound 流程会反复推进 `brainstorm -> plan -> document-review -> work -> review -> compound`。现在这些阶段主要由 Hermes 串行指挥，每一步都需要把大量历史上下文重新带入下一轮，导致两个问题：

- 上下文成本高：Hermes 既要保留产品决策，又要携带阶段产物、审查意见、执行细节和后续建议。
- 并发能力弱：多条 compound 任务需要 Hermes 持续启动下一阶段、收结果、判断状态，Hermes 本身成为 PMO 瓶颈。

目标是把 PMO 编排能力外包给一个 Codex PMO Runner。Runner 以 ledger 为唯一事实源，负责推进阶段、派发 child Codex、收敛 artifact、记录风险和下一步。Hermes 和用户只看 ledger、关键决策、风险和最终验收。

## Actors

- User：提出任务愿景、处理重大产品或安全决策、做最终验收。
- Hermes supervisor：启动或查看 PMO Runner，监控 ledger，只在 `needs-user`、`high-risk`、`failed` 或最终验收点介入。
- Codex PMO：单条 compound 任务的编排者。负责阶段推进、压缩上下文、派发 child、收敛结果、更新 ledger，但不擅自替用户做重大产品决策。
- Child Codex worker：只执行一个阶段或一个明确子任务。输入是压缩上下文；输出必须包含 artifact path、summary、validation、risks、next recommendation。
- Ledger：唯一事实源，记录任务状态、阶段、child、artifact、验证、风险、决策、预算和下一步。
- Repo / worktree：每条任务使用独立 worktree 和 branch；repo 级并发受控，避免多个 PMO 同时改同一 checkout。

## Goals

- 让一条 compound 任务能从 ledger 中恢复、继续和审计。
- 让 Codex PMO 自动或半自动推进多阶段任务，减少 Hermes 在阶段之间手动调度。
- 让 child Codex 只拿单阶段压缩上下文，降低上下文消耗和误操作面。
- 从 MVP/P0 开始证明 `PMO -> child Codex -> ledger` 闭环，Hermes 和用户只观察 ledger，不继续手动串阶段。
- 为多条 compound 任务并发打基础：P0 就要有多任务 queued/running/done 状态、基础 scheduler 和并发限制；写入 worktree 并发留到后续阶段。
- 保持安全默认值：非 work 阶段默认 read-only；work 阶段才允许 workspace-write 或 yolo，并且必须记录。
- 保持 Codex 主通信路径在 app-server / JSON-RPC / exec-json / 受监督后台 runner 上，不以 mailbox 作为主路径。

## Non-goals

- Phase 1 不实现代码、不提交、不推送、不建 PR。
- MVP 不允许 child 再派 child；只支持 `PMO -> child` 一层。
- MVP 不做跨 repo 分布式调度、云队列、多租户权限系统。
- MVP 不进入 work 写代码阶段；P0 child 只能执行 read-only smoke、ledger validation 或 document-review 类任务。
- 不把现有 `codex_bridge_tool` 重写成 PMO Runner；Bridge 是可复用执行能力，Runner 是上层编排。
- 不让 PMO 猜重大产品决策、风险接受、权限升级或验收结论。
- 不把 mailbox / inbox / outbox 作为 Codex 主通信协议。

## Requirements

### R1: Ledger Schema

Ledger 必须是机器可读、人工可审的 YAML 或 JSON 文档。MVP 默认 YAML。运行时 ledger 默认放在 profile-scoped Hermes state 下，例如 `get_hermes_home()/pmo/ledgers/<task-id>.yaml`；`docs/ledgers/` 只放 DEM 审查副本、示例 ledger 或需要纳入 repo 审查的冻结快照。Runner 必须在 ledger 中记录 `storage.mode` 和实际 `storage.runtime_path` / `storage.docs_snapshot_path`，避免 dashboard、恢复逻辑和人工审查读取不同事实源。

Ledger 至少记录：

- `schema_version`、`runner_version`、`task_id`、`dem`、`title`
- `storage`：运行时 ledger 位置、docs 快照位置、是否为示例或活跃 runtime
- `repo`：repo path、base branch、worktree path、task branch、repo lock key
- `phase`：当前阶段，如 `brainstorm_plan`、`document_review`、`work`、`review`、`compound`、`done`
- `status`：`queued`、`running`、`needs-user`、`blocked`、`failed`、`done`
- `phases`：每个 phase 的 status、result、attempt、started/ended、artifacts、blocked_by、transition_guard
- `children`：child id、phase、status、model、effort、sandbox、approval policy、started/ended、token/耗时、artifact paths、summary、validation、risks
- `artifacts`：需求、计划、审查报告、实现摘要、测试结果、PR、compound learning 等路径
- `validation`：检查项、命令、结果、时间、责任主体
- `risks`：等级、描述、owner、缓解方式、状态
- `decisions_needed`：问题、选项、推荐、选择、决策来源、阻塞阶段、状态
- `next_action`：下一步动作、owner、触发条件
- `budget` / `accounting`：模型、effort、token、耗时、child 数、预算警戒
- `locks`：repo lock / ledger lock 的 owner、lease、heartbeat、stale 检测和恢复动作
- `status_contract`：status/dashboard 输出必须包含的稳定字段和过滤规则
- `audit`：重要事件时间线，包括权限升级、phase transition、失败恢复、用户决策。

### R2: Phase State Machine

Runner 必须显式记录 phase transition。基础状态机：

1. `brainstorm_plan`
2. `document_review`
3. `work`
4. `review`
5. `compound`
6. `done`

状态约束：

- `plan` 未通过 `document_review` 前，不允许进入 `work`。
- 只有 `phases.document_review.status == done` 且 `phases.document_review.result == pass` 且 plan artifact 已通过 validation，才允许 `work` transition。
- `document_review.result == revise` 表示必须先修改 plan 并重新审查；它不是 work 绿灯。
- `document_review.result == block` 必须进入 `blocked` 或 `needs-user`，不得自动降级为 warning。
- `needs-user` 会暂停自动推进，直到 Hermes / User 写入决策。
- `failed` 必须记录失败原因、可重试性和推荐恢复动作。
- `done` 需要 artifact、validation、风险和验收状态完整。

### R3: Worker Dispatch

PMO 必须能派 child Codex 执行单阶段任务。P0 可以只支持一个最小 read-only child smoke，但必须真实启动或通过受监督 child executor 启动一个 child，并把 child task id、状态、artifact、summary、validation、risks 写回 ledger。每个 child 必须固定：

- 阶段目标和非目标
- 输入上下文摘要
- 允许读取或写入的路径边界
- sandbox / approval policy / model / effort
- 输出契约：artifact paths、summary、validation、risks、next recommendation
- 超时、预算和失败处理

默认 sandbox：

- brainstorm、plan、document-review、review：`read-only`
- work：`workspace-write`，仅在 ledger 已记录已批准计划和执行边界后启用
- `danger-full-access` 在 MVP/P1/P2 中不支持，也不得通过 PMO Runner 传给 child。
- `approval_policy=never` 禁止作为 PMO child 默认或自动升级目标；允许值必须限制为 Bridge 当前支持的 `untrusted` 或 `on-request`。
- 如未来引入 yolo 路径，必须作为单独安全设计和显式用户决策，不得混入 P0/P1/P2。

P0 child dispatch 的最小可验收形态：

- child executor abstraction 存在，默认走 Codex Bridge 或受监督 exec-json runner。
- scheduler 读取 ledger 中 queued tasks，启动不超过 concurrency limit 的 read-only child。
- 至少一个真实 child Codex smoke，例如 document-review child 或 no-op ledger validation child。
- PMO 不把 child summary 当作事实；必须校验 child result contract 和 artifact，再更新 ledger。
- P0 不允许启动 work child、写业务代码、改 worktree 或创建 PR。

### R4: Compression Handoff

每个阶段启动前，PMO 必须生成压缩 handoff，而不是把完整历史塞给 child。handoff 包含：

- 当前 ledger 摘要
- 阶段目标、输入 artifact、验收条件
- 关键决策和未决问题
- 相关 repo 路径和只读上下文
- child 输出格式要求

child 完成后，PMO 只把结果摘要、artifact path、validation、risks 和 next recommendation 写回 ledger。

### R5: Concurrency Control

- 每条 compound 任务使用独立 worktree 和 branch。
- P0 ledger/scheduler model 必须支持多条 task 的 `queued`、`running`、`done`、`failed` 展示，哪怕实际只运行 read-only child。
- scheduler 必须有全局或 profile 级 `concurrency_limit`，扫描 queued tasks，并只启动未超过 limit 的 child。
- 同一 repo 的并发 work 阶段必须有 repo lock 或 slot 限制。
- 非写入阶段可更高并发；写入阶段默认每 repo 1 条，后续可配置。
- ledger 必须记录 lock key、owner、pid 或 task id、获取/释放时间、lease TTL、最近 heartbeat、等待原因。
- Runner 恢复时必须检测 stale lock：如果 heartbeat 超过 TTL，先把 lock 标记为 `stale_detected` 并写 audit，再按配置进入 `needs-user` 或执行受控 reclaim；不得静默覆盖。
- ledger 自身写入必须使用原子写入和轻量 ledger lock，避免 scheduler/dashboard/PMO 同时写坏 YAML。

### R6: Decision Gate

以下情况必须进入 `needs-user`：

- 重大产品范围、用户体验或验收标准不明确。
- 需要接受高风险方案或跳过审查。
- 需要提升 sandbox / approval policy。
- plan 与 document-review 结论冲突。
- work 可能覆盖其他分支或 worktree 的未合并工作。

PMO 可以给推荐选项，但不得自行选择重大产品决策。

### R7: Artifact Validation

PMO 不只相信 child summary。每个阶段都必须做轻量 artifact validation：

- 文件存在、路径在允许范围内、格式可解析。
- requirements / plan 包含必需章节。
- document-review 给出 pass / revise / block 结论。
- work 阶段包含测试命令与结果。
- review 阶段包含风险评估和是否可合并建议。
- compound 阶段产物进入约定 docs 位置。

Child result 必须是结构化 JSON/YAML，最少字段为 `child_id`、`phase`、`status`、`result`、`model`、`effort`、`sandbox`、`approval_policy`、`started_at`、`ended_at`、`artifacts`、`summary`、`validation`、`risks`、`next_recommendation`。缺少任一必填字段时，PMO 必须将 child 标记为 `invalid_output`，不推进 phase。

### R8: Status Dashboard

MVP 至少提供 CLI/status 输出：

- 当前 phase / status / next_action
- 最近 child 状态
- blocking decisions
- high risks
- artifacts
- validation summary
- elapsed / token / model accounting

Status/dashboard 输出必须有稳定 JSON contract，至少包含：

- `task_id`、`title`、`phase`、`status`、`result`
- `next_action`
- `blocking_decisions`：只列 `status=open` 且阻塞当前或下一阶段的决策
- `high_risks`：只列 `severity=high` 且未关闭的风险
- `recent_children`
- `artifacts`
- `validation_summary`
- `budget_summary`
- `locks`
- `audit_tail`

后续 dashboard 可接入 TUI、gateway 或 web server，但 ledger 仍是事实源。

### R9: Recovery

Runner 必须支持从 ledger 恢复：

- child 中断：标记 child `failed` 或 `interrupted`，保留 partial artifacts。
- PMO 进程退出：重启后读 ledger，基于 `next_action` 继续或等待用户。
- artifact 缺失：进入 `failed` 或 `needs-user`，不盲目推进。
- lock 未释放：记录 stale lock 检测和人工解除路径。

### R10: Security / Sandbox

- 默认 read-only。
- work 阶段的 workspace-write 必须写入 ledger，包括批准来源和作用范围。
- 禁止默认 `approval_policy=never`。
- child 不拿完整凭据上下文；只继承执行所需的最小环境。
- 任务与 worktree 隔离，避免 child 修改主 checkout 或其他并行任务。
- 所有外部平台通知只发送 ledger 摘要，不发送敏感上下文。

### R11: Budget / Accounting

Ledger 必须记录：

- PMO 与 child 的 model、effort、启动时间、结束时间、耗时。
- 可用时记录 prompt/completion/total tokens。
- child 数量、失败重试次数、阶段总耗时。
- budget warning 和 stop condition。

## Acceptance Examples

### AE1: 单任务自动推进到 document-review

给定一个新的 DEM，Hermes 启动 PMO Runner 后，ledger 进入 `brainstorm_plan/running`。PMO 派 child 生成 requirements 和 plan，写入 artifact path。随后进入 `document_review/running`，派 child 审查 plan。只有审查结论为 `pass` 后，ledger 才允许下一步进入 work；若为 `revise`，next_action 必须是修正 plan 并重新 document-review；若为 `block`，status 变为 `needs-user` 或 `blocked`。

### AE1a: P0 child dispatch smoke

给定一个 P0 ledger，其中存在 queued read-only task，Hermes 只启动 PMO Runner 后停止参与阶段推进。PMO 读取 ledger，scheduler 在 concurrency limit 内启动一个 child Codex smoke，记录 child task id 和状态；child 返回结构化 result 后，PMO 校验 artifact/validation，写入 children、validation、risks、audit 和 next_action。Hermes 查询 status 时能看到 child 从 queued/running 到 done 或 failed 的过程。

### AE1b: P0 多任务状态展示

给定同一 profile 下有多条 ledger task，status/list 能展示每条 task 的 phase、status、next_action、最近 child 和 high risks。P0 可以只允许 read-only child 并发；worktree 写入并发和 repo lock enforcement 留到 P2。

### AE2: plan 未过 review 禁止 work

当 ledger 中 `phases.document_review.status != done`、`phases.document_review.result != pass`、或 plan artifact validation 未通过时，任何进入 `work` 的请求都会失败，并在 ledger audit 中记录拒绝原因。

### AE3: work 阶段权限升级可审计

当 PMO 准备进入 work，ledger 记录 `sandbox=workspace-write`、branch、worktree、批准来源和执行范围。若需要 yolo 或 danger-full-access，status 必须转为 `needs-user`。

### AE4: Child 输出不完整会阻塞

child 完成但未提供 artifact path 或 validation 时，PMO 不推进 phase，ledger 标记该 child `invalid_output`，记录缺失字段和 recommended recovery。

### AE5: Hermes 只读 ledger 即可判断状态

Hermes 查询 ledger status，能看到当前 phase、blocking decisions、high risks、artifact paths、validation 和 next_action，无需读取完整 child transcript。

## Risks

- 编排层过早做大，变成另一个复杂 agent 平台；MVP 必须只做单层 read-only child dispatch、ledger-first 和最小 scheduler，不进入 work 写代码阶段。
- ledger schema 若过于松散，后续 dashboard 和恢复会依赖脆弱字符串。
- 如果 child handoff 压缩过度，阶段产物可能丢失关键产品约束。
- worktree / repo lock 实现不严谨会造成并发覆盖或 stale lock。
- PMO 自动推进可能绕过用户决策，需要严格 `needs-user` gate。
- 与现有 Codex Bridge 边界不清会导致底层协议和上层 PMO 职责混杂。
