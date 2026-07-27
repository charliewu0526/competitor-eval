# PRD 0003 — 多人竞品评测工场(Multi-Runner Eval Platform)

> 承接 grill(ADR 0012–0019)与 CONTEXT.md 词汇表。把单机评测引擎升级为多人协作的产品判断工场。
> 唯一新核心接缝:**Submission → RunRecord** 翻译层;评分核心(RunRecord 进→分数/发现/排行榜出)一字不改复用。
> 第一版 = 最薄闭环(ADR-0019),脱敏 / 方法闸 / 自动 stale 先人工代替。

## Problem Statement

现在这套竞品评测引擎只有 charlie 一个人能用:跑在本机、SQLite 本地文件、靠 computer-use 手动操作。charlie 想搞清 Violoop 与热门竞品(Manus / Codex / Kimi / WorkBuddy 等)在各能力域上的真实差距,但一个人跑不过来 —— 题量、竞品数、重复执行都受限于单人产能。他需要把「执行」这件体力活分给一批实习生去做,自己退到路径外做抽查与判断,同时绝不能牺牲这套系统辛苦建立的可信度内核(只看末态、盲评、黄金集校准、防漂移)。

## Solution

把单机引擎搬成一个部署在服务器上的多人 Web 服务(ADR-0018)。实习生自注册(链接私发内部)、从任务清单领取「一道对比任务的全部」(Assignment)、用中立标准 Prompt 分别在 Violoop 与同域竞品上各跑一次、提交交付物(原始产物 + 强制执行日志包 + 客观断言人工勾选)。提交后:机器可验的断言自动判、日志包脱敏后喂盲评面板、各产品独立打分、分数作差 + 自动生成 Finding + 开源竞品源码机理分析 = 差距报告。大差距 / 评委分歧 / 疑似谎报强制人工复核,其余分层抽查。差距大的沉淀为「方法」初稿,经审核员/PM 把关后导出给研发学习。榜单按能力域分维度,每条分数绑竞品版本 + 测试日期,超期标陈旧。

评分逻辑全部复用现有引擎;新增的只是它外围的**多人前台 + 存储 + 一个 Submission→RunRecord 翻译接缝**。

## User Stories

### 账号与角色(RBAC，ADR-0014）
1. As 内部人员，I want 通过私发的注册链接自注册登录，so that 不用 PM 手动开户就能开始领任务。
2. As PM，I want 注册仅限持链接者、不对公网开放，so that 数据源可控、不被外部污染。
3. As 新注册用户，I want 默认拿到 intern（实习生）角色，so that 权限从最小开始。
4. As PM，I want 手动把某个 intern 提升为 reviewer（审核员），so that 我信任的资深执行者能分担复核。
5. As PM，I want 独占黄金集校准、评委授权/降权、任务清单、脱敏规则等权限，so that 校准这个危险开关不落到新人手里。
6. As reviewer，I want 能复核分派给我的报告但碰不到校准开关，so that 我的职责边界清晰、不会误触发重校准。

### 任务清单与领取(Assignment，ADR-0015）
7. As PM，I want 预置一个按能力域分组的任务清单，so that 实习生看到的是同域可比的题、不会拿桌面题考代码 agent。
8. As intern，I want 浏览未被领取的任务并领一道，so that 我有明确的活干、且不和别人撞题。
9. As intern，I want 领取的最小单元是「一道对比任务的全部」（Violoop + 该域全部参赛竞品），so that 同一道题的整组对打由我一人一次性完成。
10. As 系统，I want 一道 Assignment 被领后对其他人锁定，so that 不会两个实习生同时跑同一道题（并发领取控制）。
11. As intern，I want 看到每道题的详细说明 + 中立标准 Prompt，so that 我知道具体怎么做、该丢给 AI 什么指令。
12. As intern，I want 中途放弃或超时未交的任务能回到清单，so that 领了没做的题不会永久卡死。

