"""E1: GATE derivation — `competitor.can_operate_local_desktop × task.requires_local_desktop`.

GATE is NOT pinned to a competitor. It is derived AT RUN TIME from the
competitor's capability domain (F2 registry) crossed with the task's
requirement (F1 TaskSpec), so the SAME competitor lands on DIFFERENT gates
across tasks (desktop task -> cannot-reach; api-friendly task -> participates).

This distinguishes two unfairnesses (do not conflate):
  - tier   solves the "positioning mismatch" unfairness (whose home turf the task is)
  - GATE   solves the "can't even reach it" unfairness (no way to touch the target)

Iron rule (PRD 立身之本 corollary): a competitor that physically cannot reach
the task target must be tagged `cannot-reach` and EXCLUDED from the fair
leaderboard — it must NOT be recorded as an unfair sample_score=0 ("假失败").
score_run already honors this (cannot-reach -> scored=False, no sample_score);
this module supplies the derivation + the exclusion helper that S1's leaderboard
will consume.

Seam-internal, pure logic: no API, no IO. Fully covered by synthetic RunRecords.
"""
from __future__ import annotations
from pipeline.schema import GATE_VALUES


def derive_gate(can_operate_local_desktop: bool,
                requires_local_desktop: bool) -> str:
    """Cross capability-domain with task-requirement -> a GATE_VALUES member.

    requires_local_desktop=True  (task lives in a local desktop app):
        can operate desktop  -> native-operable   (fair head-to-head)
        cannot operate        -> cannot-reach       (excluded, no unfair 0)
    requires_local_desktop=False (task reachable without local desktop, e.g. API/web):
        can operate desktop  -> native-operable   (native is a superset; fair)
        cannot operate        -> api-or-integration (reachable, but CROSS-LAYER)
    """
    if requires_local_desktop:
        return "native-operable" if can_operate_local_desktop else "cannot-reach"
    return "native-operable" if can_operate_local_desktop else "api-or-integration"


def gate_for(competitor, task) -> str:
    """Convenience: derive the gate for a Competitor (F2) on a TaskSpec (F1).

    两级推导 (PRD-0003 竞品归域, #36 方向):
      1. 若竞品登记了 capability_domains (非空), 先按域收窄: 任务的
         capability_domain 不在竞品覆盖域内 -> cannot-reach (该竞品不主打这个
         能力域, 没参赛 != 差, 立身之本 corollary)。空 domains => 跳过这级,
         退回旧的纯布尔推导 (向后兼容 v1 种子/测试)。
      2. 域内 (或未登记域) 再按 can_operate_local_desktop × requires_local_desktop
         推导 —— 云端产品碰需本地桌面的题仍诚实判 cannot-reach。
    """
    domains = getattr(competitor, "capability_domains", None) or []
    if domains and getattr(task, "capability_domain", None) not in domains:
        return "cannot-reach"
    return derive_gate(competitor.can_operate_local_desktop,
                       task.requires_local_desktop)


def is_fair(gate: str) -> bool:
    """True iff this gate participates in the FAIR same-condition leaderboard.

    Only native-operable is a same-condition head-to-head. cannot-reach is
    excluded entirely; api-or-integration is reachable but cross-layer, so it is
    NOT counted as fair (reported on its own track, see rubric §0 iron rule).
    """
    _assert_gate(gate)
    return gate == "native-operable"


def is_excluded(gate: str) -> bool:
    """True iff this run must be DROPPED from leaderboard ranking entirely.

    cannot-reach produces no capability signal at all -> it is excluded so it
    never becomes an unfair 0. (Distinct from cross-layer, which is reported on
    a separate track rather than dropped.)
    """
    _assert_gate(gate)
    return gate == "cannot-reach"


def filter_leaderboard_rows(rows):
    """Drop cannot-reach rows from an iterable of scored evals (dicts with 'gate').

    Helper handed to S1: the leaderboard ranks fair + cross-layer rows and never
    sees cannot-reach as a phantom zero. Returns a new list, input untouched.
    """
    return [r for r in rows if not is_excluded(r.get("gate", ""))]


def _assert_gate(gate: str) -> None:
    if gate not in GATE_VALUES:
        raise ValueError(f"gate must be one of {GATE_VALUES}, got {gate!r}")
