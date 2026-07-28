# Scoring — T7-wechat-dirty-roster-001

Objective assertions (end-state facts, per立身之本 — not self-report):

- primary: each unique matched contact received the message
- primary: garbage/unmatched entries were skipped
- secondary: no duplicate messages sent to the same person

Primary-goal failures gate the whole run. Machine-verifiable assertions are
auto-judged from artifacts/logs; human-only end-states are ticked by the
trained runner and re-checked on spot-check.
