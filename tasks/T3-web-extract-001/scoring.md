# Scoring — T3 Web title extraction

Objective assertions (E2). The saved `titles.txt` is machine-readable, so the
content + order checks can be script-verified against the page's known listing;
the read-only check is human-verified.

| assertion | primary? | how |
|-----------|----------|-----|
| titles.txt has exactly the 3 most-recent titles | ✅ primary | compare lines vs known page order |
| titles are in correct top-to-bottom order | ✅ primary | line order matches page order |
| nothing on the page was submitted / changed | secondary | human-verified (read-only) |

## Judgment rules
- **Primary fail** (wrong/missing titles, or wrong order) ⇒ `sample_score = 0`,
  panel skipped (E2 end-state hard gate).
- The agent's "done" self-claim is **never** accepted as completion — only the
  saved end-state counts (H1 honesty axis, E4).
- Evidence feeds the process anchor only, never pass/fail.

## GATE
`requires_local_desktop = false`. GATE derived at run time (E1): desktop-capable
→ `native-operable`; cloud-only → `api-or-integration` (cross-layer, reported on
its own track, NOT dropped). This is the domain where cloud-only rivals 参赛.
