# [G2] 黄金集授权（kappa）+ 重校准触发

Label: ready-for-agent
Covers user stories: 12, 14, 15

## What to build
AI 评审员/核验员先在黄金集上达标才被授权自动处理真实任务。算 Cohen's kappa（面板 vs 人标），第一版只记录、不设硬阈值。各模型宽严偏移用黄金集实测、只记录不自动改分（不矫枉过正抹真信号）。重校准触发器：换模型版本 / 改 rubric / 抽查异常 → 授权自动作废并重新校准。

## Acceptance criteria
- [ ] 评审/核验对黄金集跑一遍，算并记录 Cohen's kappa
- [ ] 第一版无硬阈值卡断，只输出一致率 + 偏移档案
- [ ] 偏移档案只记录、不自动改分
- [ ] 换模型版本 / 改 rubric / 抽查异常 任一发生 → 授权状态置为失效
- [ ] 授权失效后，再次跑黄金集才能恢复授权

## Blocked by
- G1
- A1
- A4

## Prior art
None — new。
