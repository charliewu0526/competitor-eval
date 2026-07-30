"""FastAPI JSON API over the existing pipeline modules.

Wraps store / leaderboard / probe / sampling — the eval ENGINE is untouched.
This layer only reads the SQLite single-source-of-truth and exposes it as JSON
for the React + AntD frontend, plus a few write-back endpoints (PM judgment,
spot-check verdicts, queue rebuild).

Run:  uvicorn server.app:app --port 8600   (from repo root)
"""
from __future__ import annotations

import json
import logging
import threading
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
from pipeline.intake import Submission as _IntakeSubmission
from pipeline import reports as REPORTS
from pipeline import canary as CANARY

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
_conn_local = threading.local()   # 每线程缓存一个连接(H-1)


def _con():
    # H-1(连接生命周期): 此前每请求 store.connect() 新建连接且从不 close ——
    # SQLite 靠 GC 兜底(文件描述符堆积), PG 每请求 2+ 条物理连接永不归还, 并发上升
    # 迅速打满 max_connections -> 503 全挂。改为按「线程 + 库路径」缓存连接并复用:
    # uvicorn 默认线程池(~40 worker)下连接数收敛到 worker 数这个上界, 不再无界泄漏。
    # 零调用点改动 —— 40 个端点仍照常 `con = _con()`。SQLite 连接非线程安全, 按线程
    # 各持一个正好安全; 库路径变更(测试切临时库)时丢弃旧连、重建。
    #
    # H-3(迁移一次): 建表+迁移是一次性动作, 首次见到某库路径时迁移一次, 之后
    # skip_migrate=True 只复用连接, 免得每请求重跑 executescript + PRAGMA 风暴。
    global _migrated_for
    if _migrated_for != _DB_PATH:
        store.connect(_DB_PATH).close()   # 完整建表+迁移
        _migrated_for = _DB_PATH
        _drop_cached_con()                # 库路径变了, 弃掉线程里的旧连接

    cached = getattr(_conn_local, "con", None)
    if cached is not None and getattr(_conn_local, "path", None) == _DB_PATH:
        return cached
    con = store.connect(_DB_PATH, skip_migrate=True)
    _conn_local.con = con
    _conn_local.path = _DB_PATH
    return con


def _drop_cached_con():
    """丢弃当前线程缓存的连接(库路径切换时用, 主要服务测试切临时库)。"""
    con = getattr(_conn_local, "con", None)
    if con is not None:
        try:
            con.close()
        except Exception:
            pass
    _conn_local.con = None
    _conn_local.path = None


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
    # 榜单隔离: auto-from-census 候选题(expected 为 AI 暂定基准、未核验)不进差距报告
    # 主视图 —— 与 leaderboard/catalog 一致, 单列 /api/candidate-tasks。
    cand_ids = LB.candidate_task_ids()
    scores = [s for s in store.all_scores(con) if s.get("task_id") not in cand_ids]
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
def get_gap_report(task_id: str, baseline: str = "vio", attribution: bool = False):
    """MR-11 (#47): 一道对比任务的完整差距报告 (派生视图, 引擎不改).

    差距报告增强: 归因**默认从缓存读, 打开即自动显示**——先按当前 scores 指纹查
    attribution_cache, 命中(指纹相符=评测结果没变)则直接带进 response.attribution
    (无需现算)。未命中(从没预跑 / 评测刚变缓存失效)时:attribution=true 才实时算
    (前端手动触发兜底), 否则 attribution=null 让前端显示「分析」按钮。
    """
    con = _con()
    # 榜单隔离: 候选题(auto-from-census)不出差距报告主视图, 单列 /api/candidate-tasks。
    cand_ids = LB.candidate_task_ids()
    if task_id in cand_ids:
        raise HTTPException(404, "no scores for this task")
    scores = [s for s in store.all_scores(con) if s.get("task_id") not in cand_ids]
    finds = store.all_findings(con)
    if not any(s.get("task_id") == task_id for s in scores):
        raise HTTPException(404, "no scores for this task")
    # 先查缓存: 按本题当前 scores 指纹, 命中即自动带出归因(打开即显示)。
    task_scores = [s for s in scores if s.get("task_id") == task_id]
    fp = store.attribution_fingerprint(task_scores, baseline)
    cached = store.get_cached_attribution(con, task_id, baseline, fp)
    # 命中缓存 -> 用缓存(不现算); 未命中且请求 attribution=true -> 实时算兜底。
    rep = GAP.build_report(task_id, scores, finds,
                           registry=REG.default_registry(), baseline=baseline,
                           with_attribution=(attribution and cached is None))
    out = rep.as_dict()
    if cached is not None:
        out["attribution"] = cached          # 缓存归因(带 cached=true 标记)
    return out


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
    """把清单里的一道题铸成【产品级】可领取单元 (方案B: 领取粒度=题×产品)。

    维护任务清单属 owner 独占 (story 5, manage_task_catalog)。幂等: 已物化的
    (task,product) 复用原单。返回该题全部参赛产品的领取单元列表。

    方案B改造: 旧版铸一条"整题单"(product=None 锁死全部产品), 会导致别人领了
    整道题就没人能领 —— 这里改为按参赛集拆成 N 个单产品单元, 不同人可各领各的。
    """
    try:
        units = ASSIGN.materialize_products_for_task(_con(), body.task_id)
    except ASSIGN.AssignmentError as e:
        raise HTTPException(400, str(e))
    views = [_assignment_view(a) for a in units]
    return {"task_id": body.task_id, "units": views, "count": len(views)}


