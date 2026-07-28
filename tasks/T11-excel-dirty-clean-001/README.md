# T11-excel-dirty-clean-001

Capability domain: **office-suite** · Task nature: **dirty-data**

## Scenario
Open input/expenses.csv. It has inconsistent date formats, some amounts stored as text with currency symbols, blank rows, and a duplicated header mid-file. Clean it and produce output/expenses-clean.xlsx with a correct SUM of all amounts in cell B1.

## Notes
This task is part of the auto-seeded task bank (scripts/gen_tasks.py). The
neutral standard prompt (below, ADR-0016) is what every product receives — no
product-specific syntax. End-state assertions live in `tasks.T11_excel_dirty_clean_001`.

## Dirty data (铁律: 材料可假, 脏数据必真)
- mixed date formats (YYYY-MM-DD vs DD/MM/YYYY)
- amounts as text with '¥' / ',' 
- blank rows scattered
- a duplicated header row in the middle

