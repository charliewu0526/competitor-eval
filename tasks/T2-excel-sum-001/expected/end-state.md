# Expected end-state — T2 Excel column sum

After the task, the saved workbook must satisfy:

- Sheet `Q1`, cell **C14** = the exact arithmetic sum of `C2:C13`.
- Every other cell holds its original value (no collateral edits).
- The file is saved so an artifact exists under `output/`.

The value in C14 is what's judged — whether it's a live `=SUM(C2:C13)` formula
or a pasted number is irrelevant to pass/fail.
