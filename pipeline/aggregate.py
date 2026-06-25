"""E3: subjective aggregation — median + disagreement flag + scoring/defect split.

Core seam-internal logic (no network). Given a panel of reviewer dicts
(each like {"S1":4,...,"justifications":{"S1":"...",...},"defects":[...]}),
produce robust medians, flag disagreement (range >= 2), collect defects
SEPARATELY from scores, and evidence-gate S5.

立身之本 here: a number with no justification is noise — it is dropped from
aggregation. And "找错" (defects) never lowers "打分" (scores): defects are
collected independently so DeepSeek's strictness shows up as a defect list,
not as a depressed sample_score.
"""
from __future__ import annotations
import statistics

CAPABILITY_DIMS = ("S1", "S2", "S3", "S4")
EXPERIENCE_DIM = "S5"
ALL_DIMS = CAPABILITY_DIMS + (EXPERIENCE_DIM,)
DISAGREEMENT_THRESHOLD = 2


def _justified(panelist: dict, dim: str) -> bool:
    """A score counts only if it is a real 1-5 int AND carries a justification.

    bool is rejected (True/False would sneak through `isinstance(int)`).
    """
    v = panelist.get(dim)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    if not (1 <= v <= 5):
        return False
    just = (panelist.get("justifications") or {}).get(dim)
    return bool(just and str(just).strip())


def valid_scores(panel: list[dict], dim: str) -> list[float]:
    return [float(p[dim]) for p in panel if _justified(p, dim)]


def aggregate_dim(panel: list[dict], dim: str) -> dict:
    """Median + disagreement over the JUSTIFIED scores for one dimension."""
    scores = valid_scores(panel, dim)
    if not scores:
        return {"median": None, "scores": [], "range": None,
                "flagged": False, "n": 0}
    rng = max(scores) - min(scores)
    return {
        "median": statistics.median(scores),
        "scores": scores,
        "range": rng,
        "flagged": rng >= DISAGREEMENT_THRESHOLD,
        "n": len(scores),
    }


def has_process_evidence(ctx: dict | None) -> bool:
    """S5 depends on process evidence; without it S5 must be None, not 0.

    Explicit ctx["has_process_evidence"] wins. Otherwise infer from
    evidence_source / transcript / screenshots. "拿不到" != "差".
    """
    ctx = ctx or {}
    if "has_process_evidence" in ctx:
        return bool(ctx["has_process_evidence"])
    if ctx.get("evidence_source") in ("log", "screenshot", "recording"):
        return True
    if (ctx.get("transcript_excerpt") or "").strip():
        return True
    if ctx.get("screenshots"):
        return True
    note = ctx.get("screenshots_note")
    if note and note != "(none)":
        return True
    return False


def collect_defects(panel: list[dict]) -> list[dict]:
    """Gather every defect any panelist raised — independent of scores.

    A defect can be a plain string or a dict {desc, dim?, severity?}.
    Whoever caught it, if it's there we keep it. This NEVER touches scores.
    """
    out: list[dict] = []
    for p in panel:
        by = p.get("panelist", "?")
        for d in (p.get("defects") or []):
            if isinstance(d, str):
                desc = d.strip()
                if desc:
                    out.append({"by": by, "desc": desc})
            elif isinstance(d, dict):
                desc = str(d.get("desc", "")).strip()
                if desc:
                    item = {"by": by, "desc": desc}
                    if d.get("dim"):
                        item["dim"] = d["dim"]
                    if d.get("severity"):
                        item["severity"] = d["severity"]
                    out.append(item)
    return out


def aggregate_subjective(panel: list[dict], ctx: dict | None = None) -> dict:
    """Full subjective aggregation across all dims + defect collection.

    Returns:
      per_dim: dim -> aggregate_dim result (S5 carries reason when ungated)
      medians: dim -> median (None when no valid scores / S5 ungated)
      disagreement_flagged: [dims with range >= threshold]
      defects: [collected defect dicts]
    """
    per_dim: dict[str, dict] = {}
    medians: dict[str, float | None] = {}

    for dim in CAPABILITY_DIMS:
        agg = aggregate_dim(panel, dim)
        per_dim[dim] = agg
        medians[dim] = agg["median"]

    # S5 experience is evidence-gated.
    if has_process_evidence(ctx):
        s5 = aggregate_dim(panel, EXPERIENCE_DIM)
    else:
        s5 = {"median": None, "scores": [], "range": None, "flagged": False,
               "n": 0, "reason": "no process evidence"}
    per_dim[EXPERIENCE_DIM] = s5
    medians[EXPERIENCE_DIM] = s5["median"]

    flagged = [d for d in ALL_DIMS if per_dim[d].get("flagged")]
    return {
        "per_dim": per_dim,
        "medians": medians,
        "disagreement_flagged": flagged,
        "defects": collect_defects(panel),
    }


def weighted_capability(medians: dict, dimensions) -> float | None:
    """Capability sample factor 0..1 from the S1-S4 medians.

    `dimensions` is review_prompt.DIMENSIONS [(code, name, weight), ...].
    Only non-None capability dims contribute; their weights are RE-NORMALIZED
    so a missing dim doesn't silently deflate the score. Returns None when no
    capability dim has a valid median. S5 is NOT part of the capability score.
    """
    contrib = [(w, medians[c]) for c, _, w in dimensions
               if c in CAPABILITY_DIMS and medians.get(c) is not None]
    if not contrib:
        return None
    wsum = sum(w for w, _ in contrib)
    if wsum <= 0:
        return None
    weighted = sum(w * v for w, v in contrib) / wsum  # 1..5
    return (weighted - 1) / 4  # -> 0..1
