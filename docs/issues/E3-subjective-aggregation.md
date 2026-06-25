# [E3] 主观聚合：中位数 + 分歧标红 + 打分/找错分家

Label: ready-for-agent
Covers user stories: 6, 7, 10, 11

## What to build
三模型盲评 S1 质量 / S2 效率 / S3 可靠性 / S4 自主性 / S5 体验，每分必附 justification。聚合用中位数（稳健）；三分极差 ≥2 自动标红等人复核。「打分」和「找错」分家：缺陷不管谁抓到、只要有效就单独入库，绝不压低分数（兑现 DeepSeek「严」的价值）。S5 按锚点 5/3/1 打分，依赖过程证据，无过程证据则 S5 为空。接缝内逻辑，合成测。

## Acceptance criteria
- [ ] 合成：三分 [5,4,1] → 中位数 4；极差=4≥2 → 标红
- [ ] 合成：缺陷条目单独入库，不改变 sample_score
- [ ] 每个主观分缺 justification → 视为无效
- [ ] S5：无过程证据 → S5 为空（非 0）
- [ ] 聚合对 2 个 / 3 个评审分都成立

## Blocked by
- F1

## Prior art
pipeline/orchestrate.py —— 当前是双 AI（Gemini+Claude）；泛化为多模型 + 中位数聚合。
