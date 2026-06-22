# [T3] Widen to 3 competitors (execution harness)

Label: ready-for-agent
Covers user stories: 4, 7, 12, 13

## What to build
Extend the execution harness to run against all 3 Phase-A competitors: Simular Sai (same-layer), one cloud voice-of-market rep (Manus OR OpenAI Operator), Claude computer-use. Capture environment metadata each run; tag cross-layer comparisons; record the no-API-operability outcome.

## Acceptance criteria
- [ ] Harness runs a task on all 3 competitors + Vio
- [ ] Environment metadata captured per run (model version, date, params, prompt template)
- [ ] Cross-layer comparisons tagged `cross-layer (not same-condition)`
- [ ] no-API operability outcome recorded per competitor

## Blocked by
- T1
