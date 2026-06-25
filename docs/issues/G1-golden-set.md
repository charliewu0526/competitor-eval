# [G1] 黄金集（20-30 道全谱人工标定）

Label: ready-for-agent
Covers user stories: 13

## What to build
建一个 20-30 道人工标定的全谱黄金集，含成功 / 失败 / 谎称完成 / 模糊四类样本，作为信任锚点。它有双重用途：① AI 评审/核验授权前的对标基准（G2）；② 一组「输入→期望分」的固定回归测试，模型/规则改动后跑它防漂移。

## Acceptance criteria
- [ ] 黄金集达到 20-30 个人工标定样本
- [ ] 四类样本（成功/失败/谎称完成/模糊）各有覆盖
- [ ] 每个样本是合成 RunRecord + 人标期望分（H1 / sample_score / 关键缺陷）
- [ ] 作为回归 fixture 可被测试套件加载并断言
- [ ] OI 谎称完成案例纳入黄金集

## Blocked by
- E2
- E3

## Prior art
None — new（但 runs/ 现有 vio/OI 样本可作为前两条种子）。
