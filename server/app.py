"""FastAPI JSON API over the existing pipeline modules.

Wraps store / leaderboard / probe / sampling — the eval ENGINE is untouched.
This layer only reads the SQLite single-source-of-truth and exposes it as JSON
for the React + AntD frontend, plus a few write-back endpoints (PM judgment,
spot-check verdicts, queue rebuild).

Run:  uvicorn server.app:app --port 8600   (from repo root)
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from pipeline import store, leaderboard as LB, findings as F, sampling as SP
from pipeline import probe as PROBE

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
