"""功能B: 竞品能力普查 —— 能力清单差集 -> capability-gap 候选新功能.

治本视角:不再局限于「我们出的题」,而是拿竞品**自己声称已上线**的能力清单,和 vio
的能力清单做差集。差出来的(竞品有、vio 缺)就是候选新功能,标 capability-gap 汇入
方法沉淀 —— 和功能A(vio 失败反转)归一到同一个出口。

两条路子:
  1. diff_capabilities(rival) —— 拿已登记的能力清单做差集(纯逻辑,无网络)。
  2. extract_capabilities_via_llm(product, docs_text) —— 用 LLM 从官网/docs 原文抽出
     能力条目(status 一律先标 candidate,经复核才升 shipped)。这是 AI 复核闸的入口。

立身铁律沿袭:
  * 差集只认竞品的 shipped(已验证上线)条目为候选 —— limited/marketing/candidate 不算
    (避免把宣传话术 / 有坑的限制能力 / 未复核的抽取当成 vio「该补的」)。
  * 每条候选 Finding 必带竞品能力条目的 evidence + source(无证据不入池)。
  * 机器只标疑似 capability-gap + 现象, 不下结论;final_category / product_judgment
    留空由 PM/AI 复核。LLM 抽取产 candidate, 复核确认前绝不当已上线。
"""
from __future__ import annotations

import hashlib
import os
import re

from pipeline import capability_store as CS
from pipeline.findings import make_finding

_ENGINE = os.environ.get("GAP_ATTRIB_MODEL", "claude-opus-4-8")


# --- 能力标题标准化 (差集去重) ------------------------------------------------
_PUNCT = re.compile(r"[\s、,,。.:：;;/()()\[\]『』「」·\-—_'\"]+")


def _norm(text: str) -> str:
    """标准化能力文本用于差集匹配:去标点/空白/大小写, 取核心串。

    粗匹配即可 —— 差集宁可多列候选(PM 会复核),不宜漏。真正的语义归并在 LLM 抽取
    阶段可做得更细;这里保证『字面几乎相同』的能力不重复列成候选。
    """
    return _PUNCT.sub("", (text or "").lower())


def _tagset(entry) -> set[str]:
    return {t.lower() for t in (getattr(entry, "tags", None) or [])}


def _vio_has(entry, vio_shipped, vio_norms) -> bool:
    """判断 vio 是否已具备竞品的某能力(标题标准化包含 或 tag 交集)。"""
    en = _norm(entry.capability)
    for vn in vio_norms:
        if not vn or not en:
            continue
        # 任一方包含另一方的核心串 => 视为同一能力(粗匹配, 宁多列勿漏)。
        if en in vn or vn in en:
            return True
    et = _tagset(entry)
    if et:
        for v in vio_shipped:
            if et & _tagset(v):
                return True
    return False


# --- 1. 能力清单差集 ---------------------------------------------------------
def diff_capabilities(rival: str, baseline: str = "vio"):
    """竞品 shipped 能力里 vio 清单没有的 -> 候选新功能条目列表.

    返回 [(CapabilityEntry, )] 里竞品独有的 shipped 条目。纯逻辑,无网络、无副作用。
    竞品/基线未登记清单 -> 空(如实, 不伪造)。
    """
    rival_list = CS.load_capabilities(rival)
    vio_list = CS.load_capabilities(baseline)
    vio_shipped = vio_list.shipped()
    vio_norms = [_norm(e.capability) for e in vio_shipped]
    gaps = []
    for e in rival_list.shipped():
        if not _vio_has(e, vio_shipped, vio_norms):
            gaps.append(e)
    return gaps


