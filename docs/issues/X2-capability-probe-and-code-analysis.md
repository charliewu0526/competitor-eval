# [X2] 第二条路径：能力专项对比 + 开源代码机理分析

Label: ready-for-agent
Covers user stories: 23, 24

## What to build
第二条评测路径（v1 由 PM 手动触发）：`capability-probe` 能力专项对比——针对竞品某卖点（如省 token）设计探针任务，拿它 vs Vio 对应功能直接对打。开源竞品可附「代码机理分析」搞清它怎么做到的，让产品机会带机理证据而非只是「人家行」。

## Acceptance criteria
- [ ] capability-probe 类型任务（kind=capability-probe）可被 PM 手动触发并跑通接缝
- [ ] 探针任务可指定卖点维度（如 token 成本），并产出 Vio vs 竞品对打结果
- [ ] is_open_source=true 的竞品可附代码机理分析产物，链接到对应 finding
- [ ] 机理分析作为 finding 的证据字段，支撑「值得借鉴/必须补齐」产品判断
- [ ] 探针结果进入同一 SQLite 数据源与看板

## Blocked by
- S1

## Prior art
None — new。
