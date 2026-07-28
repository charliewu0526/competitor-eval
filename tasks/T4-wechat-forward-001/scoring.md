# Scoring — T4-wechat-forward-001

Objective assertions (end-state facts, per立身之本 — not self-report):

- primary: the file was forwarded to '财务组'
- primary: it is the correct file '季度预算.xlsx'
- secondary: no other chat received the file

Primary-goal failures gate the whole run. Machine-verifiable assertions are
auto-judged from artifacts/logs; human-only end-states are ticked by the
trained runner and re-checked on spot-check.
