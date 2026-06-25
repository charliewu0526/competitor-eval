# [A1] 三模型评审适配器（DeepSeek + GLM + Claude）

Label: ready-for-agent
Covers user stories: 6, 9

## What to build
评审面板适配器：DeepSeek + GLM + Claude（两中一西），避免同家族偏见且贴中文桌面场景。背靠背盲打 S1-S5，每分必附 justification，返回三组 {score, justification}。这是接缝后的适配器，需生产实现 + 内存假实现。

## Acceptance criteria
- [ ] 生产实现：三模型 API 各返回 S1-S5 + justification
- [ ] 内存假实现：返回固定三组分数（测试用，不调网络）
- [ ] 两实现满足同一契约（接口测试同时通过）
- [ ] 面板成员可配置（换模型不改核心）
- [ ] 缺 justification 的返回被标为无效（与 E3 对齐）

## Blocked by
- F1

## Prior art
pipeline/review_client.py + review_prompt.py —— 当前是 Gemini+Claude（Bedrock）；换面板为 DeepSeek+GLM+Claude，复用 prompt 结构。
