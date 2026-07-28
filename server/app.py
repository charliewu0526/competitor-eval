"""FastAPI JSON API over the existing pipeline modules.

Wraps store / leaderboard / probe / sampling — the eval ENGINE is untouched.
This layer only reads the SQLite single-source-of-truth and exposes it as JSON
for the React + AntD frontend, plus a few write-back endpoints (PM judgment,
spot-check verdicts, queue rebuild).

Run:  uvicorn server.app:app --port 8600   (from repo root)
"""
from __future__ import annotations

import json
from typing import Literal

from fastapi import (FastAPI, HTTPException, Header, Depends, UploadFile, File,
                     Form, BackgroundTasks)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from pipeline import store, leaderboard as LB, findings as F, sampling as SP
from pipeline import probe as PROBE
from pipeline import catalog as CATALOG
from pipeline import domain_board as DB
from pipeline import auth as AUTH
from pipeline import rbac as RBAC
from pipeline import assignments as ASSIGN
from pipeline import submissions as SUB
from pipeline import artifact_store as ART
from pipeline import review_queue as RQ
from pipeline import methods as METH
from pipeline import registry as REG
from pipeline import gap_report as GAP
from pipeline import blind_panel as BP
from pipeline import suite as SUITE
from pipeline import intake as INTAKE
from pipeline.intake import Submission as _IntakeSubmission

