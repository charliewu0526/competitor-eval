# [E1] GATE 层级推导（能力域 × 任务要求）

Label: ready-for-agent
Covers user stories: 2, 3

## What to build
GATE 层级不钉死在竞品身上，而是跑测时由 `competitor.can_operate_local_desktop × task.requires_local_desktop` 推导出 native-operable / cannot-reach。cannot-reach 的竞品自动标「不参与该题公平对比」、不入排行榜，避免拿冤枉 0 分混进榜。这是接缝内核心逻辑，纯合成 RunRecord 测，不碰 API。

## Acceptance criteria
- [ ] 合成：能力域=false + 本地桌面题 → cannot-reach，且被排除出 leaderboard
- [ ] 合成：能力域=true + 本地桌面题 → native-operable，正常参与
- [ ] cannot-reach 不产生 sample_score=0 的「假失败」记录
- [ ] 同一竞品在「需桌面」和「不需桌面」两题上推导出不同层级

## Blocked by
- F1
- F2

## Prior art
None — new。注意区分：tier 解决「定位差异」不公平，GATE 解决「够不到」不公平，二者不同。
