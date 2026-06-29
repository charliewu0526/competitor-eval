"""S1: leaderboard — one baseline vs N rivals -> ranking + per-task matrix + honesty.

Upgrades compute_gap(vio, comp) (two-party) to leaderboard(baseline, rivals[]).
Pure function over score dicts (works on either score_run() output or store rows),
no DB/network dependency so it is unit-testable in isolation.

Rules:
  * cannot-reach rows are NOT a fair head-to-head -> EXCLUDED from ranking
    (aligns with E1 / orchestrate: cannot-reach => scored=False). They are still
    reported under `excluded` so they don't silently vanish.
  * honesty (h1_honesty) travels as its OWN column, never mixed into the
    capability sample_score ranking. 「危险的强」(high capability, low honesty) and
    「可信的弱」(low capability, high honesty) stay distinguishable.
"""
from __future__ import annotations


def _is_cannot_reach(s: dict) -> bool:
    return s.get("gate") == "cannot-reach" or s.get("reason") == "cannot-reach"


def _cap(s: dict) -> float:
    v = s.get("sample_score")
    return float(v) if v is not None else 0.0


def leaderboard(baseline: str, scores: list[dict]) -> dict:
    """Build the leaderboard from a flat list of per-(task,product) score dicts.

    Returns:
      ranking: [{product, is_baseline, avg_capability, honesty_avg, n_tasks,
                 vs_baseline}]  sorted by avg_capability desc (baseline included)
      matrix:  {product: {task_id: {sample_score, h1_honesty, scored, reason}}}
      tasks:   sorted task id list (matrix columns)
      excluded:[{product, task_id, reason}]  cannot-reach / unscored rows
    """
    matrix: dict[str, dict[str, dict]] = {}
    excluded: list[dict] = []
    tasks: set[str] = set()

    for s in scores:
        prod, task = s["product"], s["task_id"]
        if _is_cannot_reach(s):
            excluded.append({"product": prod, "task_id": task,
                             "reason": "cannot-reach"})
            continue
        tasks.add(task)
        matrix.setdefault(prod, {})[task] = {
            "sample_score": s.get("sample_score"),
            "h1_honesty": s.get("h1_honesty"),
            "scored": bool(s.get("scored", True)),
            "reason": s.get("reason"),
        }

    # Per-product aggregates over the tasks it actually competed on.
    ranking = []
    for prod, by_task in matrix.items():
        caps = [_cap({"sample_score": c["sample_score"]})
                for c in by_task.values()]
        honesties = [c["h1_honesty"] for c in by_task.values()
                     if c["h1_honesty"] is not None]
        avg_cap = round(sum(caps) / len(caps), 4) if caps else 0.0
        honesty_avg = round(sum(honesties) / len(honesties), 2) if honesties else None
        ranking.append({
            "product": prod,
            "is_baseline": prod == baseline,
            "avg_capability": avg_cap,
            "honesty_avg": honesty_avg,       # SEPARATE column, never merged
            "n_tasks": len(by_task),
        })

    base_cap = next((r["avg_capability"] for r in ranking
                     if r["product"] == baseline), None)
    for r in ranking:
        r["vs_baseline"] = (round(r["avg_capability"] - base_cap, 4)
                            if base_cap is not None else None)

    # Rank by capability only; honesty stays an independent readable column.
    ranking.sort(key=lambda r: r["avg_capability"], reverse=True)
    for i, r in enumerate(ranking, 1):
        r["rank"] = i

    return {
        "baseline": baseline,
        "ranking": ranking,
        "matrix": matrix,
        "tasks": sorted(tasks),
        "excluded": excluded,
    }


def from_store(con, baseline: str = "vio") -> dict:
    """Convenience: build the leaderboard straight from the SQLite scores table."""
    from pipeline import store
    return leaderboard(baseline, store.all_scores(con))
