---
date: 2026-05-20
topic: galebrain-meeting-business-sense
focus: GaleBrain 直接发起会议、参与会议，并逐步形成业务感、业务能力与业务决策辅助能力
status: draft-for-review
---

# Ideation: GaleBrain 会议参与与业务决策能力可行性方案

## Executive Summary

**结论：可行，但必须分阶段、带授权边界推进。** 当前 Hermes/GaleBrain 底座已经具备“会议旁听/转录/摘要/行动项/定时跟进/多平台投递/长期记忆”的关键零件；短板不是模型是否能总结，而是会议发起与参会的权限边界、跨平台统一会议对象、业务事实源治理、以及决策前的证据 readback。

建议把老板需求拆成四层：

1. **P0：会议观察员** — 明确授权的会议链接或日历事件，GaleBrain 默认只听、抓 transcript、会后输出摘要/行动项/风险。
2. **P1：会议运营助理** — 会前准备议程与历史上下文，会后将行动项转成可追踪 follow-up，并回写 PMO/需求/知识事实源。
3. **P2：业务感知系统** — 从多场会议沉淀业务证据账本、组织决策地图、风险趋势和重复 blocker。
4. **P3：决策影子与受控行动** — 先做 shadow decision / recommendation，不直接替老板拍板；会议发起、邀请、发言、外部发送均走人工批准。

**不建议直接做：** “自动扫描所有日历并自动入会”“默认代表老板发言”“无审批发起会议/邀请人”“把 LLM memory 当业务事实源”。这些会快速制造信任与责任风险。

## Codebase Context

本次 grounding 基于 `/Users/wangrenzhu/work/hermes-agent` 当前代码库、近 30 天 ideation 文档、HKTMemory 检索和相关本地知识库。

### 已有能力

- `plugins/google_meet/*`：已有 Google Meet bot，支持 `meet_join/status/transcript/leave/say`；v1 可加入 Meet、开启字幕、抓取 transcript；v2 可选 realtime 发言。
- `skills/productivity/google-workspace/SKILL.md`：已有 Google Calendar list/create 等入口，可做日程读取、会议草稿、日历事件创建，但创建/删除需确认。
- `plugins/teams_pipeline/*`：已有 Microsoft Graph/Teams 会议后处理流水线，能拉 transcript/recording，产出 summary、key decisions、action items、risks。
- `gateway/platforms/feishu.py`：Feishu 入口较强，支持群聊、@、文件/媒体、交互卡片，可作为老板/团队操作面与审批面。
- `cron/` 与 `tools/cronjob_tools.py`：已有定时任务和多平台投递能力，适合会前提醒、会后 follow-up、周报聚合。
- `agent/memory_provider.py`、`plugins/memory/*`、HKTMemory：已有长期记忆与知识召回底座，可承载业务原则、历史决策、证据摘要。
- `/goal` / Goal Supervisor 相关 ideation：已有 evidence-aware supervisor 思路；主动推进不能把 `needs_user/blocked/approval_required` 误报为完成。

### 明显缺口

- **Feishu Calendar / VC meeting 工具缺失**：当前 Feishu 能力主要是消息、文档和交互，不应假设已经能直接创建飞书会议。
- **跨平台会议对象缺失**：Google Meet、Teams pipeline、手工 transcript、日历事件目前是分散产物，需要统一 schema。
- **主动参会编排缺失**：Google Meet plugin 明确不做 calendar scanning/no auto-dial；需要“日历读取 → 授权 → join”的安全层。
- **业务事实源治理缺失**：会议摘要不能直接成为业务真相；需求状态、项目状态、决策状态必须回写 canonical fact source（GitHub Issues / demand-pool / PMO ledger / 企业 KB 等）。
- **评测闭环缺失**：业务感和决策能力必须用历史/脱敏会议评测集验证，不能靠 demo 观感判断。

## Feasibility Assessment

