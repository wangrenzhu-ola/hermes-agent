---
title: Codex PMO Ledger Runner 实施计划
date: 2026-04-25
status: active
origin: docs/brainstorms/2026-04-25-codex-pmo-ledger-runner-requirements.md
dem: DEM-013
---

# Codex PMO Ledger Runner 实施计划

## 问题框架

Codex PMO Ledger Runner 要把 compound 多阶段任务从 Hermes 的手动串行编排中拆出来。核心不是再做一个聊天入口，而是建立一个 ledger-first 的 PMO 编排器：所有阶段状态、child 运行、artifact、验证、风险和决策都落在 ledger；Hermes 只负责启动、观察和处理高风险或需要用户决策的状态。

本计划只覆盖后续实现方向。本阶段不写代码、不提交、不推送、不建 PR。

## 设计原则

- Ledger 是唯一事实源；child transcript 只是审计材料，不是 Hermes 必读上下文。
- PMO 和 child 分层明确：PMO 负责编排和收敛，child 只做单阶段输出。
- 默认安全：read-only 起步，work 阶段才 workspace-write，并记录批准来源。
- P0 起就证明 `PMO -> child Codex -> ledger` 闭环；Hermes 和用户只观察 ledger，不继续手动串阶段。
- 多任务并发从第一天进入 ledger/scheduler model：P0 至少支持多 task queued/running/done 展示和 read-only child concurrency limit。
- 复用 `tools/codex_bridge_tool.py` 和 `skills/codex-bridge/` 的 app-server JSON-RPC 能力，不把 mailbox 作为主路径。

## 已拍板决策

从 AI Infra 负责人视角，本计划不保留会阻塞 P0/P1 的开放决策：

- DEC-001：P0 采用 `skill_cli_only`。P0 交付 skill reference CLI、schema、validator、status JSON contract、child executor abstraction、基础 scheduler 和测试；不新增 Hermes slash command，不要求 gateway/TUI 集成。
- DEC-002：采用 `hybrid_docs_examples_runtime_state`。运行时 ledger 默认放在 profile-scoped Hermes state，例如 `get_hermes_home()/pmo/ledgers/`；`docs/ledgers/` 只保存 DEM 审查快照、示例和需要人工 review 的冻结副本。
- DEC-003：P0 采用 `abstraction_with_codex_bridge_default`。PMO Runner 依赖一个 child execution abstraction，默认实现调用现有 Codex Bridge 或受监督 exec-json runner；不得把 Bridge 的 app-server 协议、DB 或单任务状态上提为 compound ledger。

## 分阶段 MVP

### P0: PMO -> child dispatch MVP + ledger/status/validate

目标：从最小闭环开始证明 Hermes 不再手动推进下一阶段。Hermes 启动 PMO Runner 后，PMO 读取 ledger，scheduler 扫描 queued task，在 concurrency limit 内启动至少一个 read-only child Codex smoke，收集结构化结果，校验 artifact/validation，并把 child task id、状态、summary、risks、next_action 写回 ledger。P0 不新增 slash command，不注册新的 Hermes tool，不进入 work 写代码阶段。

候选文件：

- `skills/codex-pmo-ledger-runner/SKILL.md`：面向 Hermes 的 PMO Runner 技能说明。
- `skills/codex-pmo-ledger-runner/references/cli.py`：产品化 CLI，输出 JSON。
- `skills/codex-pmo-ledger-runner/references/ledger.py`：ledger load/save、原子写入、schema defaults、phase transition guard。
- `skills/codex-pmo-ledger-runner/references/validator.py`：ledger 和 CLI 输出校验。
- `skills/codex-pmo-ledger-runner/references/status_contract.py`：status/dashboard JSON contract。
- `skills/codex-pmo-ledger-runner/references/child_executor.py`：child execution abstraction，默认实现适配 Codex Bridge 或受监督 exec-json runner。
- `skills/codex-pmo-ledger-runner/references/scheduler.py`：扫描 queued tasks，按 concurrency limit 启动 read-only child。
- `tests/skills/test_codex_pmo_ledger_runner_skill.py`：CLI 和技能契约测试。
- `tests/skills/test_codex_pmo_ledger_runner_contract.py`：ledger schema、状态机、status 输出测试。
- `tests/skills/test_codex_pmo_child_dispatch_smoke.py`：child result contract、scheduler、read-only smoke 测试；真实 child smoke 可用 opt-in integration marker。
- `docs/ledgers/`：人工可读 ledger 示例和 DEM 审查快照，不作为 runtime 默认存储。

