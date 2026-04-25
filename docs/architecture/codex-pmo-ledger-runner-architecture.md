# DEM-013 Codex PMO Ledger Runner 架构图

## 总览

```mermaid
flowchart TB
  U[User] -->|目标/决策/验收| H[Hermes Supervisor]
  H -->|观察 status/list/ledger，不推进每个 phase| L[(PMO Ledger\n唯一事实源)]

  P[Codex PMO Runner] -->|读取 queued/runnable tasks| L
  P -->|写 phase/status/children/artifacts/validation/risks/audit| L
  P -->|按 concurrency limit 调度| S[Scheduler]
  S -->|启动 read-only child| C1[Child Codex: brainstorm/plan/doc-review smoke]
  S -->|未来 P1/P2 启动 phase child| C2[Child Codex: phase worker]

  C1 -->|结构化 child result JSON/YAML| P
  C2 -->|artifact path + summary + validation + risks| P

  P -->|真实 Codex child 默认走抽象 executor| E[Child Executor Abstraction]
  E -->|默认真实路径| B[Codex Bridge\napp-server / JSON-RPC]
  E -->|测试/CI| F[Fake Executor]

  B -. 不使用 .-> M[Mailbox/inbox/outbox]

  subgraph Repo Isolation
    W1[Task Worktree A]
    W2[Task Worktree B]
    Lock[Repo write lock / slot]
  end

  P --> W1
  P --> W2
  P --> Lock
```

## Phase 状态机

```mermaid
stateDiagram-v2
  [*] --> brainstorm_plan
  brainstorm_plan --> document_review: requirements/plan ready
  document_review --> work: review pass
  document_review --> needs_user: product/security decision
  document_review --> blocked: review blocks
  work --> review: implementation + validation
  review --> compound: review approve
  review --> work: P0/P1 fixes needed
  compound --> pr
  pr --> done
  needs_user --> document_review: decision recorded
  blocked --> document_review: docs fixed
```

## P0 已实现能力

```mermaid
sequenceDiagram
  participant H as Hermes/User
  participant CLI as PMO CLI run-once
  participant L as Ledger YAML
  participant S as Scheduler
  participant X as Child Executor(fake/codex-bridge)

  H->>CLI: run-once --executor fake --concurrency-limit N
  CLI->>L: load ledgers
  CLI->>S: find queued runnable P0-safe tasks
  S->>X: dispatch read-only child smoke
  X-->>S: structured child result
  S->>L: append children/artifacts/validation/audit
  CLI-->>H: JSON summary
  H->>L: observe status/list, not raw child logs
```

## 控制面原则

PMO/Hermes 只看：

- completion event
- structured status
- ledger delta
- artifact path
- validation summary
- risks / decisions_needed

禁止把 raw child logs/transcripts 作为常规控制面。