| 能力 | 当前可行性 | 推荐阶段 | 主要依据 | 风险边界 |
|---|---:|---|---|---|
| 给定链接加入 Google Meet 并记录 | 高 | P0 | `plugins/google_meet` 已支持 join/transcript | 默认只听；无 transcript 不声称理解 |
| 会后 Teams transcript 摘要 | 高 | P0 | `plugins/teams_pipeline` 已支持 Graph transcript/recording | Graph subscription 需续期与运维监控 |
| 读取日历并提议入会 | 中 | P0/P1 | Google Workspace skill 有 Calendar list/create | 必须先询问，不自动入会 |
| 发起会议草稿 | 中 | P1 | Calendar create 可复用 | 创建前必须人审；外部邀请更高审计 |
| 在会议中发言 | 中低 | P2/P3 | `meet_say` + realtime 基础存在 | 只在被点名/批准/证据缺口提问时发言 |
| Feishu 中直接创建飞书会议 | 低 | 暂不作为 P0 | 当前 repo 未见 Feishu calendar/VC 封装 | Feishu 先做控制面，不做执行面 |
| 业务感知/决策辅助 | 中 | P2/P3 | transcript + memory + fact source 可组合 | 必须 evidence-backed、shadow mode、可评测 |
| 代老板做业务决策 | 不建议 | 不进入近期目标 | 责任/权限/事实源不足 | 只做建议与决策请求，老板确认 |

## Ranked Ideas

### 1. 会议观察员：明确授权链接/日历事件后只听、转录、摘要

**Description:** GaleBrain 第一阶段不自动扫描所有会议，也不主动发言。用户给出 Meet URL、Teams meeting reference，或从日历中批准某个事件后，GaleBrain 加入会议，抓取 transcript，输出摘要、决策、行动项、风险和证据缺口。

**Warrant:** `direct:` `plugins/google_meet/*` 已支持 `meet_join/status/transcript/leave`；`plugins/teams_pipeline/*` 已支持 Teams transcript/recording ingestion；Google Meet plugin 明确 “no calendar scanning, no auto-dial”，适合加授权层而非静默自动化。

**Rationale:** 这是最短可落地路径，也最符合“逐步对业务有感受”：先稳定观察业务会议，形成 transcript-backed 证据，再谈业务判断。

**Downsides:** 对无字幕/权限受限/多人说话重叠的会议质量依赖较高；需要处理 lobby、caption 为空、会议提前结束等状态。

**Confidence:** 90%

**Complexity:** Medium

**Status:** Unexplored

### 2. Feishu 会议控制面：审批卡 + 状态回报 + 会后交付

**Description:** 短期把 Feishu 作为老板和团队的操作面：发起会议草稿、批准 GaleBrain 入会、查看入会状态、会中批准发言、会后接收摘要和行动项确认。底层会议执行先复用 Google Meet/Teams，不急于补齐 Feishu VC。

**Warrant:** `direct:` `gateway/platforms/feishu.py` 已支持 Feishu 消息、群聊、媒体和交互卡片；本次扫描未发现 Feishu calendar/VC 专用工具，因此 Feishu 更适合先做控制面和交付面。

**Rationale:** 老板和团队主要在 Feishu 协作。把会议智能体入口放在 Feishu，可以降低使用摩擦，同时保留审批与审计。

**Downsides:** 底层实际会议平台仍可能是 Google/Teams；如果业务最终强依赖飞书会议，需要另行做 Lark Calendar/VC connector。

**Confidence:** 85%

**Complexity:** Medium

**Status:** Unexplored

### 3. 会议发起草稿流：先拟议程/参会人/时间，确认后创建

**Description:** GaleBrain 可以根据 blocker、需求或老板指令生成会议草稿：主题、目的、参会人、建议时间、议程、预期产出和邀请文案。只有王韧竹/老板确认后，才创建 Calendar event 或发送邀请。

**Warrant:** `direct:` Google Workspace skill 已支持 Calendar create/list；同时技能与安全边界要求创建/删除日历事件前必须用户确认。

**Rationale:** “发起会议”是对多人时间和组织节奏的影响，不能静默自动化。草稿流能减少组织会议的人工成本，同时保留授权链。

**Downsides:** 需要联系人/组织角色/日历空闲时间能力；外部参会人、跨时区、保密会议需要更严格规则。

**Confidence:** 78%

**Complexity:** Medium-High

**Status:** Unexplored

### 4. 会议证据账本：把 transcript 转成可追溯业务事实

**Description:** 每场会议后生成结构化 evidence ledger：业务主题、关键结论、证据句、责任人、ETA、风险、假设、置信度、来源会议、是否已回写事实源。后续所有业务判断必须引用这些证据。

**Warrant:** `direct:` Hermes memory provider 和 HKTMemory 可做长期召回；Goal Supervisor 相关 ideation 强调 evidence-aware readback；Teams pipeline 已有 Summary/Key Decisions/Action Items/Risks 输出形态。