功能：

- 创建 ledger、读取 ledger、更新 phase/status、记录 artifact/risk/decision/validation。
- 创建和列出多条 task ledger；至少展示每条 task 的 `queued`、`running`、`done`、`failed` 状态、phase、next_action 和最近 child。
- `status` 命令输出稳定 JSON：`task_id`、`title`、`phase`、`status`、`result`、`next_action`、`blocking_decisions`、`high_risks`、`recent_children`、`artifacts`、`validation_summary`、`budget_summary`、`locks`、`audit_tail`。
- `list` 命令输出多任务状态摘要，供 Hermes 和用户观察 ledger。
- `validate` 命令校验 ledger YAML、必填字段、artifact path、phase transition guard、status contract。
- runtime ledger 默认解析到 `get_hermes_home()/pmo/ledgers/<task-id>.yaml`；CLI 允许显式读取 docs snapshot。
- ledger 写入使用临时文件 + atomic replace，并记录 `updated_at`。
- 状态机守卫：`document_review` 未通过时拒绝进入 `work`。
- child executor abstraction 返回标准 `child_result_required_fields`，PMO 校验通过后才写入 ledger。
- scheduler 扫描 queued read-only tasks，启动不超过 `scheduler.concurrency_limit` 的 child。
- 至少一个真实 child Codex dispatch smoke：推荐 document-review child；也可先做 no-op ledger validation child，但必须是真实 child task，不是 PMO 内部函数。
- PMO 写入 child task id/status/artifacts/summary/validation/risks/audit，并根据 result 设置 next_action。
- P0 禁止 work child、workspace-write、代码修改、commit、push、PR。

验证：

- ledger YAML 可 round-trip。
- 必填字段缺失会失败。
- child result 缺少 task id、artifact、validation 或 required fields 时标记 `invalid_output`，不推进 phase。
- scheduler 能从 queued tasks 中启动 child，且不会超过 concurrency limit。
- `list` 能展示多条 task 的 queued/running/done/failed 状态。
- phase transition 规则可测试：只有 `phases.document_review.status == done` 且 `result == pass` 且 plan validation 通过时才允许 `work`。
- `document_review.result == revise` 会要求修正 plan + re-review，不允许进入 work。
- status JSON contract 有快照式字段测试，但不写模型列表、版本号或枚举数量的 change-detector 测试。
- P0 完成后，Hermes 能只通过 CLI/status/list 判断：当前状态、最近 child、阻塞决策、高风险、artifact、validation、下一步。

### P1: 自动推进 brainstorm -> plan -> document-review 的多 child sequence

目标：在 P0 已能启动和追踪 child 的基础上，PMO 自动编排多个只读 child，完成 brainstorm -> plan -> document-review 序列，并把每个 child 的结果收敛到 ledger。

候选文件：

- `tools/codex_pmo_ledger_runner.py`：可选 Hermes tool wrapper，薄封装 P0 skill CLI/library；不得复制 schema/state machine。
- `skills/codex-pmo-ledger-runner/references/cli.py`
- `skills/codex-pmo-ledger-runner/references/prompts.py`：阶段 handoff 模板。
- `skills/codex-pmo-ledger-runner/references/child_executor.py`：扩展 P0 executor，支持 start/status/collect/interrupt。
- `skills/codex-pmo-ledger-runner/references/scheduler.py`：支持阶段依赖和 child sequence。
- `tests/tools/test_codex_pmo_child_contract.py`
- `tests/tools/test_codex_pmo_runner_state_machine.py`

功能：

- `run --until document-review`：读取 ledger，生成每阶段 handoff，按依赖启动 brainstorm、plan、document-review child。
- child 通过 P0 `child_executor` 启动；默认 `sandbox="read-only"`、`approval_policy="on-request"`。
- 每个 child 输出 artifact path、summary、validation、risks、next recommendation。
- PMO 校验每个 child 输出和 artifact，写回 ledger，并只根据 ledger 推进下一 child。
- document-review 若 block，ledger 进入 `blocked` 或 `needs-user`。
- document-review 若 revise，PMO 只能把 next_action 设为 `revise_plan_and_rerun_document_review`，不得进入 work。

