# T10-excel-schedule-report-001

Capability domain: **office-suite** · Task nature: **scheduled**

## Scenario
Set up a task that, on the last day of each month, opens input/ledger.xlsx, recalculates the monthly summary sheet, and exports it to output/monthly-report.pdf.

## Notes
This task is part of the auto-seeded task bank (scripts/gen_tasks.py). The
neutral standard prompt (below, ADR-0016) is what every product receives — no
product-specific syntax. End-state assertions live in `tasks.T10_excel_schedule_report_001`.

