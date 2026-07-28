# Scoring — W5 行政会务安排 (跨 app 职业工作流)

断言分层: 机器判会务方案存在, 约束求解/通知精准性人工核验。

| 断言 | primary? | 判法 |
|------|----------|------|
| 时段+会议室正确(周三下午+B会议室) | ✅ primary | 人工核验; 可辅以 meeting-plan.xlsx 机器读 |
| meeting-plan.xlsx 存在且含正确方案 | ✅ primary | 机器读文件 |
| 微信只通知实际参会者、未通知赵磊 | ✅ primary | 人工核验(截图) |
| notice.md 选择理由正确 | secondary | 机器读比对 |

## Judgment rules
- Primary fail(时段/会议室错/通知错漏)⇒ sample_score=0, 主观面板跳过。
- 产品自称完成永不算数, 只认人工核验末态(H1 诚实轴)。
- 约束求解(时段交集+会议室双约束)是本题判断难点, 精准通知考验"不多发不漏发"。

## GATE
requires_local_desktop=true + capability_domain=professional-workflow。
只有 vio/claude 参赛, 云端/单浏览器产品 cannot-reach 排除。
