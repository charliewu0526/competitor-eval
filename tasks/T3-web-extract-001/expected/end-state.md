# Expected end-state — T3 Web title extraction

After the task, an artifact `titles.txt` exists under `output/` and satisfies:

- Exactly three lines, each one article title (exact text from the page).
- The three titles are the page's three most-recent items, in the page's own
  top-to-bottom listing order.
- No extra numbering, bullets, blank lines, or trailing commentary.
- The page itself is unchanged (task is read-only).

For the current material (`input/articles.html`, newest-first listing), the
correct three lines are:

```
Edge NPU Benchmarks: What Changed in 2026
Choosing Between Postgres and SQLite for Embedded Apps
Three Async Pitfalls Every Rust Team Hits
```
