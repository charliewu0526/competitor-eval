# [T6] Sink: trend board + borrowable-feature exit + bug handoff

Label: ready-for-agent
Covers user stories: 14, 15, 16

## What to build
The output sink: a trend board showing the gap derivative per domain over version events; the two-lane borrowable-feature exit (Lane 1 user-visible -> differentiation gate, default reject; Lane 2 engineering -> ROI gate, default accept) emitting GitHub issues with a mandatory human gate (`ready-for-human`); and lightweight Vio-bug capture handed to Vio's existing tracker.

## Acceptance criteria
- [ ] Board shows gap-over-time (derivative), not just a snapshot
- [ ] Borrowable feature produces a 3-column GitHub issue through the correct lane
- [ ] Lane-1 items require human gate before any auto-development
- [ ] A Vio bug found in a run is captured lightweight + handed off (no status flow kept here)

## Blocked by
- T5
