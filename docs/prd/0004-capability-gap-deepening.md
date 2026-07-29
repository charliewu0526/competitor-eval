# PRD 0004 — capability-gap 双通道深化(结论质量 + 竞品普查 + 归因升级)

> 承接 projects.competitor-eval.capability-gap-dual-channel:功能A(vio 失败反转)+ 功能B(竞品能力普查差集)已上线,两入口一出口(capability-gap → 方法沉淀)已打通。本 PRD 补齐「中间的质量与覆盖」——上线后数据体检暴露:入口/出口通了,但结论质量、竞品覆盖、复核闭环都是空的。
> 铁律不变:机器只标疑似 + 带证据引用,PM/AI 复核拍板,缺数据如实标不伪造。所有新增能力复用现有 findings / method_synth / capability_store / gap_attribution 接缝,不另造评分核心。

## Problem Statement(基于上线后真实数据体检)

| 维度 | 现状(线上 Postgres) | 痛点 |
|---|---|---|
| 交付物/日志可得性 | 38 run 里 **27 条 evidence_source=unavailable,仅 11 条有 log** | 功能A「靠日志分析」在 71% 的题上无料可用 |
| vio 真实落后 | 对打 16 题里 **仅 2 题**(T15-file-rename、TA2-morning-briefing) | 功能A 单产品视角弹药太少 |
| 竞品能力清单 | 9 个竞品**只有 town/vio 2 份**清单 | 差集「分母」严重不足,普查靠手工抠 md |
| findings 复核 | 15 条**只有 1 条**填了 final_category | 复核环节几乎空转 |
| methods 出口 | 6 条**全卡 draft,0 approved / 0 exported** | 结论从没真正到过研发手里 |

三句话总结:**(1) 结论到不了研发能直接执行的程度;(2) 竞品普查是手工的、覆盖不足;(3) 归因只盯单产品失败、且强依赖常常拿不到的日志。**

## Solution(分两期)

**第一期(A+B+C,不依赖新数据抓取管道,吃现有 38 条评测数据即可):**
- **A. 结论结构化**:方法 draft 从「一句话功能点 + 建议」升级为研发可执行卡片(功能点 / 范围边界 / 验收标准 / 优先级 / 证据链 / 竞品做法)。
- **B. 交付物对比降级路径**:归因引擎在日志 unavailable 时,改读双方交付物「成品」反推竞品好在哪,并显式标注证据档位(日志级 / 成品级 / 不可得)。
- **C. 功能A 升级为多竞品域对比矩阵**:从「vio 单产品失败反转」扩展为「按能力域横向:这道题/这个域里谁做到、谁没做到、vio 处在什么位置」,喂给 capability-gap。

**第二期(D+E,治本、需新数据管道 + 复核提效):**
- **D. 竞品自动调研入口**:加竞品 → 贴官网/新闻/社媒链接 → 自动抓取 → LLM 抽能力 → 落 candidate 待复核 → 入能力清单库。
- **E. AI 预复核**:findings / methods 复核由 AI 先给 final_category 建议 + 理由,人只需确认,解决 1/15 复核率。

**未来(F,不在本 PRD 承诺范围,仅登记方向):** 同题多次重试 + prompt 变体,用成功率区分「偶发失败」vs「真能力空白」,让功能A 判定统计上站得住。

## User Stories

### A. 结论结构化(研发可执行卡片)
1. As 研发,I want 拿到的方法卡片有明确「功能点」一句话,so that 我一眼知道要做什么。
2. As 研发,I want 卡片有「范围边界」(做到哪算够、哪些不在本次范围),so that 我不过度实现也不漏。
3. As 研发,I want 卡片有「验收标准」(怎么算补上了这个能力),so that 我知道完成的判据、可自测。
4. As 研发,I want 卡片有「优先级/影响面」(这个空白影响多少题/多少能力域),so that 我能排期。
5. As 研发,I want 卡片有「证据链」(竞品做到了的原文引用 + 出处),so that 我信这个结论、能顺藤查竞品做法。
6. As 系统,I want 结论字段缺失时如实标「待补」而非编造,so that 不伪装完整度(缺数据如实标)。
7. As reviewer,I want 结构化卡片在方法沉淀页分区展示(不是一坨 markdown),so that 复核时逐项看得清。

### B. 交付物对比降级路径(无日志时凭成品反推)
8. As 系统,I want 归因引擎先看有无日志:有日志走原路径(过程级归因),so that 不浪费已有的高质量证据。
9. As 系统,I want 日志 unavailable 时降级读「双方交付物成品」反推竞品好在哪,so that 覆盖 71% 没日志的题、不因缺日志就放弃归因。
10. As PM,I want 每条归因/结论显式标注证据档位(过程级=有日志 / 成品级=仅交付物 / 不可得),so that 我知道这条结论的可信度来自哪一层、不把成品级当过程级铁证。
11. As 系统,I want 成品级归因产出的结论 confidence 不高于过程级,so that 证据弱的结论不冒充强证据(可信度分层)。
12. As 系统,I want 两个交付物都拿不到时如实标「不可得、无法归因」,so that 不脑补竞品做法。

### C. 功能A 升级为多竞品域对比矩阵
13. As PM,I want 对一道题(或一个能力域)看到「谁做到、谁没做到、vio 处在什么位置」的横向矩阵,so that 不再局限于 vio 单产品失败这一个视角。
14. As 系统,I want 矩阵按能力域聚合(同域才同台,cannot-reach 不算失败),so that 不拿桌面题的失败冤枉云端产品。
15. As 系统,I want 矩阵里「有竞品做到、vio 没做到」的格子 → 汇入 capability-gap 候选,so that 弹药从 2 题扩到 16 题 × 9 竞品的矩阵。
16. As PM,I want 矩阵里「vio 做到、竞品普遍没做到」的格子标为 vio 领先项,so that 优势面也别漏看(对称呈现)。
17. As 系统,I want 单次失败不直接判能力空白,先看该产品在同域其他题是否具备该能力,so that 区分「这次没做」和「根本不会」(降低误判)。

