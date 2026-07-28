"""MR-6 (#42): Assignment 状态机 + 并发领取的策略层 (ADR-0015).

MR-1 已经把「地基原语」放进 store: 原子领取锁 (claim_assignment 靠
`WHERE status='open'` / PG `SELECT ... FOR UPDATE`)、放弃回开 (set_assignment_status
'abandoned' -> 'open')、并发单赢 (两写者只一条 UPDATE 命中 open 行)。本模块不重造
这些原语, 只在其上补三件 store 不该管的「策略」:

  1. 合法流转守卫 —— store.set_assignment_status 什么状态都肯写; 策略层拦住非法跳转
     (submitted 不能倒回 claimed、open 不能直接 submitted 等), 让状态机
     open -> claimed -> submitted 单向, claimed -> abandoned -> open 是唯一回路。
  2. 领取单元物化 —— 把 catalog 的一道题 (task_id + 同域 participating 产品集)
     铸成一个 Assignment (ADR-0015: 领取的最小单元 = 整道对比任务, 含该域全部参赛
     产品, 一人一次性)。
  3. 超时回收 —— 领了没交 (claimed 太久) 的 Assignment 扫回 open, 别人可再领
     (#42 AC / story 12)。放弃走 store 的 abandon; 超时是自动版的同一回路。

立身之本: 领取粒度是「整组对打由一人一次性完成」, 不许单产品零散领 (会破坏同题
同人、削弱可比性)。产品集从 catalog 的 GATE 派生参赛集来 (cannot-reach 不入组),
不在这里另判可达性。
"""
from __future__ import annotations

import time
import uuid

from pipeline import store
from pipeline import catalog as CATALOG


# --- 状态机: 合法流转表 ----------------------------------------------------
# open      : 未被领取, 挂在清单上可抢。
# claimed   : 已被某 intern 领取, 对其他人锁定 (并发领取控制)。
# submitted : 该 Assignment 全部产品交付完 (终态之一)。
# abandoned : 放弃 —— store 落地时立即重开为 open (放弃即回清单)。
STATES = ("open", "claimed", "submitted", "abandoned")

# 允许的 status -> 下一 status 集合。abandoned 是「回路指令」而非停留态:
# store.set_assignment_status('abandoned') 会把行重置成 open, 故 claimed 唯一
# 的退出除了 submitted 就是 abandoned(->open)。submitted 是终态, 不可再流转。
_ALLOWED: dict[str, frozenset[str]] = {
    "open": frozenset({"claimed"}),
    "claimed": frozenset({"submitted", "abandoned"}),
    "submitted": frozenset(),          # 终态: 交付完不回退
    "abandoned": frozenset(),          # 落地即 open, 不作为停留态被再流转
}

# 领了没交多久算超时 (秒)。MVP 默认值; 调用方可覆盖。
DEFAULT_CLAIM_TTL_SECONDS = 24 * 3600


class AssignmentError(Exception):
    """状态机非法操作 (非法流转 / 领取粒度错误等)。Web 层翻成 409/400。"""


class IllegalTransition(AssignmentError):
    """企图从当前状态跳到一个不被允许的状态。"""


def can_transition(src: str, dst: str) -> bool:
    """src 状态能否合法流转到 dst。未知状态一律 False (fail closed)。"""
    return dst in _ALLOWED.get(src, frozenset())


def _require_transition(src: str, dst: str) -> None:
    if not can_transition(src, dst):
        raise IllegalTransition(
            f"非法状态流转: {src!r} -> {dst!r} "
            f"(允许: {sorted(_ALLOWED.get(src, ()))!r})")


# --- 领取单元物化 (ADR-0015) ----------------------------------------------
def materialize_for_task(con, task_id: str, *, tasks_dir=None,
                         registry=None, assignment_id: str | None = None,
                         now: float | None = None) -> dict:
    """把 catalog 的一道题铸成一个可领取的 Assignment (幂等 on task_id)。

    产品集 = 该题 GATE 派生的参赛集 (catalog card 的 `participating`): 只含够得着
    的产品 (cannot-reach 不入组, 立身之本 —— 够不着不硬拉进来打 0)。同一 task 若
    已物化过, 复用原 id、刷新产品集, status 不动 (免得把已领的题重置回 open)。

    找不到该题 -> AssignmentError。参赛集为空 (无人能 reach) -> AssignmentError
    (没产品可打的题不该挂上清单)。
    """
    card = CATALOG.task_detail(task_id, tasks_dir=tasks_dir, registry=registry)
    if card is None:
        raise AssignmentError(f"任务不存在于清单: {task_id!r}")
    products = list(card.get("participating") or [])
    if not products:
        raise AssignmentError(
            f"任务 {task_id!r} 无参赛产品 (全 cannot-reach), 不物化为可领取单元")

    existing = _find_by_task(con, task_id)
    if existing is not None:
        # 幂等: 复用原单, 只刷新产品集 (registry 可能新增了产品)。
        store.upsert_assignment(con, {
            "id": existing["id"],
            "task_id": task_id,
            "products": products,
            "status": existing["status"],
            "claimed_by": existing.get("claimed_by"),
            "claimed_ts": existing.get("claimed_ts"),
            "created_ts": existing.get("created_ts"),
        })
        return store.get_assignment(con, existing["id"])

    aid = assignment_id or f"as-{task_id}-{uuid.uuid4().hex[:8]}"
    store.upsert_assignment(con, {
        "id": aid,
        "task_id": task_id,
        "products": products,
        "status": "open",
        "created_ts": now if now is not None else time.time(),
    })
    return store.get_assignment(con, aid)


