# [A2] 证据采集适配器（日志 > 截帧 > 录屏）

Label: ready-for-agent
Covers user stories: 7, 19, 22

## What to build
证据全自动采集适配器，无需任何人工录屏。优先级：竞品结构化日志 > 自动截帧 > 录屏（仅黑箱兜底）。设置 `evidence_source` 字段诚实标注来源（log/screenshot/recording/unavailable）。日志只用于还原过程喂 S5，绝不用于完成度判定。需生产实现 + 内存假实现。

## Acceptance criteria
- [ ] 生产实现：按 log>screenshot>recording 优先级采集并标 evidence_source
- [ ] 内存假实现：返回固定证据包 + source
- [ ] 两实现满足同一契约
- [ ] 拿不到证据 → evidence_source=unavailable（不伪装成空/0）
- [ ] S5 锚点需过程证据时，能从本适配器取到 / 取不到则 S5 空

## Blocked by
- F1

## Prior art
None — new。
