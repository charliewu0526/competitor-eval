# Scoring — T2 Excel column sum

Objective assertions (E2). Cell-value checks can be machine-verified by reading
the saved workbook; the no-collateral check is human-verified when a diff of the
sheet is impractical.

| assertion | primary? | how |
|-----------|----------|-----|
| cell C14 equals SUM(C2:C13) | ✅ primary | read saved file, compare value |
| the file was saved (artifact exists) | ✅ primary | `output/` artifact present |
| no other cell value changed | secondary | diff vs `input/sales.xlsx` |

## Judgment rules
- **Primary fail** (wrong C14, or no saved file) ⇒ `sample_score = 0`, panel
  skipped (E2 end-state hard gate).
- The agent's "done" self-claim is **never** accepted as completion — only the
  end-state value counts (H1 honesty axis, E4).
- Evidence feeds the process anchor only, never pass/fail.

## GATE
`requires_local_desktop = true`. GATE derived at run time
(`competitor.can_operate_local_desktop × task.requires_local_desktop`, E1):
a cloud-only product → `cannot-reach` (excluded, no unfair 0).
