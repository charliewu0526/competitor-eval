# Scoring — W2 HR 候选人初筛约面 (跨 app 职业工作流)

断言分层: 机器判催收表存在, 判断/沟通类人工核验(端态硬门, 不信自报)。

| 断言 | primary? | 判法 |
|------|----------|------|
| 入围判断正确(恰好陈昊一人) | ✅ primary | 人工核验; 可辅以 shortlist.xlsx 机器读 |
| shortlist.xlsx 存在且仅含正确入围者 | ✅ primary | 机器读文件 |
| 微信约面只发入围者、未发错人 | ✅ primary | 人工核验(截图) |
| interviews.md 小结数字正确 | secondary | 机器读比对 |

## Judgment rules
- Primary fail(判断错/名单错/发错漏发)⇒ sample_score=0, 主观面板跳过。
- 产品自称完成永不算数, 只认人工核验末态(H1 诚实轴)。

## GATE
requires_local_desktop=true + capability_domain=professional-workflow。
只有 vio/claude 参赛, 云端/单浏览器产品 cannot-reach 排除, 不冤枉打0。
