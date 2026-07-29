"""MR-11+ 差距归因层 (差距报告深化).

差距报告原来只回答「谁分高、差多少」(纯算术 score_diffs)。本模块在其上加一层
**归因**,回答 PM 真正要的两件事:
  1. 竞品比我们**好在哪一步**、**具体多做了什么** —— 从双方交付物原文里提取。
  2. 这算不算竞品的**新功能 / 值得借鉴的体验进步**(疑似定性,PM 拍板)。

立身铁律(一字不改地沿袭):
  * 机器只标现象、给**疑似**判断,绝不代 PM 下最终结论 —— 输出的
    suspected_category 永远是 "疑似",final_category 留空由 PM 复核填。
  * **每条结论必须附交付物原文引用**(citations 里带 product+source_file+quote)。
    没有引用支撑的结论会被标 low_confidence,宁可少说不可编造。
  * 缺数据如实标 —— 拿不到交付物 / LLM 不可用 -> dry_run 占位,绝不伪造机理。

归因只做「提取 + 引用 + 疑似归类」,判定权仍归 PM。纯派生,无副作用。
"""
from __future__ import annotations

import io
import glob as _glob
import json
import os
import zipfile
from dataclasses import dataclass, field, asdict

from pipeline import review_client as RC

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOADS = os.path.join(REPO, "board", "uploads")
# 只从这些可读文本类型里取原文引用;二进制(图片/xlsx)只记文件名存在性。
_TEXT_EXT = (".md", ".txt", ".csv", ".json", ".log", ".yaml", ".yml")
_MAX_QUOTE = 4000   # 单文件喂给 LLM 的字符上限,防超长


@dataclass
class ArtifactDoc:
    """一份交付物文件的可引用内容(纯读,来源可追溯)."""
    product: str
    source_file: str           # zip 内相对路径,如 "execution-log/EXECUTION_LOG.md"
    is_text: bool              # 文本才有 content;二进制只记存在
    content: str | None        # 截断到 _MAX_QUOTE 的原文(文本才有)
    size: int

    def as_dict(self) -> dict:
        return asdict(self)


def _read_zip_docs(product: str, zip_path: str) -> list[ArtifactDoc]:
    """把一个 submission zip 里的文本文件读成可引用 ArtifactDoc 列表."""
    docs: list[ArtifactDoc] = []
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = info.filename
                low = name.lower()
                is_text = low.endswith(_TEXT_EXT)
                content = None
                if is_text:
                    try:
                        raw = zf.read(info)[:_MAX_QUOTE * 2]
                        content = raw.decode("utf-8", errors="replace")[:_MAX_QUOTE]
                    except Exception:
                        content = None
                        is_text = False
                docs.append(ArtifactDoc(product=product, source_file=name,
                                        is_text=is_text, content=content,
                                        size=info.file_size))
    except Exception:
        pass
    return docs


def collect_artifacts(task_id: str, product: str) -> list[ArtifactDoc]:
    """收集某产品在某题的所有交付物文本(artifact + log_bundle 里的 zip).

    board/uploads/as-<task>-<product>-<hash>/<product>/{artifact,log_bundle}/*.zip
    是提交管道落盘的原始产物。缺失 -> 返回空列表(如实,不伪造)。
    """
    docs: list[ArtifactDoc] = []
    pat = os.path.join(UPLOADS, f"as-{task_id}-{product}-*", product, "*", "*.zip")
    for zp in sorted(_glob.glob(pat)):
        docs.extend(_read_zip_docs(product, zp))
    return docs


# --- 归因结果结构 ----------------------------------------------------------
@dataclass
class Citation:
    """一条结论的原文出处(可点开核验)."""
    product: str
    source_file: str
    quote: str                 # 从交付物原文里摘录的片段(不改写)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class AttributionPoint:
    """针对某竞品的一条归因结论(疑似判断 + 原文引用).

    suspected_category 只取 findings 层已有的类别词汇,不另造新判定:
      feature-gap        竞品有、我们缺的功能能力(该补齐)
      experience-borrow  竞品的体验/交互进步(值得借鉴)
      execution-detail   同能力下竞品执行更到位的步骤差异
    final_category 恒为 None —— PM 复核拍板,机器不代填。
    """
    competitor: str
    headline: str              # 一句话:竞品好在哪
    detail: str                # 展开:好在哪一步 / 多做了什么
    suspected_category: str
    final_category: None = None
    citations: list[Citation] = field(default_factory=list)
    confidence: str = "normal"  # normal | low_confidence(无引用支撑时)

    def as_dict(self) -> dict:
        d = asdict(self)
        return d


