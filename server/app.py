"""FastAPI JSON API over the existing pipeline modules.

Wraps store / leaderboard / probe / sampling — the eval ENGINE is untouched.
This layer only reads the SQLite single-source-of-truth and exposes it as JSON
for the React + AntD frontend, plus a few write-back endpoints (PM judgment,
spot-check verdicts, queue rebuild).

Run:  uvicorn server.app:app --port 8600   (from repo root)
"""
from __future__ import annotations

import json

from fastapi import (FastAPI, HTTPException, Header, Depends, UploadFile, File,
                     Form)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from pipeline import store, leaderboard as LB, findings as F, sampling as SP
from pipeline import probe as PROBE
from pipeline import catalog as CATALOG
from pipeline import auth as AUTH
from pipeline import rbac as RBAC
from pipeline import assignments as ASSIGN
from pipeline import submissions as SUB
from pipeline import artifact_store as ART

app = FastAPI(title="Competitor Eval API", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_DB_PATH = None  # default board/competitor_eval.db


def _con():
    return store.connect(_DB_PATH)


@app.get("/api/health")
def health():
    con = _con()
    n = con.execute("SELECT COUNT(*) FROM scores").fetchone()[0]
    return {"ok": True, "scores": n}


# --- glossary: machine field -> plain Chinese (人话原则) -------------------
GLOSSARY = {
    "capability": {"label": "能力分", "hint": "这道题它做得多好,0–100 分,越高越强。"},
    "honesty": {"label": "诚实度", "hint": "它说『做完了』是不是真做完了。1=谎报,5=老实。独立于能力,不混在一起。"},
    "gate": {"label": "能否参赛", "hint": "这道题的环境它够不够得着。够不着(cannot-reach)就不参与公平对比,不会被冤枉打 0 分。"},
    "objective_ratio": {"label": "硬性完成度", "hint": "靠末态事实查到的完成比例(消息真发出没),不看它自己怎么说。"},
    "disagreement": {"label": "评委分歧大", "hint": "三个 AI 评委打分差太多(极差≥2),这条需要人复核。"},
    "defects": {"label": "评委挑出的毛病", "hint": "评审面板指出的实质缺陷,哪个评委挑的都记下来。"},
    "cost": {"label": "成本", "hint": "花了多少 token / 调用几次 / 折算多少钱,必须和『是否真完成』一起看。"},
    "kappa": {"label": "AI评委可信度", "hint": "AI 评委和人工标准答案的一致率,够高才被授权自动打分。"},
}


@app.get("/api/glossary")
def glossary():
    return GLOSSARY


@app.get("/api/overview")
def overview():
    """Dashboard summary numbers."""
    con = _con()
    n_scores = con.execute("SELECT COUNT(*) FROM scores").fetchone()[0]
    n_products = con.execute("SELECT COUNT(DISTINCT product) FROM scores").fetchone()[0]
    n_tasks = con.execute("SELECT COUNT(DISTINCT task_id) FROM scores").fetchone()[0]
    n_findings = con.execute("SELECT COUNT(*) FROM findings").fetchone()[0]
    n_pending = con.execute(
        "SELECT COUNT(*) FROM spot_check_queue WHERE status='pending'").fetchone()[0]
    n_undecided = con.execute(
        "SELECT COUNT(*) FROM findings WHERE product_judgment IS NULL").fetchone()[0]
    return {
        "products": n_products,
        "tasks": n_tasks,
        "scores": n_scores,
        "findings": n_findings,
        "findings_undecided": n_undecided,
        "spotcheck_pending": n_pending,
    }


@app.get("/api/leaderboard")
def get_leaderboard(baseline: str = "vio"):
    return LB.from_store(_con(), baseline=baseline)


@app.get("/api/scores")
def get_scores():
    return store.all_scores(_con())


@app.get("/api/score/{task_id}/{product}")
def get_score(task_id: str, product: str):
    import json
    con = _con()
    row = con.execute(
        "SELECT * FROM scores WHERE task_id=? AND product=?",
        (task_id, product)).fetchone()
    if not row:
        raise HTTPException(404, "score not found")
    d = dict(row)
    for k in ("subjective_json", "disagreement_json", "defects_json"):
        try:
            d[k.replace("_json", "")] = json.loads(d.get(k) or "null")
        except Exception:
            d[k.replace("_json", "")] = None
    run = con.execute(
        "SELECT * FROM runs WHERE task_id=? AND product=?",
        (task_id, product)).fetchone()
    d["run"] = dict(run) if run else None
    return d


@app.get("/api/cost")
def get_cost():
    return store.cost_with_completion(_con())


@app.get("/api/findings")
def get_findings():
    import json
    rows = store.all_findings(_con())
    for r in rows:
        try:
            r["evidence"] = json.loads(r.get("evidence_json") or "null")
        except Exception:
            r["evidence"] = None
    return rows


@app.get("/api/probes")
def get_probes():
    import json
    rows = PROBE.probe_findings(_con())
    for r in rows:
        try:
            r["evidence"] = json.loads(r.get("evidence_json") or "null")
        except Exception:
            r["evidence"] = None
    return rows


@app.get("/api/catalog")
def get_catalog():
    """MR-5 (#41): 按能力域分组的任务清单 (只读派生视图, 不含领取).

    intern 浏览未领取前的题库: 每组 = 一个能力域 (同域才同台), 每题带中立标准
    Prompt + 说明 + 参赛竞品 (GATE 派生). 领取动作在 #42, 这里只到「看得到」.
    """
    return CATALOG.build_catalog()


@app.get("/api/catalog/{task_id}")
def get_catalog_task(task_id: str):
    card = CATALOG.task_detail(task_id)
    if card is None:
        raise HTTPException(404, "task not found in catalog")
    return card


@app.get("/api/spotcheck")
def get_spotcheck(status: str | None = None):
    return store.spot_check_queue(_con(), status=status)


@app.get("/api/authorizations")
def get_authorizations():
    return store.all_authorizations(_con())


@app.get("/api/enums")
def get_enums():
    return {
        "product_judgment": list(F.PRODUCT_JUDGMENT_VALUES),
        "final_category": list(F.FINAL_CATEGORY_VALUES),
        "suspected": list(F.SUSPECTED_VALUES),
    }


# === MR-3 (#39) 账号: 私发链接自注册登录 =================================
def current_user(authorization: str | None = Header(default=None)):
    """依赖注入: 从 Authorization: Bearer <token> 解析当前用户与角色 (story 1)."""
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    return AUTH.whoami(_con(), token)


class InviteIn(BaseModel):
    note: str | None = None
    ttl_seconds: float | None = None
    created_by: str | None = None


@app.post("/api/invites")
def issue_invite(body: InviteIn, user=Depends(current_user)):
    """PM 签发私发注册链接。仅 owner 可签发 (story 2: 不对公网开放)。"""
    try:
        RBAC.require(user, "issue_invite")
    except RBAC.PermissionDenied as e:
        raise HTTPException(403, str(e))
    inv = AUTH.issue_invite(_con(), created_by=user["id"],
                            note=body.note, ttl_seconds=body.ttl_seconds)
    return {"token": inv["token"], "note": inv.get("note"),
            "expires_ts": inv.get("expires_ts")}


class RegisterIn(BaseModel):
    invite_token: str
    name: str | None = None


@app.post("/api/register")
def register(body: RegisterIn):
    """持有效链接自注册 -> 默认 intern -> 注册即登录拿会话令牌。

    无链接/链接失效 -> 400 (无链接不能注册, story 2)。
    """
    try:
        res = AUTH.register(_con(), invite_token=body.invite_token, name=body.name)
    except AUTH.AuthError as e:
        raise HTTPException(400, str(e))
    return {"session_token": res["session_token"],
            "user": {"id": res["user"]["id"], "name": res["user"]["name"],
                     "role": res["user"]["role"]}}


class LoginIn(BaseModel):
    user_id: str


@app.post("/api/login")
def login(body: LoginIn):
    """已注册用户换发新会话令牌 (无密码, 链接即凭证; ADR-0019 最薄)。"""
    try:
        token = AUTH.login(_con(), user_id=body.user_id)
    except AUTH.AuthError as e:
        raise HTTPException(401, str(e))
    return {"session_token": token}


@app.get("/api/me")
def me(user=Depends(current_user)):
    """会话可识别当前用户与角色 (story 1 AC)。未登录 -> 401。"""
    if not user:
        raise HTTPException(401, "未登录或会话已失效")
    return {"id": user["id"], "name": user.get("name"), "role": user["role"]}


@app.post("/api/logout")
def logout(authorization: str | None = Header(default=None)):
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if token:
        AUTH.logout(_con(), token)
    return {"ok": True}


# === MR-4 (#40) RBAC: 角色提升 + 权限边界 ==============================
@app.get("/api/users")
def list_users(user=Depends(current_user)):
    """列出所有用户与角色 (PM 管理角色用)。owner 独占 (提升属校准类危险权限)。"""
    try:
        RBAC.require(user, "promote_user")
    except RBAC.PermissionDenied as e:
        raise HTTPException(403, str(e))
    return [{"id": u["id"], "name": u.get("name"), "role": u["role"]}
            for u in store.all_users(_con())]


class PromoteIn(BaseModel):
    role: str            # intern | reviewer | owner


@app.post("/api/users/{user_id}/role")
def promote_user(user_id: str, body: PromoteIn, user=Depends(current_user)):
    """owner 把某 intern 提升为 reviewer (story 4)。

    非 owner -> 403 (校准/授权类危险开关 owner 独占, story 5)。
    非法角色 / 用户不存在 -> 400。
    """
    try:
        updated = RBAC.promote(_con(), actor=user, target_user_id=user_id,
                               new_role=body.role)
    except RBAC.PermissionDenied as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"id": updated["id"], "name": updated.get("name"),
            "role": updated["role"]}


