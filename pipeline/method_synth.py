"""差距归因 -> 一句话功能点 -> 自动方法初稿 (自动闭环核心桥).

差距报告的归因层(gap_attribution)已能讲清"竞品比 vio 好在哪一步、多做了什么"
并附交付物原文引用。本模块把这些归因结论**自动提炼成研发一看就懂的一句话功能点**,
组装成方法初稿(methods draft)自动落库,进方法沉淀等人审核 —— 打通
"发现 -> 归因 -> 方法"的自动流转,人只在方法沉淀审核对不对。

立身铁律沿袭(一字不改):
  * 只从归因引用里提炼,绝不编造 —— 功能点必须对应某条带原文引用的归因结论;
    无有效引用的归因结论不生成功能点。
  * 机器只产出 draft(初稿),status=draft, author=system:auto。是否 approved
    仍由 reviewer/PM 拍板(方法复核闸不变),机器不越权把关/导出。
  * 去重: 同 (task_id, product) 已有 draft 则跳过, 不重复灌垃圾。

产出的 draft 正文结构(研发可读):
  ## 功能点(研发要做什么)   <- 一句话, LLM 从归因提炼
  ## 竞品为何强 + 落地建议     <- LLM 展开
  ## 证据(交付物原文引用)     <- 原样带出归因的 citations, 可追溯
  > 归因来源: gap_attribution / <engine>  (标注自动来源, 便于审核区分)
"""
from __future__ import annotations

import json
import os

from pipeline import gap_attribution as GA
from pipeline import methods as METH
from pipeline import store as STORE

_ENGINE = os.environ.get("GAP_ATTRIB_MODEL", "claude-opus-4-8")
AUTO_AUTHOR = "system:auto"

_SYS = """你是竞品评测系统的"方法提炼器"。给你一条已确认的差距归因结论(竞品在某任务上
比基线 vio 好在哪、多做了什么,并附交付物原文引用)。把它提炼成**研发可直接执行的卡片**。

铁律:
1. 只依据给你的归因结论和原文引用提炼,不得引入引用之外的臆测。判据不足的字段留空字符串
   (系统会如实标"待补"),绝不编造凑数。
2. feature_point 必须是**一句话、可落地的功能点**,研发一看就懂要做什么 —— 动词开头、
   具体到能力(如"接入联网检索工具,在执行前先做资料调研"),不要空泛(如"提升能力")。
3. scope 用一句话划边界:做到哪算够、哪些明确不在本次范围(防过度实现/漏做)。
4. acceptance 给可自测的验收判据:怎么算补上了这个能力(可观察的结果/行为)。
5. rival_practice 用 1-2 句转述竞品具体怎么做到的(来自引用,不脑补)。
6. suggestion 用 2-3 句讲清 vio 该怎么落地这个点。
只输出 JSON:
{"feature_point":"...","scope":"...","acceptance":"...","rival_practice":"...","suggestion":"..."}"""

# 结构化卡片字段(研发可执行)。priority 不由 LLM 判(避免主观),由 _compute_priority
# 按关联题数/域数派生粗分档。缺字段如实标此占位串, 不编造。
_CARD_FIELDS = ("feature_point", "scope", "acceptance", "rival_practice", "suggestion")
_TODO = "(待补 —— 归因判据不足,需人工补齐)"


