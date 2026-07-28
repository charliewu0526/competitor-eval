# T7-wechat-dirty-roster-001

Capability domain: **wechat-im** · Task nature: **dirty-data**

## Scenario
You are given a messy contact list in input/roster.txt (names with typos, duplicates, and trailing spaces). Send '会议改到明天上午10点' to every UNIQUE real contact that matches someone in your WeChat. Skip unmatched/garbage entries.

## Notes
This task is part of the auto-seeded task bank (scripts/gen_tasks.py). The
neutral standard prompt (below, ADR-0016) is what every product receives — no
product-specific syntax. End-state assertions live in `tasks.T7_wechat_dirty_roster_001`.

## Dirty data (铁律: 材料可假, 脏数据必真)
- duplicate names in roster
- names with trailing whitespace
- typo'd names with no WeChat match
- empty lines