def _find_by_task(con, task_id: str) -> dict | None:
    rows = con.execute(
        "SELECT * FROM assignments WHERE task_id=? ORDER BY created_ts, id LIMIT 1",
        (task_id,)).fetchone()
    return dict(rows) if rows else None


# --- 方案B: 产品级领取单元物化 (领取粒度细化到「题×产品」) --------------------
# 背景: 实习生手上各自只有一个竞品账号(无人凑齐一道题的全部参赛产品), 整题领取
# 会死锁。故把一道题的参赛集拆成 N 个「单产品」子 Assignment: 每个只含一个产品,
# 可被不同人用各自账号独立领取/提交/收口。同题不同产品分散在多个 assignment,
# 评分/榜单仍按 (task_id, product) 聚合, 横向对比不受影响。
# 代价(用户已拍板接受): 同题不同产品可能由不同人跑, 掺入人的操作差异 —— 靠
# submitted_by 留痕缓解, 不再强求「同题同人」。
def _find_by_task_product(con, task_id: str, product: str) -> dict | None:
    """按 (task_id, product) 找已物化的单产品子单元。products_json 存 [product]。"""
    for r in con.execute(
            "SELECT * FROM assignments WHERE task_id=? ORDER BY created_ts, id",
            (task_id,)):
        a = store._decode_assignment(dict(r))
        prods = a.get("products") or []
        if len(prods) == 1 and prods[0] == product:
            return a
    return None


def materialize_product_for_task(con, task_id: str, product: str, *,
                                 tasks_dir=None, registry=None,
                                 assignment_id: str | None = None,
                                 now: float | None = None) -> dict:
    """把一道题的「某一个参赛产品」铸成独立可领取单元 (幂等 on (task_id, product))。

    product 必须在该题 GATE 派生的参赛集内 (够得着), 否则 AssignmentError ——
    不给够不着的产品造领取单元 (立身之本: 够不着不硬拉进来打 0)。
    同一 (task, product) 已物化则复用原单、status 不动 (免得把已领的重置回 open)。
    """
    card = CATALOG.task_detail(task_id, tasks_dir=tasks_dir, registry=registry)
    if card is None:
        raise AssignmentError(f"任务不存在于清单: {task_id!r}")
    participating = list(card.get("participating") or [])
    if product not in participating:
        raise AssignmentError(
            f"产品 {product!r} 不在任务 {task_id!r} 参赛集 {participating!r} 内 "
            f"(够不着的产品不物化为领取单元)")

    existing = _find_by_task_product(con, task_id, product)
    if existing is not None:
        return store.get_assignment(con, existing["id"])

    aid = assignment_id or f"as-{task_id}-{product}-{uuid.uuid4().hex[:8]}"
    store.upsert_assignment(con, {
        "id": aid,
        "task_id": task_id,
        "products": [product],
        "status": "open",
        "created_ts": now if now is not None else time.time(),
    })
    return store.get_assignment(con, aid)


def materialize_products_for_task(con, task_id: str, *, tasks_dir=None,
                                  registry=None, now: float | None = None) -> list[dict]:
    """把一道题的参赛集里 EVERY 产品各铸成一个独立可领取单元, 返回单元列表。

    参赛集为空 (全 cannot-reach) -> AssignmentError (没产品可打的题不挂清单)。
    """
    card = CATALOG.task_detail(task_id, tasks_dir=tasks_dir, registry=registry)
    if card is None:
        raise AssignmentError(f"任务不存在于清单: {task_id!r}")
    participating = list(card.get("participating") or [])
    if not participating:
        raise AssignmentError(
            f"任务 {task_id!r} 无参赛产品 (全 cannot-reach), 不物化为可领取单元")
    return [materialize_product_for_task(con, task_id, p, tasks_dir=tasks_dir,
                                         registry=registry, now=now)
            for p in participating]