### 执行与提交(Submission + 日志包，ADR-0013/0016）
13. As intern，I want 对每个产品用同一条标准 Prompt（禁用产品专属语法）执行，so that 谁都不靠「母语优势」得分、榜单不被质疑偏向自家。
14. As intern，I want 为一道 Assignment 里的每个产品各提交一份 Submission，so that Violoop 和每个竞品的交付物分开记录。
15. As intern，I want 提交时上传原始产物（截图/导出文件/AI 对话记录），so that 交付物有可核查的实体。
16. As intern，I want 提交时强制上传执行日志包（执行时间线 + token 花销 + 调用次数），so that 成本与过程有真实来源、不靠事后自报。
17. As 系统，I want 缺证据（无原始产物或无日志包）时拒绝提交，so that 落实「无证据不入池」。
18. As intern，I want 勾选只能人看的客观断言（如「微信消息真发出了」），so that 机器判不了的末态由受训过的我来认定。
19. As intern，I want 声明该产品这次是否自称完成（claimed_success），so that H1 诚实度轴有输入、谎报能被抓。

### Submission→RunRecord 翻译(唯一新核心接缝）
20. As 系统，I want 把一份 Submission 翻译成引擎认识的 RunRecord，so that 现有评分核心（GATE→客观断言→盲评→H1）一字不改就能消费实习生数据。
21. As 系统，I want 机器可验的断言（文件是否存在、Excel 某格值、日志有无某事件）自动判定，so that 客观层不落人手、立身之本不被稀释。
22. As 系统，I want 从日志包解析 token/调用/时间线填入 cost_source，so that 资源效率维度有真实来源、不标 0 伪装。
23. As 系统，I want 依据竞品可达性 × 任务要求推导 GATE，so that 够不到的产品判 cannot-reach（没参赛，非差）而不是硬给 0 分。
24. As 系统，I want 一份日志包派生脱敏版与原始版，so that 面板看脱敏版（盲评不被日志泄底）、成本与抽查看原始版。

### 盲评与差距报告(ADR-0012）
25. As PM，I want 交付物送评审面板前打乱产品标签（Product A/B/C），so that 面板不知道哪个是自家、不会手软。
26. As 系统，I want 每份交付物各自独立跑评分（非成对对比），so that 差距 = 独立分数差，可被黄金集校准锚定。
27. As PM，I want 一道对比任务产出差距报告（分数差 + Finding + 开源竞品源码机理分析），so that 我看到的是「谁强多少、强在哪」而非一句空泛结论。
28. As PM，I want 榜单按能力域分维度展示，so that Codex 在代码榜、Operator 在网页榜，各归其位、同域才同台。
29. As PM，I want 每条分数显示竞品版本 + 测试日期、超期标陈旧（ADR-0017），so that 榜单不用三个月前的分数冒充现状误导决策。

### 人工复核与抽查(ADR-0014）
30. As 系统，I want 只对大差距 / 评委分歧 / 疑似谎报强制人工复核，其余分层抽查，so that PM 从每环节签字挪到路径外、不成瓶颈。
31. As reviewer/PM，I want 对一条复核项下「有道理 / 有问题」结论，so that AI 报告的靠谱程度有人把关。
32. As 系统，I want 执行某 Assignment 的实习生不被指派复核同一条，so that 职责分离、不自己批自己作业。
33. As PM，I want「有问题」的复核结论可触发黄金集重校准（仅 PM），so that 评委漂移能被纠正、但这个开关不外放。

### 沉淀方法给研发(方法复核闸）
34. As intern，I want 在差距证据包（分数差 + Finding + 机理）上提炼「方法」初稿，so that 竞品的强项能被抽象成可迁移做法。
35. As reviewer/PM，I want 方法初稿必须经我把关才能导出给研发，so that 新人没看懂机理的瞎提炼不会污染系统可信度。
36. As 研发，I want 拿到经把关的方法（竞品为何强 + Violoop 如何落地建议），so that 我能照着改进产品而不是读一堆原始截图。

### 部署与运维(ADR-0018/0019）
37. As PM，I want 系统部署为在线 Web 服务、数据库支持多人并发，so that 实习生能各自远程访问、领取不冲突。
38. As PM，I want 第一版是最薄闭环（注册→领→交→进引擎→出榜），脱敏/方法闸/自动 stale 先人工代替，so that 两三周内能让实习生真跑一道题、验证模式成立。
39. As PM，I want 所有「人工代替」项显式登记为技术债，so that 先跑起来后不会忘记补齐自动化。