@app.get("/api/catalog/{task_id}/input/{file_path:path}")
def download_task_input(task_id: str, file_path: str, user=rbac("claim_assignment")):
    """下载一道题的起始素材文件 (方案B 素材统一由系统提供 —— 远程实习生靠这个真拿到文件)。

    实习生反馈'找不到起始素材': 素材躺在本机 tasks/<id>/input/, 前端此前无下载入口。
    这里按 task_id + 相对路径回传文件。做严格路径校验防目录穿越 (只允许该题 input/ 内、
    非 README/隐藏文件)。需登录 (claim_assignment 权限), 不裸奔。
    """
    import pathlib as _pl
    # 定位任务目录 (走 suite 发现, 不信任外部拼路径)。
    tdir = None
    for t in SUITE.discover_tasks():
        if t.task_spec.task_id == task_id:
            tdir = _pl.Path(t.task_dir)
            break
    if tdir is None:
        raise HTTPException(404, f"任务不存在: {task_id}")
    idir = (tdir / "input").resolve()
    target = (idir / file_path).resolve()
    # 防目录穿越: 目标必须落在 input/ 内。
    if not str(target).startswith(str(idir) + "/") or not target.is_file():
        raise HTTPException(404, "素材文件不存在或不可访问")
    if target.name == "README.md" or target.name.startswith("."):
        raise HTTPException(404, "素材文件不存在或不可访问")
    return FileResponse(str(target), filename=target.name)


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

    # 6. 差距归因增量预跑(差距报告增强): 本题 scores 刚变, 指纹已变 -> 缓存失效,
    #    这里只对**本题**跑一次归因落缓存, 报告页/一览表打开即读缓存自动显示,
    #    不必每次开页现算。归因慢(读交付物调 Claude), 但此刻已在后台评分线程里
    #    (_score_assignment_bg), 不阻塞前台; 失败只记日志, 不影响已落库的评分。
    try:
        from pipeline import attribution_prefetch as APF
        APF.prefetch(con, only_tasks=[task_id])
    except Exception:  # noqa: BLE001
        logging.getLogger("competitor-eval").exception(
            "差距归因预跑失败 task=%s", task_id)

    return {"status": "scored", "products": [b.product for b in blind],
            "count": len(blind), "findings": len(finds)}


def _score_assignment_bg(assignment_id: str) -> None:
    """后台评分任务: 独立开连接跑整组盲评入榜, 与收口请求解耦。

    盲评面板真打多模型 (30-90s), 若同步跑, 多实习生并发提交会各占一个请求 worker
    半分钟以上, 拖垮前台。改为 BackgroundTask: 收口请求秒返 (状态已翻 submitted),
    评分在后台完成后落 runs/scores, 榜单随后出分。失败只记日志, 不影响已交付的活。
    """
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
    # E 一致率: 人拍板 final_category == AI 预复核建议? (有未决建议才记)
    try:
        sug = store.get_precheck_suggestion(_con(), "finding", str(finding_id))
        if sug and sug.get("agreed") is None and body.final_category:
            store.record_precheck_decision(
                _con(), target_type="finding", target_id=str(finding_id),
                human_decision=body.final_category,
                suggested_value=(sug.get("suggestion") or {}).get("suggested_final_category"),
                reviewer=user.get("id", ""))
    except Exception:
        logging.getLogger("competitor-eval").exception(
            "记一致率失败 finding_id=%s", finding_id)
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


@app.post("/api/gap-report/{task_id}/synthesize-methods")
def synthesize_methods(task_id: str, baseline: str = "vio",
                       user=Depends(current_user)):
    """自动闭环: 跑归因 -> 提炼一句话功能点 -> 自动落成方法初稿(draft)。

    reviewer/PM 触发(gate_method 权限, 与把关同级 —— 自动提炼进方法沉淀属复核链
    前段, 不给 intern 免审自灌)。产出的 draft status=draft, author=system:auto,
    仍需人在方法沉淀审核 approved。返回本次新建的 method 列表(可能为空:归因无
    有效引用/竞品不占优时不硬造)。
    """
    try:
        RBAC.require(user, "gate_method")
    except RBAC.PermissionDenied as e:
        raise HTTPException(403, str(e))
    con = _con()
    scores = store.all_scores(con)
    if not any(s.get("task_id") == task_id for s in scores):
        raise HTTPException(404, "no scores for this task")
    finds = store.all_findings(con)
    # 跑带归因的报告 -> 拿 attribution -> 提炼落 draft。
    rep = GAP.build_report(task_id, scores, finds,
                           registry=REG.default_registry(), baseline=baseline,
                           with_attribution=True)
    from pipeline import method_synth as MSYN
    created = MSYN.synthesize_from_attribution(con, task_id, rep.as_dict().get("attribution"))
    return {"task_id": task_id, "created": [_method_view(m) for m in created],
            "count": len(created)}


