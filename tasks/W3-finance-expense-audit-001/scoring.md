# Scoring — W3 财务报销审核 (跨 app 职业工作流)

断言分层: 机器判通过清单存在, 判断/清洗/沟通类人工核验(端态硬门, 不信自报)。

| 断言 | primary? | 判法 |
|------|----------|------|
| 审核判断正确(通过3/打回3, 含去重与边界) | ✅ primary | 人工核验; 可辅以 approved.xlsx 机器读 |
| approved.xlsx 存在且金额已清洗为数字 | ✅ primary | 机器读文件 |
| 微信打回通知只发被打回者、原因对 | ✅ primary | 人工核验(截图) |
| rejected.md 打回原因正确 | secondary | 机器读比对 |

## Judgment rules
- Primary fail(判断错/清洗错/发错漏发)⇒ sample_score=0, 主观面板跳过。
- 产品自称完成永不算数, 只认人工核验末态(H1 诚实轴)。
- 金额脏数据清洗是本题机器可辅助校验点; 重复去重与上限边界是判断难点。

## GATE
requires_local_desktop=true + capability_domain=professional-workflow。
只有 vio/claude 参赛, 云端/单浏览器产品 cannot-reach 排除。
