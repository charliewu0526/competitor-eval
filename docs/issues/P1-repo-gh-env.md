# [P1] 仓库 + gh 环境就绪，发布 PRD v2

Label: ready-for-human
Covers user stories: —（基础设施）

## What to build
让本项目的 GitHub issue 追踪上线，这样 PRD v2 + 本批工单能发布并打标签。本机当前未装 `gh`，PRD 暂以文件为权威。需安装并认证 `gh`、建好 5 个分流标签、把 PRD 0001 发布为 issue。

## Acceptance criteria
- [ ] `competitor-eval/` 已是 git 仓库且有 GitHub remote
- [ ] `gh auth status` 显示已认证
- [ ] 5 个标签存在：needs-triage / needs-info / ready-for-agent / ready-for-human / wontfix
- [ ] PRD 0001（v2）发布为 issue 并打 `ready-for-agent`
- [ ] 本批 docs/issues/ 工单发布为 issue（保留 ID 前缀于标题）

## Blocked by
None — can start immediately

## Prior art
AGENTS.md 已定义 gh issue 追踪规范 + 5 个 canonical 标签；本工单只是把它落地。