@app.get("/api/gap-report-overview")
def gap_report_overview(baseline: str = "vio"):
    """差距报告增强: 全任务差距一览(派生视图, 一眼看清各题差距 + 竞品好在哪)。

    每题一行: {task_id, domain, baseline_score, top_competitor, top_score, diff,
    competitor_leads(有竞品≥基线), attribution_summary(缓存里第一条归因 headline,
    只读缓存不实时算), candidate_count(该题 capability-gap findings 数)}。
    归因摘要**只从 attribution_cache 读** —— 一览打开要快, 不逐题调 Claude;
    没预跑缓存的题摘要为空(前端提示可点批量预跑)。
    """
    con = _con()
    # 榜单隔离: 候选题(auto-from-census)不进全任务差距一览, 单列 /api/candidate-tasks。
    cand_ids = LB.candidate_task_ids()
    scores = [s for s in store.all_scores(con) if s.get("task_id") not in cand_ids]
    finds = store.all_findings(con)
    cached = store.all_cached_attributions(con, baseline)

    from pipeline import capability_matrix as CM
    by_task: dict = {}
    for s in scores:
        by_task.setdefault(s.get("task_id"), []).append(s)
    # 每题 capability-gap 候选数(subject 非 baseline 的 capability-gap finding)。
    cand_by_task: dict = {}
    for f in finds:
        if f.get("suspected_category") == "capability-gap":
            cand_by_task[f.get("task_id")] = cand_by_task.get(f.get("task_id"), 0) + 1

    rows = []
    for task_id, ts in by_task.items():
        base = next((s for s in ts if s.get("product") == baseline
                     and s.get("sample_score") is not None), None)
        base_val = base["sample_score"] if base else None
        # 最强竞品(排除 baseline 与 cannot-reach)。
        comps = [s for s in ts if s.get("product") != baseline
                 and s.get("sample_score") is not None
                 and s.get("gate") != "cannot-reach"]
        top = max(comps, key=lambda s: s["sample_score"], default=None)
        top_score = top["sample_score"] if top else None
        diff = (top_score - base_val) if (top_score is not None and base_val is not None) else None
        # 归因摘要: 缓存里第一条 point 的 headline(只读缓存)。
        attr = cached.get(task_id) or {}
        pts = attr.get("points") or []
        summary = pts[0].get("headline") if pts else (attr.get("note") or "")
        rows.append({
            "task_id": task_id,
            "domain": CM.task_domain(task_id),
            "baseline_score": base_val,
            "top_competitor": top["product"] if top else None,
            "top_score": top_score,
            "diff": diff,
            "competitor_leads": bool(diff is not None and diff > 0),
            "attribution_summary": summary,
            "attribution_cached": bool(attr),
            "candidate_count": cand_by_task.get(task_id, 0),
        })
    # 竞品领先(diff 大)的题排前, 便于一眼看该补哪。
    rows.sort(key=lambda r: (r["diff"] if r["diff"] is not None else -999), reverse=True)
    return {"baseline": baseline, "rows": rows, "count": len(rows)}


@app.post("/api/gap-report-prefetch")
def gap_report_prefetch(baseline: str = "vio", force: bool = False,
                        user=Depends(current_user)):
    """差距报告增强: owner 手动批量预跑归因落缓存(首次填充 / 换模型后 force 重算)。

    平时归因由收口入库自动增量预跑; 这个端点用于一次性把存量题的归因补齐, 或改归因
    口径后强制全量重算。只对有竞品≥基线且指纹未命中的题跑, 慢(逐题调 Claude)但只在
    owner 主动点时触发, 不偷跑烧钱。
    """
    try:
        RBAC.require(user, "view_report_console")
    except RBAC.PermissionDenied as e:
        raise HTTPException(403, str(e))
    from pipeline import attribution_prefetch as APF
    stats = APF.prefetch(_con(), baseline=baseline, force=force)
    return stats


