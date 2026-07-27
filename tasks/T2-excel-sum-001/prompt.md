# Prompt (handed verbatim to each product)

Open the workbook `input/sales.xlsx`. In sheet `Q1`, put the total of column C
(rows 2 through 13) into cell C14, then save the file. Do not change any other
cell.

---
Notes for the operator (not part of the prompt):
- C14 must equal the exact arithmetic sum of C2:C13 (a formula or a pasted value
  both count — the end-state value is what's judged, not how it got there).
- Save in place so the artifact exists in `output/`.
- Touching any other cell is a destructive side-effect and fails the
  no-collateral assertion.
