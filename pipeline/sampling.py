"""G3 (#26): layered human spot-check — 10% / 100% / 100%.

人从「每环节签字的闸门」挪到「路径外的抽查员」。主流程入库 NEVER waits for a
human; this module builds an ASYNC spot-check queue AFTER the fact by scanning
the store. Three strata, each with its own sampling rate:

  * high-risk    — 100%: 危险结论必查（honesty-alert / Vio 翻车入 bug / 低 H1）
  * contradiction— 100%: 三模型分歧（E3 极差≥2 标红）必查——分歧是信号
  * normal       — 10% : 其余随机抽

Determinism: "random 10%" is a SEEDED hash of (task,product,run) so the same DB
yields the same sample (re-runnable, auditable) — not os-random that drifts.
The verdict write-back can trigger G2 recalibration (抽查异常 → 重校准) via
authorize.check_authorization(anomaly=True).
"""
from __future__ import annotations
import hashlib
import json

from pipeline import store

NORMAL_RATE = 0.10            # 普通任务随机抽查比例
HIGH_RISK = "high-risk"
CONTRADICTION = "contradiction"
BIG_GAP = "big-gap"           # MR-13 (#49): 大差距强制入复核队列
NORMAL = "normal"

# 高风险信号：机器疑似诚实问题 / Vio 自己翻车被路由进 bug pipeline。
_HIGH_RISK_SUSPECTED = {"honesty-alert"}
HONESTY_ALERT_THRESHOLD = 2   # h1_honesty <= 2 (1-5 轴) 视为高风险诚实结论

# MR-13「大差距」信号：复用 findings 的 feature-gap 判定(rule_feature_gap =
# 竞品成功而基线失败; rule_capability_lead = 竞品能力分领先 ≥ CAPABILITY_LEAD
# 0.15),两条都以 suspected_category="feature-gap" 落地 —— 大差距判定与发现规则
# 同源、不另立标准(呼应 gap_report.BIG_GAP = FIND.CAPABILITY_LEAD)。
_BIG_GAP_SUSPECTED = {"feature-gap"}


def _seeded_fraction(*parts: object) -> float:
    """Stable [0,1) fraction from a natural key — deterministic 'random'."""
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def in_normal_sample(task_id: str, product: str, run_idx: int,
                     rate: float = NORMAL_RATE) -> bool:
    """Whether a normal run falls into the seeded `rate` sample (default 10%)."""
    return _seeded_fraction(task_id, product, run_idx) < rate


def _loads(blob) -> list:
    if not blob:
        return []
    if isinstance(blob, (list, dict)):
        return blob if isinstance(blob, list) else [blob]
    try:
        v = json.loads(blob)
    except (TypeError, ValueError):
        return []
    return v if isinstance(v, list) else ([] if v is None else [v])


def classify_run(score: dict, findings_by_run: dict) -> tuple[str, str] | None:
    """Decide a run's stratum + human-readable reason, or None to skip.

    Precedence high-risk > contradiction > big-gap > normal-sample: a run
    matching several强制 strata is filed under the strongest 100% reason. All
    three of high-risk / contradiction / big-gap are 100%-forced review; the
    ordering only decides which reason is shown. Returns None for normal runs
    NOT picked by the 10% sample.
    """
    key = (score["task_id"], score["product"], score["run_idx"])

    # --- high-risk (100%) --------------------------------------------------
    hr_reasons = []
    h1 = score.get("h1_honesty")
    if h1 is not None and h1 <= HONESTY_ALERT_THRESHOLD:
        hr_reasons.append(f"诚实存疑 H1={h1}≤{HONESTY_ALERT_THRESHOLD}")
    for f in findings_by_run.get(key[:1], []):   # findings keyed by task_id
        if f.get("subject") != score["product"]:
            continue
        if f.get("suspected_category") in _HIGH_RISK_SUSPECTED:
            hr_reasons.append(f"疑似 {f['suspected_category']}: {f.get('subject')}")
        if f.get("routed_to"):
            hr_reasons.append(f"Vio 翻车已路由 {f['routed_to']}")
    if hr_reasons:
        return HIGH_RISK, "；".join(dict.fromkeys(hr_reasons))

    # --- contradiction (100%) ---------------------------------------------
    # accept both the DB column (disagreement_json) and the in-memory
    # score_run() shape (disagreement_flagged).
    flagged = _loads(score.get("disagreement_json")
                     if score.get("disagreement_json") is not None
                     else score.get("disagreement_flagged"))
    if flagged:
        return CONTRADICTION, f"三模型分歧标红: {', '.join(map(str, flagged))}"

    # --- big-gap (100%) ---------------------------------------------------
    # MR-13: 大差距强制入复核队列。判定复用 findings 的 feature-gap 发现(竞品成功
    # 而基线失败 / 竞品能力分领先 ≥0.15),同源不另立标准。findings 挂在该产品名下
    # 时,说明本题该产品与基线有显著差距 —— 差距大 = 必查(可能沉淀为「方法」初稿)。
    bg_reasons = []
    for f in findings_by_run.get(key[:1], []):   # findings keyed by task_id
        if f.get("subject") != score["product"]:
            continue
        if f.get("suspected_category") in _BIG_GAP_SUSPECTED:
            ph = f.get("phenomenon") or f.get("rule") or "feature-gap"
            bg_reasons.append(f"大差距: {ph}")
    if bg_reasons:
        return BIG_GAP, "；".join(dict.fromkeys(bg_reasons))

    # --- normal (10% seeded sample) ---------------------------------------
    if in_normal_sample(*key):
        frac = round(_seeded_fraction(*key), 4)
        return NORMAL, f"普通任务随机抽中 (10% 采样, seed={frac})"
    return None


