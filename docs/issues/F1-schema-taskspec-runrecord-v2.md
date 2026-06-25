# [F1] Schema：扩展 TaskSpec 与 RunRecord 到 v2 字段

Label: ready-for-agent
Covers user stories: 4, 8, 21, 22, 30, 31, 32

## What to build
把数据模型扩到 v2。TaskSpec 加 `tier`（core-common/vio-key/rival-signature/stress 四值枚举）、`kind`（task-exam/capability-probe）、`requires_local_desktop`、`dirty_data_level`（none/light/heavy）+ `dirty_data_level_suggested`。RunRecord 加成本字段 `cost_input_tokens/cost_output_tokens/cost_model_calls/cost_usd/cost_source`、`evidence_source`、`claimed_success`（供 H1 推导）。这是接缝的输入契约，必须先定。

## Acceptance criteria
- [ ] TaskSpec 新增 5 字段，tier/kind/dirty_data_level 为受限枚举，非法值被拒
- [ ] RunRecord 新增 8 字段，cost_source/evidence_source 为受限枚举
- [ ] dirty_data_level=heavy 时 known_edge_cases 必填（schema 层校验）
- [ ] 旧的合成 RunRecord 仍能加载（向后兼容，新字段有默认值）
- [ ] 单测：构造合法/非法 spec 各一，断言通过/抛错

## Blocked by
None — can start immediately

## Prior art
pipeline/schema.py —— 扩展现有模型，勿重写。
