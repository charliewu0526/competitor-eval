# T3 — Web title extraction (browser-web pilot)

> Human-readable overview. The machine-readable single source is `meta.json`.

**Task id:** `T3-web-extract-001`
**Domain:** 1 · **App:** browser · **Tier:** core-common · **Kind:** task-exam
**能力域:** browser-web (网页任务)

## Goal
A thin browser-web pilot: read a list page, extract the three most-recent
article titles in order, save them to a text file. Proves the pipeline handles
a web task in a third capability domain — and, crucially, one that does NOT
require a local desktop.

## GATE note — this domain reaches cloud agents too
`requires_local_desktop = false`. A web page is reachable via browser OR via a
cloud/API-only agent. So GATE (E1) derives:
- desktop-capable product → `native-operable` (fair head-to-head)
- cloud-only product → `api-or-integration` (**cross-layer**, reported on its
  own track — reachable, so NOT dropped as cannot-reach)

This is exactly why the catalog's per-task 参赛集 differs across domains: a
cloud-only rival that's `cannot-reach` on the WeChat task can still 参赛 here.

## Prompt (neutral, ADR-0016)
> Go to the page at `input/target-url.txt`. Find the three most recent article
> titles listed on that page and save them, one per line and in top-to-bottom
> order, to a plain text file named `titles.txt`.

## Directory layout (X1 standard)
| Path | For | Contents |
|------|-----|----------|
| `README.md` | human | this overview |
| `prompt.md` | human | the exact instruction handed to each product |
| `meta.json` | **machine** | single source of truth; `task_spec` mirrors F1 TaskSpec |
| `scoring.md` | human | how this task is judged |
| `input/` | both | `target-url.txt` — points to the local `articles.html`; `articles.html` — the list page (newest-first) |
| `expected/` | both | correct end-state description |
| `output/` | both | per-run `titles.txt` |
| `evidence/` | both | logs / screenshots per run |

## Dirty-data declaration
`dirty_data_level = none` (final, human-set). Clean by design; ad blocks,
infinite scroll, and mixed-order feeds belong to a later stress-tier task.