**Rationale:** “业务感”不是一次性摘要，而是跨会议的证据复利。证据账本能让 GaleBrain 逐步理解业务模式，同时防止 hallucination。

**Downsides:** 需要 schema 设计、去重、实体对齐、权限隔离；会议原文可能含敏感信息，不能无边界进长期记忆。

**Confidence:** 82%

**Complexity:** High

**Status:** Unexplored

### 5. 会前准备 + 会后 follow-up：把会议变成持续运营闭环

**Description:** 会前 30 分钟读取上次会议行动项、相关需求/PR/项目状态，生成议程建议和必问问题；会后将 action items 转成 owner/ETA/依赖/检查时间，并通过 cron/Feishu 做跟进提醒。

**Warrant:** `direct:` `cron/` 已支持定时任务；Teams pipeline 已能抽取 action items；Google Workspace/Calendar 可提供会议时间；PMO/GaleProject cadence 要求读回/写回事实源。

**Rationale:** 会议价值不在“开了”，而在会前对齐和会后推进。这个闭环比会中自由发言更快体现业务价值。

**Downsides:** 需要连接 GitHub Issues、demand-pool、PMO ledger、文档等事实源；提醒频率和升级规则需要调优，避免噪音。

**Confidence:** 84%

**Complexity:** Medium-High

**Status:** Unexplored

### 6. 决策影子模式：先建议、预测和复盘，不代替老板拍板

**Description:** 每场会议后 GaleBrain 生成 shadow decision log：它认为发生了什么决策、依据是什么、哪些风险升级、下一步建议、需要老板拍板的问题。后续用真实业务结果和老板反馈校准，而不是直接执行决策。

**Warrant:** `reasoned:` 业务决策能力需要可验证反馈循环。现有 transcript、memory、cron、fact-source readback 足以支撑“建议/预测/复盘”，但不足以让 agent 直接承担业务责任。

**Rationale:** 这能把“业务感”变成可训练、可评测的能力：GaleBrain 先学习老板和团队如何判断，再逐步提高建议质量。

**Downsides:** 需要人为标注/反馈，否则 shadow log 会变成自嗨文档；短期不应对外宣称“自动决策”。

**Confidence:** 76%

**Complexity:** Medium

**Status:** Unexplored

### 7. 会议业务能力 benchmark：用历史/脱敏会议验证是否真的省老板时间

**Description:** 建立 20-50 个历史/脱敏会议样本，人工标注关键决策、风险、行动项、遗漏点、后续结果。GaleBrain 每次升级会议能力前必须通过评测：摘要准确度、风险预测、owner/ETA 抽取、是否减少老板追问。

**Warrant:** `reasoned:` 老板要的是业务能力，不是 demo 感。没有评测集，系统可能很会总结但不能判断优先级和风险；Goal Supervisor 的 evidence-aware 原则也要求完成与质量由证据验证。

**Rationale:** 评测集是放权前的闸门：没达标只允许旁听/总结，达标后再开放发言、会议发起、决策建议等更高权限。

**Downsides:** 需要收集和脱敏会议材料，人工标注成本不低；但这是避免错误放权的必要成本。

**Confidence:** 80%

**Complexity:** Medium

**Status:** Unexplored

## Rejection Summary

| # | Idea | Reason Rejected |
|---|---|---|
| 1 | 自动扫描所有日历并自动入会 | 风险过高；当前 Google Meet plugin 明确不做 calendar scanning/no auto-dial；缺少授权边界。 |
| 2 | 默认代表老板在会议中自由发言 | 会议发言是高社会成本动作；应先受控发言或证据缺口提问。 |
| 3 | Feishu 直接创建飞书会议作为 P0 | 当前 repo 未发现 Feishu Calendar/VC 工具，不应把不存在能力作为近期方案前提。 |
| 4 | 把会议摘要直接写进长期 memory 当业务真相 | unsupported；业务状态必须在 canonical fact source，memory 只能做召回/证据摘要。 |
| 5 | 只做漂亮会议纪要 | below ambition floor；无法满足“业务感/业务能力/决策能力”，必须加入证据账本和 follow-up。 |
| 6 | 一次性打通所有会议平台 | too expensive；平台不对称，先 Google Meet 主动参会、Teams 被动消化、Feishu 控制面。 |
| 7 | 先做复杂组织决策地图 | 价值高但应建立在多场会议证据账本之后，作为 P2/P3 衍生能力。 |
| 8 | 会中实时多轮辩论代理 | interesting but premature；技术与组织风险都高，先限制为批准后短发言/澄清问题。 |

