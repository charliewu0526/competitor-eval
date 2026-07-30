"""MR-12 (#48): 能力域分维度榜单 + 版本/日期/stale (ADR-0017).

这是**派生视图**(同 leaderboard / catalog / gap_report 的定位): 不改评分核心,
只把既有 `scores` 按 capability_domain 分桶, 每桶复用 `leaderboard.leaderboard`
排一张榜 —— 「同域才同台」。Violoop 全域参赛; 一个竞品可同时出现在多张域榜,
正是「多维度榜单」的应有之义 (PRD 词汇表)。

三条铁律 (立身之本) 沿袭:
  * cannot-reach 不参赛 (非差): leaderboard 已把它剔出 ranking、归入 excluded,
    榜上标「未参赛」而非 0 分垫底。
  * 每条分数绑竞品版本 + 测试日期 (ADR-0017): version/tested_at 从 score 透传到
    榜单 cell 与 product 行, 不冒充现状。
  * 超期标陈旧 (stale): 有效 stale = 存过的人工/半自动 stale 标志 OR 依据 tested_at
    超过新鲜度窗口 (默认 90 天) 派生。tested_at 缺失 => 不擅自判新鲜, 只沿用存过的标志。

MVP (ADR-0019): stale 判定可人工/半自动 —— 本模块给出「按天数窗口自动派生」这半自动
能力, 但绝不覆盖已存的人工判定 (取或运算, 宁可多标不漏标)。
"""
from __future__ import annotations

import time

from pipeline import leaderboard as LB
from pipeline.catalog import DOMAIN_LABELS
from pipeline.schema import CAPABILITY_DOMAIN_VALUES

# 新鲜度窗口: 超过这么多天没重测 => 该条分数标陈旧 (ADR-0017 建议 90 天)。
DEFAULT_FRESHNESS_DAYS = 90
_DAY = 86400.0


def is_stale(tested_at: float | None, stored_stale: bool = False, *,
             now: float | None = None,
             window_days: float = DEFAULT_FRESHNESS_DAYS) -> bool:
    """有效 stale = 人工/半自动存过的标志 OR 按 tested_at 超窗自动派生.

    tested_at 缺失 (未记录测试日期) => 无法自动判新鲜, 只沿用 stored_stale
    (缺数据不擅自当新鲜, 也不伪装成陈旧 —— 如实沿用已知信息)。
    """
    if stored_stale:
        return True
    if tested_at is None:
        return False
    return (now or time.time()) - tested_at > window_days * _DAY


def _domain_of_scores(scores: list[dict], task_domains: dict[str, str]) -> dict[str, str]:
    """给每条 score 贴上它所属能力域. 未知 task_id 归 None (单列「未归域」组)。"""
    return {s.get("task_id"): task_domains.get(s.get("task_id"))
            for s in scores}


def _freshness_cols(scores: list[dict], *, now: float | None = None,
                    window_days: float = DEFAULT_FRESHNESS_DAYS) -> dict:
    """把 (task_id, product) -> {version, tested_at, stale} 索引出来.

    stale 用 is_stale 融合「存过的标志」与「按 tested_at 超窗派生」, 供榜单 cell +
    product 行贴新鲜度。product 行的 version/tested_at/stale 取该产品在本域各题里
    **最旧的一次** (最保守: 只要有一条陈旧就提醒该产品整体可能过时)。
    """
    per_cell: dict[tuple, dict] = {}
    for s in scores:
        key = (s.get("task_id"), s.get("product"))
        ta = s.get("tested_at")
        per_cell[key] = {
            "competitor_version": s.get("competitor_version"),
            "tested_at": ta,
            "stale": is_stale(ta, bool(s.get("stale", False)),
                              now=now, window_days=window_days),
        }
    return per_cell


