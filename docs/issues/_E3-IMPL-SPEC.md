# E3 (#16) 实现规格 — 主观聚合：中位数 + 分歧标红 + 打分/找错分家

> 给实现会话的精确规格。只读本文件 + 下列既有代码即可，无需历史对话。
> 接缝内核心逻辑，合成测，**绝不联网**（评审面板换内存假实现）。

## 既有代码（先读）
- `pipeline/orchestrate.py` —— 当前 `score_run` 用双 AI（gemini+claude）+ **均值**聚合，dims=S1..S4。要升级。
- `pipeline/review_prompt.py` —— `DIMENSIONS`(S1 0.4/S2·S3·S4 0.2) + `build_prompt` + `weighted_subjective`。
- `pipeline/review_client.py` —— `review_gemini/review_claude` + `_stub`（dry-run）。
- `pipeline/schema.py` —— RunRecord 有 `screenshots/transcript_excerpt/evidence_source`。
- `tests/test_objective_e2.py`、`tests/test_h1_honesty_e4.py` —— 测试风格基准 + 它们的 fake panelist（需同步更新，见下）。
- `pipeline/board.py`、`pipeline/run_t1.py` —— 下游消费者（需 None-safe）。

## 要交付的行为（issue #16 验收）
1. **中位数聚合**：每维取 valid 分的 median（稳健，抗单个离群评审）。`[5,4,1] → 中位数 4`。
2. **分歧标红**：每维 range(max−min) ≥ 2 → flagged。`[5,4,1] range=4 ≥2 → flagged`。
3. **打分/找错分家**：任一评审提的缺陷(defect)**单独入库**，无论谁抓到、只要有效就记，**绝不改变 sample_score**（兑现 DeepSeek「严」的价值）。
4. **justification 校验**：主观分缺 justification → 该分**视为无效**，从聚合中剔除（无理由的数字是噪声）。
5. **S5 体验**：锚点 5(全程可知可控)/3(有黑箱)/1(完全黑箱)，**依赖过程证据**；无过程证据 → S5 = **None（空，不是 0）**。「拿不到」≠「差」。
6. **聚合对 2 个 / 3 个评审分都成立**（泛化 N 模型，不再钉死 2 个）。