## Proposed Roadmap

### Phase 0 — 安全边界与 schema 设计（1 周）

- 定义 `MeetingArtifact`：platform、meeting_id、title、time、attendees、transcript_uri、summary、decisions、action_items、risks、evidence_refs、confidence、permissions。
- 定义会议动作权限：read-only、draft、requires_approval、forbidden。
- 定义 terminal states：`pending_approval`、`joining`、`in_meeting`、`transcribing`、`no_transcript`、`summarized`、`needs_user`、`blocked`、`failed`。
- 明确敏感动作：创建会议、邀请外部人、主动发言、发送外部结论、修改 canonical fact source。

### Phase 1 — P0 会议观察员 MVP（2-3 周）

- 支持显式 Google Meet URL 入会、抓 transcript、会后摘要。
- 支持 Teams transcript pipeline 进入统一 `MeetingArtifact`。
- Feishu 中提供入会批准、状态查询、摘要回传。
- 会后输出固定结构：结论、决策、行动项、风险、未决问题、证据片段。
- 验收：至少 5 场测试会议，入会状态准确、transcript 有效、摘要引用证据、不误报成功。

### Phase 2 — 会前/会后运营闭环（3-4 周）

- 日历读取：会议前自动生成准备 brief，但入会仍需授权。
- 会前 brief：上次行动项、相关需求/PR/PMO 状态、建议议程、必问问题。
- 会后 follow-up：owner、ETA、依赖、检查时间；到点提醒是否催办/升级。
- 写回事实源：需求/项目状态走 canonical repo/issue/PMO ledger；HKTMemory 只存证据摘要和经验。

### Phase 3 — 业务感知与决策影子（4-6 周）

- 建立会议业务证据账本，跨会议抽取重复 blocker、风险趋势、组织决策模式。
- 每场会议产出 shadow decision log：建议、反对理由、缺证据、需要老板拍板。
- 建立 benchmark：20-50 个历史/脱敏会议样本，人工评分。
- 达标后再讨论受控发言与更高权限动作。

### Phase 4 — 受控发言与会议发起自动化（后续）

- 受控发言：只在被点名/批准/证据缺口时发言；先文本审批，再 `meet_say`。
- 会议发起：GaleBrain 生成草稿和候选时间，确认后创建日历事件。
- 逐步放权：只对低风险内部会议、固定 owner、固定议程开放半自动。

## Guardrails

- **默认只听**：没有明确授权，不入会；没有批准，不发言。
- **身份透明**：GaleBrain 入会应声明身份/用途，避免暗中记录。
- **证据优先**：任何判断必须有 transcript、issue、doc、ledger 或明确来源。
- **事实源分层**：业务状态在 canonical fact source；HKTMemory/vector 只做召回层，不存秘密与快速变化真相。
- **人审动作队列**：发起会议、邀请人、外部发送、会中发言、修改需求主数据必须人审。
- **红灯停下**：登录/验证码/MFA/安全提示/权限不明/敏感会议/外部人歧义时停止并请求确认。
- **不假成功**：入会失败、无 transcript、摘要 sink 失败、事实源写回失败都必须显式报告。

## Review Questions for 王韧竹

1. P0 是否先限定为 **Google Meet 显式链接 + Teams 会后 transcript + Feishu 控制面**？
2. 哪些会议类型允许 GaleBrain 默认旁听？哪些必须逐次批准？
3. 会议 transcript 与业务证据账本应写入哪个 canonical repo / KB / Issue 体系？
4. 决策影子模式的评分人是谁：王韧竹、PMO、业务 owner，还是三者分层？
5. 老板希望看到的第一版效果，是“会后老板简报”还是“行动项追踪闭环”？

## Recommended Next Step

建议审核通过后，不直接进入实现，而是先用 `gh:brainstorm` 深挖 **Idea 1 + Idea 2 + Idea 4 的组合**：

> “Feishu 控制面驱动的 GaleBrain 会议观察员：显式授权入会、统一 MeetingArtifact、会后证据账本与行动项 follow-up。”

这条路线最稳：既能回应老板“发起/参与会议”的方向，又不会一开始越权；同时为后续业务感和决策能力打证据底座。
