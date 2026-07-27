"""Generic task-exam driver: run ONE task's operator-filled RunRecords through
the seam -> scores -> findings -> board. Generalizes run_t1 to ANY task in the
bank via meta.json's assertions_module — no per-task driver needed.

Usage:
  python -m pipeline.run_task <task_id>
  python -m pipeline.run_task T1-wechat-send-001

Run files: runs/<task_id>/*.json (preferred), else runs/*.json (legacy T1 flat).
Each run JSON: product, run_idx, gate, the manual_check ctx flags,
claimed_success (H1 input!), transcript_excerpt, artifact_summary, ...
"""
from __future__ import annotations
import sys, json, pathlib, importlib
from pipeline.schema import RunRecord
from pipeline import objective as O
from pipeline.orchestrate import score_run, compute_gap
from pipeline.board import render_board
from pipeline import findings as FIND
from pipeline import store as STORE
from pipeline.registry import default_registry
from pipeline.gate import gate_for
from pipeline import taskbank as TB

ROOT = pathlib.Path(__file__).resolve().parent.parent
REGISTRY = default_registry()


def load_task(task_id: str):
    """Load (TASK, assertions_fn) via the task's meta.assertions_module."""
    tdir = ROOT / "tasks" / task_id
    TB.assert_valid(tdir)  # enforce layout + F1 schema before running
    meta = TB.load_meta(tdir)
    mod_name = meta.get("assertions_module")
    if not mod_name:
        raise SystemExit(f"{task_id}: meta.json has no assertions_module")
    mod = importlib.import_module(mod_name)
    return mod.TASK, mod.assertions


def resolve_gate(d: dict, TASK) -> str:
    """E1: derive gate from registry capability × task requirement, not self-report."""
    try:
        comp = REGISTRY.get(d["product"])
    except KeyError:
        return d["gate"]  # unregistered -> trust operator-provided gate
    return gate_for(comp, TASK)


def build_run(d: dict, TASK, assertions):
    res = O.run_assertions(assertions(), d)
    rr = RunRecord(
        task_id=TASK.task_id, product=d["product"], run_idx=d.get("run_idx", 1),
        gate=resolve_gate(d, TASK), objective_passed=res["passed"],
        objective_total=res["total"], objective_failed_primary=res["failed_primary"],
        transcript_excerpt=d.get("transcript_excerpt", ""), env_meta=d.get("env_meta", {}),
        claimed_success=d.get("claimed_success"),
        evidence_source=d.get("evidence_source", "unavailable"),
        screenshots=d.get("screenshots", []))
    ctx = {"artifact_summary": d.get("artifact_summary", "(none)"),
           "screenshots_note": d.get("screenshots_note", "(none)")}
    try:
        blind = REGISTRY.blind_label(d["product"])
    except KeyError:
        blind = "Product ?"
    return rr, score_run(TASK, rr, ctx, blind)


def _run_files(task_id: str) -> list[pathlib.Path]:
    """Prefer runs/<task_id>/*.json; fall back to legacy flat runs/*.json."""
    nested = ROOT / "runs" / task_id
    if nested.is_dir():
        return sorted(nested.glob("*.json"))
    return sorted((ROOT / "runs").glob("*.json"))


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m pipeline.run_task <task_id>")
    task_id = sys.argv[1]
    TASK, assertions = load_task(task_id)

    files = _run_files(task_id)
    raw = [json.loads(p.read_text()) for p in files]
    # legacy flat runs/ may hold other tasks' files — keep only this task's runs
    # (a run with no explicit task_id is assumed to belong to the requested task).
    raw = [d for d in raw if d.get("task_id", task_id) == task_id]
    if not raw:
        print(f"no run files for {task_id} — drop operator run JSONs in "
              f"runs/{task_id}/ first.")
        return

    evals, by_product, ev_map, runrecs = [], {}, {}, []
    for d in raw:
        rr, sc = build_run(d, TASK, assertions)
        evals.append(sc)
        runrecs.append(rr)
        by_product[sc["product"]] = sc.get("sample_score", 0.0) or 0.0
        ev_map[sc["product"]] = {
            "evidence_source": rr.evidence_source,
            "screenshots": rr.screenshots,
            "transcript_excerpt": rr.transcript_excerpt,
        }
    ev_map["_env"] = {"app": TASK.app, "domain": TASK.domain}
    competitor = next((k for k in by_product if k != "vio"), None)
    gap = compute_gap(by_product.get("vio", 0.0),
                      by_product.get(competitor, 0.0) if competitor else 0.0)
    found = FIND.classify(TASK.task_id, evals, ev_map)
    con = STORE.connect()
    STORE.persist_eval(con, runrecs, evals, found)
    con.close()
    out = render_board(gap, evals, str(ROOT / "board" / f"{task_id}-board.md"))
    print(f"board -> {out}  |  db -> {STORE.DEFAULT_DB}")
    print(json.dumps({"task_id": task_id, "gap": gap, "evals": evals,
                      "findings": [f.as_dict() for f in found]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
