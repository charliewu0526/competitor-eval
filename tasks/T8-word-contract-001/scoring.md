# Scoring — T8-word-contract-001

Objective assertions (end-state facts, per立身之本 — not self-report):

- primary: output PDF file was produced
- primary: headings are styled and page numbers present
- secondary: content unchanged from the draft

Primary-goal failures gate the whole run. Machine-verifiable assertions are
auto-judged from artifacts/logs; human-only end-states are ticked by the
trained runner and re-checked on spot-check.
