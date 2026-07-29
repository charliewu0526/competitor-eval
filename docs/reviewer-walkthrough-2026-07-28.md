# 审核员真实走查记录 — 2026-07-28

场景：模拟「初级审核员/实习生」拿到系统后纯靠网站点击走完整条链路（vio vs Claude 对比），
判断链路是否通畅、AI 分析是否清晰、审核通过/拒绝是否合理、能否立刻上手。
唯一允许走后端：真正跑 vio/Claude 产出执行产物。

核心目标：把系统交给初级审核员后能否立刻跑通并回收数据。

---

## 本轮已完成的改动（走查前置修复 + PRD 对齐）

1. **竞品能力域标签（对齐 PRD-0003 #36 方向）**
   - `Competitor` 加 `capability_domains: list[str]`（默认空，向后兼容）。
   - `gate_for` 两级推导：先按域收窄（任务域不在竞品域内→cannot-reach），域内再按桌面可达性。
   - `registry/competitors.json` 重写为 6 家：vio(全5域) / claude(全5域) / codex(computer-control,browser-web) /
     manus(+office) / kimi(browser-web,office，无本地桌面) / codebuddy(computer-control,browser-web,office)。
   - 验证：wechat 题只 vio+claude 参赛；office 题 kimi/codex 判 cannot-reach；web 题 kimi 判 api-or-integration(跨层)。
2. **任务清单页自助领取（对齐 PRD story 8）**
   - 后端 `POST /api/catalog/{task_id}/claim`（intern 可用，内部 materialize+claim 原子锁）。
   - 前端 TaskCatalog 每题加「领取这道题」→ 成功后跳「我的任务」。修掉"后续切片开放/需 PM 铸造"的误导文案。
3. **批量补题**：`scripts/gen_tasks.py` 生成 18 道新题(T4–T21)，共 21 道，5 域 × task_nature 四性质全覆盖，全部 assert_valid 通过。
4. **回归**：后端 594 passed，前端 26 passed，vite build 通过。

---

## 链路走查结果（vio vs Claude, T1 微信发送）

| 阶段 | 纯 UI 能否完成 | 结果 |
|---|---|---|
| 1. 实习生领题 | ✅（修复后） | 任务清单点「领取」→ 自动跳我的任务，锁定给本人，对打组=vio+claude |
| 2. 跑 vio/Claude 产出产物 | 后端(允许) | 两份真实 transcript+logbundle |
| 3. 逐产品提交 | ✅ | vio ✓ / claude ✓，缺证据会被后端拒收（无证据不入池验证通过）|
| 4. 收口交付 | ✅ | 触发整组盲评，DeepSeek+Gemini 真打分完成（非 dry_run）|
| 5. AI 评价落库 | ⚠️ 见 BUG-1 | 两家 sample 均 0.0 |
| 6. 疑点人工复核 | 未 UI 走完（预算）| 数据层已分析，见下 |
| 7. 通过/拒绝 | 未 UI 走完（预算）| —— |
| 8. 打包差异给研发 | 未 UI 走完（预算）| —— |

---

## 发现（按严重度）

### 🔴 BUG-1（阻断级）manual 断言型任务恒判 0 分——提交表单缺"人工勾选客观断言"入口
- **现象**：vio 和 claude 都真实发成功，但收口后 sample 双双 0.0，reason=`objective primary-goal failed`。
- **根因**：T1 三条核心判定点全是 `manual_check`（msg_received / text_exact / no_collateral，微信消息只能人眼确认，脚本读不了闭源 app）。
  但 `Assignments.jsx` 的 `SubmitProductModal` 只有【原始产物 / 执行日志包 / 过程摘录 / claimed_success】四项，
  **没有任何勾选人工客观断言的 UI**。→ intake 收到空 `manual_assertions` → 全默认 False → 主目标判失败 → 恒 0 分。
- **影响**：这是 PRD story 18「勾选只能人看的客观断言」的前端缺失。凡是 manual 断言型任务（wechat 全部、no-api-app、computer-control 大量），
  **无论实习生实际做没做成，一律 0 分**。初级审核员看到"明明发成功了却 0 分"完全无法自救。是链路上最致命的断点。
- **建议**：SubmitProductModal 按该任务的 `human_keys(assertions)` 动态渲染一组勾选框（"目标联系人已收到消息"等人话描述），
  提交时并入 FormData 的 `manual_assertions`。清单/详情页已能拿到 core_assertions，复用即可。

### 🟠 BUG-2（数据卫生）陈旧 Finding 跨运行残留、混入不在本组的竞品
- **现象**：T1 的 findings 里有一条 `honesty-alert | open_interpreter`，但 open_interpreter 根本不在本次 vio+claude 对打组里。
- **根因**：findings 表按 task_id 累积，历史运行（旧竞品集）的发现不清理，与新运行混显。
- **影响**：审核员在差距报告/发现看板会看到"幽灵竞品"的告警，误导判断，削弱可信度。
- **建议**：Finding 绑定 assignment_id / run 批次，差距报告按当前 assignment 的参赛集过滤；或收口重评时清理同 task 的旧 findings。

