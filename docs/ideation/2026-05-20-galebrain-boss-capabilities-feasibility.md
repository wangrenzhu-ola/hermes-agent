---
date: 2026-05-20
topic: galebrain-boss-capabilities-feasibility
focus: 老板要 GaleBrain/王伟锋承担老板专用决策、飞书、Metabase、报销/行政与安全边界任务的可行性评估
source_issue: none
codebase_repo: wangrenzhu-ola/hermes-agent
core_skill_pr: https://github.com/wangrenzhu-ola/infra-hermes-core-skills/pull/549
status: draft-for-review
---

# Ideation: GaleBrain 老板专用能力可行性与方案候选

## Executive Verdict

可行，但不能把它当成“多写一点长期记忆”来做。正确路线是：老板专用偏好沉淀为 `boss-user-preferences` 技能，GaleBrain 运行时用受控路由加载；涉及 Feishu/Metabase/报销/审批/外发/凭证的能力按“读写分级 + 确认门 + 审计证据”逐步放开。

当前状态已经具备 MVP 基础：ECS GaleBrain profile 存在，`boss-user-preferences` 已安装到活跃 profile，core skills PR #549 已进入核心技能库，Feishu gateway 和 Boss profile 可运行。主要风险不是“能不能做”，而是“谁能触发、何时加载、哪些动作必须停在人审”。

建议审核口径：先批准 P0/P1 的“偏好加载 + 只读分析 + 草稿输出 + 确认门”，暂不批准自动提交审批、付款、下单、跨群主动外发、明文凭证处理。

## Codebase Context

- Hermes Agent 已支持 profile-scoped memory、skills 索引、gateway session context、Feishu WebSocket/Webhook、附件、reaction、approval card、home channel 和 cron delivery。
- `gateway/session.py` 会为每个消息源创建/复用 `AIAgent`，session context 注入平台、用户、chat/thread、home channel 等信息；适合做 Boss/群聊上下文判断。
- `agent/prompt_builder.py` 目前默认只把技能索引压入系统提示，完整技能需要 agent 主动 `skill_view` 加载；因此仅有技能文件还不等于稳定执行，需要 runtime 指针或 router 机制。
- ECS 现场：活跃 profile 为 `/data/galebrain-gjarvis-podman/hermes`，容器 `galebrain-gjarvis-boss` running；`boss-user-preferences`、`owner-only-secret-broker`、`boss-todo-ledger` 等技能可见；Feishu gateway 正在接收事件。
- 内存压力很低：GaleBrain 容器约 177MB / 16GB；长期记忆已压缩到 `MEMORY.md 33.4%`、`USER.md 24.6%`。
- Core skills：`boss-user-preferences` 已作为老板专用 skill 进入 `infra-hermes-core-skills` PR #549；但它高度用户/老板语境绑定，不应默认进入所有 runtime。
- 风险点：`FEISHU_ALLOW_ALL_USERS=true` 与 `FEISHU_GROUP_POLICY=open` 对老板能力扩展有触发面风险；日志有未处理 Lark 事件噪音；外部系统能力需要 secret broker、确认门和审计。

## Ranked Ideas

### 1. Boss Preference Router：让 GaleBrain 稳定加载老板专用技能

**Description:** 为 GaleBrain 增加一个轻量路由规则：当消息来自王韧竹、老板相关群、王伟锋/Boss 语境，或请求涉及决策、Feishu、报销、Metabase、行政、私聊透明度、高风险动作时，必须加载 `boss-user-preferences`。这不是新增业务能力，而是保证已沉淀的偏好在正确场景稳定生效。

**Warrant:** `direct:` 代码扫描显示 Hermes 只把技能索引放入系统提示，完整技能需模型主动 `skill_view`；ECS profile 已安装 `boss-user-preferences`，gateway suffix 也已有指针，但仍依赖模型执行。

**Rationale:** 如果不做稳定路由，老板专用规则会“有时记得、有时忘记”。这项改动杠杆最高：先保证行为基线，再谈更复杂的外部系统动作。

**Downsides:** 需要定义触发边界，避免普通 Feishu/Metabase 任务被过度套用老板偏好；可能影响 prompt cache 或增加少量 token。

**Confidence:** 90%

**Complexity:** Low-Medium

**Status:** Unexplored

**Review Decision Needed:** 是否允许在 GaleBrain runtime 中对老板/王韧竹/王伟锋相关场景强制加载该技能。

### 2. Boss Action Safety Matrix：把“能做/只读/草稿/必须确认/禁止”产品化

**Description:** 建立 GaleBrain 老板动作矩阵，把任务分为五档：只读分析、草稿生成、需确认发送、需本人操作、禁止处理。覆盖 Feishu 文档/群聊、Metabase、报销、审批、付款、下单/退款、账号安全、验证码、外部发送、跨群升级等。

