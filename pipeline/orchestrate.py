"""T1 orchestrator: ties GATE -> objective -> subjective -> gap into one eval.

The agent EXECUTION step (running Vio / Simular on the real task) is NOT
automated here — it is performed by a human operator who drops a RunRecord
(gate, artifact path, screenshots, transcript excerpt, manual end-state flags)
into runs/. This orchestrator consumes those records and produces scores + gap.
"""
from __future__ import annotations
import statistics
from pipeline.review_prompt import build_prompt, weighted_subjective
from pipeline.review_client import review_gemini, review_codex


def score_run(task, run, ctx, blinded_label="Product ?") -> dict:
    """run: RunRecord (already has objective fields filled by objective.run_assertions)."""
    out = {
        "task_id": task.task_id, "product": run.product, "run_idx": run.run_idx,
        "gate": run.gate, "objective_ratio": run.objective_ratio,
        "objective_failed_primary": run.objective_failed_primary,
    }
    # GATE: cannot-reach -> not same-condition, no capability score
    if run.gate == "cannot-reach":
        out.update(scored=False, reason="cannot-reach", cross_layer=True)
        return out
    out["cross_layer"] = run.gate == "api-or-integration"
    # objective primary fail -> capability failure, skip subjective
    if run.objective_failed_primary:
        out.update(scored=True, subjective=None, sample_score=0.0,
                   reason="objective primary-goal failed")
        return out
    # subjective: dual-AI panel
    prompt = build_prompt(task.prompt, blinded_label,
                          ctx.get("artifact_summary", "(none)"),
                          ctx.get("screenshots_note", "(none)"),
                          run.transcript_excerpt or "(none)")
    panel = [review_gemini(prompt), review_codex(prompt)]
    dims = ["S1", "S2", "S3", "S4"]
    disagreement = {d: abs(panel[0].get(d, 3) - panel[1].get(d, 3)) for d in dims}
    flagged = [d for d, v in disagreement.items() if v >= 2]
    mean_scores = {d: statistics.mean([panel[0].get(d, 3), panel[1].get(d, 3)]) for d in dims}
    subj = weighted_subjective(mean_scores)
    out.update(scored=True, subjective=mean_scores, panel=panel,
               disagreement=disagreement, disagreement_flagged=flagged,
               dry_run=any(p.get("dry_run") for p in panel),
               sample_score=round(run.objective_ratio * subj, 4))
    return out


def compute_gap(vio_score: float, competitor_score: float) -> dict:
    return {"vio": vio_score, "competitor": competitor_score,
            "gap": round(vio_score - competitor_score, 4)}