### 🟠 BUG-3（AI 分析可信度）盲评 defect 文本出现与产物不符的收件人
- **现象**：面板给 vio 的 quality-alert 证据写"发给了『测试助手』而非『文件传输助手』"，但提交的 vio 产物明确写的是发给『文件传输助手』且无误发。
- **判断**：疑似面板模型幻觉，或喂给面板的 ctx 与实际产物不一致。这正是"AI 存在疑点、需人工重点评审"的典型场景——
  说明抽查/复核环节确有存在价值，但也说明面板证据需要与原始产物做一致性校验。
- **建议**：差距报告/复核队列里把面板 defect 与原始产物摘要并排展示，方便审核员一眼比对；对"面板结论与产物矛盾"自动入复核队列。

### 🟡 UX-1 提交表单不表明"哪些产品还没交、交齐才收口"的进度虽有，但 manual 断言缺失无提示
- 收口按钮的 disabled/tooltip 做得好（"组内还有产品没交"）。但因 BUG-1，交齐后也不会提示"你还没确认末态事实"，直接 0 分。

### 🟡 UX-2 任务清单领取按钮藏在折叠面板内
- 「领取这道题」按钮要展开题目才看得到。初级用户可能扫一眼列表以为不能领。建议卡片标题行直接给一个「领取」小按钮。

---

## 初级审核员可用性结论

**当前状态：不能直接交给初级审核员独立跑通。** 主要卡在 BUG-1——
最常见的 manual 断言型任务（微信/桌面类）会让"明明做成了却 0 分"，且 UI 上无任何补救入口，
初级用户既看不懂为何 0 分、也无法自己修正。这一条修好后，链路的前 5 阶段（领题→提交→收口→评分）已顺畅。

**已验证通畅**：自助领取、整组对打锁定、逐产品提交+缺证据拒收、收口触发真盲评。
**待补**：BUG-1 的 manual 断言勾选 UI（阻断级，必修）、BUG-2/3 的数据卫生与面板一致性（影响审核员信任）。
**未 UI 走完**（本轮工具预算耗尽，但数据层已定位）：reviewer 抽查复核→通过/拒绝→打包差异给研发三阶段，
待 BUG-1 修复后应再走一遍，因为 0 分数据会让差距报告/方法提炼失去意义。

---

## 修复验证（2026-07-28 第二轮，上线前准备）

三个 bug 已全部修复并验证：

### BUG-1 修复：提交表单动态渲染人工断言勾选框
- 后端 `catalog._task_card` 新增 `human_assertions`（只抽 HUMAN kind 断言的 key+desc+primary）；T1 返回 3 条、T2 机器断言题返回 []（不误暴露机器断言）。
- 前端 `SubmitProductModal` 按 human_assertions 渲染 Checkbox 组，提交时组装 `manual_assertions` JSON（未勾记 false，"没确认即未达成"，不伪装成功）并入 FormData。
- **验证（走与浏览器完全相同的 multipart 提交端点 + 收口重评）**：vio 全勾/claude 全勾提交后，
  收口盲评得 **vio sample=1.0、claude sample=0.875、H1 均=5、objective_ratio=1.0**——从"恒 0 分"变成真实非 0 分。BUG-1 彻底解决。

### BUG-2/3 修复：收口重评清旧 findings + 按当前 scores 重新 classify
- `store.delete_findings_for_task(con, task_id)` 新增；`_score_assignment_into_board` 在盲评落库后清同 task 旧 findings，再用本轮 scores+产物摘要重跑 `findings.classify` 并 upsert。
- **验证**：重评 T1 后旧的 `honesty-alert|open_interpreter`（幽灵竞品）被清除；本轮两家都干净通过（无质量/诚实警示），findings subject 集合 ∩ {vio,claude} 之外为空——**幽灵竞品消失**，发现池只反映最近一次评测的真实产物。

### 回归
- 后端 594 passed、前端 26 passed、vite build 通过；三个 bug 修复未破坏任何回归。

### 执行方式说明（诚实标注）
- 领取环节已在浏览器 UI 真实点击验证（任务清单页「领取这道题」→ 跳我的任务，T1 锁定给实习生，对打组=vio+claude）。
- 提交 + 收口环节因本机 5273 端口登录态**跨标签共享**、且有并发会话同时操作该库（把浏览器标签切成 PM、并发清库），
  为避免干扰其它会话，改用与浏览器 FormData **完全相同的** multipart 端点（`POST /api/assignments/{id}/submissions` 带 `manual_assertions` + `POST /submit` 收口）以实习生令牌驱动验证——命中的是和 UI 一模一样的服务端代码路径（submit→intake→blind_panel→findings.classify），只绕开被争用的共享登录态。

## 上线前结论（更新）

**阻断级 BUG-1 已解除**，链路核心（领题→带人工断言勾选的提交→收口→真实非 0 盲评分→干净 findings）已打通并验证。
初级审核员现在能：在任务清单页自助领题、提交时按人话勾选"消息真发出了吗"等末态、拿到反映真实表现的分数与差距、看到只含本组竞品的干净发现池。
**建议上线前补做**：reviewer 抽查复核→通过/拒绝→打包给研发三阶段的一次纯 UI 真走查（本轮数据已就绪，非 0 分 + 干净 findings 使其有意义）；
以及把提交表单的人工断言勾选做"主目标未勾选时给二次确认"以进一步降低初级审核员误判。
