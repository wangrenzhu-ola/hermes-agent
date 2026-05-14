---
title: feat: Add structured Codex-style skill create contract
type: feat
status: active
date: 2026-05-14
origin: https://github.com/wangrenzhu-ola/hermes-agent/issues/13
---

# feat: Add structured Codex-style skill create contract

## Overview

为 Hermes Agent 增加一个 Codex 兼容的结构化 `skill create` 路径，让技能沉淀从“模型自由写一大段提示词”转为“结构化输入、代码校验、确定性渲染、机器可读输出”。现有 `tools/skill_manager_tool.py` 已经有技能目录创建、`SKILL.md` frontmatter 校验、支持文件目录限制、路径穿越防护和测试覆盖；本计划复用这些约束，把新增工作集中在版本化 schema、请求归一化、模板渲染、CLI/agent 调用面、文档和隔离 smoke。

---

## Problem Frame

Issue #13 的核心问题是 Hermes 的技能沉淀过度依赖长 prompt 和自由格式写作，导致规则漂移、审计困难、失败输出不稳定。目标是在 `wangrenzhu-ola/hermes-agent` 中提供一个可由 agent 调用的结构化技能创建契约：输入/输出版本化，名称、路径、frontmatter、支持文件位置等约束由代码拥有，生成结果可测试、可验证、可部署到当前活跃 Hermes 环境。

---

## Requirements Trace

- R1. 提供版本化结构化输入 schema，对应 AC-001。
- R2. 提供版本化结构化输出 schema，并由实现返回至少 `status`、`skill_name`、`path`、`files_written`、`validation`、`warnings`、`next_actions`，对应 AC-002。
- R3. `skill create` 兼容流程可以生成有效 `SKILL.md`，frontmatter 稳定，文件布局确定，对应 AC-003。
- R4. 校验拒绝 unsafe name/path、畸形输入、缺失字段，并返回机器可读错误，对应 AC-004。
- R5. 单元测试覆盖成功路径与失败路径，对应 AC-005。
- R6. 文档或开发者帮助说明 Hermes agent 如何调用结构化技能创建路径，对应 AC-006。
- R7. 合并后更新当前活跃 Hermes 环境，对应 AC-007 和 AC-008。
- R8. 在临时或隔离 skills root 中做 active-runtime smoke，证明新路径可发现/加载技能且不污染生产 skills，对应 AC-009。

---

## Scope Boundaries

- 不改业务领域技能和 AI-Infra governance 内容。
- 不把 prompt-only policy text 作为主要约束来源。
- 不把敏感运行时材料写进生成技能；涉及平台身份、人类确认或私密凭据的来源内容必须落为 blocker 或 placeholder。
- 不重写现有 `skill_manage` 能力；结构化路径应复用其已经验证过的文件安全和 frontmatter 规则，必要时抽取共享 helper。

### Deferred to Follow-Up Work

- PR 合并、活跃环境更新、active-runtime smoke 属于 `gh:work`/delivery 阶段，计划阶段只定义验收方式。

---

## Context & Research

### Relevant Code and Patterns

- `tools/skill_manager_tool.py`：现有 agent-managed skill 创建、编辑、patch、删除和支持文件写入工具；包含 `_validate_name`、`_validate_category`、`_validate_frontmatter`、`_validate_file_path`、`_create_skill`、`_write_file` 等可复用规则。
- `tests/tools/test_skill_manager_tool.py`：已有名称校验、category 校验、frontmatter 校验、路径穿越、支持目录限制、重复技能等测试模式。
- `tools/skills_tool.py`：技能加载和 `SKILL.md` frontmatter 格式约定，说明 `SKILL.md` 是 required，支持 `references/`、`templates/`、`scripts/`、`assets/`。
- `agent/skill_utils.py`：轻量 frontmatter parsing 和 skills root/external dirs 工具，适合作为新增结构化路径的共享依赖。
- `hermes_cli/main.py` 和 `hermes_cli/skills_hub.py`：`hermes skills <subcommand>` 已存在，新增结构化 create CLI 应放在该命令族下。
- `AGENTS.md`：要求优先使用 `.venv`，`scripts/run_tests.sh` 会探测 `.venv`、`venv`、`$HOME/.hermes/hermes-agent/venv`；CLI 命令需走 `hermes_cli/commands.py` 注册体系时才会同步到帮助、gateway 和 autocomplete。