关键约束：

- child 只拿压缩 handoff，不拿完整历史。
- P1 不进入 work，不写业务代码。
- 每个 child 都有超时、模型、effort、耗时记录。
- child 输出必须满足 `child_result_required_fields`；缺字段时写 `invalid_output`，不推进 phase。

### P2: work/review/compound/PR with worktree/write lock

目标：把执行阶段纳入 PMO，但每条任务隔离在独立 worktree/branch。

候选文件：

- `tools/codex_pmo_ledger_runner.py`
- `tools/codex_pmo_worktree.py`：worktree/branch/lock 辅助逻辑，或合并进 runner 内部模块。
- `tests/tools/test_codex_pmo_worktree.py`
- `tests/tools/test_codex_pmo_security.py`
- `docs/solutions/developer-experience/`：compound 输出位置。

功能：

- 创建或绑定 task worktree 和 branch。
- work 阶段只在 document-review pass 后启动。
- work child 使用 `workspace-write`，ledger 记录 sandbox、批准来源、路径边界。
- `danger-full-access` 和 `approval_policy=never` 在 P2 仍禁止，不能作为自动升级路径。
- review child 读取 diff、测试输出和 plan，生成审查 artifact。
- compound 阶段生成 solution/learning 文档。
- PR 自动化保留到 P2 后半段；PR 标题和正文未来必须中文。

关键约束：

- 不修改主 checkout。
- repo 级写入并发默认 1，必须有 repo lock lease、heartbeat、stale lock 检测和 audit。
- work 阶段失败必须保留 diff、测试输出和恢复建议。

### P3: 完整 dashboard、多 repo、长期 scheduler 优化

目标：在 P0/P1 已有多任务 ledger/list 和基础 scheduler、P2 已有 worktree/write lock 后，补完整 dashboard、多 repo 管理和长期运行的 scheduler 优化。

候选文件：

- `hermes_cli/commands.py`：如需要新增 `/pmo` 或 `/ledger` slash command。
- `cli.py`：交互 CLI handler，需遵守 slash command registry 规则。
- `gateway/run.py`：如需要 gateway 查询 ledger/status。
- `ui-tui/src/` 和 `tui_gateway/server.py`：后续 TUI dashboard 候选，不作为 MVP 必需。
- `hermes_cli/web_server.py`：后续 web status 候选。
- `tests/test_cli_*.py`、`tests/gateway/`、`tests/test_tui_gateway_server.py`：按实际入口补充。

功能：

- scheduler 扫描多个 ledger，根据 `next_action` 推进。
- repo lock / slot 管理，避免写入冲突。
- dashboard 展示所有任务的 phase、status、risks、decisions、budget。
- high-risk、needs-user、failed 自动通知 Hermes supervisor。

## 数据结构草案

Ledger 顶层结构：

```yaml
schema_version: 1
runner_version: 0.1.0
task_id: DEM-013
title: Codex PMO Ledger Runner
phase: brainstorm_plan
status: running
repo:
  root: .
  base_branch: main
  task_branch: codex/pmo-ledger-runner
  worktree: .
  repo_lock_key: hermes-agent
storage:
  mode: hybrid_docs_examples_runtime_state
  runtime_path: ~/.hermes/pmo/ledgers/DEM-013.yaml
  docs_snapshot_path: docs/ledgers/codex-pmo-ledger-runner-ledger.yaml
  active_source: runtime
policy:
  child_depth_limit: 1
  default_sandbox: read-only
  work_sandbox: workspace-write
  approval_policy: on-request
  work_requires_document_review_pass: true
  danger_full_access_allowed: false
  approval_policy_never_allowed: false
scheduler:
  concurrency_limit: 1
  read_only_child_limit: 1
  work_child_limit_per_repo: 0
  scan_statuses: [queued]
  supported_p0_task_kinds:
    - document_review_smoke
    - ledger_validation_smoke
tasks:
  - task_id: DEM-013
    status: queued
    phase: document_review
    next_action: start_p0_child_dispatch_mvp
phases:
  brainstorm_plan:
    status: done
    result: artifacts_created
    artifacts: []
  document_review:
    status: queued
    result: null
    transition_guard:
      work_requires_result: pass
children: []
artifacts: []
validation: []
risks: []
decisions_needed: []
locks:
  ledger:
    status: unlocked
  repo:
    status: not_requested
status_contract:
  version: 1
  required_fields:
    - task_id
    - title
    - phase
    - status
    - result
    - next_action
    - blocking_decisions
    - high_risks
    - recent_children
    - artifacts
    - validation_summary
    - budget_summary
    - locks
    - audit_tail
next_action:
  type: start_p0_child_dispatch_mvp
  owner: codex_pmo
budget:
  children_started: 0
  elapsed_seconds: 0
audit: []
```

