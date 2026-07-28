# Scoring — T21-web-dirty-extract-001

Objective assertions (end-state facts, per立身之本 — not self-report):

- primary: products.csv was produced
- primary: all real products extracted, ads skipped
- secondary: missing ratings handled gracefully

Primary-goal failures gate the whole run. Machine-verifiable assertions are
auto-judged from artifacts/logs; human-only end-states are ticked by the
trained runner and re-checked on spot-check.