@dataclass
class TaskAttribution:
    task_id: str
    baseline: str
    dry_run: bool              # LLM 不可用时 True(占位,不伪造)
    engine: str                # 用的模型标识,可追溯
    points: list[AttributionPoint]
    note: str | None = None
    evidence_tier: str = "process-level"   # process-level | artifact-level | unavailable

    def as_dict(self) -> dict:
        return {"task_id": self.task_id, "baseline": self.baseline,
                "dry_run": self.dry_run, "engine": self.engine,
                "note": self.note, "evidence_tier": self.evidence_tier,
                "points": [p.as_dict() for p in self.points]}


# --- 证据档位 (B: 交付物对比降级路径) --------------------------------------
# 归因证据分三档,决定归因走「过程级」还是「成品级」路径 + confidence 上限:
#   process-level  有执行日志(执行时间线/过程),能看清竞品「怎么一步步做到的」。
#   artifact-level  只有成品交付物(无日志),只能凭成品反推「它做到了什么」——
#                   看得到结果、看不清过程,结论确定性天然弱,confidence 封顶。
#   unavailable     两者都拿不到,无法归因(如实标,不脑补)。
PROCESS_LEVEL = "process-level"
ARTIFACT_LEVEL = "artifact-level"
TIER_UNAVAILABLE = "unavailable"
# artifact-level 结论的 confidence 上限:即便引用命中,也不给 normal,只到 tentative
# ——「仅凭成品反推」比「有日志看过程」弱一档,不许冒充强证据。
_TIER_CONF_CAP = {PROCESS_LEVEL: "normal", ARTIFACT_LEVEL: "tentative",
                  TIER_UNAVAILABLE: "low_confidence"}
_CONF_RANK = {"low_confidence": 0, "tentative": 1, "normal": 2}
# 日志类文件名特征:执行日志包里的时间线/过程记录(非成品)。
_LOG_HINTS = ("execution-log", "execution_log", "exec-log", "log_bundle",
              "timeline", ".log")


def _docs_have_log(docs: list[ArtifactDoc]) -> bool:
    """这批交付物里是否含执行日志(过程级证据)。仅看文件名特征,纯派生。"""
    for d in docs:
        low = (d.source_file or "").lower()
        if any(h in low for h in _LOG_HINTS):
            return True
    return False


def evidence_tier(docs_by_prod: dict, competitors: list[str],
                  baseline: str = "vio") -> str:
    """按可得证据判归因档位(process/artifact/unavailable)。

    有任一相关产品(基线或竞品)带执行日志 -> process-level(能看过程);
    否则只要有可读成品交付物 -> artifact-level(仅凭成品反推);
    连成品都没有 -> unavailable(无法归因)。
    """
    rel = [baseline] + list(competitors)
    any_docs = any(docs_by_prod.get(p) for p in rel)
    if not any_docs:
        return TIER_UNAVAILABLE
    any_log = any(_docs_have_log(docs_by_prod.get(p) or []) for p in rel)
    return PROCESS_LEVEL if any_log else ARTIFACT_LEVEL


def _cap_confidence_by_tier(conf: str, tier: str) -> str:
    """把一条结论的 confidence 按档位封顶(artifact-level 不许到 normal)。"""
    cap = _TIER_CONF_CAP.get(tier, "low_confidence")
    if _CONF_RANK.get(conf, 0) > _CONF_RANK.get(cap, 0):
        return cap
    return conf


# --- Claude 最强模型归因 ---------------------------------------------------
_ENGINE = os.environ.get("GAP_ATTRIB_MODEL", "claude-opus-4-8")

# artifact-level 降级路径专用提示片段:提醒模型只看得到成品、看不到过程,
# 结论要标不确定性,别把「成品长这样」脑补成「它一定是这么做的」。
_ARTIFACT_HINT = """
【证据档位: 仅成品级】本次拿不到执行日志,你只能看到双方的**成品交付物**,看不到
竞品一步步怎么做的过程。因此:只依据成品里能直接看到的差异下结论,用词标明不确定性
(如「成品显示…,推测其可能…」),绝不把「成品呈现的结果」当成「确定的实现过程」。
证据不足以判断竞品是否真的更好时,points 返回空数组。"""