Child result contract：

```yaml
child_id: child-001
phase: document_review
status: done
result: pass
model: gpt-5.3-codex
effort: high
sandbox: read-only
approval_policy: on-request
started_at: "2026-04-25T00:00:00Z"
ended_at: "2026-04-25T00:05:00Z"
artifacts:
  - path: docs/reviews/DEM-013-document-review.md
    kind: document_review
summary: "..."
validation:
  - name: required_sections_present
    status: pass
risks:
  - severity: medium
    description: "..."
next_recommendation:
  action: revise_plan
  reason: "..."
```

## 命令接口草案

P0 skill CLI：

```bash
python skills/codex-pmo-ledger-runner/references/cli.py init --task-id DEM-013 --title "Codex PMO Ledger Runner"
python skills/codex-pmo-ledger-runner/references/cli.py list
python skills/codex-pmo-ledger-runner/references/cli.py status docs/ledgers/codex-pmo-ledger-runner-ledger.yaml
python skills/codex-pmo-ledger-runner/references/cli.py validate docs/ledgers/codex-pmo-ledger-runner-ledger.yaml
python skills/codex-pmo-ledger-runner/references/cli.py run --until child-smoke docs/ledgers/codex-pmo-ledger-runner-ledger.yaml
python skills/codex-pmo-ledger-runner/references/cli.py record-decision docs/ledgers/codex-pmo-ledger-runner-ledger.yaml DEC-001 --choice skill_cli_only
```

P1+ 工具接口候选：

```text
codex_pmo_ledger_runner(action="init", task_id="DEM-013", title="...")
codex_pmo_ledger_runner(action="status", ledger_path="docs/ledgers/codex-pmo-ledger-runner-ledger.yaml")
codex_pmo_ledger_runner(action="advance", ledger_path="...", until="document_review")
codex_pmo_ledger_runner(action="record_decision", ledger_path="...", decision_id="...", choice="...")
codex_pmo_ledger_runner(action="validate", ledger_path="...")
codex_pmo_ledger_runner(action="list", repo=".")
```

Status JSON contract 草案：

```json
{
  "task_id": "DEM-013",
  "title": "Codex PMO Ledger Runner",
  "phase": "document_review",
  "status": "done",
  "result": "pass",
  "next_action": {"type": "start_p0_child_dispatch_mvp", "owner": "codex_pmo"},
  "blocking_decisions": [],
  "high_risks": [],
  "recent_children": [
    {"child_id": "child-001", "phase": "document_review", "status": "done", "result": "pass"}
  ],
  "artifacts": [],
  "validation_summary": {"pass": 0, "fail": 0, "warning": 0},
  "budget_summary": {"children_started": 1, "elapsed_seconds": null},
  "locks": {"ledger": {"status": "unlocked"}, "repo": {"status": "not_requested"}},
  "audit_tail": []
}
```

未来 Hermes slash command 候选：

```text
/pmo status
/pmo advance DEM-013
/pmo decide DEM-013 <decision-id>
/pmo dashboard
```

## 测试策略

必须使用 `scripts/run_tests.sh`，不直接调用 pytest。

P0 测试：

- `tests/skills/test_codex_pmo_ledger_runner_contract.py`
- 覆盖 ledger init、load/save、schema validation、status summary。
- 覆盖 child executor abstraction 和 required output fields。
- 覆盖 scheduler 扫描 queued tasks、启动 read-only child、遵守 concurrency limit。
- 覆盖 `list` 多任务状态输出，至少包含 queued/running/done/failed。
- 覆盖真实 child dispatch smoke 的 opt-in integration 路径；默认单元测试可用 fake executor，但 P0 验收必须跑一次真实 read-only child。
- 覆盖 phase transition：未通过 document-review 时拒绝 work。
- 覆盖 hybrid storage path：runtime 默认使用 `get_hermes_home()`，docs ledger 只作为显式 snapshot。
- 覆盖 stale/in-use ledger lock 不会被静默覆盖。