app = FastAPI(title="Competitor Eval API", version="1.0")
# CORS 白名单: 默认只放本地前端 (Vite 5273 / 常见 3000)。生产用 env 明列前端域名,
# 不再 allow_origins=["*"] —— 配合 Bearer 写端点, 通配来源会放大跨站写风险。
import os as _os
_CORS_ORIGINS = [o.strip() for o in _os.environ.get(
    "CORS_ALLOWED_ORIGINS",
    "http://127.0.0.1:5273,http://localhost:5273,"
    "http://127.0.0.1:3000,http://localhost:3000").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

_DB_PATH = None  # default board/competitor_eval.db


_migrated_for = None   # 记录已完成建表+迁移的 _DB_PATH(进程内一次)


def _con():
    # H-3: 建表+迁移是一次性动作。首个请求(或 _DB_PATH 变更, 如测试切临时库)迁移一次,
    # 之后每请求 skip_migrate=True 只开连接, 免得每个请求都重跑 executescript +
    # 11 张表 PRAGMA + SCHEMA 正则解析的风暴。不依赖 lifespan(TestClient 直连不触发)。
    global _migrated_for
    if _migrated_for != _DB_PATH:
        store.connect(_DB_PATH).close()   # 完整建表+迁移
        _migrated_for = _DB_PATH
    return store.connect(_DB_PATH, skip_migrate=True)


@app.get("/api/health")
def health():
    # M-2: DB 抖动/损坏时降级为 503(ok:False), 不裸穿透成 500 栈迹。
    try:
        con = _con()
        n = con.execute("SELECT COUNT(*) FROM scores").fetchone()[0]
        return {"ok": True, "scores": n}
    except Exception as e:
        raise HTTPException(503, f"数据库不可用: {e}")


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
    try:
        con = _con()
        return _overview_body(con)
    except Exception as e:                      # M-2: DB 抖动降级, 不裸穿透 500
        raise HTTPException(503, f"数据库不可用: {e}")


def _overview_body(con):
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


@app.get("/api/domain-board")
def get_domain_board(baseline: str = "vio",
                     window_days: int = DB.DEFAULT_FRESHNESS_DAYS):
    """MR-12 (#48): 能力域分维度榜单 + 版本/日期/stale (派生视图, 引擎不改).

    按 capability_domain 分桶, 每桶复用 leaderboard 排一张榜 (同域才同台)。
    每条分数透传竞品版本 + 测试日期; 超 window_days 天标 stale (ADR-0017); cannot-reach
    产品归入该榜 excluded (标「未参赛」而非 0 分垫底)。
    """
    return DB.from_store(_con(), baseline=baseline, window_days=window_days)


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


@app.get("/api/gap-report")
def list_gap_report_tasks(baseline: str = "vio"):
    """MR-11 (#47): 差距报告可选任务列表 (派生视图, 引擎不改).

    每道对比任务(有 score 落库的 task_id)产一份差距报告。这里只列出「哪些题
    能看差距报告」+ 一行摘要(参赛产品数 / 大差距条数),供前端下拉选题。
    """
    con = _con()
    scores = store.all_scores(con)
    finds = store.all_findings(con)
    reg = REG.default_registry()
    task_ids = sorted({s.get("task_id") for s in scores if s.get("task_id")})
    out = []
    for tid in task_ids:
        rep = GAP.build_report(tid, scores, finds, registry=reg, baseline=baseline)
        n_big_gap = sum(1 for d in rep.score_diffs if d.big_gap)
        n_big_lag = sum(1 for d in rep.score_diffs if d.big_lag)
        out.append({
            "task_id": tid,
            "products": len(rep.score_diffs),
            "big_gaps": n_big_gap,
            "big_lags": n_big_lag,
            "findings": len(rep.findings),
        })
    return {"baseline": baseline, "tasks": out}


@app.get("/api/gap-report/{task_id}")
def get_gap_report(task_id: str, baseline: str = "vio"):
    """MR-11 (#47): 一道对比任务的完整差距报告 (派生视图, 引擎不改)."""
    con = _con()
    scores = store.all_scores(con)
    finds = store.all_findings(con)
    if not any(s.get("task_id") == task_id for s in scores):
        raise HTTPException(404, "no scores for this task")
    rep = GAP.build_report(task_id, scores, finds,
                           registry=REG.default_registry(), baseline=baseline)
    return rep.as_dict()


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


def rbac(action: str):
    """RBAC dependency factory (体检 M-1): 消除 22 处重复的 try/RBAC.require/except.

    用法把端点签名的 `user=Depends(current_user)` 换成 `user=rbac("<action>")` —— 鉴权
    通过则注入 user dict, 不通过统一翻 403。好处: (1) 忘记加鉴权在签名上就看得出;
    (2) 权限动作作为依赖声明的一部分, 端点体只剩业务逻辑。路由 URL / HTTP 方法 /
    响应体一字不变, test_server_smoke 的路由契约不受影响。
    """
    def _guard(user=Depends(current_user)) -> dict:
        try:
            return RBAC.require(user, action)
        except RBAC.PermissionDenied as e:
            raise HTTPException(403, str(e))
    return Depends(_guard)


class InviteIn(BaseModel):
    note: str | None = None
    ttl_seconds: float | None = None
    created_by: str | None = None


@app.post("/api/invites")
def issue_invite(body: InviteIn, user=rbac("issue_invite")):
    """PM 签发私发注册链接。仅 owner 可签发 (story 2: 不对公网开放)。"""
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
def list_users(user=rbac("promote_user")):
    """列出所有用户与角色 (PM 管理角色用)。owner 独占 (提升属校准类危险权限)。"""
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
    products = a.get("products")
    product = a.get("product")
    if product is None and isinstance(products, list) and len(products) == 1:
        product = products[0]
    return {
        "id": a["id"],
        "task_id": a["task_id"],
        "products": products,
        "product": product,          # 方案B: 单产品领取单元的产品(整题遗留单元为 None)
        "status": a["status"],
        "claimed_by": a.get("claimed_by"),
        "claimed_ts": a.get("claimed_ts"),
    }


@app.get("/api/assignments")
def list_open_assignments(user=rbac("claim_assignment")):
    """列出可领取 (open) 的 Assignment + 当前用户已领取/已交付的活。

    修复: 只返回 open 会让 intern 领取后任务立即从「我的任务」消失,
    再也进不了提交环节。这里并上 assignments_for_user(当前用户持有的
    claimed/submitted),前端 AssignmentCard 按 mine+status 渲染提交/收口。
    """
    con = _con()
    seen = {}
    for a in store.open_assignments(con):
        seen[a["id"]] = a
    for a in store.assignments_for_user(con, user["id"]):
        seen[a["id"]] = a
    return [_assignment_view(store.get_assignment(con, aid)) for aid in seen]


class MaterializeIn(BaseModel):
    task_id: str


@app.post("/api/assignments/materialize")
def materialize_assignment(body: MaterializeIn, user=rbac("manage_task_catalog")):
    """把清单里的一道题铸成可领取的 Assignment (含同域参赛产品集, ADR-0015)。

    维护任务清单属 owner 独占 (story 5, manage_task_catalog)。幂等: 同题复用原单。
    """
    try:
        a = ASSIGN.materialize_for_task(_con(), body.task_id)
    except ASSIGN.AssignmentError as e:
        raise HTTPException(400, str(e))
    return _assignment_view(a)


@app.post("/api/assignments/{assignment_id}/claim")
def claim_assignment(assignment_id: str, user=rbac("claim_assignment")):
    """intern 领取一道 Assignment (整组对打一人一次性, ADR-0015)。

    并发领取: 两人抢同一道只一个成功 (store 原子锁), 落败方见 409 已锁定。
    """
    con = _con()
    try:
        a = ASSIGN.claim(con, assignment_id, user["id"])
    except ASSIGN.IllegalTransition as e:
        raise HTTPException(409, str(e))     # 已被别人锁定 / 非 open
    except ASSIGN.AssignmentError as e:
        raise HTTPException(404, str(e))
    return _assignment_view(a)


class CatalogClaimIn(BaseModel):
    task_id: str
    product: str | None = None      # 方案B: 领某一个参赛产品; 缺省=旧整题领取(兼容)


@app.post("/api/catalog/{task_id}/claim")
def claim_from_catalog(task_id: str, body: CatalogClaimIn | None = None,
                       user=rbac("claim_assignment")):
    """intern 在任务清单页直接领取 (PRD story 8: 自助领取)。

    方案B (领取粒度细化到「题×产品」): body.product 给出时, 只领这道题的这个
    产品 (materialize 该产品子单元 + claim), 不同人可用各自账号领同题不同产品。
    product 缺省时回退旧的「整题领取」(向后兼容旧前端/脚本)。

    铸造是领取的内部副作用 (不落 manage_task_catalog 权限门), 领取仍需
    claim_assignment 权限, 并发/重复由 store 原子锁兜底。
    铸造失败(题不在清单/产品够不着) -> 400; 已被别人领 -> 409。
    """
    con = _con()
    product = body.product if body else None
    try:
        if product:
            a = ASSIGN.materialize_product_for_task(con, task_id, product)
        else:
            a = ASSIGN.materialize_for_task(con, task_id)
    except ASSIGN.AssignmentError as e:
        raise HTTPException(400, str(e))
    # 已被领取(claimed/submitted): 给人话提示, 不静默失败。
    if a["status"] != "open":
        who = a.get("claimed_by")
        mine = who == user["id"]
        what = f"这道题的 {product}" if product else "这道题"
        raise HTTPException(
            409,
            f"{what}已被你领取,去『我的任务』继续。" if mine
            else f"{what}已被 {who} 领取,换一个吧。")
    try:
        a = ASSIGN.claim(con, a["id"], user["id"])
    except ASSIGN.IllegalTransition as e:
        raise HTTPException(409, str(e))
    except ASSIGN.AssignmentError as e:
        raise HTTPException(404, str(e))
    return _assignment_view(a)


@app.post("/api/assignments/{assignment_id}/abandon")
def abandon_assignment(assignment_id: str, user=rbac("claim_assignment")):
    """放弃已领取的 Assignment -> 回到清单可被再领 (story 12)。仅持有者可放弃。"""
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


def _read_artifact_summary(artifact_path, *, max_chars: int = 4000) -> str:
    """把上传的原始产物读成一段可喂评审面板的文本摘要 (走查头号硬伤的修复).

    文本产物(titles.txt / .md / .csv / .json 等)直读并截断; 二进制(截图/xlsx)
    只给文件名 + 大小说明(面板据此知道"有产物"而非误判"没做"); 缺失/读不动
    安全降级为 (none)。绝不因读产物失败而阻塞收口。
    """
    import pathlib as _p
    if not artifact_path:
        return "(none)"
    try:
        p = _p.Path(artifact_path).expanduser()
        if not p.exists():
            return "(none)"
        data = p.read_bytes()
        if not data:
            return "(empty file)"
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return f"(binary artifact: {p.name}, {len(data)} bytes)"
        text = text.strip()
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n…(truncated, total {len(text)} chars)"
        return f"[artifact {p.name}]\n{text}"
    except OSError:
        return "(none)"


def _score_assignment_into_board(con, assignment_id: str) -> dict:
    """收口后把该 Assignment 的整组 Submission 翻成 RunRecord + 独立盲评分并落库。

    这是 #43 AC4 承诺的「落库即流向 intake」的真正接线: 收口成功 -> 每个产品的
    Submission 经 intake.translate 成 RunRecord, 送盲评面板独立打分, upsert 进
    runs + scores, 榜单据此更新。纯派生, 不改状态机。

    失败(面板超时/密钥失效/任务无断言模块)只回报 status, 绝不阻塞收口 ——
    实习生已交的活不能因为评分环节抖动而回滚。
    """
    import logging
    a = store.get_assignment(con, assignment_id)
    if a is None:
        return {"status": "skipped", "reason": "assignment 不存在"}
    task_id = a.get("task_id")
    # 1. 定位 task_meta (suite.LoadedTask: 带 task_spec + assertions)。
    loaded = {t.task_spec.task_id: t for t in SUITE.discover_tasks()}
    lt = loaded.get(task_id)
    if lt is None:
        return {"status": "skipped", "reason": f"任务 {task_id} 不在任务库"}
    # 2. 把该 Assignment 每个产品的 Submission 读回, adapt 成 intake.Submission。
    #    同时把每个产品上传的**原始产物内容**读出来做成 artifact_summary,
    #    这是评审面板判「做没做成」的核心证据——不喂产物, 面板只见日志包会把明明
    #    做对的任务全判成「无产物/没做」(走查发现的头号硬伤)。
    subs = []
    ctx_by_product = {}
    for row in store.submissions_for(con, assignment_id):
        row = dict(row)
        row.setdefault("task_id", task_id)
        subs.append(_IntakeSubmission.from_store_row(row))
        ctx_by_product[row["product"]] = {
            "artifact_summary": _read_artifact_summary(row.get("artifact_path")),
            "screenshots_note": row.get("transcript_excerpt", "") or "(none)",
        }
    if not subs:
        return {"status": "skipped", "reason": "无 submission 可评分"}
    # 3. 独立盲评 -> 落 runs + scores (真实评审面板, REVIEW_PANEL 决定成员)。
    #    ctx_by_product 把产物内容送进面板上下文(经 blind_panel 脱敏后再喂模型)。
    reg = REG.default_registry()
    blind = BP.score_submissions(subs, lt, reg, ctx_by_product=ctx_by_product)
    BP.persist_blind_scores(con, blind)

    # 4. 收口重评 => 重新生成发现池 (走查 BUG-2/3 修复)。
    #    先清同 task 旧 findings (上一轮旧竞品集的残留会造成「幽灵竞品」+ 与本轮
    #    产物不符的 defect), 再按**本轮**scores 重新 classify —— 发现池永远只反映
    #    最近一次评测的真实产物, 不与历史脏数据混显。evidence 喂产物摘要, 供机理挖掘。
    store.delete_findings_for_task(con, task_id)
    scores = [b.score for b in blind]
    evidence = {}
    for b in blind:
        summary = ctx_by_product.get(b.product, {}).get("artifact_summary", "")
        evidence[b.product] = [{"source": "artifact",
                                "ref": (summary or "")[:200]}]
    finds = F.classify(task_id, scores, evidence=evidence)
    for fnd in finds:
        # 逐条兜底(优化点2): 单条 finding 落库失败不拖垮整批评分事务 ——
        # 否则一条坏数据(如历史脏行/序列冲突)会让整个收口重评崩, 谎报竞品的
        # honesty-alert 全军覆没(BUG-5 已治本, 这里再加一层防御, 单条坏不影响其余)。
        try:
            store.upsert_finding(con, fnd)
        except Exception:  # noqa: BLE001
            logging.getLogger("competitor-eval").exception(
                "upsert_finding 失败 task=%s subject=%s", task_id, fnd.subject)
            try:
                con.rollback()   # 清掉 PG 的 aborted-transaction 状态, 才能继续下一条
            except Exception:  # noqa: BLE001
                pass

    # 5. 收口评分落库后**自动重建分层抽查队列**(优化点1): 否则实习生收口后, 高风险/
    #    矛盾疑点不会自动进队列, reviewer 要手动点「重建」才看得到, 极易漏看谎报。
    #    自动 rebuild 让「收口 -> 疑点入队 -> reviewer 复核」全自动衔接。失败只记日志,
    #    不影响已落库的评分。
    try:
        SP.build_queue(con)
    except Exception:  # noqa: BLE001
        logging.getLogger("competitor-eval").exception(
            "自动重建抽查队列失败 task=%s", task_id)

    return {"status": "scored", "products": [b.product for b in blind],
            "count": len(blind), "findings": len(finds)}


def _score_assignment_bg(assignment_id: str) -> None:
    """后台评分任务: 独立开连接跑整组盲评入榜, 与收口请求解耦。

    盲评面板真打多模型 (30-90s), 若同步跑, 多实习生并发提交会各占一个请求 worker
    半分钟以上, 拖垮前台。改为 BackgroundTask: 收口请求秒返 (状态已翻 submitted),
    评分在后台完成后落 runs/scores, 榜单随后出分。失败只记日志, 不影响已交付的活。
    """
    import logging
    try:
        con = _con()
        _score_assignment_into_board(con, assignment_id)
    except Exception:  # noqa: BLE001
        logging.getLogger("competitor-eval").exception(
            "后台自动评分失败 assignment=%s", assignment_id)


@app.post("/api/assignments/{assignment_id}/submit")
def submit_assignment(assignment_id: str, background: BackgroundTasks,
                      user=rbac("submit")):
    """把已领取的 Assignment 标记 submitted (claimed -> submitted)。仅持有者可交。

    收口成功后**异步**触发整组评分入榜 (#43 AC4 接线): 评分在后台跑, 收口请求
    立即返回 score_status='scoring'(评分进行中), 前端据此提示「已交付, 评分进行中,
    稍后刷新榜单」。多实习生并发提交互不阻塞 (评分不再占前台 worker)。
    """
    con = _con()
    try:
        a = ASSIGN.submit(con, assignment_id, by=user["id"])
    except ASSIGN.IllegalTransition as e:
        raise HTTPException(409, str(e))
    except ASSIGN.AssignmentError as e:
        code = 404 if "不存在" in str(e) else 403
        raise HTTPException(code, str(e))
    # 收口即返回, 评分丢后台 —— 面板慢不拖垮前台, 也绝不回滚已交付的活。
    background.add_task(_score_assignment_bg, assignment_id)
    view = _assignment_view(a)
    view["score_status"] = {"status": "scoring",
                            "reason": "评分进行中, 稍后刷新榜单查看结果"}
    return view


@app.post("/api/assignments/reclaim-stale")
def reclaim_stale_assignments(user=rbac("manage_task_catalog")):
    """扫描领了太久没交的 Assignment 扫回 open (超时回收, story 12)。owner 触发。"""
    reclaimed = ASSIGN.reclaim_stale(_con())
    return {"reclaimed": reclaimed, "count": len(reclaimed)}


# === MR-7 (#43) 提交表单 + 原始产物上传 + 缺证据拒收 =====================
@app.get("/api/assignments/{assignment_id}/submissions")
def list_submissions(assignment_id: str, user=rbac("submit")):
    """一道 Assignment 的提交进度: 参赛集里哪些产品已交、哪些还缺 (整组对打看板)。

    任意已登录用户(intern 起)可看自己领的活的进度。
    """
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
        raise HTTPException(400, str(e))       # 无原始产物不入池
    except SUB.LogBundleMissing as e:
        raise HTTPException(400, str(e))       # 无日志包不入池 (#45 AC1)
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
# 复核类写端点: 篡改评测结论 / 重建抽查队列 / 写入人工裁定, 都会污染系统可信度,
# 故必须鉴权 (此前裸奔无守卫, 匿名可写 — 已修)。judgment/verdict 是复核动作
# (reviewer 起), rebuild 是抽查队列维护 (owner 独占)。
class JudgmentIn(BaseModel):
    # 枚举值与 findings.PRODUCT_JUDGMENT_VALUES / FINAL_CATEGORY_VALUES 对齐
    # (非法值 pydantic 层即 422, 不再写脏数据入库)。
    product_judgment: Literal[
        "必须补齐", "值得借鉴", "观察中", "不适合Violoop"] | None = None
    final_category: Literal[
        "bug", "feature-gap", "experience-borrow", "honesty-alert",
        "not-actionable"] | None = None


@app.post("/api/findings/{finding_id}/judgment")
def set_judgment(finding_id: int, body: JudgmentIn, user=Depends(current_user)):
    try:
        RBAC.require(user, "review")
    except RBAC.PermissionDenied as e:
        raise HTTPException(403, str(e))
    hit = store.set_judgment(_con(), finding_id,
                             product_judgment=body.product_judgment,
                             final_category=body.final_category)
    if not hit:
        raise HTTPException(404, f"finding {finding_id} 不存在")  # H-2: 不再静默 200
    return {"ok": True, "id": finding_id}


@app.post("/api/spotcheck/rebuild")
def rebuild_spotcheck(user=rbac("manage_task_catalog")):
    return SP.build_queue(_con())


class VerdictIn(BaseModel):
    status: Literal["ok", "anomaly"]     # 非法值 -> pydantic 422, 不再穿透成 500
    verdict_note: str | None = None


@app.post("/api/spotcheck/{queue_id}/verdict")
def submit_verdict(queue_id: int, body: VerdictIn, user=rbac("review")):
    # checked_by 绑定认证身份, 不从请求体取 (此前客户端可伪造 "PM" 签字 — 已修)。
    kwargs = dict(status=body.status, checked_by=user["id"],
                  verdict_note=body.verdict_note)
    if body.status == "anomaly":
        kwargs.update(role="reviewer", name="panel")
    SP.submit_verdict(_con(), queue_id, **kwargs)
    return {"ok": True, "id": queue_id}


# === MR-13 (#49) 人工复核队列 + 职责分离 + 重校准 (ADR-0014) ================
class AssignReviewerIn(BaseModel):
    reviewer_id: str


@app.post("/api/spotcheck/{queue_id}/assign")
def assign_reviewer(queue_id: int, body: AssignReviewerIn,
                    user=Depends(current_user)):
    """把一条复核项指派给某 reviewer (职责分离守卫, AC2)。

    需 'review' 权限 (intern -> 403); 被指派者不能是该 (task,product) 的执行者
    (不自己批自己作业 -> 409)。
    """
    try:
        item = RQ.assign_reviewer(_con(), queue_id,
                                  reviewer=user, reviewer_id=body.reviewer_id)
    except RBAC.PermissionDenied as e:
        raise HTTPException(403, str(e))
    except RQ.SeparationOfDuties as e:
        raise HTTPException(409, str(e))     # 职责分离冲突
    except RQ.ReviewError as e:
        raise HTTPException(404, str(e))
    return item


class ReviewVerdictIn(BaseModel):
    verdict: Literal["reasonable", "problematic"]   # 有道理 / 有问题
    note: str | None = None


@app.post("/api/spotcheck/{queue_id}/review")
def review_verdict(queue_id: int, body: ReviewVerdictIn,
                   user=Depends(current_user)):
    """reviewer/PM 对复核项下「有道理」/「有问题」结论 (AC3)。不触发校准。

    checked_by 绑定认证身份 (防伪造签字)。intern -> 403; 已指派他人且非 owner
    下结论 -> 409。
    """
    try:
        item = RQ.submit_verdict(_con(), queue_id, reviewer=user,
                                 verdict=body.verdict, note=body.note)
    except RBAC.PermissionDenied as e:
        raise HTTPException(403, str(e))
    except RQ.SeparationOfDuties as e:
        raise HTTPException(409, str(e))
    except RQ.ReviewError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "id": queue_id, "status": item.get("status"),
            "verdict": body.verdict}


