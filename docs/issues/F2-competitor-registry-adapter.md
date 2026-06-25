# [F2] 竞品登记表适配器（registry）

Label: ready-for-agent
Covers user stories: 1

## What to build
第 5 个适配器：竞品登记表。静态记录每个竞品 `{ id, display_name, can_operate_local_desktop:bool, is_open_source, repo, status }`。能力域第一版是布尔，结构预留未来升级为 `reachable_envs[]`。盲标 A/B/C 由登记顺序自动派发，不再硬编码。加竞品只改登记表、不改代码。

## Acceptance criteria
- [ ] 生产实现：从文件/DB 读登记表，返回竞品集
- [ ] 内存假实现：返回固定竞品集（测试用，不碰 IO）
- [ ] 两实现满足同一契约（同一接口测试同时跑过）
- [ ] 盲标 A/B/C 按登记顺序自动派发，新增竞品无需改代码
- [ ] 单测：加一个竞品 → 自动获得下一个盲标字母

## Blocked by
- F1

## Prior art
None — new（接缝后的第 5 个适配器）。