**Warrant:** `direct:` `boss-user-preferences` 和现有记忆均明确要求付款、审批提交、账号安全、凭证/验证码、外部发送必须先确认或转本人/Infra；Hermes gateway 已有 approval card 和高风险确认基础。

**Rationale:** 老板要 GaleBrain 做更多事，最大风险是边界含糊。矩阵能把 prompt 规则变成可测试、可审核、可扩展的产品契约。

**Downsides:** 初版需要人工定义动作分类；过严会降低自动化价值，过松会带来事故风险。

**Confidence:** 88%

**Complexity:** Medium

**Status:** Unexplored

**Review Decision Needed:** 是否以“草稿/确认门”为默认，而不是直接自动提交/发送。

### 3. Boss Data Analyst MVP：先做只读 Metabase/业务数据分析，不做写操作

**Description:** 让 GaleBrain 优先胜任老板最关心的视频/语音业务数据分析：动态取昨日数据，按财务、投放团队/优化师、产品、ROI、首日收入、DAU、金币库存等维度输出老板视角结论。初期只读 Metabase，不写入业务系统，不发送到非授权群。

**Warrant:** `direct:` ECS 已有 Metabase URL 指针、`metabase-login` 技能/secret-store 边界；长期记忆保留了视频业务 question 4201/5805/4319 和语音日报指标口径。

**Rationale:** 这是老板场景价值最高、风险相对可控的能力：只读、可验证、有明确业务收益。做好它能证明 GaleBrain 从“聊天助手”变成“老板数据助理”。

**Downsides:** 凭证有效性、卡片参数、数据口径会漂移；需要定期 smoke 和异常回退。若 secret 注入不稳定，会出现“技能会说但取不到数”。

**Confidence:** 82%

**Complexity:** Medium

**Status:** Unexplored

**Review Decision Needed:** 是否把只读数据分析列为第一批业务 MVP。

### 4. Feishu Draft Workspace：先帮老板准备字段/消息/审批草稿，不直接提交

**Description:** 对报销、审批、群消息、文档输出等 Feishu 场景，GaleBrain 默认生成“字段草稿/消息草稿/证据清单”，并明确标注未提交。只有用户明确确认后，才调用实际 Feishu 操作工具；高风险动作仍转本人。

**Warrant:** `direct:` 现有 `boss-core-config` 已写明 Payment / Approval Draft Boundary；Feishu skills 包含 document reader/authoring/revoke/calendar 等，但高风险动作需要明确授权。

**Rationale:** 老板要的是节省时间，不是让机器人越权。草稿 workspace 能先释放 70% 的整理/填写价值，同时规避误提交、误发群、审批事故。

**Downsides:** 用户可能期待“直接完成”，需要 UI/文案清晰区分“字段草稿”和“流程内草稿”。

**Confidence:** 84%

**Complexity:** Medium

**Status:** Unexplored

**Review Decision Needed:** 是否接受“先草稿、再确认”的默认体验。

### 5. Boss Capability Ledger：把老板能力建设做成长期看板，而非散落聊天

**Description:** 建立老板能力建设 ledger，按 CEO/COO/CMO/CFO/个人认知恢复五层维护能力、缺口、进度、证据、下一步。GaleBrain 每次处理相关任务时更新或引用 ledger，避免跨天遗忘。

**Warrant:** `direct:` `boss-user-preferences` 明确要求 Boss Skills 底层能力看板；ECS 已有 `boss-todo-ledger`，并规定 cross-day todo 不能依赖 transient memory。

**Rationale:** 老板能力建设是长期主线，不能靠会话记忆。Ledger 能形成可审查、可迭代的“老板操作系统”。

**Downsides:** 需要防止 ledger 变成流水账；需要定期清理和 owner review。

**Confidence:** 78%

**Complexity:** Medium

**Status:** Unexplored

**Review Decision Needed:** 是否将 Boss 能力看板作为 GaleBrain 的长期状态源。

### 6. Private Message Transparency：私聊 GaleBrain 默认向王韧竹可见

**Description:** 当有人私聊 GaleBrain/GJarvis，系统向王韧竹做安全提示或在授权看板中记录摘要，确保老板代理没有“暗箱私聊”。根据隐私/合规需要，可区分敏感内容、业务内容和仅元数据提醒。

**Warrant:** `direct:` `boss-user-preferences` 明确“有人私聊 GaleBrain/GJarvis 时，需要提醒用户，并确保私聊内容对用户可见”；Feishu gateway 能识别 DM/群聊和 sender 身份。

**Rationale:** 这是老板代理的治理底线：别人绕过用户找代理，会影响授权、责任和信息透明。

**Downsides:** 需要小心处理隐私/合规；不应无差别转发所有私聊全文，建议先做元数据提醒 + 授权可读摘要。

**Confidence:** 75%

**Complexity:** Medium

**Status:** Unexplored

**Review Decision Needed:** 私聊透明度是“全文同步”还是“提醒 + 可审计摘要”。