## Implementation Decisions

### 唯一新核心接缝：Submission → RunRecord
- 新增一个翻译模块（概念名 `intake`），签名思路：`translate(submission, task_meta, registry) -> RunRecord`。它是多人系统与评分核心之间**唯一**的耦合点。上游（Web/上传/权限）只负责把 Submission 喂给它，下游（orchestrate/board/findings）完全复用、不改。
- 与现有 5 个适配器同构：真实现 + 内存假实现，各自可独立测（沿用 A1–A4/F2 的 prior art）。
- 断言翻译分工在此落地：机器可验断言走脚本/规则判定，人工勾选断言从 Submission 读取；GATE 用现有 `gate_for(competitor, task)` 推导，不信自报。
- 日志包解析产出 cost 字段（复用 A3 成本适配器契约）+ 脱敏版/原始版两视图。

### 数据模型变更（F1 schema 扩展）
- RunRecord / score 增字段：`competitor_version`、`tested_at`、`stale`（ADR-0017 数据新鲜度）。
- 新增实体：`User`（id/角色 intern|reviewer|owner）、`Assignment`（task_id + 参赛产品集合 + 领取人 + 状态 open|claimed|submitted|abandoned）、`Submission`（assignment_id + product + 原始产物引用 + 日志包引用 + 人工勾选断言 + claimed_success）。
- `Method`（差距证据包上的提炼初稿 + 把关状态 draft|approved|exported）。

### 存储与部署（ADR-0018）
- **数据库拍板:自托管 Postgres**(PM 已定 2026-07-27)。理由:①并发领取是刚需,`SELECT FOR UPDATE` / `UNIQUE(assignment_id,status)` 是教科书解法;②要部署成多进程 Web 服务,SQLite 的单写锁在此架构下是隐患,它定位是嵌入式单机库,与多人服务不搭;③**数据必须留在本地**(守住内部可控的立身之本),故不选托管云库(Supabase/Neon)——评测数据不出本地;④评分核心对存储的依赖已隔离在 store 层,迁移主要改 store + SQL 方言,评分核心不动,「现有 20 测试保绿」即迁移护栏;⑤趁现在数据少、地基未浇筑,早迁比晚迁省事。
- **文件(原始产物 + 日志包)不进库**,走服务端文件目录(MVP 阶段,ADR-0019);数据库只存路径引用,不塞二进制。对象存储留作后续升级。
- Web 服务层新建（现有 `server/app.py` 是只读看板 API，需扩展为带鉴权 + 写入的多人服务）；前端从只读看板扩为带登录 + 领取 + 上传的多角色前台。

### 盲评与报告（复用 + 编排）
- 盲标签复用现有 registry `blind_label`；打乱在「送面板前」这一步做。
- 差距报告是**派生视图**（分数差 + Finding + 机理），不是新审核逻辑：新增一个报告组装层从现有 scores/findings 读数拼装。
- 分层抽查复用现有 sampling.build_queue；「大差距」作为新入队理由并入现有分层规则。

### 交付物打包 skill（客户端前置，MR-15）
- 实习生不懂怎么打包交付物+日志,故提供一个客户端打包 skill,把「原始产物 + 执行日志包」在实习生机器上收齐成标准压缩包,上传后服务端 intake 解包翻译成 Submission→RunRecord。它是提交链（#43/#44/#45）的客户端前置,不是独立功能。
- **定位:一键自动导出为目标,优雅降级为底线。** 每家竞品导出机制不同（有的有导出按钮、有的日志只在云端、有的 token 拿不到）,不存在万能导出器。形态 = 通用打包器 + 每竞品导出配方(recipe) + 校验器。能自动的自动到底,自动不了退半自动/手动+配方指引。
- **缺数据如实标 unavailable**（PM 定 2026-07-27,呼应 cost_source 诚实原则）:闭源竞品拿不到的 token/日志,标 unavailable,校验器**允许通过**——缺失本身是信息,绝不伪装成 0。
- **校验器是核心价值**（真正降低出错率的地方）:打包时检查证据齐全（有日志/有原始产物/字段全/拿不到的如实标 unavailable）,不合格当场拒绝出包,而非传到服务端才发现。
- **边界:skill 只收证据,不下判定。** 末态是否达成仍由实习生人工勾选（#44）,绝不从竞品自述日志「读出成功」——那等于让 AI 自述当证据,破立身之本。
- **压缩包 manifest 明确标产品身份**,好让服务端 intake 知道该怎么脱敏（ADR-0013,skill 只收原始+如实标,脱敏在服务端做）。