# --- 领取 (并发控制复用 store 原子锁) --------------------------------------
def claim(con, assignment_id: str, user_id: str) -> dict:
    """intern 领取一道 Assignment。成功回传领到的 Assignment。

    并发控制完全走 store.claim_assignment 的原子锁 (两人抢同一道只一个赢); 这里
    只在失败时给出「为什么没领到」的清晰错误:
      - 不存在 -> AssignmentError
      - 已被领 / 非 open -> IllegalTransition (open->claimed 是唯一入口)
    """
    a = store.get_assignment(con, assignment_id)
    if a is None:
        raise AssignmentError(f"Assignment 不存在: {assignment_id!r}")
    won = store.claim_assignment(con, assignment_id, user_id)
    if not won:
        cur = store.get_assignment(con, assignment_id)
        raise IllegalTransition(
            f"领取失败: {assignment_id!r} 当前 {cur['status']!r} "
            f"(已被 {cur.get('claimed_by')!r} 锁定或非 open)")
    return store.get_assignment(con, assignment_id)


def submit(con, assignment_id: str, *, by: str | None = None) -> dict:
    """把已领取的 Assignment 标记为 submitted (claimed -> submitted)。

    仅持有者可交 (by 给出时校验), 且必须处于 claimed (open/submitted/abandoned
    都非法) —— 守卫状态机单向。"""
    a = store.get_assignment(con, assignment_id)
    if a is None:
        raise AssignmentError(f"Assignment 不存在: {assignment_id!r}")
    _require_transition(a["status"], "submitted")
    if by is not None and a.get("claimed_by") != by:
        raise AssignmentError(
            f"只有领取者可提交: {assignment_id!r} 归 {a.get('claimed_by')!r}, 非 {by!r}")
    # 带守卫原子写: 仅当仍为 claimed 才推进, 堵住与 reclaim_stale 的 TOCTOU。
    if not store.set_assignment_status(con, assignment_id, "submitted",
                                       expected_from="claimed"):
        raise IllegalTransition(
            f"提交失败: {assignment_id!r} 已不在 claimed (可能被超时回收或并发改动)")
    return store.get_assignment(con, assignment_id)


def abandon(con, assignment_id: str, *, by: str | None = None) -> dict:
    """放弃一道已领取的 Assignment -> 回到 open 可被再领 (story 12)。

    仅 claimed 可放弃; 仅持有者可放弃 (by 给出时校验)。store 落地时把行重置为
    open + 清空 claimed_by/claimed_ts。"""
    a = store.get_assignment(con, assignment_id)
    if a is None:
        raise AssignmentError(f"Assignment 不存在: {assignment_id!r}")
    _require_transition(a["status"], "abandoned")
    if by is not None and a.get("claimed_by") != by:
        raise AssignmentError(
            f"只有领取者可放弃: {assignment_id!r} 归 {a.get('claimed_by')!r}, 非 {by!r}")
    # 带守卫原子写: 仅当仍为 claimed 才回收, 避免覆盖并发下已变更的状态。
    if not store.set_assignment_status(con, assignment_id, "abandoned",
                                       expected_from="claimed"):
        raise IllegalTransition(
            f"放弃失败: {assignment_id!r} 已不在 claimed (可能被并发改动)")
    return store.get_assignment(con, assignment_id)


# --- 超时回收 (自动版的 abandon, #42 AC / story 12) -----------------------
def reclaim_stale(con, *, ttl_seconds: float = DEFAULT_CLAIM_TTL_SECONDS,
                  now: float | None = None) -> list[str]:
    """把领了太久没交的 claimed Assignment 扫回 open, 返回被回收的 id 列表。

    判据: status='claimed' 且 now - claimed_ts > ttl_seconds。回收走与放弃相同
    的回路 (set_assignment_status 'abandoned' -> open + 清持有者), 保证「领了没做
    的题不会永久卡死」。submitted 的不动 (已交付, 不是卡死)。"""
    t = now if now is not None else time.time()
    reclaimed: list[str] = []
    for a in store.assignments_by_status(con, "claimed"):
        cts = a.get("claimed_ts")
        if cts is None:
            continue
        if t - cts > ttl_seconds:
            # 带守卫: 仅当此刻仍为 claimed 才回收。若用户已在这一瞬提交 (claimed->
            # submitted), UPDATE 命中 0 行, 不会把已交付的作业错误重置回 open (H1 第二路径)。
            if store.set_assignment_status(con, a["id"], "abandoned",
                                           expected_from="claimed"):
                reclaimed.append(a["id"])
    return reclaimed
