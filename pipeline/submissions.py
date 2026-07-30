"""MR-7 (#43): the submission pipeline — intern 交付物落库 + 缺证据拒收 + 流向 intake.

本切片补的是 #38(intake 接缝: Submission → RunRecord)与 #42(Assignment 状态机)
之间那层「策略 + 存储接线」: intern 为一道 Assignment 里的每个产品各提交一份
Submission(原始产物 + 日志包 + 人工勾选断言 + claimed_success)。store 已有
`submissions` 表 + `upsert_submission`(MR-1 地基),intake 已有 `Submission` /
`translate`(#38);这里只负责三件 store/intake 不该管的策略:

  1. 无证据不入池(PRD story 17 / #43 AC3)—— 缺原始产物 => 拒收。原始产物是
     「可核查的实体」(截图/导出文件/AI 对话记录),没有它这份提交没有立身之本,
     当场 raise EvidenceMissing,绝不落库、绝不进引擎。日志包(#44)与后续的
     无日志包拒收在下一切片,这里对齐 #43 AC 只强制原始产物;日志包缺失如实
     透传给 intake -> cost/evidence unavailable(诚实,不伪造 0)。
  2. 领取粒度守卫(ADR-0015)—— 只能给「该 Assignment 参赛产品集」里的产品提交,
     给不在组里的产品提交是错单(WrongProduct),拒收。Assignment 必须处于
     claimed 且由本人持有才能提交(职责: 谁领谁交)。
  3. 流向 intake(#43 AC4)—— 落库后可把这份 Submission 翻成引擎认识的 RunRecord
     (调用 #38 的 translate,GATE 派生/客观断言/成本解析一字不改复用)。翻译是
     纯读派生,不改状态机;把整组交完 -> submitted 的收口仍走 assignments.submit。

立身之本: 末态由人工勾选(manual_assertions)认定,claimed_success 是自报仅喂 H1;
本模块只收证据 + 守边界,不下判断、不从竞品自述读成功。
"""
from __future__ import annotations

import time
import uuid

from pipeline import store
from pipeline import intake as INTAKE
from pipeline.intake import Submission


class SubmissionError(Exception):
    """提交被拒的基类。Web 层翻成 4xx。"""


class EvidenceMissing(SubmissionError):
    """缺原始产物(无可核查实体)—— 无证据不入池 (#43 AC3, story 17)。"""


class LogBundleMissing(SubmissionError):
    """缺执行日志包 —— 无日志包不入池 (#45 AC1, story 16/17)。

    MR-9 起日志包从「可选」升为「强制」:成本与过程必须有真实来源,不靠事后自报。
    注意区分两个层级(呼应 PRD「缺数据如实标 unavailable」):
      * 日志包「文件」强制上传 —— 压根没交包 => 拒收(本异常)。
      * 包内某些字段(闭源竞品的 token 等)拿不到 => 如实标 unavailable,不拒收
        (那由 intake 解析时透传,不伪造 0)。
    即「你必须交一个包,但包里黑箱字段可以诚实标缺失」—— 两者不矛盾。
    """


class WrongProduct(SubmissionError):
    """给不在该 Assignment 参赛产品集里的产品提交 —— 领取粒度错单 (ADR-0015)。"""


class NotSubmittable(SubmissionError):
    """Assignment 不在可提交状态(非 claimed / 非持有者)—— 谁领谁交。"""


def _has_artifact(artifact_path) -> bool:
    """原始产物是否算「有」: 非空、去空白后非空串。存在性由上传层已落盘保证,
    这里只拦「压根没给」的空提交(防止空壳入池)。"""
    return bool(artifact_path and str(artifact_path).strip())


def _has_log_bundle(log_bundle_path) -> bool:
    """日志包是否算「有」: 同 _has_artifact —— 只拦「压根没交包」的空提交。
    包「文件」必须在(#45 AC1 强制);包「内字段」拿不到照 unavailable 透传,不在此拦。"""
    return bool(log_bundle_path and str(log_bundle_path).strip())


