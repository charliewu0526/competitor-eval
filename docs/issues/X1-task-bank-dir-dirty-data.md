# [X1] 任务库目录规范 + 脏数据声明制

Label: ready-for-agent
Covers user stories: 30, 31, 32

## What to build
每个任务一个固定目录：README/prompt/meta.json/input/expected/output/evidence/scoring（人读 md，机器读 meta.json）。任务声明 `dirty_data_level`（none/light/heavy）：声明 heavy 才必填 `known_edge_cases`，并与 tier 交叉校验，守住「材料可假、脏数据必真」铁律又不官僚。出题 AI 给 `dirty_data_level_suggested` + 候选坑，人/核验 AI 定 final，两值并存（AI 不自评合格）。

## Acceptance criteria
- [ ] 固定目录布局落地，含 README/prompt/meta.json/input/expected/output/evidence/scoring
- [ ] meta.json 为机器可读单一源，与 schema（F1）字段一致
- [ ] dirty_data_level=heavy ⇒ known_edge_cases 必填，否则校验失败
- [ ] suggested 与 final 两值并存，校验确认非同一来源填写
- [ ] T1_wechat_send 迁入新目录规范作为样板

## Blocked by
- F1

## Prior art
tasks/T1_wechat_send.py —— 第一个任务；按本规范正式化目录布局。