# === MR-6 (#42) 并发领取 + Assignment 状态机 (ADR-0015) ===================
def _assignment_view(a: dict) -> dict:
    """对外投影: 只暴露状态机需要的字段 (含参赛产品集)。"""
    return {
        "id": a["id"],
        "task_id": a["task_id"],
        "products": a.get("products"),
        "status": a["status"],
        "claimed_by": a.get("claimed_by"),
        "claimed_ts": a.get("claimed_ts"),
    }


@app.get("/api/assignments")
def list_open_assignments(user=Depends(current_user)):
    """列出可领取 (open) 的 Assignment。任意已登录用户可看 (intern 起)。"""
    try:
        RBAC.require(user, "claim_assignment")
    except RBAC.PermissionDenied as e:
        raise HTTPException(403, str(e))
    con = _con()
    return [_assignment_view(store.get_assignment(con, a["id"]))
            for a in store.open_assignments(con)]


class MaterializeIn(BaseModel):
    task_id: str


@app.post("/api/assignments/materialize")
def materialize_assignment(body: MaterializeIn, user=Depends(current_user)):
    """把清单里的一道题铸成可领取的 Assignment (含同域参赛产品集, ADR-0015)。

    维护任务清单属 owner 独占 (story 5, manage_task_catalog)。幂等: 同题复用原单。
    """
    try:
        RBAC.require(user, "manage_task_catalog")
    except RBAC.PermissionDenied as e:
        raise HTTPException(403, str(e))
    try:
        a = ASSIGN.materialize_for_task(_con(), body.task_id)
    except ASSIGN.AssignmentError as e:
        raise HTTPException(400, str(e))
    return _assignment_view(a)