@app.post("/api/spotcheck/{queue_id}/recalibrate")
def recalibrate_from_review(queue_id: int, user=Depends(current_user)):
    """对一条「有问题」复核项触发黄金集重校准 —— 仅 owner (AC4)。

    危险开关 owner 独占 (reviewer -> 403); 复核项须已是 anomaly (有「有问题」结论)
    才能触发 (否则 400)。
    """
    try:
        out = RQ.trigger_recalibration(_con(), queue_id, actor=user,
                                       role="reviewer", name="panel")
    except RBAC.PermissionDenied as e:
        raise HTTPException(403, str(e))
    except RQ.ReviewError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "id": queue_id,
            "recalibration_triggered": out["recalibration_triggered"],
            "authorization": out["authorization"]}


# === MR-14 (#50) 方法初稿提炼 + 复核闸 + 导出 (方法复核闸) =================
def _method_view(m: dict) -> dict:
    """对外投影: 方法初稿的对外字段 (含把关状态)。"""
    return {
        "id": m["id"], "task_id": m["task_id"], "product": m["product"],
        "draft": m["draft"], "status": m["status"],
        "author": m.get("author"),
        "gated_by": m.get("gated_by"),
    }


@app.get("/api/methods")
def list_methods(status: str | None = None, user=Depends(current_user)):
    """列出方法初稿 (可按 status 过滤)。任意已登录用户 (intern 起) 可看。"""
    try:
        RBAC.require(user, "submit")
    except RBAC.PermissionDenied as e:
        raise HTTPException(403, str(e))
    return [_method_view(m) for m in METH.list_methods(_con(), status=status)]


