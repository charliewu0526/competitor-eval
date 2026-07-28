# Scoring — W1 销售对账催款 (跨 app 职业工作流)

这是一道跨 app 职业工作流任务,断言【分层】:能机器判的从产出文件自动判,
判断/沟通类挂人工核验(端态硬门,不信自报)。

| 断言 | primary? | 判法 |
|------|----------|------|
| 未到账判断正确(恰好海通贸易+本立设计两家) | ✅ primary | 人工核验(runner 勾选);可辅以 unpaid.xlsx 机器读 |
| output/unpaid.xlsx 存在且含正确两家+发票号+金额 | ✅ primary | 机器读文件:客户集={海通贸易,本立设计}, 金额={12500,8800} |
| 微信催款只发对这两家的正确联系人,未发错/未发已到账 | ✅ primary | 人工核验(端态,截图为证) |
| summary.md 数字正确(4笔/已到账2/未到账2/合计21300) | secondary | 机器读文件比对 |
| 催款消息措辞得体专业 | secondary | 盲评主观面板(非机器断言) |

## Judgment rules
- **Primary fail**(判断错 / 催收表错 / 发错人漏发)⇒ `sample_score = 0`,主观面板跳过(E2 端态硬门)。
- 产品自称"已完成"永不算数,只认人工核验的末态(H1 诚实轴,E4)。
- 机器断言(unpaid.xlsx / summary.md 内容)可自动判;人工断言(判断正确性、微信发送末态)由受训 runner 勾选、抽查复核。
- evidence/ 只喂 S5 过程锚点与措辞盲评,永不定 pass/fail。

## 跨 app 判断难点(本题的区分度所在)
- 户名模糊匹配:银行流水"云图科技有限公司"= 应收"云图科技"(同一家,已到账)。
- 干扰流水:"某某个人 2000"与任何应收无关,不能误判为到账。
- 金额核对:到账金额需与应收金额一致才算真到账。
- 判断链条错一环即 primary fail —— 这正是能拉开产品差距的地方。

## GATE
`requires_local_desktop = true` + `capability_domain = professional-workflow`。
GATE 运行时派生:只有登记了 professional-workflow 域且能操控本地全套桌面的产品
(vio / claude)参赛;云端/单一浏览器产品(operator/mariner/kimi/codebuddy)
及不覆盖该域的 codex/manus 一律 `cannot-reach`,排除出榜,不冤枉打 0。
