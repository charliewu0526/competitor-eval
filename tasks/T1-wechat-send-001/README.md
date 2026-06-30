# T1 — WeChat send (sample task)

> Human-readable overview. The machine-readable single source is `meta.json`.

**Task id:** `T1-wechat-send-001`
**Domain:** 1 (closed-source desktop app operation)
**App:** WeChat · **Tier:** core-common · **Kind:** task-exam

## Goal
The thinnest pilot task used to prove the pipeline end-to-end: send one exact
WeChat message to one named contact, touching no one else.

WeChat exposes no public desktop-send API, so a cloud-only agent GATEs as
`cannot-reach`; Vio and rivals must operate the GUI directly. The end-state
lives inside a closed app and cannot be read by a script — the primary-goal
assertion is therefore a **human-verified** flag dropped into the RunRecord.

## Directory layout (X1 standard)
| Path | For | Contents |
|------|-----|----------|
| `README.md` | human | this overview |
| `prompt.md` | human | the exact instruction handed to each product |
| `meta.json` | **machine** | single source of truth; `task_spec` mirrors F1 TaskSpec |
| `scoring.md` | human | how this task is judged (assertions → score) |
| `input/` | both | starting materials given to the product (may be faked) |
| `expected/` | both | the correct end-state description / golden artifact |
| `output/` | both | per-run product artifacts land here |
| `evidence/` | both | logs / screenshots / recordings backing each run |

## Dirty-data declaration
`dirty_data_level = none` (final, set by a human). This pilot uses a clean,
unambiguous instruction on purpose — the dirty-data regime is exercised by
later stress-tier tasks. See `meta.json → dirty_data` for provenance.