@app.post("/api/assignments/{assignment_id}/claim")
def claim_assignment(assignment_id: str, user=Depends(current_user)):
    """intern 领取一道 Assignment (整组对打一人一次性, ADR-0015)。

    并发领取: 两人抢同一道只一个成功 (store 原子锁), 落败方见 409 已锁定。
    """
    try:
        RBAC.require(user, "claim_assignment")
    except RBAC.PermissionDenied as e:
        raise HTTPException(403, str(e))
    con = _con()
    try:
        a = ASSIGN.claim(con, assignment_id, user["id"])
    except ASSIGN.IllegalTransition as e:
        raise HTTPException(409, str(e))     # 已被别人锁定 / 非 open
    except ASSIGN.AssignmentError as e:
        raise HTTPException(404, str(e))
    return _assignment_view(a)


@app.post("/api/assignments/{assignment_id}/abandon")
def abandon_assignment(assignment_id: str, user=Depends(current_user)):
    """放弃已领取的 Assignment -> 回到清单可被再领 (story 12)。仅持有者可放弃。"""
    try:
        RBAC.require(user, "claim_assignment")
    except RBAC.PermissionDenied as e:
        raise HTTPException(403, str(e))
    con = _con()
    try:
        a = ASSIGN.abandon(con, assignment_id, by=user["id"])
    except ASSIGN.IllegalTransition as e:
        raise HTTPException(409, str(e))
    except ASSIGN.AssignmentError as e:
        # 不存在 -> 404; 非持有者 -> 403
        code = 404 if "不存在" in str(e) else 403
        raise HTTPException(code, str(e))
    return _assignment_view(a)


