# [S1] SQLite 单一数据源 + 排行榜 + 看板自动渲染

Label: ready-for-agent
Covers user stories: 28, 29

## What to build
数据存 SQLite 单一数据源（runs / scores / findings 等表），看板从库自动渲染（可导出 Markdown/HTML），不再手维护 Markdown。`compute_gap(vio, comp)`（两方）升级为 `leaderboard(baseline, rivals[])`：一基线 vs N 竞品 → 排名 + 按题矩阵 + honesty 独立列。看板同时展示能力分排行榜和 honesty 列，使「危险的强」和「可信的弱」一眼可辨。

## Acceptance criteria
- [ ] SQLite schema：runs/scores/findings 表建好，写入/读取通过
- [ ] leaderboard(baseline, rivals[]) 输出排名 + 按题矩阵 + honesty 列
- [ ] cannot-reach 竞品不出现在排行榜（与 E1 对齐）
- [ ] 看板从库渲染，可导出 md/html，无需手改文件
- [ ] honesty 作为独立列展示，不并入能力分

## Blocked by
- E1
- E3
- E4
- E5

## Prior art
pipeline/board.py —— 当前输出 Markdown；把权威源挪到 SQLite，board 改为从库渲染。
