# Scoring — T19-web-form-001

Objective assertions (end-state facts, per立身之本 — not self-report):

- primary: confirmation screenshot was saved
- primary: the form was submitted successfully
- primary: fields match the profile data

Primary-goal failures gate the whole run. Machine-verifiable assertions are
auto-judged from artifacts/logs; human-only end-states are ticked by the
trained runner and re-checked on spot-check.