_SYS = """你是竞品评测系统的差距归因分析器。基线产品是 vio(Violoop)。
给你一道任务的 expected(判定标准)、以及基线 vio 与某竞品各自的交付物原文。
你的唯一职责:找出**竞品比 vio 好在哪一步、具体多做了什么**,并判断这是否是
竞品的新功能/值得借鉴的体验进步。

铁律(违反则输出作废):
1. 每条结论必须能落到交付物原文 —— 在 citations 里给出 product、source_file、
   以及**逐字摘录**的 quote(不得改写、不得脑补)。找不到原文支撑就不要下这条结论。
2. 你只给**疑似**判断,不下最终定论。suspected_category 只能从这三个里选:
   feature-gap(竞品有我们缺的能力) / experience-borrow(值得借鉴的体验进步) /
   execution-detail(同能力下执行更到位)。
3. 若竞品并不比 vio 好、或证据不足,points 返回空数组,别硬凑。
只输出 JSON,格式:
{"points":[{"competitor":"manus","headline":"...","detail":"...",
"suspected_category":"feature-gap","citations":[{"product":"manus",
"source_file":"...","quote":"..."}]}]}"""


def _docs_block(docs: list[ArtifactDoc]) -> str:
    if not docs:
        return "(无交付物 / 未上传)"
    parts = []
    for d in docs:
        if d.is_text and d.content:
            parts.append(f"### [{d.product}] {d.source_file}\n```\n{d.content}\n```")
        else:
            parts.append(f"### [{d.product}] {d.source_file} (二进制/{d.size}B,仅存在)")
    return "\n\n".join(parts)


import urllib.request as _urlreq


