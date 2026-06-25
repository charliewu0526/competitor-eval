# [E2] 客观断言层（末态硬验完成度）

Label: ready-for-agent
Covers user stories: 5, 20

## What to build
完成度不靠 AI 读自述，由客观断言层用末态事实硬判（消息真发出没、文件真生成没）。primary 断言失败 → sample_score=0 且跳过主观评审。日志只用于还原过程喂 S5，完成度永远以末态为准——这样竞品「谎称完成」当场被拆穿（复刻 OI 案例）。接缝内核心逻辑，合成 RunRecord 测。

## Acceptance criteria
- [ ] 合成：primary 断言失败 → sample_score=0、主观层被跳过
- [ ] 合成：primary 通过 → 进入主观评审
- [ ] 完成度判定只读末态字段，绝不读 claimed_success/日志文本
- [ ] 单测覆盖：末态成功、末态失败、末态缺证据三种情形

## Blocked by
- F1

## Prior art
pipeline/objective.py —— 扩展现有断言逻辑。