### Institutional Learnings

- 本阶段可用 HKTMemory 检索失败，不能把向量记忆当作计划依据。
- 既有 issue artifact 明确要求使用干净 worktree 或隔离 checkout，避免破坏 unrelated dirty changes。

### External References

- 未使用外部资料。目标 repo 已有足够直接模式：技能创建工具、技能加载工具、CLI 命令族和测试套件。

---

## Key Technical Decisions

- 复用现有 skill manager 约束而不是另建一套校验规则：这样 AC-003/AC-004 可以继承已经测试过的 `SKILL.md`、名称、路径和支持文件目录规则，减少漂移。
- 新增结构化 library 作为核心，实现 CLI 和 agent 调用共享：CLI/工具层只负责解析输入和输出，schema validation、归一化、渲染和写入结果由单一模块拥有。
- schema 采用版本字段显式分流：初版固定 `schema_version: "hermes.skill_create_request.v1"` 和 `schema_version: "hermes.skill_create_result.v1"`，后续升级可并存处理。
- 支持文件只允许写入 `references/`、`templates/`、`scripts/`、`assets/`：与 `tools/skill_manager_tool.py` 的 `ALLOWED_SUBDIRS` 保持一致。
- smoke 必须使用临时或显式隔离 skills root：AC-009 的关键不是只生成文件，而是证明 active Hermes 可以发现/加载，同时不污染生产 `~/.hermes/skills`。

---

## Open Questions

### Resolved During Planning

- 结构化路径应替换还是复用 `skill_manage`：复用并抽取共享校验/写入逻辑，避免两套文件安全规则。
- CLI 应挂在哪里：挂在 `hermes skills create`，因为 repo 已有 `hermes skills` 命令族；agent-facing helper 可直接调用 library。

### Deferred to Implementation

- 最终模块名是否为 `tools/structured_skill_create.py` 或拆到 `agent/skill_create_contract.py`：实现时根据 import 依赖避免循环。
- 是否需要 `--dry-run`：issue 未要求；如果实现成本低，可作为验证-only 模式，但不能影响 AC 必需路径。
- 活跃环境具体更新命令：依赖本机当前 Hermes 安装形态和 PR 合并后的 checkout 状态，应在 delivery 阶段确认。

---

## Output Structure

    tools/
      structured_skill_create.py
    hermes_cli/
      skill_create.py
    tests/
      tools/
        test_structured_skill_create.py
      hermes_cli/
        test_skills_create_command.py
    docs/
      structured-skill-create.md

## Structured Schema Deliverables

AC-001 and AC-002 require inspectable schema deliverables, not only prose field lists or incidental Python validation. The implementation must expose the v1 request and result schemas in a deterministic form that black-box callers and tests can inspect.

- `tools/structured_skill_create.py` must export `REQUEST_SCHEMA_VERSION = "hermes.skill_create_request.v1"` and `RESULT_SCHEMA_VERSION = "hermes.skill_create_result.v1"`.
- The module must expose request/result schema objects through stable names such as `SKILL_CREATE_REQUEST_SCHEMA_V1` and `SKILL_CREATE_RESULT_SCHEMA_V1`, or typed models with deterministic `to_json_schema()`/equivalent export functions.
- Schema exports must include required fields, optional fields, enum values, and stable validation error codes. At minimum, required request fields are `schema_version`, `name`, `description`, and `instructions`; required result fields are `schema_version`, `status`, `skill_name`, `path`, `files_written`, `validation`, `warnings`, and `next_actions`.
- Tests must assert schema version constants, required fields, `status` enum values, and validation error code enum values. These tests are the black-box evidence for AC-001 and AC-002.
- CLI/help documentation may describe the schema, but the code-level schema export is the source of truth.

---

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