@app.post("/api/vio-gap/{task_id}/classify")
def classify_vio_gap(task_id: str, baseline: str = "vio",
                     synthesize: bool = True, user=Depends(current_user)):
    """功能A: 对 vio 失败题反转成信号 —— 归因引擎判「执行差距 vs 能力空白」。

    reviewer/PM 触发(gate_method 权限, 与把关同级)。读 vio 交付物 + expected,调
    Claude 最强模型判 execution-gap / capability-gap(带 vio 交付物原文引用)。只有
    capability-gap 落 Finding(subject=vio, suspected_category=capability-gap)并(默认)
    自动提炼成方法初稿(draft, 待人/AI 复核)。execution-gap / 无引用 / dry_run 不落。
    返回归因判定 + 落库的 Finding + 本次新建的方法 draft。
    """
    try:
        RBAC.require(user, "gate_method")
    except RBAC.PermissionDenied as e:
        raise HTTPException(403, str(e))
    con = _con()
    scores = store.all_scores(con)
    vio_row = next((s for s in scores
                    if s.get("task_id") == task_id and s.get("product") == baseline), None)
    if vio_row is None:
        raise HTTPException(404, f"no {baseline} score for this task")
    # 只对「基线确实失败」的题反转成信号 —— vio 通过的题没有失败可归因。
    failed = (vio_row.get("objective_failed_primary")
              or vio_row.get("gate") == "cannot-reach"
              or (vio_row.get("sample_score") is not None
                  and float(vio_row.get("sample_score") or 0) <= 0.0))
    if not failed:
        return {"task_id": task_id, "skipped": True,
                "reason": f"{baseline} 在该题未失败, 无失败可归因(能力空白反转仅针对失败题)",
                "verdict": None, "finding": None, "created": []}

    from pipeline import vio_gap as VG
    result = VG.classify_vio_failure(task_id, baseline=baseline)
    rd = result.as_dict()

    finding_out = None
    created = []
    if rd.get("finding"):
        fid = store.upsert_finding(con, rd["finding"])
        finding_out = {**rd["finding"], "id": fid}
        if synthesize:
            from pipeline import method_synth as MSYN
            created = MSYN.synthesize_from_vio_gap(con, task_id, rd)
    return {"task_id": task_id, "verdict": rd.get("verdict"),
            "confidence": rd.get("confidence"), "dry_run": rd.get("dry_run"),
            "note": rd.get("note"), "finding": finding_out,
            "created": [_method_view(m) for m in created], "count": len(created)}


@app.post("/api/capability-census/{rival}")
def run_capability_census(rival: str, baseline: str = "vio",
                          synthesize: bool = True, user=Depends(current_user)):
    """功能B: 竞品能力普查差集 —— 竞品已上线、vio 清单缺失的能力 -> capability-gap 候选。

    reviewer/PM 触发(gate_method 权限)。读 registry/capabilities/<rival>.json 与
    vio.json 做差集,竞品 shipped 里 vio 缺的每条 -> capability-gap Finding
    (subject=rival, rule=capability-census, task_id=census-<rival>)落库,并(默认)
    自动提炼成方法初稿(draft, 待人/AI 复核)。竞品/基线未登记清单 -> 空(如实)。
    """
    try:
        RBAC.require(user, "gate_method")
    except RBAC.PermissionDenied as e:
        raise HTTPException(403, str(e))
    from pipeline import capability_census as CEN
    from pipeline import method_synth as MSYN
    con = _con()
    findings = CEN.census_to_findings(rival, baseline=baseline)
    persisted = []
    for fd in findings:
        fid = store.upsert_finding(con, fd)
        persisted.append({**fd, "id": fid})
    created = []
    if synthesize and persisted:
        created = MSYN.synthesize_from_census(con, rival, persisted, baseline=baseline)
    return {"rival": rival, "baseline": baseline,
            "candidates": len(persisted),
            "findings": persisted,
            "created": [_method_view(m) for m in created], "count": len(created)}


class CapabilityExtractIn(BaseModel):
    product: str
    docs_text: str
    source: str = ""


@app.post("/api/capability-extract")
def extract_capabilities(body: CapabilityExtractIn, persist: bool = False,
                         user=Depends(current_user)):
    """功能B: LLM 从官网/docs 原文抽竞品能力条目(AI 复核闸: 一律落 candidate)。

    reviewer/PM 触发。抽出的条目 status 强制为 candidate(留痕 LLM 原判于 tags),
    差集不认 candidate 为候选 —— 必须经复核(review_capability)升 shipped 才进差集。
    persist=true 时把抽取结果并入 registry/capabilities/<product>.json(与已有条目合并,
    去重按能力文本);否则只返回抽取预览不落盘。
    """
    try:
        RBAC.require(user, "gate_method")
    except RBAC.PermissionDenied as e:
        raise HTTPException(403, str(e))
    from pipeline import capability_census as CEN
    from pipeline import capability_store as CS
    extracted = CEN.extract_capabilities_via_llm(
        body.product, body.docs_text, source=body.source)
    saved_path = None
    if persist and extracted.entries:
        existing = CS.load_capabilities(body.product)
        seen = {CEN._norm(e.capability) for e in existing.entries}
        merged = list(existing.entries)
        for e in extracted.entries:
            if CEN._norm(e.capability) not in seen:
                merged.append(e)
                seen.add(CEN._norm(e.capability))
        existing.entries = merged
        saved_path = CS.save_capabilities(existing)
    return {"product": body.product, "note": extracted.note,
            "extracted": [e.as_dict() for e in extracted.entries],
            "count": len(extracted.entries), "persisted": bool(saved_path)}


class CapabilityResearchIn(BaseModel):
    product: str
    source_urls: list[str] = []          # 官网/新闻/社媒公开链接
    persist: bool = True