def build_queue(con, *, rate: float = NORMAL_RATE) -> dict:
    """Scan the store and (re)build the spot-check queue. ASYNC: this is called
    AFTER persist_eval, never inside the main ingest path.

    Returns a summary {enqueued, by_stratum, total_scored}. Idempotent —
    re-enqueue refreshes stratum/reason but preserves any human verdict.
    """
    scores = store.all_scores(con)
    findings = store.all_findings(con)
    # 走查 BUG-4: 先清「当前评分集里已不存在、且尚无人工裁决」的陈旧 pending 抽查项
    # (旧竞品集残留的幽灵复核项), 再按本轮 scores 重建 —— 队列只反映当前评测。
    valid_keys = {(sc["task_id"], sc["product"], sc.get("run_idx"))
                  for sc in scores}
    purged = store.purge_stale_spot_checks(con, valid_keys)
    by_task: dict = {}
    for f in findings:
        by_task.setdefault((f["task_id"],), []).append(f)

    summary = {HIGH_RISK: 0, CONTRADICTION: 0, BIG_GAP: 0, NORMAL: 0}
    enqueued = 0
    for sc in scores:
        # cannot-reach / unscored runs are not a fair check target.
        if not sc.get("scored", 1):
            continue
        decision = classify_run(sc, by_task)
        if decision is None:
            continue
        stratum, reason = decision
        store.enqueue_spot_check(con, task_id=sc["task_id"],
                                 product=sc["product"], run_idx=sc["run_idx"],
                                 stratum=stratum, reason=reason)
        summary[stratum] += 1
        enqueued += 1
    return {"enqueued": enqueued, "by_stratum": summary,
            "total_scored": len(scores), "purged_stale": purged}


def submit_verdict(con, queue_id: int, *, status: str,
                   checked_by: str | None = None,
                   verdict_note: str | None = None,
                   role: str | None = None, name: str | None = None,
                   members=None) -> dict:
    """Record a human spot-check verdict and, on 'anomaly', fire the G2
    recalibration trigger for the named reviewer/verifier subject.

    status: 'ok' (matches machine) | 'anomaly' (human disagrees → 重校准).
    Returns {recorded: True, recalibration_triggered: bool, authorization?}.
    """
    if status not in ("ok", "anomaly"):
        raise ValueError("status must be 'ok' or 'anomaly'")
    store.record_spot_check(con, queue_id, status=status,
                            checked_by=checked_by, verdict_note=verdict_note)
    out = {"recorded": True, "recalibration_triggered": False}
    if status == "anomaly" and role and name:
        from pipeline import authorize
        res = authorize.check_authorization(con, role=role, name=name,
                                            members=members or [],
                                            anomaly=True)
        out["recalibration_triggered"] = not res["authorized"]
        out["authorization"] = res
    return out
