# [A2] 证据采集适配器（日志 > 截帧 > 录屏）

Label: ready-for-agent
Covers user stories: 7, 19, 22

## What to build
证据全自动采集适配器，无需任何人工录屏。优先级：竞品结构化日志 > 自动截帧 > 录屏（仅黑箱兜底）。设置 `evidence_source` 字段诚实标注来源（log/screenshot/recording/unavailable）。日志只用于还原过程喂 S5，绝不用于完成度判定。需生产实现 + 内存假实现。

## Acceptance criteria
- [x] 生产实现：按 log>screenshot>recording 优先级采集并标 evidence_source
- [x] 内存假实现：返回固定证据包 + source
- [x] 两实现满足同一契约
- [x] 拿不到证据 → evidence_source=unavailable（不伪装成空/0）
- [x] S5 锚点需过程证据时，能从本适配器取到 / 取不到则 S5 空

## Implementation (2026-06-29)
- `pipeline/evidence_client.py` — 生产实现 `EvidenceCollector`:按 log>screenshot>recording 优先级探测真实 artifact,最高有效层定 evidence_source;`collect_from_run()` 直接从 RunRecord.env_meta/screenshots 取证。`for_completion` 硬编码 False(证据绝不判完成度)。
- `pipeline/evidence_fakes.py` — 内存假实现 `FakeEvidenceCollector`:零磁盘 I/O,按 source 返回固定证据包,满足同一契约。
- 契约 `{evidence_source, items, has_process_evidence, for_completion}` 直接可作 ctx 喂 `aggregate.aggregate_subjective()`——携带 S5 闸门读的两个键。
- `tests/test_evidence_adapter_a2.py` — 16 用例覆盖全部 5 条验收(优先级、unavailable 不伪装、契约一致、for_completion 不变量、S5 闸门联动)。

## Blocked by
- F1

## Prior art
None — new。