@app.post("/api/capability-research")
def run_capability_research(body: CapabilityResearchIn, user=Depends(current_user)):
    """D: 竞品自动调研 —— 贴官网/新闻/社媒链接 → 抓取 → LLM 抽能力 → 落 candidate。

    reviewer/PM 触发(gate_method 权限)。抓公开页(失败如实标)→ 抽能力条目一律
    candidate(AI 复核闸,带 source_url+fetched_at)→ persist 则并入
    registry/capabilities/<product>.json(按能力文本去重)。差集不认 candidate,须经
    /api/capabilities/{product}/review 复核升 shipped 才进候选。全部抓不到 → 如实标。
    """
    try:
        RBAC.require(user, "gate_method")
    except RBAC.PermissionDenied as e:
        raise HTTPException(403, str(e))
    from pipeline import capability_census as CEN
    res = CEN.auto_research(body.product, body.source_urls, persist=body.persist)
    return {"product": body.product, "note": res.get("note"),
            "fetched": [{"url": f["url"], "ok": f["ok"], "note": f.get("note", "")}
                        for f in res.get("fetched", [])],
            "extracted": res.get("extracted", []),
            "count": len(res.get("extracted", [])),
            "persisted": res.get("persisted", False)}


class CapabilityReviewIn(BaseModel):
    capability: str                      # 要复核的能力条目文本(定位用)
    approve: bool                        # True=升 shipped, False=维持 candidate


@app.post("/api/capabilities/{product}/review")
def review_capability_entry(product: str, body: CapabilityReviewIn,
                            user=Depends(current_user)):
    """D: 复核一条 candidate 能力条目 —— approve=True 升 shipped 进差集。

    reviewer/PM(gate_method)。只动 candidate 条目(shipped/limited/marketing 是数据源
    事实不改)。升 shipped 后 diff_capabilities 才认它为候选新功能。留痕复核人。
    """
    try:
        RBAC.require(user, "gate_method")
    except RBAC.PermissionDenied as e:
        raise HTTPException(403, str(e))
    from pipeline import capability_census as CEN
    from pipeline import capability_store as CS
    clist = CS.load_capabilities(product)
    hit = None
    for e in clist.entries:
        if e.capability == body.capability:
            hit = e
            break
    if hit is None:
        raise HTTPException(404, f"能力条目未找到: {body.capability!r}")
    CEN.review_capability(hit, approve=body.approve, reviewer=user.get("id", ""))
    CS.save_capabilities(clist)
    # 升 shipped 钩子: 确认为已上线能力后, 自动脚手架一道候选题(provenance=
    # auto-from-census, 隔离于公平主榜单)。异常不阻断复核主流程(如实记 note)。
    generated_task = None
    gen_note = None
    if body.approve and hit.status == "shipped":
        try:
            from pipeline import task_gen as TG
            generated_task = TG.generate_candidate_task(hit, product)
        except Exception as ex:
            gen_note = f"候选题自动生成失败(如实标, 不阻断复核): {str(ex)[:160]}"
    return {"product": product, "capability": hit.capability,
            "status": hit.status, "approved": body.approve,
            "generated_task": generated_task, "gen_note": gen_note}


@app.get("/api/candidate-tasks")
def list_candidate_tasks():
    """自动生成候选题(provenance=auto-from-census)只读列表 —— 与公平主榜单隔离。

    这些题由能力普查差集自动生成, prompt/expected 是 AI 暂定基准、未经人核验, 不进
    公平主榜单。此端点单列它们供人真跑核验后转正(把 provenance 改 human)。每条带
    来源竞品/能力/证据/出处 + 中立 Prompt, 前端据此打「未核验」醒目标记。
    """
    from pipeline import suite as SUITE
    from pipeline import taskbank as TB
    out = []
    for t in SUITE.discover_tasks():
        s = t.task_spec
        if s.provenance != "auto-from-census":
            continue
        prov = {}
        try:
            prov = TB.load_meta(t.task_dir).get("provenance") or {}
        except Exception:
            prov = {}
        out.append({
            "task_id": s.task_id,
            "app": s.app,
            "capability_domain": s.capability_domain,
            "kind": s.kind,
            "prompt": s.prompt,
            "provenance": s.provenance,
            "rival": prov.get("rival"),
            "capability": prov.get("capability"),
            "evidence": prov.get("evidence"),
            "source": prov.get("source"),
            "generated_at": prov.get("generated_at"),
            "note": prov.get("note"),
        })
    return {"count": len(out),
            "tasks": sorted(out, key=lambda c: c["task_id"])}


