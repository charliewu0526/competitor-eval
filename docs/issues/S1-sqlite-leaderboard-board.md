# [S1] SQLite 单一数据源 + 排行榜 + 看板自动渲染

Label: ready-for-agent
Covers user stories: 28, 29

## What to build
数据存 SQLite 单一数据源（runs / scores / findings 等表），看板从库自动渲染，不再手维护 Markdown。`compute_gap(vio, comp)`（两方）升级为 `leaderboard(baseline, rivals[])`：一基线 vs N 竞品 → 排名 + 按题矩阵 + honesty 独立列。看板同时展示能力分排行榜和 honesty 列，使「危险的强」和「可信的弱」一眼可辨。

**范围升级（2026-06-25 PM 决定）**：看板形态从「只导出静态 Markdown」升级为 **Streamlit 本地 Web 看板**——`streamlit run` 起一个本地页面，PM 可一眼看排行榜 + honesty 列 + 发现列表，并**在「发现」行内直接编辑「产品判断 / 最终分类」字段写回 SQLite**（取代手填数据库的反人类操作）。Markdown/HTML 导出降级为附带能力（分享/留档用）。不违背「人当路径外抽查员」哲学——恰恰让抽查不痛苦。纯本地、单文件 SQLite、无需账号/部署。完整前后端（React+API）仍推迟到 v2 规模化后。

## Acceptance criteria
- [ ] SQLite schema：runs/scores/findings 表建好，写入/读取通过
- [ ] leaderboard(baseline, rivals[]) 输出排名 + 按题矩阵 + honesty 列
- [ ] cannot-reach 竞品不出现在排行榜（与 E1 对齐）
- [ ] Streamlit 本地看板：`streamlit run` 起页面，展示排行榜 + honesty 列 + 发现列表
- [ ] 发现行内可编辑「产品判断 / 最终分类」并写回 SQLite（PM 无需手改数据库）
- [ ] 看板从库渲染，可附带导出 md/html，无需手改文件
- [ ] honesty 作为独立列展示，不并入能力分

## Blocked by
- E1
- E3
- E4
- E5

## Prior art
pipeline/board.py —— 当前输出 Markdown；把权威源挪到 SQLite，board 改为从库渲染。
