# TB3 — 越用越自主（assistant-integration / rival-signature）

**竞品卖点验证题**。验证 Town 宣传的「给你一个 dial 不是 switch / 准备好就放开自主 / grant autonomy when ready」落地到什么程度——放开审批后能否真端到端自主闭环。

- **能力域**：assistant-integration
- **任务性质**：long-horizon
- **tier**：rival-signature（竞品主打卖点轨）
- **脏数据**：none（考的是自主闭环程度，非脏数据）
- **参赛**：town + vio 对打
- **requires_local_desktop**：false → town 判 `api-or-integration`，vio 判 `native-operable`

## 立身之本
只认末态事实：分步执行看 `output/autonomy-log.md`，是否真闭环/卡几次确认由受训 intern 人核。声称已发送的动作必须有真实末态证据（草稿/发送记录）。不信产品自述"我全自动做完了"。

## 三种结局都有用
- 放开审批后真端到端闭环 → 话术为真 → **violoop 对齐这个自主度**
- 步步仍卡「要你确认」→ 坐实"自主"有限
- 部分闭环 → 记录卡点数量，划出真实边界

## ⚠ 安全
放开自主 + 真发送有副作用。**在测试用/隔离账号里跑，勿用生产邮箱真发给真人。**

## 起始素材
- `input/request.txt`：一个需 3 步以上才能办完的请求
- `input/contacts.txt`：联系人
- `input/inbox/`：可供检索的往来
- `expected/end-state.md`：端到端应完成的步骤清单 + 判定"是否真闭环"的观察点
