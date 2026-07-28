# T18-dedupe-dirty-001

Capability domain: **computer-control** · Task nature: **dirty-data**

## Scenario
The folder input/messy-dir/ has nested subfolders with duplicate files (same content, different names), empty folders, and .DS_Store junk. Produce a deduplicated flat copy in output/clean-dir/ keeping one copy of each unique file; remove junk.

## Notes
This task is part of the auto-seeded task bank (scripts/gen_tasks.py). The
neutral standard prompt (below, ADR-0016) is what every product receives — no
product-specific syntax. End-state assertions live in `tasks.T18_dedupe_dirty_001`.

## Dirty data (铁律: 材料可假, 脏数据必真)
- identical content under different filenames
- empty nested folders
- .DS_Store / Thumbs.db junk
- deeply nested structure

