# Scoring — T17-cleanup-schedule-001

Objective assertions (end-state facts, per立身之本 — not self-report):

- primary: a daily schedule was registered in the log
- primary: deletion criteria (>7 days) is correct
- secondary: it logs removed files

Primary-goal failures gate the whole run. Machine-verifiable assertions are
auto-judged from artifacts/logs; human-only end-states are ticked by the
trained runner and re-checked on spot-check.