```mermaid
flowchart LR
  A[JSON/YAML request] --> B[parse + schema_version dispatch]
  B --> C[normalize skill name/category/support files]
  C --> D[validate required fields and safety rules]
  D --> E[render deterministic SKILL.md]
  E --> F[write via existing skill manager-compatible helpers]
  F --> G[validate generated skill loadability]
  G --> H[versioned machine-readable result]
```

---

## Implementation Units

- [ ] U1. **Define structured request/result contract**

**Goal:** 建立版本化输入和输出数据模型，确保 AC-001/AC-002 有稳定代码契约，而不是散落在 prompt 文本中。

**Requirements:** R1, R2, R4

**Dependencies:** None

**Files:**
- Create: `tools/structured_skill_create.py`
- Test: `tests/tools/test_structured_skill_create.py`

**Approach:**
- 定义 v1 request 字段：`schema_version`、`name`、`description`、`intent`、`instructions`、`category`、`metadata`、`support_files`、`source_context`、`overwrite_policy`。
- 定义 v1 result 字段：`schema_version`、`status`、`skill_name`、`path`、`files_written`、`validation`、`warnings`、`next_actions`。
- 导出 inspectable schema artifact：`SKILL_CREATE_REQUEST_SCHEMA_V1` 和 `SKILL_CREATE_RESULT_SCHEMA_V1`，或等价 typed model schema export；字段顺序和 enum 值必须稳定。
- validation error 使用稳定 code，例如 `INVALID_SCHEMA_VERSION`、`MISSING_REQUIRED_FIELD`、`INVALID_SKILL_NAME`、`UNSAFE_FILE_PATH`、`DUPLICATE_SKILL`、`INVALID_FRONTMATTER`。
- `status` 至少区分 `success`、`validation_error`、`write_error`，避免调用方解析自然语言。

**Execution note:** 先写失败用例覆盖 schema version、必填字段和机器可读错误，再实现模型和校验。

**Patterns to follow:**
- `tools/skill_manager_tool.py` 的 `_validate_name`、`_validate_category`、`_validate_file_path`、`ALLOWED_SUBDIRS`。
- `tests/tools/test_skill_manager_tool.py` 的 table-style failure assertions。

**Test scenarios:**
- Happy path: 输入完整 v1 request，归一化后 result schema 包含全部必需字段，`validation.errors` 为空。
- Schema path: request/result schema exports include expected version constants, required fields, allowed `status` values, and stable validation error codes.
- Error path: `schema_version` 缺失或未知，返回 `status=validation_error` 和 `INVALID_SCHEMA_VERSION`。
- Error path: 缺失 `name`、`description` 或 `instructions`，返回对应字段级错误。
- Error path: `support_files` 使用 `../escape.txt` 或顶层 `secret.txt`，返回 `UNSAFE_FILE_PATH`，且不写文件。
- Edge case: category 为空时生成 flat skill path；category 含 `/` 时返回机器可读错误。

**Verification:**
- 结构化校验层不依赖模型文本，所有失败路径都能由调用方只看 JSON 字段判断。

---

- [ ] U2. **Render deterministic SKILL.md and write allowed support files**

**Goal:** 从结构化输入生成稳定 `SKILL.md` 和可选支持文件，复用既有 skill manager 安全写入约束。

**Requirements:** R3, R4

**Dependencies:** U1

**Files:**
- Modify: `tools/structured_skill_create.py`
- Modify: `tools/skill_manager_tool.py`
- Test: `tests/tools/test_structured_skill_create.py`
- Test: `tests/tools/test_skill_manager_tool.py`

**Approach:**
- 将可复用的验证或写入 helper 保持在 `tools/skill_manager_tool.py` 或轻量抽到新模块，但避免破坏现有 `skill_manage` API。
- 生成 `SKILL.md` frontmatter 时固定字段顺序：`name`、`description`，可选 `version`、`metadata`。
- body 使用确定性 section 顺序：标题、触发条件、步骤、验证、注意事项；来自 request 的 `instructions` 和 `source_context` 只能进入明确 section。
- 支持文件写入前逐个调用现有路径校验，写入后统一返回 repo/runtime 相对路径列表。
- duplicate skill 默认拒绝；只有明确 overwrite policy 且实现安全时才允许覆盖。
- 多文件写入必须以临时目录或等价 staged write 实现原子化：任一文件校验或写入失败时，不得留下可被 discovery 看到的半成品 skill 目录。

