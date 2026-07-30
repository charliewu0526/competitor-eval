"""评测报告分析文字生成器(Claude 4.6 sonnet)。

PM 只看报告就能懂:三处自动生成的人话分析 ——
  1. domain_summary  : 某能力域榜单的一段 vio 优劣势总结(读排名/分差/各维均值)。
  2. matrix_reading  : 按题矩阵的一段解读(哪些题领先/落后、集中在什么类型)。
  3. competitor_radar: 按竞品聚合的五维数据(纯 scores 聚合, 不调 LLM)。

分工同 gap_attribution: 真实调用走 Claude(强制代理访问 Anthropic), 无 key -> dry_run
占位不伪造。模型取 ANALYSIS_MODEL(默认 claude-sonnet-4-6, 即 Claude 4.6 sonnet)。
文字生成慢且花钱, 由 analysis_prefetch 在评分落库后增量预跑落缓存(见 store.analysis_cache),
前端开页读缓存 —— 数据变(scores 指纹变)才重算, 随任务完成实时刷新。
"""
from __future__ import annotations

import json
import os

from pipeline import review_client as RC
from pipeline import leaderboard as LB
from pipeline import capability_matrix as CM
from pipeline import store as STORE

# Claude 4.6 sonnet. temperature 在新版 Claude 已废弃(传了 400), 不带。
_MODEL = os.environ.get("ANALYSIS_MODEL", "claude-sonnet-4-6")
_MAX_TOKENS = int(os.environ.get("ANALYSIS_MAX_TOKENS", "1200"))

DIM_LABEL = {"S1": "质量", "S2": "效率", "S3": "可靠性", "S4": "自主性", "S5": "体验"}
_DIMS = ("S1", "S2", "S3", "S4", "S5")