### MVP 人工代替项（ADR-0019，登记为技术债）
- 脱敏：先人工洗日志再送审（不做自动脱敏流水线）。
- 方法复核闸：先线下/口头把关（不做系统门禁）。
- 自动 stale：先人看测试日期（不做后台自动标灰）。

## Testing Decisions

- **好测试只验外部行为，不验实现细节。** 主战场是唯一新接缝：给一个假 Submission（含日志包 fixture + 勾选断言），断言 `translate` 产出正确的 RunRecord（objective flags / gate / cost 字段 / claimed_success / 脱敏版内容不含品牌词）。这是本 PRD 最该密集覆盖的地方，prior art = 现有 5 个适配器测试（`test_*_adapter_*.py`）的「真实现 vs 内存假实现契约」范式。
- **脱敏正确性**单独测：喂入含品牌/模型指纹的日志，断言脱敏版洗净（洗漏 = 破盲，属高风险回归）。
- **RBAC 边界**测：intern 不能复核、reviewer 不能触发校准、执行者不被指派复核自己的 Assignment（职责分离）。
- **并发领取**测：两个请求同抢一道 Assignment，只有一个成功、另一个看到已锁定。
- **端到端集成测**（沿用 `test_suite_x6` / `test_drivers_x3` 范式）：假 Submission → 翻译 → 评分 → 榜单出现带版本/日期的分数。
- 评分核心本身**不新增测试**——它没改，复用现有 20 个测试作为回归护栏。
- 外围（注册/上传/Web 路由）走轻量集成测，不为它们各立核心接缝。

## Out of Scope

- **完整自动化的脱敏 / 方法闸 / stale 判定**——MVP 先人工，后续迭代补（已登记技术债）。
- **同题多人重复执行**去除执行偏差——ADR-0015 明确不做，残余风险靠标准 Prompt + 日志包 + 盲评兜底；若日后榜单被偏差污染再引入「双人跑」升级路径。
- **capability-probe 卖点专项路径的多人化**——第一版聚焦 task-exam 主干；probe 仍由 PM 手动触发。
- **三条 Pipeline 中的「竞品情报」条**（v2 再做，见 CONTEXT）。
- **tier 的其余三层**（vio-key / rival-signature / stress）——先只填 core-common。
- **竞品自动版本探测**——闭源竞品版本不透明，MVP 记测试日期 + 人工填 build 标识即可。

## Further Notes

- 竞品归域（PM 已确认 2026-07-27）：**桌面操作域**(Manus·Codex·Claude Computer Use·**CodeBuddy**)/ **通用任务域**(Manus·Kimi·Claude·**CodeBuddy**)/ **网页任务域**(OpenAI Operator·Manus·Mariner)/ **写代码域**(Codex·Claude·**CodeBuddy**)。WorkBuddy 已确认即 **CodeBuddy(腾讯云代码助手,codebuddy.cn)——是全能工作助手,不止写代码**,故跨桌面/通用/写代码多域参赛(具体每域是否参赛以该域任务它能否 reach 为准,GATE 推导决定,不预先排除)。Claude Computer Use 与 OpenAI Operator 已纳入(各自域标杆对手)。Violoop 全域参赛。一个产品可同时出现在多个能力域榜单——这正是「多维度榜单」的应有之义。
- 立身之本贯穿全程：只看末态事实、AI 自述不算证据、机器只标现象人下判断。多人化引入的新噪声源（实习生）通过职责分离 + 强制证据 + 盲评 + 抽查被约束，而非信任。
- 关联 ADR：0012（独立打分）、0013（日志脱敏）、0014（三级角色）、0015（领取粒度）、0016（中立 Prompt）、0017（数据新鲜度）、0018（Web 服务）、0019（MVP 最薄闭环）。词汇一律用 CONTEXT.md。