def submit_product(con, *, assignment_id: str, product: str,
                   artifact_path: str | None,
                   log_bundle_path: str | None = None,
                   manual_assertions: dict | None = None,
                   machine_ctx: dict | None = None,
                   claimed_success: bool | None = None,
                   submitted_by: str | None = None,
                   transcript_excerpt: str = "",
                   competitor_version: str | None = None,
                   tested_at: float | None = None,
                   submission_id: str | None = None,
                   now: float | None = None) -> dict:
    """intern 为一道 Assignment 里的 ONE 产品提交一份 Submission。

    守卫顺序(fail fast,越根本越先拦):
      1. Assignment 存在 & 可提交(claimed + 本人持有)—— 否则 NotSubmittable。
      2. product 在该 Assignment 参赛产品集内 —— 否则 WrongProduct(领取粒度)。
      3. 有原始产物 —— 否则 EvidenceMissing(无证据不入池,#43 AC3)。
      4. 有执行日志包 —— 否则 LogBundleMissing(无日志包不入池,#45 AC1)。
    四关全过才落库(store.upsert_submission,幂等 on (assignment_id, product):
    同产品重交覆盖旧的)。注意日志「文件」强制,但包内字段拿不到照 unavailable
    透传给 intake(不伪造 0)—— 两个层级不矛盾。

    返回落库后的 submission 行(dict,manual_assertions 已解析)。
    """
    a = store.get_assignment(con, assignment_id)
    if a is None:
        raise NotSubmittable(f"Assignment 不存在: {assignment_id!r}")
    if a.get("status") != "claimed":
        raise NotSubmittable(
            f"Assignment {assignment_id!r} 当前 {a.get('status')!r}, "
            f"只有 claimed(已领取未交)可提交")
    if submitted_by is not None and a.get("claimed_by") != submitted_by:
        raise NotSubmittable(
            f"只有领取者可提交: {assignment_id!r} 归 {a.get('claimed_by')!r}, "
            f"非 {submitted_by!r}(谁领谁交)")

    products = a.get("products") or []
    if product not in products:
        raise WrongProduct(
            f"产品 {product!r} 不在 Assignment {assignment_id!r} 参赛集 "
            f"{products!r} 内(领取粒度: 只给同域参赛产品提交)")

    if not _has_artifact(artifact_path):
        raise EvidenceMissing(
            f"缺原始产物(截图/导出文件/AI 对话记录): {assignment_id!r}/{product!r} "
            f"—— 无证据不入池,提交被拒")

    if not _has_log_bundle(log_bundle_path):
        raise LogBundleMissing(
            f"缺执行日志包(时间线/token/调用次数): {assignment_id!r}/{product!r} "
            f"—— 成本与过程须有真实来源,无日志包不入池 (#45 AC1),提交被拒")

    sid = submission_id or f"sub-{assignment_id}-{product}-{uuid.uuid4().hex[:8]}"
    store.upsert_submission(con, {
        "id": sid,
        "assignment_id": assignment_id,
        "product": product,
        "artifact_path": artifact_path,
        "log_bundle_path": log_bundle_path,
        "manual_assertions": manual_assertions or {},
        "machine_ctx": machine_ctx or {},
        "claimed_success": claimed_success,
        "submitted_by": submitted_by,
        "submitted_ts": now if now is not None else time.time(),
        "transcript_excerpt": transcript_excerpt,
        "competitor_version": competitor_version,
        "tested_at": tested_at,
    })
    return _submission_row(con, assignment_id, product)


def delete_product(con, *, assignment_id: str, product: str,
                   requested_by: str | None = None) -> dict | None:
    """收口前撤回某产品已上传的产物(删这份 Submission)。

    守卫顺序(与 submit_product 对称,谁领谁改):
      1. Assignment 存在 —— 否则 NotSubmittable。
      2. 仍处于 claimed(未收口)—— submitted 之后不可再改(收口后产物冻结)。
      3. 本人持有 —— 只有领取者可删自己的产物。
    删掉该产品的 Submission 行,返回被删行的文件路径(供 Web 层删磁盘);该产品
    本没交过 -> None(幂等)。product 是否在参赛集不再校验(删本就存在的行即可)。
    """
    a = store.get_assignment(con, assignment_id)
    if a is None:
        raise NotSubmittable(f"Assignment 不存在: {assignment_id!r}")
    if a.get("status") != "claimed":
        raise NotSubmittable(
            f"Assignment {assignment_id!r} 当前 {a.get('status')!r}, "
            f"只有 claimed(已领取未收口)可撤回产物(收口后产物已冻结)")
    if requested_by is not None and a.get("claimed_by") != requested_by:
        raise NotSubmittable(
            f"只有领取者可撤回产物: {assignment_id!r} 归 {a.get('claimed_by')!r}, "
            f"非 {requested_by!r}(谁领谁改)")
    return store.delete_submission(con, assignment_id, product)


def _submission_row(con, assignment_id: str, product: str) -> dict:
    for row in store.submissions_for(con, assignment_id):
        if row.get("product") == product:
            return row
    raise SubmissionError(
        f"落库后读回失败: {assignment_id!r}/{product!r}")


def submission_progress(con, assignment_id: str) -> dict:
    """一道 Assignment 的提交进度: 参赛集里哪些产品已交、哪些还缺。

    用于前端「整组对打」看板 + 判断能否收口(每个产品各一份才算齐)。
    """
    a = store.get_assignment(con, assignment_id)
    if a is None:
        raise SubmissionError(f"Assignment 不存在: {assignment_id!r}")
    products = a.get("products") or []
    submitted = {row["product"] for row in store.submissions_for(con, assignment_id)}
    missing = [p for p in products if p not in submitted]
    return {
        "assignment_id": assignment_id,
        "products": products,
        "submitted": sorted(submitted),
        "missing": missing,
        "complete": len(missing) == 0 and len(products) > 0,
    }


def to_run_record(con, *, assignment_id: str, product: str,
                  task_meta, registry):
    """把一份已落库的 Submission 流向 #38 intake 接缝 -> RunRecord (#43 AC4)。

    这是「提交 → 引擎」的接线: 从 store 读回该产品的 Submission 行,adapt 成
    intake.Submission,交给 intake.translate(GATE 派生 / 客观断言 / 成本解析 /
    脱敏……评分核心一字不改复用)。纯读派生,不改状态机。

    找不到该产品的 Submission -> SubmissionError。
    """
    row = None
    for r in store.submissions_for(con, assignment_id):
        if r.get("product") == product:
            row = r
            break
    if row is None:
        raise SubmissionError(
            f"无此产品的 Submission: {assignment_id!r}/{product!r}")
    row.setdefault("task_id", _task_id_of(con, assignment_id))
    sub = Submission.from_store_row(row)
    return INTAKE.translate(sub, task_meta, registry)


def _task_id_of(con, assignment_id: str) -> str:
    a = store.get_assignment(con, assignment_id)
    return (a or {}).get("task_id", "") if a else ""