@app.post("/api/assignments/{assignment_id}/submit")
def submit_assignment(assignment_id: str, user=Depends(current_user)):
    """把已领取的 Assignment 标记 submitted (claimed -> submitted)。仅持有者可交。"""
    try:
        RBAC.require(user, "submit")
    except RBAC.PermissionDenied as e:
        raise HTTPException(403, str(e))
    con = _con()
    try:
        a = ASSIGN.submit(con, assignment_id, by=user["id"])
    except ASSIGN.IllegalTransition as e:
        raise HTTPException(409, str(e))
    except ASSIGN.AssignmentError as e:
        code = 404 if "不存在" in str(e) else 403
        raise HTTPException(code, str(e))
    return _assignment_view(a)


@app.post("/api/assignments/reclaim-stale")
def reclaim_stale_assignments(user=Depends(current_user)):
    """扫描领了太久没交的 Assignment 扫回 open (超时回收, story 12)。owner 触发。"""
    try:
        RBAC.require(user, "manage_task_catalog")
    except RBAC.PermissionDenied as e:
        raise HTTPException(403, str(e))
    reclaimed = ASSIGN.reclaim_stale(_con())
    return {"reclaimed": reclaimed, "count": len(reclaimed)}


# === MR-7 (#43) 提交表单 + 原始产物上传 + 缺证据拒收 =====================
@app.get("/api/assignments/{assignment_id}/submissions")
def list_submissions(assignment_id: str, user=Depends(current_user)):
    """一道 Assignment 的提交进度: 参赛集里哪些产品已交、哪些还缺 (整组对打看板)。

    任意已登录用户(intern 起)可看自己领的活的进度。
    """
    try:
        RBAC.require(user, "submit")
    except RBAC.PermissionDenied as e:
        raise HTTPException(403, str(e))
    try:
        return SUB.submission_progress(_con(), assignment_id)
    except SUB.SubmissionError as e:
        raise HTTPException(404, str(e))


