# [T5] Golden-set calibration loop (kappa)

Label: ready-for-agent
Covers user stories: 8, 9

## What to build
Build the human-anchored golden set to 20-30 samples (AI proposes scores + rationale + disagreement flags; PM approves the recorded score). Roll-and-freeze the rubric after a 5-sample trial, then compute panel-vs-human kappa; iterate rubric if below threshold. Auto-surface reviewer disagreements.

## Acceptance criteria
- [ ] Rubric frozen after 5-sample trial alignment
- [ ] Golden set reaches 20-30 human-approved samples
- [ ] Cohen's kappa (panel vs human) computed and recorded
- [ ] Below-threshold triggers rubric revision + re-measure
- [ ] Reviewer-disagreement samples auto-surfaced

## Blocked by
- T2
- T3
- P3