**Execution note:** 对渲染输出做精确字符串或结构断言，防止字段顺序和目录布局漂移。

**Patterns to follow:**
- `_create_skill` 的 frontmatter/content validation 和 atomic write。
- `_write_file` 的 allowed subdirectory/path traversal 处理。

**Test scenarios:**
- Happy path: request 生成 `<skill>/SKILL.md`，frontmatter 含稳定 `name` 和 `description`，body section 顺序稳定。
- Happy path: `support_files` 写入 `references/guide.md`、`templates/template.md`、`scripts/helper.py`、`assets/sample.txt` 并返回 `files_written`。
- Error path: duplicate skill 在默认 policy 下失败，返回 `DUPLICATE_SKILL`，不覆盖原文件。
- Error path: frontmatter 渲染后不合法时返回 `INVALID_FRONTMATTER`，不留下半成品目录。
- Error path: 一个合法 support file 之后跟随一个 unsafe path 时整体失败，返回 `UNSAFE_FILE_PATH`，且 skill 目录和已 staging 的 support file 都不存在。
- Integration: 生成后的 `SKILL.md` 可被 `tools.skills_tool.skill_view` 或相同 frontmatter parser 读取。

**Verification:**
- 生成布局稳定，失败时无半写入文件或路径逃逸。

---

- [ ] U3. **Expose `hermes skills create` CLI for structured input**

**Goal:** 给人和自动化 executor 一个清晰入口，通过 JSON/YAML 文件或 stdin 调用结构化创建路径。

**Requirements:** R1, R2, R3, R4, R6

**Dependencies:** U1, U2

**Files:**
- Create: `hermes_cli/skill_create.py`
- Modify: `hermes_cli/main.py`
- Modify: `hermes_cli/commands.py`
- Test: `tests/hermes_cli/test_skills_create_command.py`

**Approach:**
- 在 `hermes skills` 子命令族下新增 `create`，接受 `--input <path>` 或 stdin。
- 支持 JSON 和 YAML 解析；解析失败统一转为 v1 result JSON。
- CLI stdout 默认输出 machine-readable JSON；人类可读 Rich 输出如要支持，应放在显式 flag 后，避免 agent 调用面不稳定。
- 帮助文本说明 request/result schema、skills root 隔离参数和示例最小 payload。

**Patterns to follow:**
- `hermes_cli/main.py` 中现有 `skills search/install/inspect/list` argparse 子命令。
- `hermes_cli/skills_hub.py` 的 `do_*` 函数拆分模式：CLI parser 薄，逻辑函数可测试。

**Test scenarios:**
- Happy path: CLI 读取 JSON request，stdout 返回 `status=success` 和 `files_written`。
- Happy path: CLI 读取 YAML request，行为与 JSON 一致。
- Error path: malformed JSON/YAML 返回 `status=validation_error`，stderr 不成为唯一错误来源。
- Error path: 未提供 input 且 stdin 为空，返回缺失输入错误。
- Integration: `hermes skills create --help` 包含 structured contract 说明和最小字段名。

**Verification:**
- agent 可以稳定调用 CLI 并只解析 stdout JSON 判断结果。

---

- [ ] U4. **Add agent-facing helper/tool compatibility path**

**Goal:** 让 Hermes agent 可以在需要沉淀 workflow 时调用结构化路径，而不是自行拼接完整 `SKILL.md`。

**Requirements:** R1, R2, R3, R4, R6

**Dependencies:** U1, U2

**Files:**
- Modify: `tools/skill_manager_tool.py`
- Modify: `tools/registry.py` or existing tool registration surface if needed
- Test: `tests/tools/test_skill_manager_tool.py`
- Test: `tests/tools/test_structured_skill_create.py`

