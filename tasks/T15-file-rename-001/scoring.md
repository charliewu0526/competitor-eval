# Scoring — T15-file-rename-001

Objective assertions (end-state facts, per立身之本 — not self-report):

- primary: all jpgs renamed to the date pattern
- primary: sequence numbering is correct per day
- secondary: non-image files untouched

Primary-goal failures gate the whole run. Machine-verifiable assertions are
auto-judged from artifacts/logs; human-only end-states are ticked by the
trained runner and re-checked on spot-check.
