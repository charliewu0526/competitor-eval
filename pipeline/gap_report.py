"""MR-11 (#47): 差距报告派生视图 (ADR-0012).

一道对比任务(一个 Assignment / task_id)产出一份可读差距报告。这是**派生视图**,
不是新审核逻辑:只从既有 `scores` + `findings` 组装,复用 leaderboard 的
`vs_baseline` 差值语义、findings 的机器规则产出、probe 的 code-analysis 机理证据、
registry 的开源/repo 元数据。评分核心、发现规则一字不改。

铁律沿袭(立身之本):
  * 机器只标现象不下结论 —— 报告透传 finding.phenomenon,PM-fillable 的
    product_judgment / final_category 原样带出,报告绝不代填。
  * 缺数据如实标 —— 竞品拿不到分(cannot-reach)或没做机理分析时标 None/未分析,
    绝不伪装成 0 或编造机理。
  * 大差距自动生成 Finding —— 复用 findings.classify 已产出的 feature-gap /
    capability-lead 发现,报告只把它们归拢呈现,不另造判定。

三块内容(对应 #47 AC):
  1. score_diffs : Violoop(基线)vs 各竞品的分数差(算术,非判断)。
  2. findings    : 本题机器发现(现象事实,机器只标不下结论)。
  3. mechanisms  : 开源竞品的源码机理分析(带 repo 链接);闭源标 unavailable。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict

from pipeline import findings as FIND
from pipeline.domain_board import is_stale, DEFAULT_FRESHNESS_DAYS

BASELINE = "vio"
# 复用发现层「竞品显著领先」的门槛,保持大差距判定与发现规则同源、不另立标准。
BIG_GAP = FIND.CAPABILITY_LEAD  # 0.15


@dataclass
class ScoreDiff:
    """一个产品在本题的分数与相对基线的差(纯算术,不含判断)."""
    product: str
    is_baseline: bool
    sample_score: float | None
    baseline_score: float | None
    diff: float | None            # competitor - baseline; 正=竞品领先, 负=竞品落后, None=不可比
    gate: str | None
    scored: bool
    reason: str | None
    cannot_reach: bool
    big_gap: bool                 # 竞品显著领先(diff>=+BIG_GAP): 该补齐的功能差距信号
    big_lag: bool                 # 竞品显著落后(diff<=-BIG_GAP): 基线领先的对称面,别漏看
    honesty: int | None           # H1 诚实度(1-5),独立轴带出: 0分是老实翻车还是谎报翻车
    competitor_version: str | None
    tested_at: float | None
    stale: bool

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class CodeMechanism:
    """开源竞品的源码机理分析条目(带 repo 链接).

    mechanism 来自本题 finding 里的 code-analysis 证据(probe/X2 产出);开源但尚未
    分析则 mechanism=None(未分析,如实标),闭源竞品 is_open_source=False、无 repo。
    绝不从竞品自述「读出」机理——那等于让 AI 自述当证据,破立身之本。
    """
    product: str
    is_open_source: bool
    repo: str | None
    mechanism: str | None
    refs: list[str] = field(default_factory=list)
    analyst: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class GapReport:
    task_id: str
    baseline: str
    score_diffs: list[ScoreDiff]
    findings: list[dict]          # 机器发现(现象),PM-fillable 字段原样带出
    mechanisms: list[CodeMechanism]

    def as_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "baseline": self.baseline,
            "score_diffs": [d.as_dict() for d in self.score_diffs],
            "findings": self.findings,
            "mechanisms": [m.as_dict() for m in self.mechanisms],
        }


# --- helpers ---------------------------------------------------------------
def _is_cannot_reach(sc: dict) -> bool:
    return sc.get("gate") == "cannot-reach" or sc.get("reason") == "cannot-reach"


def _score_of(sc: dict) -> float | None:
    """cannot-reach 无能力分(没参赛,非差)-> None,绝不当 0 参与作差."""
    if _is_cannot_reach(sc):
        return None
    return sc.get("sample_score")


def _mechanism_from_findings(product: str, task_findings: list[dict]) -> dict | None:
    """从本题 finding 的 evidence 里挖出该产品的 code-analysis 机理条目.

    机理证据是 probe/X2 以 {"source":"code-analysis", ...} 挂进 finding.evidence 的。
    报告只**转述**已有机理事实,绝不自造。返回最先命中的一条(带 repo/refs/analyst)。
    """
    for f in task_findings:
        if f.get("subject") != product:
            continue
        ev = f.get("evidence")
        if isinstance(ev, str):
            try:
                ev = json.loads(ev)
            except Exception:
                ev = None
        for e in (ev or []):
            if isinstance(e, dict) and e.get("source") == "code-analysis":
                return e
    return None


# --- 1. 分数差 -------------------------------------------------------------
def build_score_diffs(task_scores: list[dict], baseline: str = BASELINE, *,
                      now: float | None = None,
                      window_days: float = DEFAULT_FRESHNESS_DAYS) -> list[ScoreDiff]:
    """基线 vs 各竞品的分数差(算术). cannot-reach 标记但不参与作差(diff=None).

    stale 与分维度榜单同口径: 用 domain_board.is_stale 融合「存过的标志」与「按
    tested_at 超新鲜度窗口(默认 90 天)自动派生」—— 否则超期数据在差距报告里会被
    当成新鲜显示, 与榜单不一致(体检发现的自动 stale 未贯通)。"""
    base = next((s for s in task_scores if s.get("product") == baseline), None)
    base_val = _score_of(base) if base else None

    diffs: list[ScoreDiff] = []
    for sc in task_scores:
        prod = sc.get("product")
        val = _score_of(sc)
        is_base = prod == baseline
        cr = _is_cannot_reach(sc)
        # diff 只在两边都有真实分时才算;任一缺(cannot-reach / 未打分)-> None(不可比)。
        diff = None
        if not is_base and val is not None and base_val is not None:
            diff = round(val - base_val, 4)
        # big_gap = 竞品显著领先(该补齐); big_lag = 竞品显著落后(基线领先的对称面)。
        # 两者都以 BIG_GAP 为门槛,方向相反 —— 一个满分碾压竞品的差距也必被标记,
        # PM 不会漏看最刺眼的那一行。基线行 diff=None,两标志都 False。
        big = diff is not None and diff >= BIG_GAP
        lag = diff is not None and diff <= -BIG_GAP
        diffs.append(ScoreDiff(
            product=prod, is_baseline=is_base,
            sample_score=val,
            baseline_score=None if is_base else base_val,
            diff=diff, gate=sc.get("gate"),
            scored=bool(sc.get("scored", True)), reason=sc.get("reason"),
            cannot_reach=cr, big_gap=big, big_lag=lag,
            # H1 诚实度独立轴原样带出(不折进能力分): 让 PM 一眼看清 0 分是老实翻车
            # (H1=4)还是谎报翻车(H1=1)—— 危险的强 vs 可信的弱的关键区分。
            honesty=sc.get("h1_honesty"),
            competitor_version=sc.get("competitor_version"),
            tested_at=sc.get("tested_at"),
            stale=is_stale(sc.get("tested_at"), bool(sc.get("stale", False)),
                           now=now, window_days=window_days)))
    # 基线排最前,其余按 diff 降序(领先最多的竞品先呈现),None 沉底。
    diffs.sort(key=lambda d: (not d.is_baseline,
                              -(d.diff if d.diff is not None else -1e9)))
    return diffs


# --- 2 + 3. 组装整份报告 ---------------------------------------------------
def build_report(task_id: str, task_scores: list[dict], task_findings: list[dict],
                 registry=None, baseline: str = BASELINE, *,
                 now: float | None = None,
                 window_days: float = DEFAULT_FRESHNESS_DAYS) -> GapReport:
    """组装一道对比任务的差距报告(纯派生,无副作用).

    task_scores   : 本题各产品的 score dict(store.all_scores 过滤 task_id,或内存)。
    task_findings : 本题机器发现 dict(findings.classify 产出 / store 读回)。
    registry      : F2 registry(取 is_open_source / repo 元数据);None 则机理块留空。
    window_days   : stale 新鲜度窗口(默认 90 天), 与分维度榜单同口径。
    机器只标现象:findings 原样带出(含 PM-fillable 的 product_judgment/final_category),
    报告不代填、不下结论。
    """
    scores = [s for s in task_scores if s.get("task_id", task_id) == task_id]
    finds = [f for f in task_findings if f.get("task_id") == task_id]
    score_diffs = build_score_diffs(scores, baseline, now=now, window_days=window_days)

    # 机理块:遍历本题出现过的**竞品**(非基线),读 registry 元数据 + 挖机理证据。
    mechanisms: list[CodeMechanism] = []
    seen: set[str] = set()
    for sc in scores:
        prod = sc.get("product")
        if prod == baseline or prod in seen:
            continue
        seen.add(prod)
        is_oss, repo = False, None
        if registry is not None:
            try:
                comp = registry.get(prod)
                is_oss, repo = bool(comp.is_open_source), comp.repo
            except KeyError:
                pass
        ana = _mechanism_from_findings(prod, finds)
        # 开源才谈机理:闭源竞品拿不到源码,mechanism=None(unavailable,如实标)。
        # 开源但尚未分析 -> 也 None(未分析),绝不伪造。
        mechanisms.append(CodeMechanism(
            product=prod, is_open_source=is_oss, repo=repo,
            mechanism=(ana.get("mechanism") if (is_oss and ana) else None),
            refs=list(ana.get("refs") or []) if (is_oss and ana) else [],
            analyst=(ana.get("analyst") if (is_oss and ana) else None)))

    return GapReport(task_id=task_id, baseline=baseline,
                     score_diffs=score_diffs, findings=finds,
                     mechanisms=mechanisms)


def from_store(con, task_id: str, registry=None, baseline: str = BASELINE, *,
               now: float | None = None,
               window_days: float = DEFAULT_FRESHNESS_DAYS) -> GapReport:
    """便捷:直接从 SQLite store 组装一道题的差距报告(读 scores + findings).

    window_days: stale 新鲜度窗口, 与分维度榜单同口径(默认 90 天自动派生)。"""
    from pipeline import store as STORE
    scores = [s for s in STORE.all_scores(con) if s.get("task_id") == task_id]
    finds = [f for f in STORE.all_findings(con) if f.get("task_id") == task_id]
    return build_report(task_id, scores, finds, registry=registry, baseline=baseline,
                        now=now, window_days=window_days)