**Approach:**
- 保持 `skill_manage(action="create")` 兼容旧调用。
- 新增结构化 action 或新工具名时，参数 schema 必须表达 request object，不要求模型写完整 `SKILL.md`。
- 输出直接返回 v1 result JSON，不把错误只放在自然语言 `error` 字符串。
- 如果选择扩展 `skill_manage`，需确保旧 tests 不变；如果选择新工具，需确保 toolset 分类仍为 `skills`。

**Patterns to follow:**
- `SKILL_MANAGE_SCHEMA` 的 tool registration 方式。
- `tests/run_agent/test_run_agent.py` 中 toolset/tool name 归类测试。

**Test scenarios:**
- Happy path: agent-facing structured call 创建技能并返回 v1 result。
- Error path: unsafe support file 返回 structured validation error。
- Regression: 旧 `skill_manage(action="create", content=...)` 仍然通过现有测试。
- Integration: tool registry 能发现新结构化入口或扩展后的 schema。

**Verification:**
- agent 不需要生成完整 `SKILL.md` 也能创建合规技能；旧接口无破坏。

---

- [ ] U5. **Document contract and operational usage**

**Goal:** 给 Hermes agent caller 和开发者明确调用方式、字段含义、错误处理、隔离 smoke 用法。

**Requirements:** R6, R8

**Dependencies:** U1, U2, U3

**Files:**
- Create: `docs/structured-skill-create.md`
- Modify: `README.md` or `README.zh-CN.md` if repo convention expects feature discoverability there
- Test: `tests/hermes_cli/test_skills_create_command.py`

**Approach:**
- 文档包含最小 JSON/YAML request、成功 result、validation error result、支持文件目录规则、敏感信息处理规则。
- 明确 agent prompt 应只传意图和来源上下文，格式和路径规则由代码处理。
- 说明如何使用临时 skills root 或 profile 隔离 smoke，避免污染生产 skills。

**Patterns to follow:**
- README 中现有 CLI feature 说明风格。
- `tools/skills_tool.py` docstring 中的技能目录结构说明。

**Test scenarios:**
- Test expectation: none -- 文档本身不引入运行时行为；CLI help 测试在 U3 覆盖字段可发现性。

**Verification:**
- 新开发者可以只看文档构造一个有效 structured request，并知道如何处理失败 result。

---

- [ ] U6. **Delivery validation and active-environment smoke**

**Goal:** 合并后更新当前活跃 Hermes 环境，并用隔离 root 验证结构化创建路径可被 active runtime 发现或加载。

**Requirements:** R7, R8

**Dependencies:** U1, U2, U3, U4, U5

**Files:**
- Modify: `scripts/run_tests.sh` only if existing test runner cannot cover new tests
- Test: `tests/tools/test_structured_skill_create.py`
- Test: `tests/hermes_cli/test_skills_create_command.py`

**Approach:**
- PR 合并前运行 focused unit/CLI tests 和 repo test runner 的相关 slice。
- 合并后更新当前活跃 Hermes checkout/environment，再执行隔离 smoke。
- smoke 创建 disposable skill，验证生成、加载、发现，然后清理临时 root；不得写入生产 `~/.hermes/skills`。
- smoke result 需要保存 evidence，供 AC-007 到 AC-009 勾选。

**Patterns to follow:**
- `AGENTS.md` 中 `.venv` 和 `scripts/run_tests.sh` 的环境探测方式。
- `tests/tools/test_skill_manager_tool.py` 的 tmp skills root patching 模式。

**Test scenarios:**
- Integration: 临时 skills root 中 structured create 成功后，Hermes skill loading path 可以读取该 `SKILL.md`。
- Error path: active smoke 若发现生产 root 被写入，应失败并记录污染路径。
- Regression: 更新 active environment 后 `hermes skills list` 或等效 discovery 不因新增入口崩溃。

**Verification:**
- AC-007/AC-008/AC-009 有真实命令输出或日志 evidence；若 runtime 不可用，必须记录 blocked/skipped，不得声称完成。