def _post_via_proxy(url: str, headers: dict, payload: dict, timeout: int = 120) -> dict:
    """POST 到西方端点(Anthropic),**强制走代理**,不受 NO_PROXY 影响.

    坑(实测): launchd 后端设了 NO_PROXY=127.0.0.1,localhost(为让 localhost 回环
    绕过系统代理)。而我们的代理本身就在 127.0.0.1:7897 —— urllib 的默认 opener 会把
    「通过 127.0.0.1 代理访问 Anthropic」也命中 NO_PROXY 而绕过代理直连,国内直连
    Anthropic 必被 cloudflare 403。故这里用显式 ProxyHandler 的独立 opener,把代理
    钉死在请求上,绕开 urllib 对 NO_PROXY 的解析。代理地址取 GAP_ATTRIB_HTTPS_PROXY
    或 HTTPS_PROXY;都没有则退回普通请求(直连)。
    """
    proxy = (os.environ.get("GAP_ATTRIB_HTTPS_PROXY")
             or os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"))
    headers = {"User-Agent": RC._UA, **headers}
    data = json.dumps(payload).encode()
    req = _urlreq.Request(url, data=data, headers=headers, method="POST")
    if proxy:
        opener = _urlreq.build_opener(
            _urlreq.ProxyHandler({"http": proxy, "https": proxy}))
        with opener.open(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    with _urlreq.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _claude(prompt: str) -> dict:
    """调 Claude 最强模型(claude-opus-4-8),强制走代理访问 Anthropic."""
    key = os.environ.get("CLAUDE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return {"__dry_run__": True}
    url = "https://api.anthropic.com/v1/messages"
    hdr = {"Content-Type": "application/json", "x-api-key": key,
           "anthropic-version": "2023-06-01"}
    # 注意: claude-opus-4-8 起 temperature 已废弃(传了会 400),不带该字段。
    body = {"model": _ENGINE,
            "max_tokens": int(os.environ.get("GAP_ATTRIB_MAX_TOKENS", "4096")),
            "system": _SYS,
            "messages": [{"role": "user", "content": prompt}]}
    out = _post_via_proxy(url, hdr, body)
    return RC._parse_scores(out["content"][0]["text"])


def _validate_points(raw_points: list, docs_by_prod: dict[str, list[ArtifactDoc]]
                     ) -> list[AttributionPoint]:
    """把 LLM 原始 points 校验成 AttributionPoint:每条引用必须能在交付物原文里
    **逐字命中**,否则该引用剔除;一条结论若最终无任何有效引用 -> 标 low_confidence。
    这是「结论必须可追溯」铁律的机器闸,防 LLM 编造出处。"""
    valid_cats = {"feature-gap", "experience-borrow", "execution-detail"}
    points: list[AttributionPoint] = []
    for rp in (raw_points or []):
        if not isinstance(rp, dict):
            continue
        comp = str(rp.get("competitor", "")).strip()
        cat = str(rp.get("suspected_category", "")).strip()
        if cat not in valid_cats:
            cat = "execution-detail"
        good_cites: list[Citation] = []
        for c in (rp.get("citations") or []):
            if not isinstance(c, dict):
                continue
            cp = str(c.get("product", comp)).strip()
            sf = str(c.get("source_file", "")).strip()
            q = str(c.get("quote", "")).strip()
            if not q:
                continue
            # 逐字命中校验:引用文本必须真出现在该产品某份交付物原文里。
            hit = False
            for d in docs_by_prod.get(cp, []):
                if d.content and q[:120] in d.content:
                    hit = True
                    break
            if hit:
                good_cites.append(Citation(product=cp, source_file=sf, quote=q))
        conf = "normal" if good_cites else "low_confidence"
        points.append(AttributionPoint(
            competitor=comp, headline=str(rp.get("headline", "")).strip(),
            detail=str(rp.get("detail", "")).strip(),
            suspected_category=cat, citations=good_cites, confidence=conf))
    return points


def attribute_task(task_id: str, competitors: list[str], expected_text: str = "",
                   baseline: str = "vio") -> TaskAttribution:
    """对一道题做归因:读双方交付物 -> Claude 最强模型分析 -> 校验引用 -> 结构化。

    competitors : 本题里**领先或持平**基线、值得归因的竞品(调用方从 score_diffs 选)。
    expected_text: 任务判定标准原文(tasks/<id>/expected/end-state.md),给模型对齐。
    LLM 不可用 -> dry_run=True 占位,不伪造。
    """
    base_docs = collect_artifacts(task_id, baseline)
    docs_by_prod: dict[str, list[ArtifactDoc]] = {baseline: base_docs}
    for c in competitors:
        docs_by_prod[c] = collect_artifacts(task_id, c)

    # 无任何竞品交付物可读 -> 如实标,不硬跑模型。
    if not any(docs_by_prod.get(c) for c in competitors):
        return TaskAttribution(task_id=task_id, baseline=baseline, dry_run=True,
                               engine=_ENGINE, points=[],
                               evidence_tier=TIER_UNAVAILABLE,
                               note="竞品交付物缺失或不可读,无法归因(如实标)")

    # B: 判归因档位。有日志走过程级;仅成品走降级路径(提示模型只凭成品反推)。
    tier = evidence_tier(docs_by_prod, competitors, baseline=baseline)

    comp_block = "\n\n".join(
        f"## 竞品 {c} 的交付物\n{_docs_block(docs_by_prod.get(c, []))}"
        for c in competitors)
    artifact_hint = _ARTIFACT_HINT if tier == ARTIFACT_LEVEL else ""
    prompt = (f"# 任务 {task_id}\n\n## 判定标准(expected)\n{expected_text or '(未提供)'}\n\n"
              f"## 基线 {baseline}(Violoop)的交付物\n{_docs_block(base_docs)}\n\n"
              f"{comp_block}\n{artifact_hint}\n\n"
              "请按 system 指令找出竞品比 vio 好在哪、多做了什么,只输出 JSON。")

    try:
        res = _claude(prompt)
    except Exception as ex:
        return TaskAttribution(task_id=task_id, baseline=baseline, dry_run=True,
                               engine=_ENGINE, points=[],
                               note=f"归因模型调用失败(如实标): {str(ex)[:160]}")
    if res.get("__dry_run__"):
        return TaskAttribution(task_id=task_id, baseline=baseline, dry_run=True,
                               engine=_ENGINE, points=[],
                               note="未配置 CLAUDE_API_KEY,归因跳过(占位)")
    if res.get("error"):
        return TaskAttribution(task_id=task_id, baseline=baseline, dry_run=True,
                               engine=_ENGINE, points=[],
                               note=f"归因输出不可解析(如实标): {res.get('error')}")

    points = _validate_points(res.get("points"), docs_by_prod)
    return TaskAttribution(task_id=task_id, baseline=baseline, dry_run=False,
                           engine=_ENGINE, points=points)


def load_expected(task_id: str) -> str:
    """读任务判定标准原文(expected/end-state.md 优先,退 README)。"""
    base = os.path.join(REPO, "tasks", task_id, "expected")
    for fn in ("end-state.md", "README.md"):
        p = os.path.join(base, fn)
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    return f.read()[:_MAX_QUOTE]
            except Exception:
                pass
    return ""