def census_to_findings(rival: str, baseline: str = "vio") -> list[dict]:
    """差集 -> capability-gap Finding 列表(subject=rival).

    每条候选新功能一条 Finding:phenomenon 陈述『竞品已上线该能力、vio 清单缺失』,
    evidence 带竞品能力条目的 source/证据。task_id 用合成 id(census:<rival>)以复用
    findings/methods 的 (task_id, ...) 键结构。机器只标疑似, 不下结论。
    """
    out: list[dict] = []
    for e in diff_capabilities(rival, baseline):
        evid = [{"source": "capability-list",
                 "ref": f"[{rival}] {e.capability} — {e.evidence} ({e.source})"}]
        phen = (f"{rival} 已上线能力『{e.capability}』(证据: {e.evidence});"
                f"基线 {baseline} 能力清单未登记该能力入口 —— 疑似能力空白, 候选新功能")
        # 每条候选给独立 task_id(census-<rival>-<能力指纹>):findings 表
        # UNIQUE(task_id, rule, subject) 与 methods 去重键 (task_id, product) 都以
        # task_id 区分,否则同竞品多条候选会塌成一条。指纹按能力文本稳定 -> 重跑幂等
        # 更新同一条,不重复灌 draft。
        digest = hashlib.sha1(_norm(e.capability).encode("utf-8")).hexdigest()[:8]
        f = make_finding(
            task_id=f"census-{rival}-{digest}", rule="capability-census",
            suspected_category="capability-gap", subject=rival,
            phenomenon=phen, evidence=evid)
        if f is not None:
            out.append(f.as_dict())
    return out


# --- 2. LLM 抽取 (AI 复核闸入口) --------------------------------------------
_EXTRACT_SYS = """你是竞品能力普查抽取器。给你某竞品官网/文档/评测的原文,抽出它**声称
具备的具体能力条目**(不是能力域, 是可落地的功能点, 如『自然语言生成演示 deck 并导出
PDF』)。对每条判断真实性档位:
  shipped   —— 原文明确是已上线、可验证的功能(docs/changelog/features 页)。
  limited   —— 部分真实 / 有明显限制(原文自己或评测提到限制)。
  marketing —— 纯宣传话术, 无功能支撑(关系营销/愿景措辞)。
铁律:每条必须给 evidence(原文依据)。只输出 JSON:
{"entries":[{"capability":"...","status":"shipped","evidence":"原文依据","source":"出处"}]}"""


def extract_capabilities_via_llm(product: str, docs_text: str,
                                 source: str = "") -> "CS.CapabilityList":
    """用 LLM 从原文抽能力条目 -> CapabilityList(status 一律降级为 candidate).

    AI 复核闸: 无论 LLM 标 shipped/limited/marketing, 机器抽取的结果一律先标
    **candidate**(待复核) —— 差集不认 candidate 为候选, 必须经 review_capability
    (LLM 或人)确认才升 shipped。LLM 原判的 status 存进 tags(如 "llm:shipped")留痕。
    LLM 不可用 / 输出不可解析 -> 空清单(如实, 不伪造)。
    """
    from pipeline import gap_attribution as GA
    key = os.environ.get("CLAUDE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return CS.CapabilityList(product=product, entries=[],
                                 note="未配置 CLAUDE_API_KEY, LLM 抽取跳过")
    url = "https://api.anthropic.com/v1/messages"
    hdr = {"Content-Type": "application/json", "x-api-key": key,
           "anthropic-version": "2023-06-01"}
    body = {"model": _ENGINE,
            "max_tokens": int(os.environ.get("GAP_ATTRIB_MAX_TOKENS", "4096")),
            "system": _EXTRACT_SYS,
            "messages": [{"role": "user",
                          "content": f"竞品: {product}\n出处: {source}\n\n原文:\n{docs_text[:12000]}"}]}
    try:
        out = GA._post_via_proxy(url, hdr, body)
        res = GA.RC._parse_scores(out["content"][0]["text"])
    except Exception as ex:
        return CS.CapabilityList(product=product, entries=[],
                                 note=f"LLM 抽取失败(如实标): {str(ex)[:160]}")
    if res.get("error"):
        return CS.CapabilityList(product=product, entries=[],
                                 note=f"LLM 抽取输出不可解析: {res.get('error')}")
    entries = []
    for r in (res.get("entries") or []):
        if not isinstance(r, dict):
            continue
        cap = str(r.get("capability", "")).strip()
        ev = str(r.get("evidence", "")).strip()
        if not cap or not ev:
            continue                       # 无证据不入清单
        llm_status = str(r.get("status", "")).strip() or "unknown"
        try:
            entries.append(CS.CapabilityEntry(
                capability=cap, status="candidate", evidence=ev,
                source=str(r.get("source", source)).strip(),
                tags=[f"llm:{llm_status}"]))     # 留痕 LLM 原判, 但落 candidate
        except ValueError:
            continue
    return CS.CapabilityList(product=product, entries=entries,
                             note=f"LLM 抽取({_ENGINE}), 全部 candidate 待复核")


