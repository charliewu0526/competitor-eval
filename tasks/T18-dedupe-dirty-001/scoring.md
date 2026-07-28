# Scoring — T18-dedupe-dirty-001

Objective assertions (end-state facts, per立身之本 — not self-report):

- primary: each unique file kept exactly once
- primary: junk files removed
- secondary: no unique file lost

Primary-goal failures gate the whole run. Machine-verifiable assertions are
auto-judged from artifacts/logs; human-only end-states are ticked by the
trained runner and re-checked on spot-check.