@app.post("/api/capability-matrix/{domain}")
def run_capability_matrix(domain: str, baseline: str = "vio",
                          synthesize: bool = True, user=Depends(current_user)):
    """C: 多竞品能力域对比矩阵 —— 按能力域横向普查,空白格 -> capability-gap 候选。

    reviewer/PM 触发(gate_method 权限)。读该域全部题 × 参赛产品的分数聚成矩阵:
    竞品做到、vio 没做到(且 vio 同域他题未证明具备)的格子 -> capability-gap Finding
    (subject=竞品, rule=capability-matrix, task_id=matrix-<domain>-<指纹>)落库,并(默认)
    自动提炼成结构化方法卡片 draft(待人/AI 复核)。返回矩阵 + 落库 Finding + 新建 draft。
    """
    try:
        RBAC.require(user, "gate_method")
    except RBAC.PermissionDenied as e:
        raise HTTPException(403, str(e))
    from pipeline import capability_matrix as CM
    from pipeline import method_synth as MSYN
    con = _con()
    scores = store.all_scores(con)
    matrix = CM.build_matrix(scores, domain, baseline=baseline)
    if not matrix.task_ids:
        raise HTTPException(404, f"能力域 {domain!r} 下无题或无分数")
    findings = CM.matrix_to_capability_gap_findings(matrix)
    persisted = []
    for fd in findings:
        fid = store.upsert_finding(con, fd)
        persisted.append({**fd, "id": fid})
    created = []
    if synthesize and persisted:
        created = MSYN.synthesize_from_matrix(con, domain, persisted, baseline=baseline)
    return {"domain": domain, "baseline": baseline,
            "matrix": matrix.as_dict(),
            "candidates": len(persisted), "findings": persisted,
            "created": [_method_view(m) for m in created], "count": len(created)}


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
    E: 若此前对该 method 跑过 AI 预复核, 把关(approve)即人拍板 -> 记一致率
    (AI 建议 approve 且人也 approve -> agreed=True)。
    """
    try:
        m = METH.approve_method(_con(), reviewer=user, method_id=method_id)
    except RBAC.PermissionDenied as e:
        raise HTTPException(403, str(e))
    except METH.MethodNotFound as e:
        raise HTTPException(404, str(e))
    except METH.IllegalMethodState as e:
        raise HTTPException(409, str(e))
    # E 一致率: 人 approve == AI 建议 approve? (有未决建议才记)
    try:
        sug = store.get_precheck_suggestion(_con(), "method", str(method_id))
        if sug and sug.get("agreed") is None:
            store.record_precheck_decision(
                _con(), target_type="method", target_id=str(method_id),
                human_decision="approve",
                suggested_value=(sug.get("suggestion") or {}).get("suggestion"),
                reviewer=user.get("id", ""))
    except Exception:
        logging.getLogger("competitor-eval").exception(
            "记一致率失败 method_id=%s", method_id)
    return _method_view(m)


class PrecheckOut(BaseModel):
    pass


@app.post("/api/findings/{finding_id}/precheck")
def precheck_finding_endpoint(finding_id: int, user=Depends(current_user)):
    """E: 对一条 finding 跑 AI 预复核 —— 给 final_category/product_judgment 建议 + 理由。

    reviewer/PM(review 权限)。只给建议不落最终(人是最终闸);建议落 precheck_log
    待人确认。返回 AI 建议供复核页展示。
    """
    try:
        RBAC.require(user, "review")
    except RBAC.PermissionDenied as e:
        raise HTTPException(403, str(e))
    import json as _json
    from pipeline import precheck as PC
    con = _con()
    finds = store.all_findings(con)
    fd = next((f for f in finds if str(f.get("id")) == str(finding_id)), None)
    if fd is None:
        raise HTTPException(404, f"finding {finding_id} 不存在")
    try:
        fd["evidence"] = _json.loads(fd.get("evidence_json") or "null")
    except Exception:
        pass
    sug = PC.precheck_finding(fd)
    if not sug.get("dry_run"):
        store.log_precheck_suggestion(con, target_type="finding",
                                      target_id=str(finding_id), suggestion=sug)
    return {"finding_id": finding_id, "suggestion": sug}


@app.post("/api/methods/{method_id}/precheck")
def precheck_method_endpoint(method_id: int, user=Depends(current_user)):
    """E: 对一条 method draft 跑 AI 预复核 —— 给 approve/revise 建议 + 理由。"""
    try:
        RBAC.require(user, "gate_method")
    except RBAC.PermissionDenied as e:
        raise HTTPException(403, str(e))
    from pipeline import precheck as PC
    con = _con()
    m = next((x for x in METH.list_methods(con) if str(x.get("id")) == str(method_id)), None)
    if m is None:
        raise HTTPException(404, f"method {method_id} 不存在")
    sug = PC.precheck_method(m)
    if not sug.get("dry_run"):
        store.log_precheck_suggestion(con, target_type="method",
                                      target_id=str(method_id), suggestion=sug)
    return {"method_id": method_id, "suggestion": sug}


@app.get("/api/precheck/agreement")
def precheck_agreement_endpoint(target_type: str | None = None,
                                user=Depends(current_user)):
    """E: AI 预复核建议 vs 人工最终结论的一致率(只统计已拍板记录)。"""
    try:
        RBAC.require(user, "review")
    except RBAC.PermissionDenied as e:
        raise HTTPException(403, str(e))
    return store.precheck_agreement(_con(), target_type=target_type)


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


# === MR-B (#56) 用户反馈: 提交(文字+截图+自动附日志)+ 反馈台只读 ==========
# 一条「人能报、owner 能看」的可演示闭环, AI 尚未接入(C/D 加)。薄转发: 逻辑在
# pipeline/reports.py(状态机 + 视图裁剪)与 artifact_store(截图/日志通道复用),
# 端点只做鉴权 + 落盘 + 调策略层 + 翻错误码, 沿用 46 条路由的薄转发风格。

def _snapshot_backend_log(report_id: str, *, max_bytes: int = 64_000) -> str | None:
    """提交反馈时自动附带后端日志尾部快照(story 2: 用户不必手动收集)。

    读 board/backend.log(run_frontend.sh 的落点)尾部 max_bytes 存成该 report 的
    log 附件。仅 owner/AI 可见(ADR-0013, 由反馈台 RBAC 把关, 不进提交者视图)。
    日志不存在 / 读失败 -> 返回 None(不阻断提交: 附日志是增益不是前置条件)。
    """
    import pathlib as _pl
    log_path = ART.upload_root().parent / "board" / "backend.log"
    try:
        if not log_path.is_file():
            return None
        data = log_path.read_bytes()
        tail = data[-max_bytes:] if len(data) > max_bytes else data
        return ART.save_report_upload(report_id=report_id, kind="log",
                                      filename="backend.log", data=tail)
    except Exception:
        return None


@app.post("/api/reports")
async def submit_report(
    text: str = Form(default=""),
    screenshots: list[UploadFile] | None = File(default=None),
    user=Depends(current_user),
):
    """登录用户提交一条反馈(文字 + 一或多张截图), 系统自动附带后端日志。

    仅登录用户可提(submit_report=intern 起, 未登录 403)。提交后 report 自动
    submitted -> queued 入 cron 队列(C 由 cron 扫 queued 触发修复 Agent)。
    截图走 artifact_store 复用通道, 库里不存二进制; 返回提交者视图(无 diff/诊断)。
    """
    try:
        RBAC.require(user, "submit_report")
    except RBAC.PermissionDenied as e:
        raise HTTPException(403, str(e))

    con = _con()
    # 1. 建 report(submitter 必填, 可追责)。
    try:
        r = REPORTS.create(con, submitter=user["id"], text=text or None)
    except REPORTS.ReportError as e:
        raise HTTPException(400, str(e))
    rid = r["id"]

    # 2. 截图落盘(复用 artifact_store, 可多张; 空文件跳过)。
    saved = 0
    for up in (screenshots or []):
        data = await up.read()
        if ART.has_bytes(data):
            ART.save_report_upload(report_id=rid, kind="screenshot",
                                   filename=up.filename, data=data)
            saved += 1

    # 3. 自动附带后端日志尾部(增益, 失败不阻断)。
    _snapshot_backend_log(rid)

    # 4. submitted -> queued(入 cron 队列, 松耦合等 C 来扫)。
    r = REPORTS.enqueue(con, rid)

    view = REPORTS.submitter_view(r)
    view["screenshots"] = saved
    return view


@app.get("/api/reports/mine")
def list_my_reports(user=Depends(current_user)):
    """提交者查看自己每条反馈的状态(处理中/已修复/需人工)。

    未登录 -> 401。返回中**不含** diff/诊断/分支/测试结果(submitter_view 裁剪,
    story 5: 内部细节不外泄)。
    """
    if not user:
        raise HTTPException(401, "未登录或会话已失效")
    return REPORTS.list_for_submitter(_con(), user["id"])


@app.get("/api/reports/console")
def report_console(user=rbac("view_report_console")):
    """owner 反馈台: 列全部反馈 + 状态(只读骨架)。owner 独占(story 21)。

    MR-B 只做只读列表; diff 面板 / 批准按钮由 MR-C、MR-D 加。needs-human /
    ai-failed 的高亮(story 20)由前端据 status 派生。附每条截图/日志计数供预览。
    """
    con = _con()
    rows = REPORTS.list_for_console(con)
    for row in rows:
        rid = row.get("id")
        row["screenshot_count"] = len(ART.list_report_uploads(rid, "screenshot"))
        row["has_log"] = bool(ART.list_report_uploads(rid, "log"))
    return rows


# === MR-D (#59) 上线闸门: 批准(冒烟金丝雀+回滚+安静窗口)/ 拒绝 ==============
# 薄转发: 逻辑在 pipeline/canary.py(run_canary 编排 + 状态机回写)。owner 独占
# (approve_patch)。批准走真金丝雀: 临时端口起新进程 -> 健康+冒烟全过才切主进程,
# 失败自动 git checkout 回 good commit + 重启旧版; 有 in-flight 评测则延迟(除非
# force)。sever 端点只做鉴权 + 调编排层 + 翻错误码。

class ApproveIn(BaseModel):
    force: bool = False   # 有活跃领题/评测时仍强制上线(跳过安静窗口等待)。


class RejectIn(BaseModel):
    message: str | None = None   # 给 AI/自己留一句为何拒绝。
    retry: bool = False          # True: 拒绝后再排队让 AI 按留言重试一次。


@app.post("/api/reports/{report_id}/approve")
def approve_report(report_id: str, body: ApproveIn | None = None,
                   user=rbac("approve_patch")):
    """owner 批准一个 patch-ready 补丁 -> 冒烟金丝雀上线(story 17/18/19)。

    - 有 in-flight 领题/评测且未 force -> 200 {outcome:"deferred"}(排安静窗口,
      不硬重启踹掉正在跑的评测), 不报错。
    - 冒烟全过 -> 切主进程, report -> resolved, 通知提交者。
    - 健康/冒烟失败 -> 自动回滚旧版, report -> needs-human(附失败原因)。
    非 patch-ready -> 409。真金丝雀在 owner 机器上跑(生产装配), 决策逻辑见 canary。
    """
    force = bool(body.force) if body else False
    try:
        out = CANARY.approve(_con(), report_id, allow_when_busy=force)
    except REPORTS.ReportError as e:
        # 非 patch-ready / 不存在 -> 冲突/未找到(canary 守卫 & reports.get)。
        raise HTTPException(409, str(e))
    except Exception as e:
        # 金丝雀上线是起子进程/跑 git/切主进程的重活, 任何一步炸了(起不了候选
        # 进程、健康检查连不上、git 回滚失败等)都不该裸奔成 500 白屏。翻成
        # 502 + 人话原因, 让 owner 在反馈台看到「为什么没上成」而非空错误。
        import traceback
        traceback.print_exc()
        raise HTTPException(502, f"上线金丝雀执行失败: {e}")
    # report 行按 owner 视图返回(反馈台可见内部字段)。
    r = out.get("report")
    return {"outcome": out.get("outcome"),
            "reason": out.get("reason") or out.get("detail"),
            "inflight": out.get("inflight"),
            "good_commit": out.get("good_commit"),
            "report": REPORTS.console_view(r) if r else None}


@app.post("/api/reports/{report_id}/reject")
def reject_report(report_id: str, body: RejectIn | None = None,
                  user=rbac("approve_patch")):
    """owner 拒绝一个 patch-ready 补丁 -> needs-human(附留言; story 16)。

    retry=True 时拒绝后再 enqueue 回 queued, 让修复 Agent 按留言重试一次。
    非 patch-ready -> 409。
    """
    msg = body.message if body else None
    retry = bool(body.retry) if body else False
    try:
        r = CANARY.reject(_con(), report_id, message=msg, retry=retry)
    except REPORTS.ReportError as e:
        raise HTTPException(409, str(e))
    return REPORTS.console_view(r)


# === needs-human / ai-failed 的人工处置(补 UI 缺口)========================
# 反馈台里 needs-human / ai-failed 是「优先处理」的红色高亮态, 但此前只有 patch-ready
# 有 approve/reject 入口, 这两态在前端无任何人工操作按钮 —— 反馈卡死无法收口。
# 状态机(reports._ALLOWED)本就允许 needs-human/ai-failed -> queued(让 AI 重试)
# 与 -> closed(人工收口), 这里补上对应端点。owner 独占(approve_patch, 与审补丁同权)。

class HumanResolveIn(BaseModel):
    note: str | None = None   # 人工处置留言(记进诊断, 供追溯)。


@app.post("/api/reports/{report_id}/close")
def close_report(report_id: str, body: HumanResolveIn | None = None,
                 user=rbac("approve_patch")):
    """人工收口一条反馈 -> closed(终态)。合法来源: needs-human / ai-failed / resolved。

    用于 owner 判定「已人工处理 / 无需处理 / 已线下解决」时把反馈关掉, 让它离开
    优先处理队列。非法来源(如 queued 处理中)-> 409。留言记进 diagnosis 供追溯。
    """
    note = body.note if body else None
    con = _con()
    try:
        cur = REPORTS.get(con, report_id)
        # 顺带把人工留言落进 diagnosis(仅当来源允许写该产出列)。
        if note and cur.get("status") in ("needs-human", "ai-failed"):
            try:
                store.set_user_report_status(
                    con, report_id, cur["status"], expected_from=cur["status"],
                    fields={"diagnosis": ((cur.get("diagnosis") or "") +
                            f"\n[人工留言] {note}").strip()})
            except Exception:
                pass
        r = REPORTS.close(con, report_id)
    except REPORTS.IllegalTransition as e:
        raise HTTPException(409, str(e))
    except REPORTS.ReportError as e:
        raise HTTPException(404, str(e))
    return REPORTS.console_view(r)


@app.post("/api/reports/{report_id}/retry")
def retry_report(report_id: str, body: HumanResolveIn | None = None,
                 user=rbac("approve_patch")):
    """把 needs-human / ai-failed 的反馈重新入队 -> queued, 让修复 Agent 再试一次。

    与「拒绝补丁 + 重试」共用重排队语义, 但入口是这两个卡住的态。非法来源 -> 409。
    """
    note = body.note if body else None
    con = _con()
    try:
        cur = REPORTS.get(con, report_id)
        if note and cur.get("status") in ("needs-human", "ai-failed"):
            try:
                store.set_user_report_status(
                    con, report_id, cur["status"], expected_from=cur["status"],
                    fields={"diagnosis": ((cur.get("diagnosis") or "") +
                            f"\n[人工重试留言] {note}").strip()})
            except Exception:
                pass
        r = REPORTS.enqueue(con, report_id)
    except REPORTS.IllegalTransition as e:
        raise HTTPException(409, str(e))
    except REPORTS.ReportError as e:
        raise HTTPException(404, str(e))
    return REPORTS.console_view(r)


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
