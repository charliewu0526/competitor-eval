"""MR-13 (#49): 人工复核队列 + 职责分离 + 重校准 (ADR-0014).

G3 (sampling.py) already builds the async spot-check queue by strata
(high-risk / contradiction / big-gap 100%,其余 10% 随机). This slice adds the
THREE policies G3 left out, all on top of the same `spot_check_queue`:

  1. 职责分离 (story 32 / AC2) —— 执行某 Assignment 的 intern 不被指派复核同一条。
     `assign_reviewer` refuses to bind a reviewer who EXECUTED that (task,product)
     run (store.executors_for_task_product join). 不自己批自己作业。

  2. 复核结论 (story 6 / AC3) —— reviewer/PM 对复核项下「有道理」(reasonable=matches
     machine) / 「有问题」(problematic=human disagrees) 结论。人话映射到既有
     spot_check_queue.status: 有道理->'ok', 有问题->'anomaly'。intern 不能复核
     (RBAC 'review' 起, reviewer/owner)。

  3. 重校准 (story 33 / AC4) —— 「有问题」CAN trigger 黄金集重校准, but ONLY owner
     (RBAC 'calibrate_golden' 独占). A reviewer files「有问题」; the recalibration
     switch stays off their reach. 这个开关绝不外放。故这里把「下结论」与「触发
     重校准」两个动作拆开:
        * submit_verdict(reviewer/owner): 记录 ok/anomaly, 不碰校准。
        * trigger_recalibration(owner-only): 对一条 anomaly 复核项真正重校准评委,
          走 authorize.check_authorization(anomaly=True) 撤授权 + 记录 provenance。

立身之本: 复核只对「机器已标的现象」下人话判断, 不改评分核心; 校准这一危险开关
由 RBAC owner 独占, 职责分离由「执行者名单」硬约束 —— 多人化的新噪声用职责边界
约束, 而非信任。
"""
from __future__ import annotations

from pipeline import store
from pipeline import rbac as RBAC
from pipeline import authorize as AUTHZ


# 人话结论 -> spot_check_queue.status。「有道理」= 认同机器/面板; 「有问题」= 人
# 不认同 -> anomaly, 可被 owner 用作重校准依据。
VERDICT_OK = "reasonable"        # 有道理
VERDICT_PROBLEM = "problematic"  # 有问题
_VERDICT_TO_STATUS = {VERDICT_OK: "ok", VERDICT_PROBLEM: "anomaly"}


class ReviewError(Exception):
    """复核策略层错误 (职责分离违规 / 非法结论 / 状态不符)。Web 层翻 4xx。"""


class SeparationOfDuties(ReviewError):
    """企图把复核指派给该条的执行者 —— 违反职责分离 (不自己批自己作业)。"""


# --- 1. 指派复核者 (职责分离守卫) -----------------------------------------
def eligible_reviewer(con, queue_id: int, reviewer_id: str) -> bool:
    """reviewer_id 是否可复核 queue_id: 只要 TA 不是该 (task,product) 的执行者。"""
    item = store.get_spot_check(con, queue_id)
    if item is None:
        raise ReviewError(f"复核项不存在: {queue_id!r}")
    executors = store.executors_for_task_product(
        con, item["task_id"], item["product"])
    return reviewer_id not in executors


def assign_reviewer(con, queue_id: int, *, reviewer: dict | None,
                    reviewer_id: str) -> dict:
    """把一条复核项指派给 reviewer_id (职责分离守卫)。

    - actor(reviewer)必须有 'review' 权限 (intern 被拒, AC3)。
    - reviewer_id 不能是该 (task,product) 的执行者 —— 否则 SeparationOfDuties
      (AC2: 执行者不被指派复核自己执行的 Assignment)。
    返回更新后的复核项。
    """
    RBAC.require(reviewer, "review")
    if not eligible_reviewer(con, queue_id, reviewer_id):
        raise SeparationOfDuties(
            f"用户 {reviewer_id!r} 执行过该 (task,product), 不可被指派复核同一条 "
            f"(职责分离: 不自己批自己作业)")
    store.assign_reviewer(con, queue_id, reviewer_id)
    return store.get_spot_check(con, queue_id)


# --- 2. 下复核结论 (reviewer/PM; 不触发校准) ------------------------------
def submit_verdict(con, queue_id: int, *, reviewer: dict | None,
                   verdict: str, note: str | None = None) -> dict:
    """reviewer/owner 对复核项下「有道理」/「有问题」结论 (AC3)。

    - 需 'review' 权限 (intern 被拒)。
    - verdict ∈ {reasonable, problematic} —— 否则 ReviewError。
    - 若该项已指派了别的 reviewer, 只有被指派者 (或 owner) 能下结论 —— 职责分离
      不止指派, 也约束「谁能批」。
    checked_by 绑定认证身份 (不从请求体取, 防伪造签字)。仅记录, 绝不在此触发重校准
    —— 校准开关由 owner 独占的 trigger_recalibration 单独持有。
    """
    RBAC.require(reviewer, "review")
    status = _VERDICT_TO_STATUS.get(verdict)
    if status is None:
        raise ReviewError(
            f"非法复核结论: {verdict!r} (合法: {tuple(_VERDICT_TO_STATUS)})")
    item = store.get_spot_check(con, queue_id)
    if item is None:
        raise ReviewError(f"复核项不存在: {queue_id!r}")

    actor_id = (reviewer or {}).get("id")
    is_owner = RBAC.can((reviewer or {}).get("role"), "calibrate_golden")
    assigned = item.get("assigned_reviewer")
    if assigned and actor_id != assigned and not is_owner:
        raise SeparationOfDuties(
            f"复核项 {queue_id!r} 已指派给 {assigned!r}, 非指派者且非 owner 不可下结论")

    store.record_spot_check(con, queue_id, status=status,
                            checked_by=actor_id, verdict_note=note)
    return store.get_spot_check(con, queue_id)


