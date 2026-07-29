"""E: AI 预复核器 —— 复核前 AI 先给建议 + 理由,人只需确认(人是最终闸).

上线后数据体检暴露: findings 15 条只 1 条填了 final_category、methods 6 条全卡 draft
—— 复核环节空转。本模块让 AI 在人复核前先读 finding/method 给出建议:

  * precheck_finding  -> 建议 final_category / product_judgment + 理由(枚举对齐 findings)。
  * precheck_method   -> 建议 approve / revise + 理由。

铁律(E 的立身之本):
  * AI 只给**建议**,绝不落最终结论。final_category / approve 仍由人在复核端点拍板
    (人是最终闸)。本模块纯读 + 调 LLM,无落库副作用。
  * 建议的枚举值必须落在 findings.FINAL_CATEGORY_VALUES / PRODUCT_JUDGMENT_VALUES 内,
    越界一律退回 None(不塞脏建议)。
  * LLM 不可用 / 输出不可解析 -> dry_run 占位(如实标,不伪造建议)。
"""
from __future__ import annotations

import json
import os

from pipeline import gap_attribution as GA
from pipeline import findings as F

_ENGINE = os.environ.get("GAP_ATTRIB_MODEL", "claude-opus-4-8")

_FINDING_SYS = """你是竞品评测系统的"复核助手"。给你一条机器产出的疑似发现(现象 +
证据引用 + 疑似类别),你的职责:为人类复核员**预判**它应归入哪个最终类别、以及对
Violoop 的产品判断,并给出简短理由。你只是给建议,最终由人拍板。

final_category 只能从这些里选一个:{final_cats}
product_judgment 只能从这些里选一个:{prod_judgments}

铁律:只依据给你的现象和证据判断,证据不足就在 reason 里说明并选最保守项。
只输出 JSON:{{"final_category":"...","product_judgment":"...","reason":"一句话理由"}}"""

_METHOD_SYS = """你是竞品评测系统的"方法把关助手"。给你一条自动提炼的方法初稿(研发
可执行卡片),你的职责:为人类把关员**预判**这条初稿是可以直接 approve(通过)还是需要
revise(打回补充),并给理由。你只是给建议,最终由人拍板。

判据: 功能点是否清晰可执行、范围/验收是否具体、证据链是否支撑、有无"待补"关键字段。
只输出 JSON:{"suggestion":"approve" 或 "revise","reason":"一句话理由"}"""


def _call_claude(system: str, user_content: str, max_tokens: int = 1024) -> dict:
    """调 Claude 给建议,强制走代理。无 key -> dry_run 标记。"""
    key = os.environ.get("CLAUDE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return {"__dry_run__": True}
    url = "https://api.anthropic.com/v1/messages"
    hdr = {"Content-Type": "application/json", "x-api-key": key,
           "anthropic-version": "2023-06-01"}
    body = {"model": _ENGINE, "max_tokens": max_tokens, "system": system,
            "messages": [{"role": "user", "content": user_content}]}
    out = GA._post_via_proxy(url, hdr, body)
    return GA.RC._parse_scores(out["content"][0]["text"])


def precheck_finding(finding: dict) -> dict:
    """AI 预复核一条 finding -> {suggested_final_category, suggested_product_judgment,
    reason, dry_run}. 越界枚举退回 None;LLM 不可用 -> dry_run。只给建议不落库。"""
    ev = finding.get("evidence") or finding.get("evidence_json") or ""
    if isinstance(ev, (list, dict)):
        ev = json.dumps(ev, ensure_ascii=False)
    sys = _FINDING_SYS.format(
        final_cats=" / ".join(F.FINAL_CATEGORY_VALUES),
        prod_judgments=" / ".join(F.PRODUCT_JUDGMENT_VALUES))
    content = (f"疑似类别: {finding.get('suspected_category')}\n"
               f"对象产品: {finding.get('subject')}\n"
               f"现象: {finding.get('phenomenon')}\n"
               f"证据: {ev[:2000]}\n\n请给出复核建议 JSON。")
    try:
        res = _call_claude(sys, content)
    except Exception as ex:
        return {"suggested_final_category": None, "suggested_product_judgment": None,
                "reason": f"预复核调用失败(如实标): {str(ex)[:140]}", "dry_run": True}
    if res.get("__dry_run__"):
        return {"suggested_final_category": None, "suggested_product_judgment": None,
                "reason": "未配置 CLAUDE_API_KEY,预复核跳过(占位)", "dry_run": True}
    if res.get("error"):
        return {"suggested_final_category": None, "suggested_product_judgment": None,
                "reason": f"预复核输出不可解析(如实标): {res.get('error')}", "dry_run": True}
    fc = str(res.get("final_category", "")).strip()
    pj = str(res.get("product_judgment", "")).strip()
    # 越界枚举退回 None(不塞脏建议)
    fc = fc if fc in F.FINAL_CATEGORY_VALUES else None
    pj = pj if pj in F.PRODUCT_JUDGMENT_VALUES else None
    return {"suggested_final_category": fc, "suggested_product_judgment": pj,
            "reason": str(res.get("reason", "")).strip(), "dry_run": False}


def precheck_method(method: dict) -> dict:
    """AI 预复核一条 method draft -> {suggestion: approve|revise, reason, dry_run}.
    越界建议退回 None;LLM 不可用 -> dry_run。只给建议不落库。"""
    draft = method.get("draft") or ""
    content = (f"任务: {method.get('task_id')} · 产品: {method.get('product')}\n\n"
               f"方法初稿:\n{draft[:3000]}\n\n请给出把关建议 JSON。")
    try:
        res = _call_claude(_METHOD_SYS, content)
    except Exception as ex:
        return {"suggestion": None, "reason": f"预复核调用失败(如实标): {str(ex)[:140]}",
                "dry_run": True}
    if res.get("__dry_run__"):
        return {"suggestion": None, "reason": "未配置 CLAUDE_API_KEY,预复核跳过(占位)",
                "dry_run": True}
    if res.get("error"):
        return {"suggestion": None,
                "reason": f"预复核输出不可解析(如实标): {res.get('error')}", "dry_run": True}
    sug = str(res.get("suggestion", "")).strip().lower()
    sug = sug if sug in ("approve", "revise") else None
    return {"suggestion": sug, "reason": str(res.get("reason", "")).strip(),
            "dry_run": False}
