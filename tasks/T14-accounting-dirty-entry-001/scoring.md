# Scoring — T14-accounting-dirty-entry-001

Objective assertions (end-state facts, per立身之本 — not self-report):

- primary: each unique valid receipt entered exactly once
- primary: unreadable receipts were flagged not guessed
- secondary: no duplicate voucher entries

Primary-goal failures gate the whole run. Machine-verifiable assertions are
auto-judged from artifacts/logs; human-only end-states are ticked by the
trained runner and re-checked on spot-check.