def auto_research(product: str, urls: list[str], *,
                  persist: bool = True) -> dict:
    """D: 自动调研一个竞品 —— 抓来源链接 -> LLM 抽能力 -> 落 candidate 待复核.

    urls   : 用户贴的官网/新闻/社媒公开链接。
    流程: source_fetch 抓取(失败如实标)-> merge 成功正文 -> extract_capabilities_via_llm
    抽能力(一律 candidate,AI 复核闸)-> 每条打上其来源 URL + 抓取时间 -> persist 则并入
    registry/capabilities/<product>.json(按能力文本去重,不覆盖已 shipped/limited 的事实条目)。
    返回 {product, fetched:[抓取状态], extracted:[新condidate], persisted, note}。
    全部来源抓不到 -> 不调 LLM,如实标(缺数据不伪造)。
    """
    from pipeline import source_fetch as SF
    fetched = SF.fetch_sources(urls)
    merged, ok_sources = SF.merge_fetched_text(fetched)
    if not merged:
        return {"product": product, "fetched": fetched, "extracted": [],
                "persisted": False,
                "note": "所有来源均未抓到可读正文(如实标,不伪造能力条目)"}

    # 抓取时间取最早成功来源的(整体调研时点);source_url 用成功来源 URL 串。
    fetched_at = ok_sources[0].get("fetched_at")
    src_label = ", ".join(f["url"] for f in ok_sources)
    extracted = extract_capabilities_via_llm(product, merged, source=src_label)
    # 给每条 candidate 补 source_url + fetched_at(可追溯)。
    for e in extracted.entries:
        if not e.source_url:
            e.source_url = src_label
        if not e.fetched_at:
            e.fetched_at = fetched_at

    persisted = False
    if persist and extracted.entries:
        existing = CS.load_capabilities(product)
        seen = {_norm(x.capability) for x in existing.entries}
        merged_entries = list(existing.entries)
        for e in extracted.entries:
            if _norm(e.capability) not in seen:
                merged_entries.append(e)
                seen.add(_norm(e.capability))
        existing.entries = merged_entries
        CS.save_capabilities(existing)
        persisted = True

    return {"product": product, "fetched": fetched,
            "extracted": [e.as_dict() for e in extracted.entries],
            "persisted": persisted, "note": extracted.note}


def review_capability(entry: "CS.CapabilityEntry", *, approve: bool,
                      reviewer: str = "") -> "CS.CapabilityEntry":
    """AI/人 复核闸: 把一条 candidate 条目确认(->shipped)或维持待议.

    approve=True -> status 升 shipped(留痕 reviewer);approve=False -> 保持 candidate。
    只处理 candidate 条目 —— 已 shipped/limited/marketing 的不在此改(那是数据源事实)。
    """
    if entry.status != "candidate":
        return entry
    if approve:
        entry.status = "shipped"
        if reviewer:
            entry.tags = list(entry.tags) + [f"reviewed:{reviewer}"]
    return entry