### 7. Boss Runtime Eval & Watchdog：用自动验收防止“会说不会做”

**Description:** 建立一组老板专用 smoke/eval：是否加载 `boss-user-preferences`、是否拒绝明文密码、是否把报销图放到正确字段、是否不主动跨群升级、是否能输出昨日数据日报、是否区分字段草稿与真实提交。接入现有 GaleBrain watchdog。

**Warrant:** `direct:` 当前已有 GaleBrain availability watchdog；ECS 现场显示技能/内存已压缩但模型端到端 smoke 需要显式验证；历史问题集中在权限、凭证、文档读取、误发/噪音。

**Rationale:** 老板专用能力一旦上线，不能只靠 prompt 期待。Eval 能把规则变成持续验收，减少回归。

**Downsides:** 需要维护测试用例和模拟输入；涉及 Feishu/Metabase 的真实 smoke 要控制成本与权限。

**Confidence:** 80%

**Complexity:** Medium

**Status:** Unexplored

**Review Decision Needed:** 是否要求每次部署 Boss profile 后跑这组 smoke 才算完成。

## Recommended Phased Plan

### P0 — 已完成/可立即确认

1. 长期记忆压缩：`MEMORY.md 33.4%`、`USER.md 24.6%`。
2. 老板专用偏好沉淀为 `boss-user-preferences`。
3. ECS GaleBrain active profile 已能看到该 skill。
4. Core skill PR #549 已进入核心技能库。

### P1 — 建议立刻做，风险低、收益高

1. 做 Boss Preference Router：保证相关场景稳定加载 `boss-user-preferences`。
2. 写 Boss Action Safety Matrix：明确只读/草稿/确认/本人操作/禁止。
3. 加 5-8 个老板专用 eval smoke，防止回归。
4. 在 core skill manifest/README 中标注该 skill 为 Wang Renzhu/Boss/GaleBrain 专用，不默认泛化。

### P2 — 业务 MVP

1. Metabase 只读日报/临时分析。
2. Feishu 文档/群聊/报销字段草稿。
3. Boss capability ledger 看板。
4. 私聊 GaleBrain 透明提醒。

### P3 — 谨慎开放

1. Feishu workflow 内真实草稿创建。
2. 经确认后的定向发送/文档创建。
3. 更复杂的行政/生活任务搜索与候选整理。

### 暂不建议开放

1. 自动付款、自动下单、自动退款。
2. 自动提交审批。
3. 自动跨群升级、@all、向无关群转发。
4. 明文凭证/验证码处理。
5. 未经确认的外部发送。

## Rejection Summary

| # | Idea | Reason Rejected |
|---|------|-----------------|
| 1 | 把所有老板偏好继续塞回 USER.md | 已经容量满且容易指令污染；技能更适合流程规则。 |
| 2 | 让 GaleBrain 默认对所有用户开放老板能力 | 与 Boss-specific 隔离冲突，`ALLOW_ALL_USERS/open` 已是风险点。 |
| 3 | 直接开放自动提交审批/付款/下单 | 高风险动作，缺少确认门和审计，不符合用户安全边界。 |
| 4 | 把 `boss-user-preferences` 做成全局通用 core 默认技能 | 过度用户专属，会污染非老板 runtime。 |
| 5 | 只靠 prompt 文案约束，不做 eval/watchdog | 历史问题证明权限、凭证、误发、噪音需要可验证机制。 |
| 6 | 先做大型“全能 Boss Agent” | 范围过大，且外部系统权限/secret/审计未完全产品化。 |
| 7 | 私聊 GaleBrain 全文无差别转发给用户 | 可能有隐私/合规风险；更稳的是提醒 + 可审计摘要/授权读取。 |
| 8 | 把 Metabase 凭证放在 skill/memory/session 里 | 明确违反秘密治理；必须走 owner-only secret broker/root-only secret store。 |

## Feasibility Checklist for Review

- [ ] 是否同意 `boss-user-preferences` 只服务老板/GaleBrain runtime，不作为通用默认技能。
- [ ] 是否同意 P1 先做 router + safety matrix + eval，而不是直接开放写操作。
- [ ] 是否同意 Metabase 首批只做只读分析。
- [ ] 是否同意 Feishu/报销/审批首批只做字段草稿和消息草稿。
- [ ] 是否同意私聊 GaleBrain 采用“提醒 + 可审计摘要/授权读取”，而不是无差别全文转发。
- [ ] 是否要求 core skills 再补 manifest/README/governance 标注。

## Handoff Options

1. 选择 Idea 1：进入 `gh:brainstorm`，定义 Boss Preference Router 的准确触发规则。
2. 选择 Idea 2：进入 `gh:brainstorm`，产出 Boss Action Safety Matrix。
3. 选择 Idea 3/4：进入业务 MVP 方案细化。
4. 先审核本文，确认 P1/P2/P3 边界后再规划实施。
