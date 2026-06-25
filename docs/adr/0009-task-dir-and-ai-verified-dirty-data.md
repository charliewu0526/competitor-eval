# ADR-0009 — 任务库目录结构 + 脏数据声明制 + AI核验/人抽查

- 状态：已接受
- 日期：2026-06-25
- 关联：ADR-0002/0003（TaskSpec 字段）、ADR-0004（证据喂 S5）、ADR-0011（黄金集授权）

## 决策

### 目录结构（采纳原始设计 + 三个接口）

```
Task-XXX/
  README.md  prompt.md
  meta.json              ← 机器入口：task_id, tier, kind, app,
                            requires_local_desktop, core_assertions,
                            dirty_data_level_suggested / dirty_data_level
  input/                 ← AI 生成材料包
  expected/              ← 标准答案（最重要）
    answer_key.* / expected_structure.md / known_edge_cases.md
  output/                ← 竞品产出
  evidence/end-state/    ← 末态证据 → 客观层
  evidence/process/      ← 过程证据 → S5 体验分
  scoring.md
```

人读 `.md`，机器读 `meta.json`，两套并存。

### 脏数据：声明制（不是机械必填）

- `meta.json` 必含 `dirty_data_level: none | light | heavy`。
- 声明 `light/heavy` → `known_edge_cases.md` 必填，坑数配等级。
- 声明 `none` → 放行，但记录「此题不测脏数据」。
- **与 tier 交叉校验**：声明 `stress` 却 `dirty_data_level=none` → 矛盾报警。

### 谁定等级：AI 建议 + 独立 AI 核验自动放行 + 人异步抽查

- 出题 AI 输出 `dirty_data_level_suggested` + 候选坑清单（草稿）。
- **独立核验 AI**（与出题用不同模型，不能自评）核对坑真实性/等级 → 放行即自动入库，**不阻塞等人**。
- `suggested ≠ final` 的差值记录，作为「AI 出题靠谱度」信号。
- 人退到路径外，做异步抽查（比例见 ADR-0011），不在关键路径上当闸门。
- **唯一不可砍的人类锚点：黄金集（ADR-0011）** —— 否则 AI 集体漂移无人察觉。

## 后果

- 立身之本一致：AI 自报不算数（呼应 ADR-0004），核验必须第三方。
