# [A3] 成本统计适配器 + 单价表

Label: ready-for-agent
Covers user stories: 21, 22

## What to build
成本统计适配器：按任务记 token 用量 + 调用次数 + 折算成本 $ 三个数，并与「是否真完成」一起看（防「摆烂没干完」伪装成「省 token」）。`cost_source` 诚实标注（self-report/proxy/unavailable）。`cost_usd` 由独立维护的「模型每百万 token 单价表」折算（价格会变，单独成表）。需生产实现 + 内存假实现。

## Acceptance criteria
- [ ] 生产实现：采集 token/calls 并按单价表折算 cost_usd，标 cost_source
- [ ] 内存假实现：返回固定成本三元组 + source
- [ ] 两实现满足同一契约
- [ ] 单价表独立成文件，改价不改代码；缺价 → cost_usd 标 unavailable
- [ ] 成本与 sample_score 并排可取（成本不能脱离完成度单独解读）

## Blocked by
- F1

## Prior art
None — new。
