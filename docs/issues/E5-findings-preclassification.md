# [E5] 发现预分类 + 产品判断 + Bug 流转

Label: ready-for-agent
Covers user stories: 25, 26, 27

## What to build
评测产物变成「发现 Finding」。机器按 5 条确定性 if-then 规则预分类，只贴「疑似」标签（疑似 Bug / 功能差距 / 体验借鉴 / 诚实警示），无证据不入池、机器只标现象不下结论。最终归类 + `产品判断`（必须补齐/值得借鉴/观察中/不适合 Violoop）由 PM 填。Vio 自己翻车的发现自动流入 Bug pipeline，带复现任务/环境/失败步骤/证据。接缝内逻辑，合成测。

## Acceptance criteria
- [ ] 合成：竞品完成 + Vio 失败 → 疑似功能差距 标签
- [ ] 合成：发现无证据 → 不入池
- [ ] 机器只写「疑似」+ 现象，产品判断/最终分类字段留空待 PM 填
- [ ] 合成：Vio 末态失败的发现 → 自动进 Bug pipeline，含 repro+env+steps+evidence
- [ ] 5 条规则各有一条合成用例覆盖

## Blocked by
- E2
- E3

## Prior art
None — new。
