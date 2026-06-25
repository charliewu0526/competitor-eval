# to-issues slice spec — PRD v2

> Source: docs/prd/0001-competitor-eval-system.md (v2, 32 user stories).
> Architecture: single test seam `RunRecord → 分数/发现/排行榜`, 5 adapters behind it.
> Each issue = independently claimable. Label `ready-for-agent` unless noted.
> Every issue file MUST have: title `# [ID] ...`, `Label:`, `Covers user stories:`, `## What to build`, `## Acceptance criteria` (checkboxes), `## Blocked by`, `## Prior art` (existing code to extend or "none — new").
> Filenames: `<ID>-<kebab>.md`.

## Phase P — prerequisites
- **P1** repo + gh env + labels + publish PRD. Label `ready-for-human`. Stories: —. Blocked by: none. Prior art: AGENTS.md describes gh issue tracker + 5 labels (needs-triage/needs-info/ready-for-agent/ready-for-human/wontfix); gh not installed locally → this unblocks publishing PRD+issues as GitHub issues.

## Phase F — foundation (blocks the seam)
- **F1** Schema: extend TaskSpec (`tier` 4-enum, `kind` task-exam/capability-probe, `requires_local_desktop`, `dirty_data_level` + `dirty_data_level_suggested`) and RunRecord (`cost_input_tokens/cost_output_tokens/cost_model_calls/cost_usd/cost_source`, `evidence_source`, `claimed_success`). Stories: 4,8,21,22,30,31,32. Blocked by: none. Prior art: pipeline/schema.py (extend, don't rewrite).
- **F2** Competitor registry adapter: `{id,display_name,can_operate_local_desktop:bool,is_open_source,repo,status}`; blind A/B/C auto-dispatched by registration order; real (file/DB) + in-memory fake. Stories: 1. Blocked by: F1. Prior art: none — new (5th adapter).

## Phase E — eval core (inside the seam, synthetic-RunRecord tested, NO API)
- **E1** GATE derivation: `competitor.can_operate_local_desktop × task.requires_local_desktop` → native-operable / cannot-reach at run time; cannot-reach auto-excluded from leaderboard (no unfair 0). Stories: 2,3. Blocked by: F1,F2. Prior art: none — new.
- **E2** Objective assertion layer: end-state hard judgment (msg actually sent); primary fail → sample_score=0 + skip subjective. Log never used for completion. Stories: 5,20. Blocked by: F1. Prior art: pipeline/objective.py (extend).
- **E3** Subjective aggregation: median aggregation of 3 scores, range≥2 → red disagreement flag; score-vs-defect split (defects ingested separately regardless of who caught them, never lowers score); S5 anchors 5/3/1 require process evidence. Stories: 6,7,10,11. Blocked by: F1. Prior art: pipeline/orchestrate.py (currently dual-AI; generalize).
- **E4** H1 honesty axis: `claimed_success` vs verified end-state → H1 1-5 (true+fail→1, admit-fail→4), independent of sample_score. Stories: 8. Blocked by: F1,E2. Prior art: runs/ OI case (claimed COMPLETE, obj=0) is the canonical fixture.
- **E5** Findings pre-classification: 5 deterministic if-then rules → suspected labels (疑似Bug/功能差距/体验借鉴/诚实警示), no evidence→not ingested; machine labels 现象 only, PM fills `产品判断`(必须补齐/值得借鉴/观察中/不适合)+最终分类; Vio-own failures auto-flow to Bug pipeline w/ repro+env+steps+evidence. Stories: 25,26,27. Blocked by: E2,E3. Prior art: none — new.

## Phase A — adapters (behind seam; each needs real + in-memory fake)
- **A1** Three-model review adapter: DeepSeek+GLM+Claude (两中一西) blind panel, each score + justification. Stories: 6,9. Blocked by: F1. Prior art: pipeline/review_client.py + review_prompt.py (currently Gemini+Claude via Bedrock; swap panel).
- **A2** Evidence capture adapter: priority log>auto-screenshot>recording(黑箱兜底); sets `evidence_source`; log feeds S5 process only. Stories: 7,19,22. Blocked by: F1. Prior art: none — new.
- **A3** Cost accounting adapter + standalone price table (per-M-token): records token/calls/usd + `cost_source`(self-report/proxy/unavailable). Stories: 21,22. Blocked by: F1. Prior art: none — new.
- **A4** AI verification adapter: generator≠verifier model (no self-eval), verify-pass → auto-ingest (non-blocking). Stories: 14,17. Blocked by: F1. Prior art: none — new.

## Phase S — storage + board
- **S1** SQLite single data source (runs/scores/findings tables) + leaderboard(baseline vs N rivals → ranking + per-task matrix + honesty column) + board auto-render (export md/html). Stories: 28,29. Blocked by: E1,E3,E4,E5. Prior art: pipeline/board.py (currently md; move source-of-truth to SQLite, render from it).

## Phase G — golden set & calibration (防漂移)
- **G1** Golden set: 20-30 human-labeled full-spectrum samples (success/fail/谎称完成/模糊) as trust anchor + regression fixtures. Stories: 13. Blocked by: E2,E3. Prior art: none — new.
- **G2** Golden-set authorization: reviewer/verifier must hit golden set first; compute Cohen's kappa (panel vs human); v1 record-only no hard threshold; bias offset recorded not auto-applied. Recalibration triggers: model version change / rubric change / anomaly sampling → authorization auto-void + re-calibrate. Stories: 12,14,15. Blocked by: G1,A1,A4. Prior art: none — new.
- **G3** Layered human sampling: random 10% normal / 100% contradictions / 100% high-risk; async, no per-step signoff gate. Stories: 16,18. Blocked by: S1. Prior art: none — new.

## Phase X — second path + task bank
- **X1** Task bank: fixed per-task dir (README/prompt/meta.json/input/expected/output/evidence/scoring; human reads md, machine reads meta.json); dirty_data_level declaration (none/light/heavy, heavy⇒known_edge_cases required, cross-check w/ tier); generator gives `_suggested`+candidate edge cases, human/verifier sets final, both values coexist. Stories: 30,31,32. Blocked by: F1. Prior art: tasks/T1_wechat_send.py (first task; formalize dir layout).
- **X2** Second path: PM-manual capability-probe (探针 task vs Vio counterpart on a rival selling point e.g. token-saving); open-source competitors get code-mechanism analysis (机理证据). Stories: 23,24. Blocked by: S1. Prior art: none — new.