### D. 竞品自动调研入口(第二期)
18. As PM,I want 在系统里有一个「添加竞品」入口,so that 不用手改 registry json。
19. As PM,I want 添加竞品时可贴官网链接 / 新闻链接 / 社媒链接作为调研来源,so that 抽取有一手依据。
20. As 系统,I want 添加后可一键启动自动调研:抓取来源 → LLM 抽能力条目 → 落 candidate,so that 普查从手工变自动。
21. As 系统,I want 抓取的每条能力带来源 URL + 抓取时间,so that 可追溯、可判新鲜度。
22. As reviewer/PM,I want 自动抽取的能力条目一律 candidate 待复核,确认才升 shipped 进差集,so that 营销话术不混进候选(沿袭 AI 复核闸)。
23. As 系统,I want 抓取失败/来源不可达时如实标,不产伪造能力条目,so that 缺数据如实标。

### E. AI 预复核(第二期)
24. As reviewer,I want AI 对每条待复核 finding 先给 final_category 建议 + 理由,so that 我从「填空」变「确认」,解决复核空转。
25. As reviewer,I want AI 对方法 draft 先给「可 approve / 需打回 + 原因」建议,so that 把关提速。
26. As 系统,I want AI 预复核只给建议、最终仍由人拍板落库,so that 不让 AI 自己批自己(人是最终闸)。
27. As PM,I want AI 预复核建议与人最终结论的一致率被记录,so that 能观测 AI 复核的可信度、必要时收紧。

## 架构接缝(复用现有,不另造核心)

| 工作流 | 复用的现有件 | 新增的最小件 |
|---|---|---|
| A 结论结构化 | `method_synth._render_draft` / `_synthesize_one` | draft 从自由 markdown → 结构化字段(feature_point / scope / acceptance / priority / evidence / rival_practice);`_synthesize_one` 的 LLM 提示多产出这几段;方法卡片渲染分区 |
| B 交付物降级 | `gap_attribution` / `vio_gap`(已有 `_docs_block` + 引用校验) | 归因入口加「证据档位」判定:有 log → process-level;仅 artifact → artifact-level;都无 → unavailable。confidence 上限随档位收窄 |
| C 多竞品矩阵 | `gap_report` / `findings` / `capability_census` | 新派生视图 `capability_matrix`:按 (能力域 × 题 × 产品) 聚合 scores → 「谁做到/没做到」矩阵;空白格 → 复用 `census_to_findings` 的 capability-gap 落库路径 |
| D 自动调研 | `capability_store` / `capability_census.extract_capabilities_via_llm`(已有 LLM 抽取 + candidate 闸) | 竞品登记 UI + 来源抓取器(webfetch/websearch)→ 喂已有 extract → save_capabilities;registry 加来源字段 |
| E AI 预复核 | `authorizations` 校准表 / `review_client` 面板 / `spot_check_queue` | 预复核器:读 finding/method → LLM 给建议;建议写入待复核项(不落最终);记录建议 vs 人工一致率 |

**关键:A/B/C 全部落在 pipeline 派生层与 LLM 提示层,不碰评分核心、不改 store schema(除 D 的 registry 来源字段)。** 这也是它们能吃现有数据、第一期就交付的原因。

## Non-Goals(本 PRD 明确不做)

- 不改评分核心(GATE → 客观断言 → 盲评 → H1),不改榜单聚合口径。
- 不做 F(多次重试 + prompt 变体求成功率)—— 需执行器联动,单独立项。
- D 的抓取不做全站爬虫 / 绕反爬 / 登录墙内容,只取公开可 webfetch 的官网/新闻/社媒页面;取不到如实标。
- E 不让 AI 自动落最终结论 —— AI 永远只给建议,人是最终闸。

## 交付分期与验收

### 第一期(A + B + C)
- **A 验收**:方法 draft 落库即为结构化卡片,6 个字段齐全或如实标「待补」;方法沉淀页分区显示;现有 6 条 town draft 重新生成后字段完整。
- **B 验收**:对一道有日志的题归因标 process-level;对一道无日志题(27 条 unavailable 之一)能凭交付物产出 artifact-level 归因且 confidence 明确低于 process-level;两者档位在 gap-report 页可见。
- **C 验收**:能对某能力域(如 assistant-integration)产出多竞品矩阵,矩阵空白格落成 capability-gap Finding;真跑落线上 Postgres、前端可见。
- **一期整体**:全量单测不回归;新增离线单测覆盖每条路径的分支 + dry_run。

### 第二期(D + E)
- **D 验收**:UI 添加竞品 + 贴 3 类链接 → 启动自动调研 → 抽出 candidate 能力条目落库(带来源 URL);复核升 shipped 后进差集真产候选。
- **E 验收**:待复核 finding/method 显示 AI 建议 + 理由;人确认后落库;一致率被记录且可查。

## Open Questions —— 已拍板(2026-07-29)

1. **A 的优先级/影响面** → 采纳粗分档起步:按该 capability-gap 关联的题数 / 能力域数量派生高/中/低,不引入主观权重。
2. **C 的矩阵粒度** → 先按「能力域」聚合(粗、够用),不做单题 × 产品级。
3. **D 的抓取** → 用系统内 `webfetch`/`websearch`(可控、够公开页),不做全站爬虫。
