# ADR-0006 — 用 SQLite 单一数据源，看板自动渲染

- 状态：已接受
- 日期：2026-06-24

## 背景

初版设想用 Markdown 当看板。PM 反馈：手动更新 Markdown 费劲、数据量一大难看。

## 决策

第一版即用 **SQLite 作为单一数据源**（表：runs / findings / scores 等），**看板从库自动渲染**，不再手动维护看板文件。

## 理由

1. **零手动维护**：跑完评测脚本自动出表，消除 Markdown 实时更新的痛。
2. **真查询能力**：筛选/排序/聚合，数据量大也直观。
3. **为什么 SQLite 不是 MySQL/Postgres**：单文件、零部署、跟 git 走、Python 直读，对当前数据量是最佳点。

## 后果

- runs/*.json 仍可作为 operator 录入的原始输入，但聚合结果落 SQLite。
- 看板（排行榜/发现池）是 SQLite 的渲染视图（可导出 Markdown/HTML 给人看）。
- 代价：schema 演进时改库字段比改 Markdown 略麻烦，但 SQLite 改动几行可控。
