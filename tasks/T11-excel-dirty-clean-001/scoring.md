# Scoring — T11-excel-dirty-clean-001

Objective assertions (end-state facts, per立身之本 — not self-report):

- primary: cleaned workbook was produced
- primary: SUM in B1 equals the correct total 48213.5
- secondary: dirty rows were correctly normalized

Primary-goal failures gate the whole run. Machine-verifiable assertions are
auto-judged from artifacts/logs; human-only end-states are ticked by the
trained runner and re-checked on spot-check.