@app.post("/api/assignments/{assignment_id}/submissions")
async def submit_submission(
    assignment_id: str,
    product: str = Form(...),
    artifact: UploadFile | None = File(default=None),
    log_bundle: UploadFile | None = File(default=None),
    manual_assertions: str | None = Form(default=None),
    claimed_success: bool | None = Form(default=None),
    transcript_excerpt: str = Form(default=""),
    competitor_version: str | None = Form(default=None),
    tested_at: float | None = Form(default=None),
    user=Depends(current_user),
):
    """intern 为一道 Assignment 里的一个产品提交一份 Submission (multipart)。

    先落盘原始产物 + 日志包(服务端文件目录, ADR-0019 库里只存路径), 再走
    submissions 策略层的三关守卫(可提交 / 产品在参赛集 / 有原始产物)。
    缺原始产物 -> 400(无证据不入池, story 17 / AC3)。落库成功即流向 #38 intake。
    """
    try:
        RBAC.require(user, "submit")
    except RBAC.PermissionDenied as e:
        raise HTTPException(403, str(e))

    con = _con()

    # 1. 原始产物落盘(缺内容 -> 不落盘, 交由策略层拒收)。
    artifact_path = None
    if artifact is not None:
        data = await artifact.read()
        if ART.has_bytes(data):
            artifact_path = ART.save_upload(
                assignment_id=assignment_id, product=product, kind="artifact",
                filename=artifact.filename, data=data)

    # 2. 日志包落盘(#43 只强制原始产物; 日志包缺失如实透传给 intake)。
    log_bundle_path = None
    if log_bundle is not None:
        data = await log_bundle.read()
        if ART.has_bytes(data):
            log_bundle_path = ART.save_upload(
                assignment_id=assignment_id, product=product, kind="log_bundle",
                filename=log_bundle.filename, data=data)

    # 3. 人工勾选断言(JSON 字符串)解析。
    ticks = None
    if manual_assertions:
        try:
            ticks = json.loads(manual_assertions)
        except (ValueError, TypeError):
            raise HTTPException(400, "manual_assertions 必须是合法 JSON 对象")
        if not isinstance(ticks, dict):
            raise HTTPException(400, "manual_assertions 必须是 JSON 对象(键=断言 ctx 名)")

    # 4. 策略层守卫 + 落库(缺原始产物在此被拒 -> 400)。
    try:
        row = SUB.submit_product(
            con, assignment_id=assignment_id, product=product,
            artifact_path=artifact_path, log_bundle_path=log_bundle_path,
            manual_assertions=ticks, claimed_success=claimed_success,
            submitted_by=user["id"], transcript_excerpt=transcript_excerpt,
            competitor_version=competitor_version, tested_at=tested_at)
    except SUB.EvidenceMissing as e:
        raise HTTPException(400, str(e))       # 无证据不入池
    except SUB.WrongProduct as e:
        raise HTTPException(400, str(e))       # 领取粒度错单
    except SUB.NotSubmittable as e:
        code = 404 if "不存在" in str(e) else 409
        raise HTTPException(code, str(e))

    return {
        "id": row["id"], "assignment_id": assignment_id, "product": product,
        "artifact_path": row.get("artifact_path"),
        "log_bundle_path": row.get("log_bundle_path"),
        "progress": SUB.submission_progress(con, assignment_id),
    }


# --- writes ---------------------------------------------------------------
class JudgmentIn(BaseModel):
    product_judgment: str | None = None
    final_category: str | None = None


@app.post("/api/findings/{finding_id}/judgment")
def set_judgment(finding_id: int, body: JudgmentIn):
    store.set_judgment(_con(), finding_id,
                       product_judgment=body.product_judgment,
                       final_category=body.final_category)
    return {"ok": True, "id": finding_id}


@app.post("/api/spotcheck/rebuild")
def rebuild_spotcheck():
    return SP.build_queue(_con())


class VerdictIn(BaseModel):
    status: str           # ok | anomaly
    checked_by: str = "PM"
    verdict_note: str | None = None


@app.post("/api/spotcheck/{queue_id}/verdict")
def submit_verdict(queue_id: int, body: VerdictIn):
    kwargs = dict(status=body.status, checked_by=body.checked_by,
                  verdict_note=body.verdict_note)
    if body.status == "anomaly":
        kwargs.update(role="reviewer", name="panel")
    SP.submit_verdict(_con(), queue_id, **kwargs)
    return {"ok": True, "id": queue_id}
