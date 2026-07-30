"""差距报告增强: 归因增量预跑 —— 把归因结果按题落库缓存, 报告页/一览表直接读。

归因(读双方交付物调 Claude 最强模型)慢且贵, 不能每次开报告页现算。本模块遍历有
评测分数的题, 只对「有竞品 ≥ 基线(值得归因)且 scores 指纹未命中缓存(评测结果变了
或从没算过)」的题跑一次归因并落缓存; 已命中(指纹相符)的题跳过不重算 —— 归因跟着
评测结果走, 分数/产品没变就一直用缓存(省钱)。

设计:
  - 无竞品 ≥ 基线的题也写一条「空归因」缓存(note=无需归因), 避免每轮重复扫它们。
  - force=True: 忽略缓存全部重算(换模型/改归因口径后用)。
  - 归因引擎不可用/单题失败不影响整体 —— 该题跳过, 继续下一题(如实, 不伪造)。
铁律沿袭: 归因仍是机器只摆事实 + 带交付物原文引用, 缓存只是存这份事实, 不改判定。
"""
from __future__ import annotations

from pipeline import store as STORE
from pipeline import gap_report as GR


def _has_competitor_at_or_above_baseline(task_scores: list[dict],
                                         baseline: str) -> bool:
    """本题是否有竞品分数 ≥ 基线(值得归因; 落后的竞品由 findings 覆盖, 不归因)。"""
    base = next((s for s in task_scores
                 if s.get("product") == baseline
                 and s.get("sample_score") is not None), None)
    if base is None:
        return False
    bval = base["sample_score"]
    for s in task_scores:
        if (s.get("product") != baseline and s.get("sample_score") is not None
                and s["sample_score"] >= bval):
            return True
    return False


def prefetch(con, baseline: str = "vio", *, force: bool = False,
             only_tasks: list[str] | None = None) -> dict:
    """增量预跑归因落缓存。返回 {scanned, computed, skipped, cached_hit, no_competitor}。

    only_tasks: 限定只处理这些 task_id(入库钩子传变化的题); None 则全量扫。
    force: 忽略缓存全部重算。
    """
    all_scores = STORE.all_scores(con)
    by_task: dict[str, list[dict]] = {}
    for s in all_scores:
        by_task.setdefault(s.get("task_id"), []).append(s)

    stats = {"scanned": 0, "computed": 0, "skipped": 0,
             "cached_hit": 0, "no_competitor": 0}
    for task_id, task_scores in by_task.items():
        if only_tasks is not None and task_id not in only_tasks:
            continue
        stats["scanned"] += 1
        fp = STORE.attribution_fingerprint(task_scores, baseline)

        # 缓存命中(指纹相符)且非强制 -> 跳过不重算。
        if not force and STORE.get_cached_attribution(con, task_id, baseline, fp) is not None:
            stats["cached_hit"] += 1
            continue

        # 无竞品 ≥ 基线 -> 写空归因缓存(避免每轮重复扫), 不调引擎。
        if not _has_competitor_at_or_above_baseline(task_scores, baseline):
            STORE.upsert_attribution_cache(
                con, task_id=task_id, baseline=baseline, scores_fingerprint=fp,
                attribution={"task_id": task_id, "baseline": baseline,
                             "dry_run": False, "engine": None, "points": [],
                             "note": "本题无竞品达到或超过基线,无需归因"},
                engine=None)
            stats["no_competitor"] += 1
            continue

        # 有竞品 ≥ 基线且缓存未命中 -> 跑归因(读交付物调引擎)落缓存。
        try:
            rep = GR.from_store(con, task_id, baseline=baseline, with_attribution=True)
            attr = rep.as_dict().get("attribution")
        except Exception:
            stats["skipped"] += 1
            continue
        if not attr:
            stats["skipped"] += 1
            continue
        STORE.upsert_attribution_cache(
            con, task_id=task_id, baseline=baseline, scores_fingerprint=fp,
            attribution=attr, engine=attr.get("engine"))
        stats["computed"] += 1
    return stats