def build_domain_board(scores: list[dict], task_domains: dict[str, str],
                       baseline: str = "vio", *,
                       now: float | None = None,
                       window_days: float = DEFAULT_FRESHNESS_DAYS,
                       domain_labels: dict | None = None) -> dict:
    """按能力域分维度组装多张榜 (纯派生, 无副作用).

    scores       : 扁平的 per-(task,product) score dict 列表 (store.all_scores 或内存)。
    task_domains : {task_id: capability_domain} —— 哪道题属哪个能力域 (由 catalog/suite
                   从 TaskSpec.capability_domain 派生, 本模块不自己发现任务)。
    返回:
      {
        boards: [{domain, label, hint, leaderboard(=LB.leaderboard 输出), n_tasks,
                  freshness:{ "task|product": {version,tested_at,stale} },
                  product_freshness:{product:{version,tested_at,stale}} }],
        window_days,
        ungrouped: [同结构, domain=None] —— task_domains 里查不到域的分数不静默消失。
      }
    域顺序 = CAPABILITY_DOMAIN_VALUES, 空域不出现 (只列有分数的域)。一个竞品可同时
    出现在多张域榜 —— 各域独立分桶、独立排名, 正是多维度榜单的应有之义。
    """
    labels = domain_labels or DOMAIN_LABELS
    dom_of = _domain_of_scores(scores, task_domains)

    by_domain: dict[str | None, list[dict]] = {}
    for s in scores:
        by_domain.setdefault(dom_of.get(s.get("task_id")), []).append(s)

    def _board(domain, group_scores) -> dict:
        lb = LB.leaderboard(baseline, group_scores)
        cell_fresh = _freshness_cols(group_scores, now=now, window_days=window_days)
        # product 行新鲜度: 取该产品各题里最旧的一条 (最保守提醒)。
        prod_fresh: dict[str, dict] = {}
        for (task, prod), fr in cell_fresh.items():
            cur = prod_fresh.get(prod)
            ta = fr["tested_at"]
            if cur is None:
                prod_fresh[prod] = dict(fr)
                continue
            # 已陈旧则保持陈旧; tested_at 取更早的一条 (None 视为最不新鲜)。
            cur["stale"] = cur["stale"] or fr["stale"]
            cur_ta = cur["tested_at"]
            if ta is None or (cur_ta is not None and ta < cur_ta):
                cur["tested_at"] = ta
                cur["competitor_version"] = fr["competitor_version"]
        meta = labels.get(domain, {"label": domain or "未归域", "hint": ""})
        # freshness 用字符串键 "task|product" 便于 JSON 序列化 (元组键 JSON 不支持)。
        fresh_json = {f"{t}|{p}": v for (t, p), v in cell_fresh.items()}
        return {
            "domain": domain,
            "label": meta.get("label", domain or "未归域"),
            "hint": meta.get("hint", ""),
            "leaderboard": lb,
            "n_tasks": len(lb.get("tasks", [])),
            "freshness": fresh_json,
            "product_freshness": prod_fresh,
        }

    boards: list[dict] = []
    for dom in CAPABILITY_DOMAIN_VALUES:
        grp = by_domain.get(dom)
        if not grp:
            continue
        boards.append(_board(dom, grp))

    ungrouped = []
    if by_domain.get(None):
        ungrouped.append(_board(None, by_domain[None]))

    return {"boards": boards, "window_days": window_days, "ungrouped": ungrouped}


def task_domain_map(tasks_dir=None) -> dict[str, str]:
    """便捷: 从任务库派生 {task_id: capability_domain} (复用 suite.discover_tasks)。"""
    from pipeline import suite as SUITE
    return {t.task_spec.task_id: t.task_spec.capability_domain
            for t in SUITE.discover_tasks(tasks_dir)}


def from_store(con, baseline: str = "vio", *, now: float | None = None,
               window_days: float = DEFAULT_FRESHNESS_DAYS,
               tasks_dir=None) -> dict:
    """便捷: 直接从 store 的 scores + 任务库域映射组装分维度榜单.

    榜单隔离: provenance=auto-from-census 的候选题分数不进任何分维度公平榜 (它们的
    expected 是 AI 暂定基准、未核验), 从 scores 里剔除后再分桶。human 题不受影响。
    """
    from pipeline import store as STORE
    from pipeline import leaderboard as LB
    scores = STORE.all_scores(con)
    cand_ids = LB.candidate_task_ids(tasks_dir)
    fair = [s for s in scores if s.get("task_id") not in cand_ids]
    return build_domain_board(fair, task_domain_map(tasks_dir),
                              baseline=baseline, now=now,
                              window_days=window_days)