class MethodDraftIn(BaseModel):
    task_id: str
    product: str
    draft: str


@app.post("/api/methods")
def create_method(body: MethodDraftIn, user=Depends(current_user)):
    """intern 在差距证据包上创建方法初稿 (draft, AC1 / story 34)。"""
    try:
        m = METH.draft_method(_con(), author=user, task_id=body.task_id,
                              product=body.product, draft=body.draft)
    except RBAC.PermissionDenied as e:
        raise HTTPException(403, str(e))
    except METH.MethodError as e:
        raise HTTPException(400, str(e))
    return _method_view(m)


@app.post("/api/methods/{method_id}/approve")
def approve_method(method_id: int, user=Depends(current_user)):
    """reviewer/PM 把关方法初稿 draft->approved (AC3 / story 35)。

    intern -> 403; 非 draft (已批/已导出) -> 409。
    """
    try:
        m = METH.approve_method(_con(), reviewer=user, method_id=method_id)
    except RBAC.PermissionDenied as e:
        raise HTTPException(403, str(e))
    except METH.MethodNotFound as e:
        raise HTTPException(404, str(e))
    except METH.IllegalMethodState as e:
        raise HTTPException(409, str(e))
    return _method_view(m)


@app.get("/api/methods/{method_id}/preview")
def preview_method(method_id: int, user=Depends(current_user)):
    """把关前预览导出后研发看到的 markdown (不改状态)。reviewer/PM 用。"""
    try:
        RBAC.require(user, "gate_method")
    except RBAC.PermissionDenied as e:
        raise HTTPException(403, str(e))
    try:
        doc = METH.preview_export(_con(), method_id, registry=REG.default_registry())
    except METH.MethodNotFound as e:
        raise HTTPException(404, str(e))
    return {"id": method_id, "document": doc}


