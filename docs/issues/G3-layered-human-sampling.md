# [G3] 分层人工抽查（10% / 100% / 100%）

Label: ready-for-agent
Covers user stories: 16, 18

## What to build
人从「每环节签字闸门」挪到「路径外抽查员」。人只做异步分层抽查：普通任务随机 10%、矛盾项（三模型分歧标红）100%、高风险结论 100%。系统不因等签字而卡住——抽查是事后异步的，不阻塞主流程。

## Acceptance criteria
- [x] 抽查队列按规则采样：普通随机 10%、矛盾 100%、高风险 100%
- [x] 抽查为异步，主流程入库不等待人工处理
- [x] 矛盾项（E3 标红）必然进入 100% 抽查队列
- [x] 抽查结果可回写并触发 G2 的「抽查异常 → 重校准」
- [x] 看板/队列能列出待抽查项及其分层原因

## Implementation (2026-06-29)
- `pipeline/sampling.py` — 分层引擎:`build_queue()` 扫库分层、`classify_run()` 三层规则(高风险>矛盾>普通10%seeded)、`submit_verdict()` 回写并触发 G2 重校准。
- `pipeline/store.py` — 新增 `spot_check_queue` 表 + `enqueue_spot_check`/`record_spot_check`/`spot_check_queue` CRUD(队列项 UNIQUE(task,product,run),重建刷新分层但保留人工结论)。
- `board_app.py` — 「抽查队列」看板区:列出待抽查项+分层原因,行内「一致/异常→重校准」按钮。
- `tests/test_sampling_g3.py` — 17 用例覆盖 5 条验收(seeded 10% 比例、矛盾/高风险 100%、precedence、异步解耦 persist_eval 不入队、anomaly→吊销授权)。

## Blocked by
- S1

## Prior art
None — new。
