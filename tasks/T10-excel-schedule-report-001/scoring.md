# Scoring — T10-excel-schedule-report-001

Objective assertions (end-state facts, per立身之本 — not self-report):

- primary: a monthly schedule was registered in the log
- primary: the report generation steps are correct
- secondary: export target path is correct

Primary-goal failures gate the whole run. Machine-verifiable assertions are
auto-judged from artifacts/logs; human-only end-states are ticked by the
trained runner and re-checked on spot-check.
