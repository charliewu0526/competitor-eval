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
比基线 vio 好在哪、多做了什么,并附交付物原文引用)。把它提炼成研发能直接照做的东西。

铁律:
1. 只依据给你的归因结论和原文引用提炼,不得引入引用之外的臆测。
2. feature_point 必须是**一句话、可落地的功能点**,研发一看就懂要做什么 —— 动词开头、
   具体到能力(如"接入联网检索工具,在执行前先做资料调研"),不要空泛(如"提升能力")。
3. suggestion 用 2-3 句讲清 vio 该怎么落地这个点。
只输出 JSON: {"feature_point":"...","suggestion":"..."}"""


def _synthesize_one(point: dict) -> dict | None:
    """把一条归因 point 提炼成 {feature_point, suggestion}。

    无有效原文引用的归因结论(citations 空 / low_confidence)不提炼 -> None,
    守住"只从引用提炼、不编造"。LLM 不可用或输出不可解析 -> None(如实跳过)。
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
              "请提炼成 JSON。")
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
    fp = str(res.get("feature_point", "")).strip()
    if not fp or res.get("error"):
        return None
    return {"feature_point": fp,
            "suggestion": str(res.get("suggestion", "")).strip()}


def _render_draft(point: dict, synth: dict, engine: str) -> str:
    """组装研发可读的方法初稿正文(功能点 + 落地建议 + 原文引用 + 来源标注)。"""
    cites = point.get("citations") or []
    cite_lines = "\n".join(
        f"- [{c.get('product')}] `{c.get('source_file')}`: {c.get('quote')}"
        for c in cites) or "- (无)"
    return "\n".join([
        "## 功能点(研发要做什么)",
        synth["feature_point"],
        "",
        "## 竞品为何强 + Violoop 落地建议",
        synth.get("suggestion") or point.get("detail", ""),
        "",
        "## 差距归因(机器观察)",
        f"- 竞品: {point.get('competitor')}",
        f"- 疑似类别: {point.get('suspected_category')}",
        f"- 归因: {point.get('headline')}",
        "",
        "## 证据(交付物原文引用)",
        cite_lines,
        "",
        f"> 自动提炼来源: gap_attribution / {engine} · 状态 draft, 待 reviewer/PM 审核。",
    ])


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
        draft = _render_draft(p, synth, engine)
        row = METH.draft_method(con, author={"id": AUTO_AUTHOR, "role": "reviewer"},
                                task_id=task_id, product=product, draft=draft)
        created.append(row)
        existing.add((task_id, product))
    return created
