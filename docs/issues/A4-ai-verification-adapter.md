# [A4] AI 核验适配器（出题≠核验，不自评）

Label: ready-for-agent
Covers user stories: 14, 17

## What to build
AI 核验适配器：核验 AI 与出题 AI 必须用不同模型（不能自评）。核验通过即自动入库，出题流程不阻塞。核验员先在黄金集上达标才被授权处理真实任务（授权逻辑见 G2）。需生产实现 + 内存假实现。

## Acceptance criteria
- [ ] 生产实现：核验 AI 调用与出题模型不同家族，输出 pass/fail + 理由
- [ ] 内存假实现：返回固定核验结果
- [ ] 两实现满足同一契约
- [ ] 出题模型 == 核验模型时被拒（强制不自评）
- [ ] 核验 pass → 自动入库（无人工签字闸门）

## Blocked by
- F1

## Prior art
None — new。