def _synthesize_one(point: dict) -> dict | None:
    """把一条归因 point 提炼成结构化卡片 dict(feature_point/scope/acceptance/...)。

    无有效原文引用的归因结论(citations 空 / low_confidence)不提炼 -> None,
    守住"只从引用提炼、不编造"。LLM 不可用或输出不可解析 -> None(如实跳过)。
    feature_point 是硬要求(空则整条不成立 -> None);其余字段缺则留空(渲染时标待补)。
    """
    cites = point.get("citations") or []
    if not cites or point.get("confidence") == "low_confidence":
        return None
    cite_txt = "\n".join(
        f"- [{c.get('product')}] {c.get('source_file')}: {c.get('quote')}"
        for c in cites)
    prompt = (f"竞品: {point.get('competitor')}\n"
              f"疑似类别: {point.get('suspected_category')}\n"
              f"归因标题: {point.get('headline')}\n"
              f"归因详情: {point.get('detail')}\n"
              f"交付物原文引用:\n{cite_txt}\n\n"
              "请提炼成结构化卡片 JSON。")
    try:
        # 复用 gap_attribution 的强制走代理 _post + system 提示栈, 只换 system 内容。
        key = os.environ.get("CLAUDE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            return None
        url = "https://api.anthropic.com/v1/messages"
        hdr = {"Content-Type": "application/json", "x-api-key": key,
               "anthropic-version": "2023-06-01"}
        body = {"model": _ENGINE,
                "max_tokens": int(os.environ.get("GAP_ATTRIB_MAX_TOKENS", "1024")),
                "system": _SYS,
                "messages": [{"role": "user", "content": prompt}]}
        out = GA._post_via_proxy(url, hdr, body)
        res = GA.RC._parse_scores(out["content"][0]["text"])
    except Exception:
        return None
    if res.get("error"):
        return None
    fp = str(res.get("feature_point", "")).strip()
    if not fp:
        return None            # feature_point 是硬要求, 缺则整条不成立
    # 其余字段: 有则带出, 缺则留空(渲染时如实标待补)。
    card = {"feature_point": fp}
    for f in _CARD_FIELDS[1:]:
        card[f] = str(res.get(f, "")).strip()
    return card


def _compute_priority(con, subject: str, feature_point: str,
                      task_id: str | None = None) -> tuple[str, str]:
    """按关联题数 / 能力域数量派生优先级粗分档(高/中/低),纯算术、无主观权重。

    影响面 = 该 subject 名下 capability-gap findings 关联的**不同 task_id 数**(去重)+
    这些题横跨的**能力域数**。题多/域多 => 影响面大 => 高优先级。
    分档(粗、可解释, PRD OQ1 拍板起步): tasks>=3 或 domains>=2 => 高; tasks==2 => 中;
    否则(单题单域) => 低。拿不到 con / 读失败 -> 低 + 说明(如实, 不夸大)。
    返回 (档位, 一句话影响面说明)。
    """
    try:
        finds = [f for f in STORE.all_findings(con)
                 if f.get("subject") == subject
                 and f.get("suspected_category") == "capability-gap"]
    except Exception:
        return "低", "影响面未知(读发现失败,如实标)"
    task_ids = {f.get("task_id") for f in finds if f.get("task_id")}
    if task_id:
        task_ids.add(task_id)
    # 能力域: 从 task_id 前缀粗归(census-<rival>-* / matrix-<domain>-* / T*/TA*/W*)。
    # 精确域映射在 scores 里没有直接列, 这里用题号族做粗估, 只服务分档不做判定。
    n_tasks = len(task_ids)
    domains = set()
    for t in task_ids:
        t = str(t)
        if t.startswith("matrix-"):
            parts = t.split("-")
            if len(parts) >= 2:
                domains.add(parts[1])
        elif t.startswith("census-"):
            domains.add("census")
        else:
            domains.add(t.split("-")[0][:3])   # T1/T10/TA2/W1 族粗归
    n_dom = len(domains)
    if n_tasks >= 3 or n_dom >= 2:
        tier = "高"
    elif n_tasks == 2:
        tier = "中"
    else:
        tier = "低"
    return tier, f"关联 {n_tasks} 道题、跨 {n_dom} 个能力域族(粗分档,纯题数/域数派生)"


def _seg(value: str) -> str:
    """字段取值, 空则如实标待补(不编造)。"""
    v = (value or "").strip()
    return v if v else _TODO


def _render_draft(point: dict, synth: dict, engine: str,
                  source: str = "gap_attribution", *,
                  priority: str | None = None,
                  priority_note: str = "") -> str:
    """组装研发可执行的结构化方法卡片(六段 + 证据链 + 来源标注)。

    source 标注自动来源, 便于复核区分:
      gap_attribution   —— 竞品比 vio 好(同题对打归因), point.competitor 是竞品。
      vio_gap           —— vio 自己失败判「能力空白」, point.competitor 是基线 vio。
      capability_census —— 竞品能力清单里 vio 缺失的条目(清单差集)。
      capability_matrix —— 多竞品能力域矩阵里的空白格(竞品做到、vio 没做到)。
    六段(研发一看就懂要做什么/做到哪/怎么验/多重要/竞品怎么做的/证据在哪):
      功能点 / 范围边界 / 验收标准 / 优先级·影响面 / 竞品做法+落地建议 / 证据链。
    缺字段如实标待补(_TODO), 绝不编造凑数。
    """
    cites = point.get("citations") or []
    cite_lines = "\n".join(
        f"- [{c.get('product')}] `{c.get('source_file')}`: {c.get('quote')}"
        for c in cites) or "- (无)"
    is_cap_gap = point.get("suspected_category") == "capability-gap"
    reason_heading = ("## 竞品做法 + Violoop 落地建议" if not is_cap_gap
                      else "## 能力空白落地建议")
    obs_heading = ("## 能力空白归因(机器观察)" if is_cap_gap
                   else "## 差距归因(机器观察)")
    subj_label = "基线(vio 缺此能力)" if source == "vio_gap" else "竞品/来源"
    # 竞品做法 + 落地建议合并成一段(rival_practice 缺则退回 headline/detail)。
    rival = synth.get("rival_practice", "")
    suggestion = synth.get("suggestion") or point.get("detail", "")
    practice_block = "\n".join(filter(None, [
        f"- 竞品做法: {_seg(rival)}",
        f"- Violoop 落地建议: {_seg(suggestion)}",
    ]))
    prio = priority or "未评"
    return "\n".join([
        "## 功能点(研发要做什么)",
        _seg(synth.get("feature_point")),
        "",
        "## 范围边界(做到哪算够 / 哪些不在本次范围)",
        _seg(synth.get("scope")),
        "",
        "## 验收标准(怎么算补上了这个能力)",
        _seg(synth.get("acceptance")),
        "",
        "## 优先级 · 影响面",
        f"- 优先级: {prio}" + (f" · {priority_note}" if priority_note else ""),
        "",
        reason_heading,
        practice_block,
        "",
        obs_heading,
        f"- {subj_label}: {point.get('competitor')}",
        f"- 疑似类别: {point.get('suspected_category')}",
        f"- 归因: {point.get('headline')}",
        "",
        "## 证据链(交付物/清单原文引用)",
        cite_lines,
        "",
        f"> 自动提炼来源: {source} / {engine} · 状态 draft, 待 reviewer/PM 审核。",
    ])


def synthesize_from_vio_gap(con, task_id: str, vio_gap: dict, *,
                            skip_existing: bool = True) -> list[dict]:
    """功能A: 把 vio_gap 的「能力空白」判定自动提炼成方法初稿并落库(status=draft)。

    vio_gap : vio_gap.VioGapResult.as_dict() 的产出。只有 verdict==capability-gap
    且带有效引用(confidence=normal)才提炼 —— dry_run / execution-gap / 无引用一律
    返回 [](如实, 不硬造)。产品固定为基线自身(subject=vio):这是「vio 缺什么能力」
    的候选新功能, 提炼后进方法沉淀等 reviewer/PM/AI 复核。
    去重: 同 (task_id, 'vio') 已有 draft 则跳过。
    """
    if not vio_gap or vio_gap.get("dry_run"):
        return []
    if vio_gap.get("verdict") != "capability-gap":
        return []
    baseline = vio_gap.get("baseline") or "vio"
    # 塑成 _synthesize_one 认识的 point 形状(citations 来自 vio 自己的交付物引用)。
    point = {
        "competitor": baseline,
        "headline": vio_gap.get("headline", ""),
        "detail": vio_gap.get("detail", ""),
        "suspected_category": "capability-gap",
        "confidence": vio_gap.get("confidence", "normal"),
        "citations": vio_gap.get("citations") or [],
    }
    if not point["citations"] or point["confidence"] == "low_confidence":
        return []

    if skip_existing:
        for m in METH.list_methods(con):
            if (m.get("task_id"), m.get("product")) == (task_id, baseline):
                return []

    synth = _synthesize_one(point)
    if not synth:
        return []
    engine = vio_gap.get("engine") or _ENGINE
    prio, note = _compute_priority(con, baseline, point["headline"], task_id=task_id)
    draft = _render_draft(point, synth, engine, source="vio_gap",
                          priority=prio, priority_note=note)
    row = METH.draft_method(con, author={"id": AUTO_AUTHOR, "role": "reviewer"},
                            task_id=task_id, product=baseline, draft=draft)
    return [row]


def synthesize_from_census(con, rival: str, findings: list[dict], *,
                           baseline: str = "vio",
                           skip_existing: bool = True) -> list[dict]:
    """功能B: 把能力普查差集的 capability-gap Finding 自动提炼成方法初稿(draft)。

    findings : capability_census.census_to_findings(rival) 的产出(capability-gap,
    subject=rival, evidence 带竞品能力条目)。每条差集候选提炼成一句话功能点落 draft
    (product=rival, task_id=finding.task_id 即 census-<rival>),进方法沉淀等复核。
    去重: 同 (task_id, product) 已有 draft 跳过。竞品能力条目本身即证据(可追溯),
    塑成 point 的 citations 供 _synthesize_one/_render_draft 复用。
    """
    if not findings:
        return []
    existing = set()
    if skip_existing:
        for m in METH.list_methods(con):
            existing.add((m.get("task_id"), m.get("product")))

    created: list[dict] = []
    for fd in findings:
        if fd.get("suspected_category") != "capability-gap":
            continue
        task_id = fd.get("task_id") or f"census-{rival}"
        if skip_existing and (task_id, rival) in existing:
            continue
        # 竞品能力条目当作引用(source_file=capability-list),证据可追溯。
        cites = [{"product": rival, "source_file": "capability-list",
                  "quote": e.get("ref", "")}
                 for e in (fd.get("evidence") or []) if e.get("ref")]
        if not cites:
            continue
        point = {"competitor": rival, "headline": fd.get("phenomenon", ""),
                 "detail": fd.get("phenomenon", ""),
                 "suspected_category": "capability-gap", "confidence": "normal",
                 "citations": cites}
        synth = _synthesize_one(point)
        if not synth:
            continue
        prio, note = _compute_priority(con, rival, point["headline"], task_id=task_id)
        draft = _render_draft(point, synth, _ENGINE, source="capability_census",
                              priority=prio, priority_note=note)
        row = METH.draft_method(con, author={"id": AUTO_AUTHOR, "role": "reviewer"},
                                task_id=task_id, product=rival, draft=draft)
        created.append(row)
        existing.add((task_id, rival))
    return created


def synthesize_from_matrix(con, domain: str, findings: list[dict], *,
                           baseline: str = "vio",
                           skip_existing: bool = True) -> list[dict]:
    """C: 把多竞品能力域矩阵的 capability-gap Finding 提炼成方法初稿(draft)。

    findings : capability_matrix.matrix_to_capability_gap_findings(m) 的产出
    (capability-gap, subject=竞品, evidence 带矩阵证据, task_id=matrix-<domain>-<指纹>)。
    结构与 census Finding 同形(subject=竞品 + evidence.ref),故复用 census 的提炼逻辑:
    每条候选按其 subject(竞品)分别塑 point → 结构化卡片 draft。去重同 (task_id, 竞品)。
    """
    if not findings:
        return []
    existing = set()
    if skip_existing:
        for m in METH.list_methods(con):
            existing.add((m.get("task_id"), m.get("product")))

    created: list[dict] = []
    for fd in findings:
        if fd.get("suspected_category") != "capability-gap":
            continue
        rival = fd.get("subject")
        task_id = fd.get("task_id") or f"matrix-{domain}"
        if skip_existing and (task_id, rival) in existing:
            continue
        cites = [{"product": rival, "source_file": "capability-matrix",
                  "quote": e.get("ref", "")}
                 for e in (fd.get("evidence") or []) if e.get("ref")]
        if not cites:
            continue
        point = {"competitor": rival, "headline": fd.get("phenomenon", ""),
                 "detail": fd.get("phenomenon", ""),
                 "suspected_category": "capability-gap", "confidence": "normal",
                 "citations": cites}
        synth = _synthesize_one(point)
        if not synth:
            continue
        prio, note = _compute_priority(con, rival, point["headline"], task_id=task_id)
        draft = _render_draft(point, synth, _ENGINE, source="capability_matrix",
                              priority=prio, priority_note=note)
        row = METH.draft_method(con, author={"id": AUTO_AUTHOR, "role": "reviewer"},
                                task_id=task_id, product=rival, draft=draft)
        created.append(row)
        existing.add((task_id, rival))
    return created


def synthesize_from_attribution(con, task_id: str, attribution: dict, *,
                                skip_existing: bool = True) -> list[dict]:
    """把一道题的归因结果自动提炼成方法初稿并落库(status=draft)。

    attribution : gap_attribution.TaskAttribution.as_dict() 的产出。
    返回本次新建的 method 行列表。dry_run / 无 points -> 返回 [](如实, 不硬造)。
    去重: skip_existing 时, 同 (task_id, product) 已有 draft 则跳过。
    """
    if not attribution or attribution.get("dry_run"):
        return []
    points = attribution.get("points") or []
    if not points:
        return []
    engine = attribution.get("engine") or _ENGINE

    existing = set()
    if skip_existing:
        for m in METH.list_methods(con):
            existing.add((m.get("task_id"), m.get("product")))

    created: list[dict] = []
    for p in points:
        product = p.get("competitor")
        if skip_existing and (task_id, product) in existing:
            continue
        synth = _synthesize_one(p)
        if not synth:
            continue           # 无引用支撑 / 提炼失败 -> 不生成(守铁律)
        prio, note = _compute_priority(con, product, p.get("headline", ""), task_id=task_id)
        draft = _render_draft(p, synth, engine, priority=prio, priority_note=note)
        row = METH.draft_method(con, author={"id": AUTO_AUTHOR, "role": "reviewer"},
                                task_id=task_id, product=product, draft=draft)
        created.append(row)
        existing.add((task_id, product))
    return created
