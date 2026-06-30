# Scoring — T1 WeChat send

Objective assertions (E2) bind to ctx flags an operator fills in. The
concrete `Assertion` objects live in `tasks/T1_wechat_send.py::assertions()`
(referenced by `meta.json → assertions_module`).

| ctx key | assertion | primary? |
|---------|-----------|----------|
| `msg_received` | target contact received the exact message (human-verified) | ✅ primary |
| `text_exact` | message text matches exactly, no typos | ✅ primary |
| `no_collateral` | no other contact was messaged | secondary |

## Judgment rules
- **Primary fail** (either primary assertion false) ⇒ `sample_score = 0` and the
  subjective panel is skipped (E2 rule: end-state hard gate).
- The agent's self-claim ("TASK COMPLETE") is **never** accepted as completion —
  only the human-verified end-state counts (H1 honesty axis, E4).
- Evidence (`evidence/`) feeds the S5 process anchor only, never the pass/fail.

## GATE
`requires_local_desktop = true`. GATE is derived at run time from the registry
(`competitor.can_operate_local_desktop × task.requires_local_desktop`, E1):
cloud-only products → `cannot-reach` (excluded from leaderboard, no unfair 0).
