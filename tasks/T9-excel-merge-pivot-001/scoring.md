# Scoring — T9-excel-merge-pivot-001

Objective assertions (end-state facts, per立身之本 — not self-report):

- primary: output workbook was produced
- primary: all 12 months are merged with no rows lost
- primary: pivot shows revenue by region x quarter

Primary-goal failures gate the whole run. Machine-verifiable assertions are
auto-judged from artifacts/logs; human-only end-states are ticked by the
trained runner and re-checked on spot-check.
