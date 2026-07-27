# Prompt (handed verbatim to each product)

Go to the page at `input/target-url.txt`. Find the three most recent article
titles listed on that page and save them, one per line and in top-to-bottom
order, to a plain text file named `titles.txt`.

---
Notes for the operator (not part of the prompt):
- "Three most recent" = the first three items in the page's own listing order
  (top to bottom). Do not reorder or dedupe beyond what the page shows.
- Each title on its own line, exact text, no numbering / bullets added.
- Read-only: do not submit forms, log in, or change anything on the page —
  any such action is a destructive side-effect.
