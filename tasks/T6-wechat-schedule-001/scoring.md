# Scoring — T6-wechat-schedule-001

Objective assertions (end-state facts, per立身之本 — not self-report):

- primary: a scheduled/timed send was set up
- primary: a schedule registration event exists in the log
- secondary: the message content is exactly correct

Primary-goal failures gate the whole run. Machine-verifiable assertions are
auto-judged from artifacts/logs; human-only end-states are ticked by the
trained runner and re-checked on spot-check.
