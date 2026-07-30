# ADR-0011 — 黄金集授权机制 + 分层抽查（信任锚点）

- 状态：已接受
- 日期：2026-06-25
- 关联：ADR-0009（AI 核验）、ADR-0005（偏移档案先记不改）、T5 issue

## 背景

所有自动化（AI 核验、AI 打分）都假设「AI 判断和人对得上」。黄金集是持续验证该假设、并在 AI 集体漂移时报警的唯一锚点。

## 决策

### 黄金集构造

- 第一版 **20-30 道**，人工亲手标定满分答案。
- **全谱覆盖**：明确成功 / 明确失败（含「谎称完成」H1 锚）/ 模糊待确认 / 每个 tier × 每个 dirty_data_level 至少各一。
- 规模理由：<20 覆盖不全，>30 人工标定太贵；性价比拐点。

### 授权机制

- AI 核验员/打分员先在黄金集上跑，与人工答案算一致率（Cohen's kappa）。
- 过阈值 → 授权自动处理真实任务；低于 → 退回人工 + 报警。
- **第一版先不设硬阈值**：先记录、观察几轮一致率，有真实数据再定线（同 ADR-0005 克制原则）。

### 重新校准触发点（不靠固定周期）

1. **换模型/模型版本** → 旧授权立即作废，必须重过黄金集（最重要）。
2. **rubric 改动**（如新增 S5/H1）→ 补对应标定。
3. **抽查发现异常** → 触发重校。

### 分层抽查（上岗后巡检）

| 对象 | 抽查比例 |
|---|---|
| AI 放行的普通任务 | 随机 10% |
| `suggested ≠ final`（AI 出题vs核验打架） | 100% |
| H1 诚实警示 / 客观层失败 | 100% |
| 进入「功能差距/必须补齐」的发现 | 100% |

核心：普通任务低比例随机抽（省力），高风险/矛盾项全抽（保质量）。

## 后果

- 黄金集=上岗考试，抽查=上岗巡检，两层防 AI 漂移。
- 人只在黄金集（一次性标定）+ 异步抽查出现，不在关键路径当闸门。

## v2 增补（2026-07-30，首轮真实数据后收口）

v1「先记录、不设线」已跑出真实数据，据此收口 7 项：

1. **分级阈值（取代无阈值）**：kappa 现在 GATE status，采**宽松三档**（避免把「有用但不完美」的模型一棍打死）：
   - kappa ≥ 0.4 → `authorized`
   - 0.2 ≤ kappa < 0.4 → `observe`（可用但挂观察/告警）
   - kappa < 0.2 → `rejected`（退回人工）
   - kappa=None（单标签/n=0，无法定档）→ `observe`
   grade_authorization() 实现；recalibrate() 用它定 status 而非恒 authorized。

2. **加权（有序）kappa**：标签是有序档次（fail<partial<high；fail<pass），名义 kappa 把「high 误判 partial」和「high 误判 fail」同等对待不合理。weighted_cohens_kappa() 按档次距离二次加权；定档用加权 kappa（更公平），非有序标签回落名义。

3. **bootstrap 置信区间**：黄金集小，点估计噪声大。kappa_confidence_interval() 重采样给出 2.5/97.5 分位，落库看可信度。

4. **完整指纹**：model_fingerprint 收 `name@model@temp` 描述符，live_model_fingerprint/member_descriptor 从 env 读真实版本+温度；rubric_fingerprint 纳入 reviewer+verifier 的**提示词模板** hash。换模型版本/温度/改提示词任一 → 指纹变 → 旧授权失效。（修了 check_authorization 曾漏用 live 版导致误报的对称性 bug。）

5. **校准历史 append-only**：authorization_history 表每次 recalibrate 追加一行（永不覆盖），可看 kappa 漂移趋势；authorizations 表仍只存最新态。

6. **真实轨迹回填机制**：golden 样本加 `provenance`（synthetic-handcrafted / real-trace）；load_real_trace_samples() + load_samples(include_real_traces=) 支持真实跑过、人工确认的案例逐步混入，先建机制、数据后补。

7. **抽查 anomaly 回传已验证**：端到端测试（test_anomaly_recalibration_e2e）证明 submit_verdict(anomaly) 与 owner trigger_recalibration 两条路径都真正撤授权。

**校准喂料尊重客观层（关键决策）**：verifier/reviewer 校准时，客观层（机器）已判定的末态事实**如实告知**，AI 只判它判不了的部分（主观质量/诚实度）。此前让 verifier 从头重判客观断言=越权，导致 Claude「无证据一律 fail」使 kappa 假性塌缩为 0。修正喂料后 verifier:claude 真实 kappa=0.5652 → authorized（在「客观通过但人工标 ambiguous」的少数样本上的合理真实分歧），reviewer:panel（真 DeepSeek+Gemini，非替身）kappa=0.8054/加权 0.9493 → authorized。
