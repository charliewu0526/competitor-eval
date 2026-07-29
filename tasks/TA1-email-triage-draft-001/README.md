# TA1 — 邮件三分类 + 起草回复（assistant-integration / dirty-data）

对标 Town 核心卖点：收件箱三分类 + 按用户语气起草回复、审批优先不自动发。

- **能力域**：assistant-integration（云端/API 集成，非本地 GUI 操控）
- **任务性质**：dirty-data（混入冷邮件/营销诱导误判）
- **tier**：stress
- **requires_local_desktop**：false → 云端产品（Town）判 `api-or-integration` 跨层轨；vio 判 `native-operable`

## 立身之本
只认末态事实：分类结果看 `output/triage.json`，草稿看 `output/drafts/`，是否误发看审批日志/截图。不信产品自述完成。

## 文件
- `input/inbox/`：10 封待分类邮件
- `input/voice-sample.txt`：用户既往语气样本
- `expected/end-state.md`：正确三分类 + 应起草回复清单
- `output/`：triage.json + drafts/
- `evidence/`：日志/截图
