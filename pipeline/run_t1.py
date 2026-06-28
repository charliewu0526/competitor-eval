"""End-to-end T1 driver. Consumes operator-filled RunRecords -> scores -> board.

Usage:
  python -m pipeline.run_t1 --demo     # dry-run with stub runs (no device/keys)
  python -m pipeline.run_t1            # read real runs from runs/*.json

A real run file is a JSON dict with: product, run_idx, gate, transcript_excerpt,
env_meta, and the human-verified assertion flags (msg_received, text_exact,
no_collateral), plus optional artifact_summary / screenshots_note.
"""
from __future__ import annotations
import sys, json, pathlib
from pipeline.schema import RunRecord
from pipeline import objective as O
from pipeline.orchestrate import score_run, compute_gap
from pipeline.board import render_board
from pipeline.registry import default_registry
from tasks.T1_wechat_send import TASK, assertions

ROOT = pathlib.Path(__file__).resolve().parent.parent
# F2: blind labels come from the registry (registration order), not hardcoded.
# Adding a competitor = edit registry/competitors.json, no code change here.
REGISTRY = default_registry()


def build_run(d: dict):
    asserts = assertions()
    res = O.run_assertions(asserts, d)
    rr = RunRecord(
        task_id=TASK.task_id, product=d["product"], run_idx=d.get("run_idx", 1),
        gate=d["gate"], objective_passed=res["passed"], objective_total=res["total"],
        objective_failed_primary=res["failed_primary"],
        transcript_excerpt=d.get("transcript_excerpt", ""), env_meta=d.get("env_meta", {}),
        claimed_success=d.get("claimed_success"),  # E4: feeds H1 honesty axis
        evidence_source=d.get("evidence_source", "unavailable"),  # E3: gates S5
        screenshots=d.get("screenshots", []),
    )
    ctx = {"artifact_summary": d.get("artifact_summary", "(none)"),
           "screenshots_note": d.get("screenshots_note", "(none)")}
    try:
        blind = REGISTRY.blind_label(d["product"])
    except KeyError:
        blind = "Product ?"  # not in registry yet -> unblinded placeholder
    return rr, score_run(TASK, rr, ctx, blind)


DEMO = [
    {"product": "vio", "run_idx": 1, "gate": "native-operable",
     "msg_received": True, "text_exact": True, "no_collateral": True,
     "transcript_excerpt": "opened WeChat, located 测试助手, typed message, sent.",
     "artifact_summary": "message visible in chat, timestamp present"},
    {"product": "simular", "run_idx": 1, "gate": "native-operable",
     "msg_received": True, "text_exact": False, "no_collateral": True,
     "transcript_excerpt": "opened WeChat, sent message with a typo (3pm->3点开 missing char)."},
]


def main():
    demo = "--demo" in sys.argv
    raw = DEMO if demo else [json.loads(p.read_text())
                             for p in sorted((ROOT / "runs").glob("*.json"))]
    if not raw:
        print("no run files in runs/ — use --demo or drop operator run JSONs first.")
        return
    evals, by_product = [], {}
    for d in raw:
        _, sc = build_run(d)
        evals.append(sc)
        by_product[sc["product"]] = sc.get("sample_score", 0.0) or 0.0
    competitor = next((k for k in by_product if k != "vio"), None)
    gap = compute_gap(by_product.get("vio", 0.0),
                      by_product.get(competitor, 0.0) if competitor else 0.0)
    out = render_board(gap, evals, str(ROOT / "board" / "domain1-board.md"))
    print(f"board -> {out}")
    print(json.dumps({"gap": gap, "evals": evals}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