## Delivery Evidence Contract

Delivery is not complete until AC-007 through AC-009 have concrete evidence artifacts. If any step cannot run in the available environment, the delivery phase must mark that criterion blocked or skipped with the exact command and reason.

- **AC-007 merge evidence:** record the PR URL/number, merge commit SHA, target branch, and `git rev-parse HEAD` from the merged checkout. If no PR can be merged from the phase environment, record `BLOCKED_NO_MERGE_PERMISSIONS_OR_REMOTE_STATE`.
- **AC-008 active environment update evidence:** detect the active Hermes install in this order: `command -v hermes`, `hermes --version` or equivalent CLI version output, `python -c` import path for `hermes_cli`, and any repo path reported by the active executable. Record the update command actually used, such as pulling the active checkout, reinstalling editable package, or restarting the active service. If the active install cannot be identified or updated without unsafe global changes, record a blocked verdict.
- **AC-009 isolated smoke evidence:** run the structured create path with a temporary skills root only. Record `mktemp` root path, pre/post listing for the production skills root if it exists, the structured request payload path, result JSON path, discovery/load command output, and cleanup result. The smoke must fail if production `~/.hermes/skills` changes.
- **Evidence paths:** save command transcripts or JSON summaries under the GCW reports/work area and reference them from the handoff JSON. Do not rely on chat text as the only evidence.
- **Closeout rule:** local unit tests plus a generated skill in the scratch checkout are insufficient for AC-007 through AC-009. Those criteria require merge, active-environment update, and active-runtime smoke evidence or an explicit blocked/skipped verdict.

---

## System-Wide Impact

- **Interaction graph:** 新入口连接 `hermes skills create`、agent-facing skills tool、`tools/skill_manager_tool.py`、`tools/skills_tool.py` 和 skill discovery/cache invalidation。
- **Error propagation:** validation 和 write failure 必须以 result JSON 传播；Rich/stderr 文本只能辅助人类阅读。
- **State lifecycle risks:** 创建技能涉及目录和多文件写入；失败时需避免半成品目录、重复覆盖、cache 未清理。
- **API surface parity:** CLI 与 agent tool 必须共享同一 library，避免同一 request 在两个入口产生不同结果。
- **Integration coverage:** 仅 mock schema 不足以证明 AC-003/AC-009；必须覆盖生成后 load/discovery 的跨层路径。
- **Unchanged invariants:** 现有 `skill_manage(action="create", content=...)`、`skill_view`、`skills_list`、hub install 和 bundled skill sync 不应改变语义。

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| 两套技能创建规则并存导致漂移 | 新结构化入口复用或抽取 `skill_manager_tool` 现有校验和写入 helper |
| CLI 为人类输出 Rich 文本导致 agent 难解析 | 默认 stdout 只输出 v1 result JSON |
| active smoke 污染生产 skills | 要求临时或隔离 skills root，并把污染检查作为 smoke 失败条件 |
| schema 过早绑定复杂 product 行为 | v1 只覆盖 skill 创建所需结构、校验、文件布局和 warnings/next_actions |
| PR 合并后 active 环境更新方式不确定 | delivery 阶段根据本机实际安装路径确认，并记录 blocker 或 evidence |

---

## Documentation / Operational Notes

- 文档必须把 prompt 层限制为“意图和来源上下文”，明确不可把私密运行时材料写入生成技能。
- Handoff 给 `gh:work` 时应指定在真实 `wangrenzhu-ola/hermes-agent` worktree 中执行，避免只在 GCW phase scratch clone 中开发。
- runtime acceptance 需要真实 active Hermes 环境，不属于 plan phase 可完成范围。

---

## Sources & References

- Origin issue: https://github.com/wangrenzhu-ola/hermes-agent/issues/13
- Related code: `tools/skill_manager_tool.py`
- Related code: `tools/skills_tool.py`
- Related code: `agent/skill_utils.py`
- Related code: `hermes_cli/main.py`
- Related tests: `tests/tools/test_skill_manager_tool.py`
- Related tests: `tests/tools/test_skills_hub.py`