# --- 2b. 三级闭环反哺: 标记存疑 / 排除出榜 / owner 改分 -------------------
# 抽查员看完一次运行的完整完成情况后, 除了下「有道理/有问题」结论, 还能对这次运行
# 的分数做三级处置, 真正回写进榜单(不再只是记一条抽查结论):
#   - 标记存疑(suspect): reviewer 起。分数保留在榜, 但打「存疑」标, 提示这条待商榷。
#   - 排除出榜(excluded): reviewer 起。这次运行不进公平排名(如执行明显跑偏/材料错),
#     但记录保留供审计, 不静默删。
#   - owner 改分(overridden): owner 独占。人工覆写能力分(可含诚实度), 机器原分留痕,
#     榜单消费时优先用 override 分。改分是最重的干预, 只给 owner。
def _run_key(con, queue_id: int) -> tuple[str, str, int]:
    item = store.get_spot_check(con, queue_id)
    if item is None:
        raise ReviewError(f"复核项不存在: {queue_id!r}")
    return item["task_id"], item["product"], item["run_idx"]


def mark_suspect(con, queue_id: int, *, reviewer: dict | None,
                 note: str | None = None) -> dict:
    """标记这次运行的分数「存疑」(reviewer 起)。保留在榜, 打标提示待商榷。"""
    RBAC.require(reviewer, "review")
    tid, prod, ridx = _run_key(con, queue_id)
    store.set_review_status(con, task_id=tid, product=prod, run_idx=ridx,
                            status="suspect", note=note,
                            by=(reviewer or {}).get("id"))
    return store.get_spot_check(con, queue_id)


def exclude_run(con, queue_id: int, *, reviewer: dict | None,
                note: str | None = None) -> dict:
    """把这次运行「排除出榜」(reviewer 起)。不进公平排名, 记录保留供审计。"""
    RBAC.require(reviewer, "review")
    tid, prod, ridx = _run_key(con, queue_id)
    store.set_review_status(con, task_id=tid, product=prod, run_idx=ridx,
                            status="excluded", note=note,
                            by=(reviewer or {}).get("id"))
    return store.get_spot_check(con, queue_id)


def clear_review_status(con, queue_id: int, *, reviewer: dict | None) -> dict:
    """撤销存疑/排除处置(reviewer 起), 恢复为机器原判。改分的撤销同样清标。"""
    RBAC.require(reviewer, "review")
    tid, prod, ridx = _run_key(con, queue_id)
    store.set_review_status(con, task_id=tid, product=prod, run_idx=ridx,
                            status=None, note=None,
                            by=(reviewer or {}).get("id"))
    return store.get_spot_check(con, queue_id)


def override_score(con, queue_id: int, *, actor: dict | None,
                   sample_score: float | None, h1_honesty: int | None = None,
                   note: str | None = None) -> dict:
    """owner 人工改分(owner 独占 calibrate_golden)。机器原分留痕, 榜单用 override 分。

    sample_score 必须在 [0,1](能力分区间), h1_honesty 若给必须 1-5 —— 否则 ReviewError。
    reviewer/intern 在此被 RBAC 拒(403): 改分是最重干预, 只给 owner。
    """
    RBAC.require(actor, "calibrate_golden")  # owner 独占
    if sample_score is not None and not (0.0 <= float(sample_score) <= 1.0):
        raise ReviewError(f"能力分须在 [0,1]: 收到 {sample_score!r}")
    if h1_honesty is not None and not (1 <= int(h1_honesty) <= 5):
        raise ReviewError(f"诚实度须在 1-5: 收到 {h1_honesty!r}")
    tid, prod, ridx = _run_key(con, queue_id)
    store.apply_score_override(con, task_id=tid, product=prod, run_idx=ridx,
                               sample_score=sample_score, h1_honesty=h1_honesty,
                               note=note, by=(actor or {}).get("id"))
    return store.get_spot_check(con, queue_id)


# --- 3. 触发重校准 (owner 独占) -------------------------------------------
def trigger_recalibration(con, queue_id: int, *, actor: dict | None,
                          role: str = "reviewer", name: str = "panel",
                          members=None) -> dict:
    """对一条「有问题」复核项触发黄金集重校准 —— 仅 owner (story 33 / AC4).

    危险开关 owner 独占 (RBAC 'calibrate_golden'): reviewer 只能下「有问题」结论,
    碰不到这个开关。前置: 该复核项必须已是 anomaly (有人下了「有问题」) —— 没有
    「有问题」结论就没有重校准的依据。

    重校准走 G2 authorize.check_authorization(anomaly=True): 对应评委/verifier
    subject 授权被撤 (revoked), 必须重新清黄金集才能恢复。记录 provenance
    (recalibrated_by/ts) 到该复核项, 留审计追溯。
    返回 {recalibration_triggered, authorization, item}。
    """
    RBAC.require(actor, "calibrate_golden")   # intern/reviewer 在此被拒 (403)
    item = store.get_spot_check(con, queue_id)
    if item is None:
        raise ReviewError(f"复核项不存在: {queue_id!r}")
    if item.get("status") != "anomaly":
        raise ReviewError(
            f"复核项 {queue_id!r} 当前 {item.get('status')!r}, 只有「有问题」"
            f"(anomaly) 的结论才能触发重校准")

    res = AUTHZ.check_authorization(con, role=role, name=name,
                                    members=members or [], anomaly=True)
    store.record_recalibration(con, queue_id, by=(actor or {}).get("id"))
    return {
        "recalibration_triggered": not res["authorized"],
        "authorization": res,
        "item": store.get_spot_check(con, queue_id),
    }
