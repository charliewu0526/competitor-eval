# 测试用例:三身份端到端全生命周期

> 目的:证明多人竞品评测工场的最薄闭环在**三种身份各自的职责边界**下都成立。
> 上真人前的最后一道验收 —— 先把用例写清楚(本文件),再用脚本 `scripts/e2e_three_roles.py`
> 真穿通(FastAPI TestClient + 真鉴权 + 真落库,离线临时库,不碰生产 board/)。
>
> 立身之本:只看末态事实、职责分离、越权即拒。每条用例都标了**预期结果**,脚本逐条断言。

## 三种身份与职责(RBAC 权限矩阵,源自 pipeline/rbac.py)

| 身份 | rank | 能做(累加低阶权限) | 典型职责 |
|------|------|----------------------|----------|
| **intern** 实习生 | 0 | `claim_assignment` 领任务 · `submit` 提交/提炼方法初稿 | 领一道题→真跑→交原始产物+日志→提炼方法 draft |
| **reviewer** 审核员 | 1 | intern 全部 + `review` 复核AI报告/抽查裁定 · `gate_method` 方法把关 | 复核可疑评分、把关方法初稿 draft→approved |
| **owner** PM | 2 | reviewer 全部 + 6 个危险开关 | 签链接/提升角色/物化任务/维护清单/校准/脱敏 |

**owner 独占的 6 个危险开关**:`promote_user` 角色提升 · `issue_invite` 签发注册链接 ·
`calibrate_golden` 黄金集校准 · `authorize_reviewer` 评委授权 · `manage_task_catalog` 任务清单 ·
`manage_desensitization` 脱敏规则。校准类绝不落到新人甚至审核员手里(PRD story 5)。

**未登录(匿名)**:除注册/登录外一律拒(401/403)。

---

## 场景总览

一条主线贯穿三身份,穿插越权负例。所有步骤对同一道题 `T1-wechat-send-001`
(参赛集 vio / open_interpreter / simular),同一临时库。

```
owner 建场 → intern 领并跑并交 → intern 提炼方法 → reviewer 把关+复核 → owner 收口治理
```

---

## A. owner(PM)建场

| # | 操作 | 预期结果 |
|---|------|----------|
| A1 | owner 登录换会话令牌 | 200,`/me` role=owner |
| A2 | owner 签发私发注册链接 `issue_invite` | 200,拿到 invite token |
| A3 | owner 物化 T1 为可领取 Assignment `manage_task_catalog` | 200,products=参赛集(≥1),status=open |

## B. intern(实习生)自注册 + 领取 + 提交

| # | 操作 | 预期结果 |
|---|------|----------|
| B1 | intern 持链接自注册 | 200,新用户 role=**intern**(默认最小权限) |
| B2 | intern 看 open 清单 | 200,含 A3 的 Assignment |
| B3 | intern 领取该 Assignment `claim` | 200,claimed_by=intern |
| B4 | intern **缺原始产物**提交一个产品 | **400 无证据不入池**(立身之本) |
| B5 | intern 为参赛集每个产品各交一份(真上传 artifact+日志包) | 每个 200;进度 complete=true |
| B6 | intern 收口整组 `submit` | 200,status=submitted |

## C. intern 越权负例(职责边界下沿)

| # | 越权尝试 | 预期结果 |
|---|----------|----------|
| C1 | intern 签发注册链接 `issue_invite` | **403**(owner 独占) |
| C2 | intern 物化任务 `manage_task_catalog` | **403** |
| C3 | intern 提升自己为 owner `promote_user` | **403** |
| C4 | intern 复核/抽查裁定 `review` | **403**(复核 reviewer 起) |
| C5 | intern 把关方法初稿 `gate_method` | **403** |

## D. intern 提炼方法初稿(方法闸入口)

| # | 操作 | 预期结果 |
|---|------|----------|
| D1 | intern 在差距证据包上创建 Method draft | 200,status=draft |
| D2 | intern 直接导出未把关的 draft | **409 NotApproved**(未把关不能进研发) |

## E. reviewer(审核员)复核 + 方法把关

| # | 操作 | 预期结果 |
|---|------|----------|
| E1 | owner 把一个 intern 提升为 reviewer `promote_user` | 200,role=reviewer |
| E2 | reviewer 把关方法 draft→approved `gate_method` | 200,status=approved,gated_by=reviewer |
| E3 | reviewer 导出 approved 方法 | 200,status=exported,文档含"落地建议"+"差距证据" |
| E4 | reviewer 越权:签发链接 `issue_invite` | **403**(危险开关仍 owner 独占) |
| E5 | reviewer 越权:提升角色 `promote_user` | **403** |

## F. owner 治理 + 末位保护

| # | 操作 | 预期结果 |
|---|------|----------|
| F1 | owner 把 reviewer 降回 intern `promote_user` | 200,role=intern |
| F2 | owner 降走系统最后一个 owner | **拒绝**(末位 owner 保护,系统不能无 owner) |

## G. 匿名负例

| # | 操作 | 预期结果 |
|---|------|----------|
| G1 | 无令牌访问 `/api/me` | **401** |
| G2 | 无令牌领取 Assignment | **403**(未登录无权) |

---

## 通过标准

上述 A–G 全部断言通过 = 三身份职责边界成立、最薄闭环端到端穿通、立身之本(无证据拒收 /
未把关不进研发 / 越权即拒 / 末位 owner 保护)全部守住。任一条失败即阻断"上真人"。

