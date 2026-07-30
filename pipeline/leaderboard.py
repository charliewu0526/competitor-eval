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


def candidate_task_ids(tasks_dir=None) -> set[str]:
    """任务库里 provenance=auto-from-census 的 task_id 集合 (榜单隔离用)。

    这些题的 expected 是 AI 暂定基准、未经人核验, 拿它给所有产品打分会失真 ——
    故必须从公平主榜单剔除, 单列「自动生成候选题」区 (供人真跑核验后转正)。
    发现失败 (任务库不可读) => 空集 (宁可不隔离也不误伤, 如实降级)。
    """
    try:
        from pipeline import suite as SUITE
        return {t.task_spec.task_id for t in SUITE.discover_tasks(tasks_dir)
                if getattr(t.task_spec, "provenance", "human") == "auto-from-census"}
    except Exception:
        return set()


def from_store(con, baseline: str = "vio", *, tasks_dir=None) -> dict:
    """Convenience: build the leaderboard straight from the SQLite scores table.

    榜单隔离: provenance=auto-from-census 的候选题分数**不进公平排名** (它们的
    expected 是 AI 暂定基准), 单独收进返回结构的 `candidate_tasks` 段 (标注未核验),
    不静默消失。human 题走原公平主榜单逻辑不受影响。
    """
    from pipeline import store
    all_rows = store.all_scores(con)
    cand_ids = candidate_task_ids(tasks_dir)
    fair = [s for s in all_rows if s.get("task_id") not in cand_ids]
    cand = [s for s in all_rows if s.get("task_id") in cand_ids]
    board = leaderboard(baseline, fair)
    board["candidate_tasks"] = {
        "note": ("auto-from-census 候选题: expected 为 AI 暂定基准、未经人核验, "
                 "不进公平主榜单; 供人真跑核验后转正 human。"),
        "task_ids": sorted(cand_ids),
        "scores": cand,
    }
    return board