## 设计决定（已拍板，照做）
- **新建 `pipeline/aggregate.py`** 放纯聚合逻辑（E3 核心，可独立单测）。orchestrate 只负责接线。
- **capability sample_score 权重仍只用 S1–S4**（review_prompt.DIMENSIONS，和为 1.0）。**S5 中位数作为独立体验轴上报**，不折进 sample_score（不臆造 S5 权重）。
- **panel 成员泛化但成员身份不属 E3**：DeepSeek/GLM/Claude 的真实 client 是 A1(#19) 的事。E3 只把聚合泛化成接受 N 个 panelist。**调用点用 call-time 名字解析**，保证 E2/E4 仍能 monkeypatch `orchestrate.review_gemini/review_claude`：
  ```python
  PANELISTS = ("review_gemini", "review_claude")  # A1 会扩成三模型
  def _run_panel(prompt): return [globals()[n](prompt) for n in PANELISTS]
  ```

## `pipeline/aggregate.py` 接口
- `CAPABILITY_DIMS=("S1","S2","S3","S4")`、`EXPERIENCE_DIM="S5"`、`DISAGREEMENT_THRESHOLD=2`
- `_justified(panelist, dim) -> bool`：分是数字(非 bool) 且 1≤v≤5 且 `justifications[dim]` 非空。
- `valid_scores(panel, dim) -> list[float]`：只取 justified 的分。
- `aggregate_dim(panel, dim) -> {median, scores, range, flagged, n}`；无 valid 分 → median=None,range=None,flagged=False,n=0。
- `has_process_evidence(ctx) -> bool`：优先看 `ctx["has_process_evidence"]`(显式)；否则 `evidence_source in (log/screenshot/recording)` 或 `transcript_excerpt` 非空 或 `screenshots` 非空 或 `screenshots_note` 非 "(none)"。
- `aggregate_subjective(panel, ctx=None) -> {per_dim, medians(dim->median), disagreement_flagged[list], defects[list]}`：S1–S4 直接聚合；S5 仅在 `has_process_evidence` 时聚合，否则 `{median:None,...,reason:"no process evidence"}`。
- `collect_defects(panel) -> [{by, desc, ...}]`：扫每个 panelist 的 `defects`（str 或 dict），独立于分数。
- `weighted_capability(medians, dimensions) -> float|None`：对 medians 中非 None 的 capability 维按权重**重归一**求 1..5，再映射到 0..1（`(v-1)/4`）；全 None → None。

## orchestrate.score_run 改造
- cannot-reach / objective_failed_primary 两条早退路径**保持不变**（sample_score=0、subjective=None；E2/E4 依赖）。
- 主观路径：`panel=_run_panel(prompt)` → `agg=aggregate_subjective(panel, ctx2)`，其中 `ctx2` 合并 ctx + `{transcript_excerpt, evidence_source, screenshots}` 来自 run。
- `cap=weighted_capability(agg["medians"], DIMENSIONS)`；`sample_score = round(objective_ratio*cap,4) if cap is not None else 0.0`。
- out 增加/保留：`subjective=agg["medians"]`、`subjective_detail=agg["per_dim"]`、`disagreement_flagged=agg["disagreement_flagged"]`、`defects=agg["defects"]`、`dry_run=any(...)`、`panel=panel`。保留 `scored=True`。

## 配套改动
- `review_prompt.build_prompt`：JSON 输出规格加 **S5**(1/3/5 锚点说明) 和 **`defects`:[一句话缺陷] 数组**；`justifications` 含 S1–S5。`weighted_subjective` 可留作兼容，但 orchestrate 改用 `weighted_capability`。
- `review_client._stub`：加 S5、给每维占位 justification（`"dry-run stub"`）、`defects:[]`，使 --demo 仍走通。
- `tests/test_objective_e2.py`、`tests/test_h1_honesty_e4.py` 的 `_fake_panelist`：给 S1–S4(及可选 S5) 补上 `justifications`（否则 E3 校验会判无效，破坏这两组测试）。改完两组测试须仍全绿。
- `pipeline/board.py`：`subj_norm` 对 None 安全（只对非 None capability 维求均值）；flags 增加 defect 数（如 `defects:2`）。
- `pipeline/run_t1.py`：`build_run` 的 ctx 传 `evidence_source/screenshots`（供 S5 判定）。DEMO 数据给个 `screenshots_note` 或 transcript 让 S5 可算（也保留一条无证据的用于演示 S5 空）。

## 新测试 `tests/test_subjective_e3.py`（合成、离线）
覆盖全部验收：
- `aggregate_dim([5,4,1]) → median 4, range 4, flagged True`；`[4,4] → median 4 range 0 不标红`。
- 2 个分 与 3 个分都能聚合（median 行为正确，如 `[5,3]→4`、`[5,4,1]→4`）。
- 缺 justification 的分被剔除：如 panel 有 3 个分但其中 1 个无 justification → 只用 2 个聚合。某维全部无 justification → median None。
- defect 分家：某 panelist 报 defect + 仍给高分 → defects 收集到、sample_score 不因 defect 下降（对比有/无 defect 两次 score_run，sample_score 相同）。
- S5：有过程证据 → S5 聚合出数；无过程证据 → S5 median None（**断言 is None，非 0**）。
- seam 级 `score_run`：用 `_SeamCase` 换 fake panelist，断言 `disagreement_flagged`、`subjective`、`defects`、`sample_score` 符合预期。
- OI 回归不被破坏（primary fail → sample_score 0、subjective None 仍成立）。

## 收尾
- 跑 `python -m unittest discover -s tests -v`，**全绿**（E2/E4/schema/E3 都要过）。
- 跑 `python -m pipeline.run_t1 --demo` 不报错、能出 board。
- 提交：`git add -A && git commit -m "E3 (#16): subjective median aggregation + disagreement flag + scoring/defect split + S5 evidence-gated"`。不要 push。