# --- Claude 调用(复用 gap_attribution 的强制代理姿势) ----------------------
def _claude(system: str, prompt: str) -> dict:
    """调 Claude 4.6 sonnet, 强制走代理访问 Anthropic。返回 {text} 或 {__dry_run__}。

    坑同 gap_attribution: launchd 后端设了 NO_PROXY=127.0.0.1, urllib 默认 opener 会
    把「经 127.0.0.1 代理访问 Anthropic」也命中 NO_PROXY 而直连 -> 被 cloudflare 403。
    故用显式 ProxyHandler 独立 opener 把代理钉死在请求上。
    """
    key = os.environ.get("CLAUDE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return {"__dry_run__": True}
    import urllib.request as _u
    url = "https://api.anthropic.com/v1/messages"
    hdr = {"Content-Type": "application/json", "x-api-key": key,
           "anthropic-version": "2023-06-01", "User-Agent": RC._UA}
    body = {"model": _MODEL, "max_tokens": _MAX_TOKENS,
            "system": system,
            "messages": [{"role": "user", "content": prompt}]}
    proxy = (os.environ.get("GAP_ATTRIB_HTTPS_PROXY")
             or os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"))
    data = json.dumps(body).encode()
    req = _u.Request(url, data=data, headers=hdr, method="POST")
    if proxy:
        opener = _u.build_opener(_u.ProxyHandler({"http": proxy, "https": proxy}))
        with opener.open(req, timeout=120) as r:
            out = json.loads(r.read().decode())
    else:
        with _u.urlopen(req, timeout=120) as r:
            out = json.loads(r.read().decode())
    try:
        return {"text": out["content"][0]["text"].strip()}
    except Exception:
        return {"error": "unparseable", "raw": str(out)[:300]}


# --- 1. 竞品雷达图数据(纯 scores 聚合, 不调 LLM) --------------------------
def competitor_radar(con, baseline: str = "vio",
                     domain: str | None = None) -> dict:
    """按竞品聚合五维:每个产品跨题的主观五维(S1-S5)中位/均值。

    返回 {baseline, domain, products:[{product, is_baseline, dims:{S1..S5}, n}]}。
    多竞品叠加在一张雷达图上对比, vio 高亮。domain 给定时只聚合该域任务。
    纯数据派生, 随 scores 表实时变化, 不需缓存。
    """
    scores = STORE.all_scores(con)
    task_domain = _task_domain_map() if domain else {}
    agg: dict[str, dict] = {}
    for s in scores:
        prod = s.get("product")
        if not prod:
            continue
        if domain and task_domain.get(s.get("task_id")) != domain:
            continue
        subj = s.get("subjective") or {}
        if not isinstance(subj, dict):
            continue
        bucket = agg.setdefault(prod, {d: [] for d in _DIMS})
        for d in _DIMS:
            v = subj.get(d)
            if isinstance(v, dict):
                v = v.get("median", v.get("score"))
            if isinstance(v, (int, float)):
                bucket[d].append(float(v))
    products = []
    for prod, dims in agg.items():
        out_dims = {}
        n = 0
        for d in _DIMS:
            vals = dims[d]
            out_dims[d] = round(sum(vals) / len(vals), 2) if vals else None
            n = max(n, len(vals))
        if any(v is not None for v in out_dims.values()):
            products.append({"product": prod, "is_baseline": prod == baseline,
                             "dims": out_dims, "n": n})
    # baseline 排前, 其余按 S1 均值降序
    products.sort(key=lambda p: (not p["is_baseline"],
                                 -(p["dims"].get("S1") or 0)))
    return {"baseline": baseline, "domain": domain,
            "dim_labels": DIM_LABEL, "products": products}


def _task_domain_map() -> dict:
    """task_id -> capability_domain(用于按域过滤雷达/榜单)。缺失容错为空。"""
    try:
        from pipeline import suite
        out = {}
        for t in suite.discover_tasks():
            tid = getattr(t, "task_id", None) or (t.get("task_id") if isinstance(t, dict) else None)
            dom = getattr(t, "capability_domain", None) or (t.get("capability_domain") if isinstance(t, dict) else None)
            if tid:
                out[tid] = dom
        return out
    except Exception:
        return {}


# --- 2. 分维度榜单:某域的 vio 优劣势总结(Claude) --------------------------
_DOMAIN_SYS = """你是竞品评测系统的分析师, 基线产品是 vio(Violoop)。给你一个能力域的
榜单数据(各产品能力分排名、与 vio 的分差、五维 S1质量/S2效率/S3可靠性/S4自主性/
S5体验 的均值、诚实度)。用**一段中文人话**(3-5 句, 面向产品经理)总结:vio 在这个
域相对竞品的**优势和劣势**具体是什么 —— 排第几、领先/落后谁多少分、强在哪一维、
弱在哪一维。只依据给的数据, 不编造。不要列表、不要小标题, 就一段话。"""


def domain_summary(con, domain: str, board: dict, baseline: str = "vio") -> dict:
    """一段 vio 在某能力域的优劣势总结。board=该域 domain-board 数据(含 leaderboard)。

    返回 {text} 或 {dry_run:True}(无 key)。数据不足(无排名)时返回明确空态文字。
    """
    lb = (board or {}).get("leaderboard") or {}
    ranking = lb.get("ranking") or []
    if not ranking:
        return {"text": "", "empty": True,
                "note": "这个域还没有可对比的评分, 跑几道题落库后自动生成总结。"}
    radar = competitor_radar(con, baseline=baseline, domain=domain)
    payload = {
        "domain": domain, "domain_label": board.get("label"),
        "baseline": baseline,
        "ranking": [{"rank": r.get("rank"), "product": r.get("product"),
                     "is_baseline": r.get("is_baseline"),
                     "capability_100": round((r.get("avg_capability") or 0) * 100),
                     "vs_baseline_pts": (None if r.get("vs_baseline") is None
                                         else round(r["vs_baseline"] * 100)),
                     "honesty": r.get("honesty_avg")}
                    for r in ranking],
        "five_dims_by_product": {p["product"]: p["dims"] for p in radar["products"]},
        "dim_labels": DIM_LABEL,
    }
    res = _claude(_DOMAIN_SYS, json.dumps(payload, ensure_ascii=False))
    if res.get("__dry_run__"):
        return {"dry_run": True,
                "note": "未配置 Claude key, 无法生成总结(不伪造)。"}
    return {"text": res.get("text", ""), "engine": _MODEL,
            "error": res.get("error")}


# --- 3. 按题矩阵解读(Claude) ----------------------------------------------
_MATRIX_SYS = """你是竞品评测系统的分析师, 基线产品是 vio(Violoop)。给你一张「产品 ×
任务」的能力分矩阵(0-100, 越高越好)。用**一段中文人话**(3-5 句, 面向产品经理)解读:
vio 在**哪些题领先、哪些题明显落后**竞品, 这些领先/落后的题是否集中在某类任务(看
task_id 前缀/名字规律)。点出最值得注意的差距。只依据数据, 不编造。就一段话, 不要列表。"""


def matrix_reading(con, matrix: dict, baseline: str = "vio") -> dict:
    """一段按题矩阵的解读(哪题领先/落后、集中在什么类型)。matrix=leaderboard.matrix 结构。"""
    mtx = (matrix or {}).get("matrix") or {}
    tasks = (matrix or {}).get("tasks") or []
    if not mtx or not tasks:
        return {"text": "", "empty": True,
                "note": "还没有可对比的按题成绩, 跑几道题落库后自动生成解读。"}
    # 压成紧凑表: {product: {task: score_100}}
    compact = {}
    for prod, row in mtx.items():
        compact[prod] = {t: (None if not (row.get(t)) or row[t].get("sample_score") is None
                             else round(row[t]["sample_score"] * 100))
                         for t in tasks}
    payload = {"baseline": baseline, "tasks": tasks, "matrix_100": compact}
    res = _claude(_MATRIX_SYS, json.dumps(payload, ensure_ascii=False))
    if res.get("__dry_run__"):
        return {"dry_run": True,
                "note": "未配置 Claude key, 无法生成解读(不伪造)。"}
    return {"text": res.get("text", ""), "engine": _MODEL,
            "error": res.get("error")}
