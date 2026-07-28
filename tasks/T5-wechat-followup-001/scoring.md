# Scoring — T5-wechat-followup-001

Objective assertions (end-state facts, per立身之本 — not self-report):

- primary: all 3 contacts received the reminder
- primary: message text matches exactly for each
- secondary: no unintended contact was messaged

Primary-goal failures gate the whole run. Machine-verifiable assertions are
auto-judged from artifacts/logs; human-only end-states are ticked by the
trained runner and re-checked on spot-check.
