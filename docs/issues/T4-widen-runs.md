# [T4] Widen to multiple runs (variance + long-task checkpoints)

Label: ready-for-agent
Covers user stories: 6

## What to build
Add repetition handling: short tasks run 3x for mean+variance; long tasks use few-runs + checkpoint scoring instead of N-times variance.

## Acceptance criteria
- [ ] Short tasks executed 3x; mean + variance computed
- [ ] Long tasks scored via checkpoints, not full repetition
- [ ] Variance surfaced on the board alongside the gap number

## Blocked by
- T3
