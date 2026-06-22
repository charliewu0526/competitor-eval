# Vio User Scenario Constitution — v0

> Status: **v0 = assumption-driven**. Built from 3-source triangulation (PM intuition + competitor marketing + Vio public positioning), NOT yet from telemetry/interviews.
> Graduation to v1: after first telemetry batch OR >=10 user interviews, ratios move from "guessed" to "measured".
> Date: 2026-06-22. Phase A Step 0 deliverable.

## Source legend
- 🟢 high — appears across all three sources (PM + competitors + Vio official)
- 🟡 medium — strong on some sources, gap on others
- 🟠 special — Vio-unique, little/no competitor benchmark possible

## The key bet (read first)
Vio's moat = operating **closed-source, no-API desktop apps**, **locally**, **proactively**, for **long unattended tasks**. The benchmark must test these as first-class axes — otherwise gaps systematically over-credit cloud competitors and under-credit Vio. A new capability axis is added on top of every scenario: **"no-API operability"** (can the competitor even do this without an API/integration?).

## Scenario domains + placeholder mix

### Core layer (~70%, fixed across versions — comparability baseline)
| # | Scenario domain | Weight (placeholder) | Source | Confidence | Why it's core |
|---|---|:---:|---|:---:|---|
| 1 | Closed-source desktop app operation (WeChat, CapCut, QuickBooks, ERP) | ~25% | Vio-official + PM | 🟢 | Vio's primary moat — must test |
| 2 | Office artifact production (Word/Excel/PPT, incl. invoice entry, weekly reports) | ~25% | all three | 🟢 | Universal + Vio-advertised |
| 3 | Long-running / 24-7 unattended tasks (overnight batch) | ~15% | Vio-official + PM | 🟢 | Vio differentiation |

### Frontier layer (~30%, rolling — tracks competitors & weak zones)
| # | Scenario domain | Weight (placeholder) | Source | Confidence | Why it's frontier |
|---|---|:---:|---|:---:|---|
| 4 | Web research / multi-step info synthesis | ~20% | competitor #1 (10/12) | 🟡 | **KEY TEST** — competitors' strongest area, Vio's weak zone; elevated by PM as priority despite being a gap-front, because roadmap needs this signal |
| 5 | Proactive automation suggestion | ~10% | Vio-unique | 🟠 | **SPECIAL** — see handling below |

## Special handling: domain #5 (proactive suggestion)
Almost no competitor markets this. Do NOT score it head-to-head (no comparable). Instead treat it as a **moat-monitoring sentinel**: each eval cycle, check whether ANY competitor has started shipping proactive/screen-observing suggestion. If yes -> raise an alert (moat erosion), don't compute a score. Its 10% weight funds the monitoring, not a comparison.

## Out of v0 (explicitly excluded for now)
- Shopping/booking, phone calls, website-building, CRM/sales, coding — high across competitors but NOT in Vio's stated user base (geeks + small-B: design studios, film/TV, real-estate, cross-border e-commerce). Revisit if v1 telemetry shows real usage.

## Open items blocking v1
1. Golden-set curator: PM alone vs PM+QA/eng (still unowned).
2. Borrowable-feature -> roadmap intake mechanism (the "last mile", still unowned).
3. Real ratios — current weights are placeholders pending data.
