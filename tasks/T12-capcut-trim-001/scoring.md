# Scoring — T12-capcut-trim-001

Objective assertions (end-state facts, per立身之本 — not self-report):

- primary: exported video file exists
- primary: the clip is trimmed to 00:05-00:20
- secondary: export is 1080p

Primary-goal failures gate the whole run. Machine-verifiable assertions are
auto-judged from artifacts/logs; human-only end-states are ticked by the
trained runner and re-checked on spot-check.