@app.post("/api/methods/{method_id}/export")
def export_method(method_id: int, user=Depends(current_user)):
    """把已把关的 Method 导出为研发可读格式 (AC4 / story 36)。

    复核闸核心 (AC2): 未经把关 (draft) -> 409 NotApproved, 不能越过 reviewer。
    intern -> 403。
    """
    try:
        out = METH.export_method(_con(), actor=user, method_id=method_id,
                                 registry=REG.default_registry())
    except RBAC.PermissionDenied as e:
        raise HTTPException(403, str(e))
    except METH.MethodNotFound as e:
        raise HTTPException(404, str(e))
    except METH.NotApproved as e:
        raise HTTPException(409, str(e))
    return {"method": _method_view(out["method"]), "document": out["document"]}


# --- 静态前端 (build -> serve 接缝) --------------------------------------
# 所有 API 都在 /api/* 前缀下(上方 44 个路由)。这里把 vite build 产物挂在根路径,
# 让 uvicorn 单端口(8600)同时出 API + 站点 —— cloudflared 只需暴露这一个口。
# 放在所有 /api 路由之后注册, 不会遮挡接口。dist 不存在时静默跳过(纯 dev 模式)。
import pathlib as _pathlib

_DIST = _pathlib.Path(__file__).resolve().parent.parent / "frontend" / "dist"
if (_DIST / "index.html").exists():
    # /assets/* 等构建资源走真实文件。
    app.mount("/assets", StaticFiles(directory=str(_DIST / "assets")), name="assets")

    @app.get("/{full_path:path}")
    def _spa(full_path: str):
        # SPA fallback: 未命中 /api 与 /assets 的路径一律回 index.html,
        # 交给前端 React Router 处理, 否则刷新子路由会 404。
        candidate = _DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(_DIST / "index.html"))
