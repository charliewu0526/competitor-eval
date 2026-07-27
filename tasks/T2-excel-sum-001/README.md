# T2 — Excel column sum (office-suite pilot)

> Human-readable overview. The machine-readable single source is `meta.json`.

**Task id:** `T2-excel-sum-001`
**Domain:** 1 (closed-source desktop app operation)
**App:** Excel · **Tier:** core-common · **Kind:** task-exam
**能力域:** office-suite (办公套件)

## Goal
A thin office-suite pilot: open a workbook, drop the sum of one column range
into one cell, save. Proves the pipeline handles a file-producing desktop task
(`expects_file = true`) in a different capability domain than the WeChat pilot.

## Prompt (neutral, ADR-0016)
> Open the workbook `input/sales.xlsx`. In sheet `Q1`, put the total of column
> C (rows 2 through 13) into cell C14, then save the file. Do not change any
> other cell.

The instruction is product-neutral: no Excel-macro / product-specific syntax,
so every product (Violoop or rival) gets the same words — no home-turf advantage.

## Directory layout (X1 standard)
| Path | For | Contents |
|------|-----|----------|
| `README.md` | human | this overview |
| `prompt.md` | human | the exact instruction handed to each product |
| `meta.json` | **machine** | single source of truth; `task_spec` mirrors F1 TaskSpec |
| `scoring.md` | human | how this task is judged (assertions → score) |
| `input/` | both | `sales.xlsx` starting workbook (may be faked) |
| `expected/` | both | correct end-state description |
| `output/` | both | per-run saved workbook lands here |
| `evidence/` | both | logs / screenshots per run |

## Dirty-data declaration
`dirty_data_level = none` (final, human-set). Clean by design; merged cells /
hidden rows / text-as-number traps belong to a later stress-tier task. See
`meta.json → dirty_data` for provenance.