P1 测试：

- `tests/tools/test_codex_pmo_child_contract.py`
- 验证多 child sequence：brainstorm child -> plan child -> document-review child。
- 验证 PMO 只根据 ledger 和 child result contract 推进阶段，处理 invalid output。
- mock `codex_bridge` 用于错误路径和超时路径；真实 read-only child path 已在 P0 smoke 覆盖。

P2 测试：

- `tests/tools/test_codex_pmo_worktree.py`
- 使用临时 git repo 验证 branch/worktree 创建、路径隔离、lock 行为。
- `tests/tools/test_codex_pmo_security.py` 覆盖 sandbox 默认值和权限升级审计。

P3 测试：

- scheduler 多 ledger 扫描、repo slot 限制、stale lock 处理。
- CLI/gateway/TUI dashboard 按实际入口补充集成测试。

## 与现有 Codex Bridge 的集成边界

现有边界：

- `tools/codex_bridge_tool.py` 已通过 Codex app-server stdio JSON-RPC 启动、查询、steer、interrupt、respond Codex 任务。
- `skills/codex-bridge/` 是 Bridge 的产品化 CLI 和校验层。
- Bridge 明确不使用 mailbox，并拒绝 `danger-full-access` 和 `approval_policy=never` 默认路径。

PMO Runner 应做：

- 作为上层编排器调用 Bridge 或未来 exec-json runner。
- 根据阶段选择 sandbox、model、effort、prompt/handoff。
- 把 Bridge task id、thread id、状态摘要写入 ledger。
- 使用 Bridge 的 status/notification 能力获得 child 完成摘要。
- 通过 `child_executor` abstraction 依赖 Bridge 的稳定 start/status/steer/interrupt/respond contract，允许微信侧或其他 Codex Bridge 垂直增强底层 transport，而不影响 PMO ledger schema。

PMO Runner 不应做：

- 不重写 Codex app-server 协议。
- 不把 PMO ledger 写进 `codex_bridge.db` 作为主要事实源。
- 不把 Bridge 的单任务状态当作 compound 任务状态。
- 不让 Bridge 负责 phase state machine、决策 gate 或 repo lock。
- 不把 mailbox/inbox/outbox 作为 child 主路径或 fallback 主路径。

## 实施顺序建议

1. P0 先落 `skills/codex-pmo-ledger-runner/` 的 ledger/status/list/validate、child executor abstraction、基础 scheduler 和 read-only child dispatch smoke。
2. P0 锁定 status JSON contract、runtime ledger path、ledger lock、phase transition guard、child result contract 和 concurrency limit。
3. P1 扩展为 brainstorm -> plan -> document-review 的多 child sequence，并保持只读阶段。
4. P2 开始前必须先做 document-review，通过后再允许 worktree、write lock 和写入阶段。
5. P3 在 P0/P1/P2 闭环稳定后做完整 dashboard、多 repo 和长期 scheduler 优化。

## 风险与缓解

- 风险：P0 schema 一次设计过重。缓解：只强制状态机和必填字段，其他字段允许向后兼容扩展。
- 风险：P0 child dispatch 把实现面拉大。缓解：只允许 read-only smoke 和最小 scheduler，不进入 work、不改 worktree。
- 风险：PMO 自动推进绕过用户。缓解：把 `needs-user` gate 写成 transition guard 并测试。
- 风险：child 输出格式不稳定。缓解：validator 接受 JSON/YAML 结构化摘要，缺字段不推进。
- 风险：worktree 并发破坏用户改动。缓解：每任务独立 worktree，repo 写 slot 默认 1。
- 风险：Bridge 与 Runner 职责混杂。缓解：Bridge 只管 Codex task transport，Runner 只管 compound PMO state。

## Document-review 关注点

下一阶段 document-review 应重点审查：

- ledger schema 是否足够支撑恢复、dashboard 和并发。
- phase state machine 是否严格阻止未审查 plan 进入 work。
- 安全默认值是否符合 read-only 优先、workspace-write 有记录的约束。
- P0/P1/P2/P3 切片是否过大，是否能独立验收。
- 与 `tools/codex_bridge_tool.py` / `skills/codex-bridge/` 的边界是否清晰。
