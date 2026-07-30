"""评测报告分析文字增量预跑 —— 评分落库后把 Claude 生成的分析文字按域/全局落缓存。

同 attribution_prefetch 的姿势: 分析文字(读最新 scores 调 Claude 4.6 sonnet)慢且花钱,
不能每次开报告页现算。本模块在评分落库后(_score_assignment_into_board 钩子)对:
  - 变化题所属能力域的 domain-summary(vio 优劣势总结)
  - 全局 matrix-reading(按题矩阵解读)
各跑一次并落 analysis_cache; fingerprint 未变(scores 没变)则跳过不重算(省钱)。
前端开页读缓存 -> 随任务完成实时刷新。引擎不可用/失败不影响已落库的评分。
"""
from __future__ import annotations

from pipeline import store as STORE
from pipeline import analysis_synth as AS
from pipeline import domain_board as DB
from pipeline import leaderboard as LB


def prefetch(con, baseline: str = "vio", *,
             only_tasks: list[str] | None = None,
             force: bool = False) -> dict:
    """增量预跑分析文字落缓存。

    only_tasks: 限定只刷这些 task 影响到的域(入库钩子传变化的题); None 则全量域。
    force: 忽略指纹全部重算(换模型/改口径后用)。
    返回 {domains_computed, domains_cached, matrix_computed, matrix_cached, skipped}。
    """
    stats = {"domains_computed": 0, "domains_cached": 0,
             "matrix_computed": 0, "matrix_cached": 0, "skipped": 0}
    scores = STORE.all_scores(con)
    dom_map = AS._task_domain_map()

    # 1. 域总结: 确定要刷哪些域(only_tasks 影响到的域, 或全部)。
    board = DB.from_store(con, baseline=baseline)
    boards = (board.get("boards") or []) + (board.get("ungrouped") or [])
    target_domains = None
    if only_tasks is not None:
        target_domains = {dom_map.get(t) for t in only_tasks}

    for b in boards:
        dom = b.get("domain")
        if target_domains is not None and dom not in target_domains:
            continue
        scope = dom or "__nodomain__"
        sub = [s for s in scores if dom_map.get(s.get("task_id")) == dom]
        fp = STORE.analysis_fingerprint(sub, baseline, scope=scope)
        if not force and STORE.get_cached_analysis(
                con, "domain-summary", scope, baseline, fingerprint=fp) is not None:
            stats["domains_cached"] += 1
            continue
        try:
            res = AS.domain_summary(con, dom, b, baseline=baseline)
            STORE.upsert_analysis_cache(
                con, kind="domain-summary", scope=scope, baseline=baseline,
                scores_fingerprint=fp, analysis=res, engine=res.get("engine"))
            stats["domains_computed"] += 1
        except Exception:
            stats["skipped"] += 1

    # 2. 全局矩阵解读(任一题变都可能改变矩阵格局 -> 每次评分后按指纹判)。
    fp_all = STORE.analysis_fingerprint(scores, baseline, scope="__all__")
    if not force and STORE.get_cached_analysis(
            con, "matrix-reading", "__all__", baseline, fingerprint=fp_all) is not None:
        stats["matrix_cached"] += 1
    else:
        try:
            lb = LB.from_store(con, baseline=baseline)
            res = AS.matrix_reading(con, lb, baseline=baseline)
            STORE.upsert_analysis_cache(
                con, kind="matrix-reading", scope="__all__", baseline=baseline,
                scores_fingerprint=fp_all, analysis=res, engine=res.get("engine"))
            stats["matrix_computed"] += 1
        except Exception:
            stats["skipped"] += 1

    return stats
