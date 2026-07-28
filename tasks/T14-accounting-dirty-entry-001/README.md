# T14-accounting-dirty-entry-001

Capability domain: **no-api-app** · Task nature: **dirty-data**

## Scenario
Open the desktop accounting app. Enter the vouchers from input/receipts/ (a folder of scanned receipts with inconsistent naming, some blurry, some duplicates). Enter each unique valid receipt once; flag the unreadable ones instead of guessing.

## Notes
This task is part of the auto-seeded task bank (scripts/gen_tasks.py). The
neutral standard prompt (below, ADR-0016) is what every product receives — no
product-specific syntax. End-state assertions live in `tasks.T14_accounting_dirty_entry_001`.

## Dirty data (铁律: 材料可假, 脏数据必真)
- inconsistent file naming
- blurry/unreadable scans
- duplicate receipts
- a non-receipt image mixed in

