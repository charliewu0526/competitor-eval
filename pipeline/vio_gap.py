"""功能A: cannot-reach / vio 失败 反转成信号 —— 执行差距 vs 能力空白.

原来「vio 够不着、竞品做到了」的题(vio 失败)只作为 feature-gap 现象记一笔。
本模块把 vio 自己的失败**再往里问一层**:vio 的交付物是

  * 执行差距 execution-gap —— 有这个能力入口、试了但做错(该进 bug/质量轴修);
  * 能力空白 capability-gap —— 根本没有这个能力入口(该补的候选新功能)。

只有 capability-gap 单独成类、进方法沉淀作候选新功能;execution-gap 不产 Finding
(它由 vio-bug / quality-alert 轴覆盖,别重复灌进「该补的新功能」)。

立身铁律(一字不改沿袭 gap_attribution / findings):
  * 机器只给**疑似**判定(verdict),绝不代 PM 下最终结论 —— 产出的 Finding
    suspected_category=capability-gap 是「疑似」,final_category 留空由 PM/AI 复核填。
  * 判定必须落到 vio 交付物原文引用(citations 逐字命中校验),无引用支撑 ->
    confidence=low_confidence,不生成 Finding(宁可少说不可编造)。
  * 缺数据如实标 —— 拿不到 vio 交付物 / LLM 不可用 -> dry_run 占位,绝不伪造机理。

纯派生 + 一次 LLM 判定,判定权仍归 PM/复核。复用 gap_attribution 的强制走代理
_post_via_proxy + 交付物读取,只换 system 提示与产出结构。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict

from pipeline import gap_attribution as GA
from pipeline.findings import make_finding, Finding

EXECUTION_GAP = "execution-gap"
CAPABILITY_GAP = "capability-gap"
_VERDICTS = (EXECUTION_GAP, CAPABILITY_GAP)

_ENGINE = os.environ.get("GAP_ATTRIB_MODEL", "claude-opus-4-8")

_SYS = """你是竞品评测系统的「基线失败归因器」。基线产品是 vio(Violoop)。
给你一道任务的 expected(判定标准),以及基线 vio 在该题的交付物原文(执行日志/产物)。
vio 在这道题上**失败了**(末态核验未通过或够不着)。你的唯一职责:判断这次失败属于
哪一种,并给出**逐字原文引用**支撑:

  1. execution-gap(执行差距):vio **有**这个能力入口 —— 它确实尝试去做了(日志里
     能看到它打开了对应 app / 调用了对应工具 / 走了对应流程),只是中途做错、做偏、
     没做完。这是「能力在、执行没到位」,该进 bug / 质量修复轨。
  2. capability-gap(能力空白):vio **根本没有**这个能力入口 —— 日志里看不到它有对应
     的工具 / 集成 / 操作路径去触达任务目标,它是「不会做/够不着」而非「做错」。这是
     该补齐的候选新功能。

铁律(违反则输出作废):
1. verdict 只能是 "execution-gap" 或 "capability-gap" 二选一。
2. 你的判定必须能落到 vio 交付物原文 —— 在 citations 里给出 source_file 和**逐字摘录**
   的 quote(不得改写、不得脑补)。判 capability-gap 尤其要有「找不到能力入口」的原文
   依据(如日志显示它反复尝试无关操作 / 明确说没有该工具 / 根本没触及目标 app)。
3. 证据不足以区分时,判 execution-gap(更保守 —— 不轻易断言「没能力」,避免冤枉标缺口)。
只输出 JSON,格式:
{"verdict":"capability-gap","headline":"一句话:vio 缺什么能力入口/哪步执行差",
"detail":"展开:凭什么这么判",
"citations":[{"source_file":"execution-log/EXECUTION_LOG.md","quote":"逐字原文"}]}"""


@dataclass
class VioGapResult:
    """vio 一道失败题的归因判定结果(疑似 + 引用 + 可选 Finding).

    verdict          : execution-gap | capability-gap | None(dry_run 时)
    finding          : 仅当 verdict==capability-gap 且有有效引用时非 None。
    dry_run          : LLM 不可用 / 无交付物 / 输出不可解析时 True(占位不伪造)。
    """
    task_id: str
    baseline: str
    verdict: str | None
    headline: str
    detail: str
    citations: list[dict] = field(default_factory=list)
    confidence: str = "normal"          # normal | tentative | low_confidence
    dry_run: bool = False
    engine: str = _ENGINE
    note: str | None = None
    finding: dict | None = None         # Finding.as_dict(),capability-gap 才有
    evidence_tier: str = "process-level"  # process-level | artifact-level | unavailable

    def as_dict(self) -> dict:
        d = asdict(self)
        return d


def _claude_verdict(prompt: str) -> dict:
    """调 Claude 最强模型判定,强制走代理(复用 gap_attribution 的 _post_via_proxy)."""
    key = os.environ.get("CLAUDE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return {"__dry_run__": True}
    url = "https://api.anthropic.com/v1/messages"
    hdr = {"Content-Type": "application/json", "x-api-key": key,
           "anthropic-version": "2023-06-01"}
    body = {"model": _ENGINE,
            "max_tokens": int(os.environ.get("GAP_ATTRIB_MAX_TOKENS", "2048")),
            "system": _SYS,
            "messages": [{"role": "user", "content": prompt}]}
    out = GA._post_via_proxy(url, hdr, body)
    return GA.RC._parse_scores(out["content"][0]["text"])


def _validate_citations(raw_cites, vio_docs) -> list[dict]:
    """引用逐字命中校验:每条 quote 必须真出现在 vio 某份交付物原文里,否则剔除。

    与 gap_attribution._validate_points 同一把尺子(防 LLM 编造出处),但这里主语固定
    是基线,只在 vio 自己的交付物里核验。返回命中的 {source_file, quote} 列表。
    """
    good: list[dict] = []
    for c in (raw_cites or []):
        if not isinstance(c, dict):
            continue
        sf = str(c.get("source_file", "")).strip()
        q = str(c.get("quote", "")).strip()
        if not q:
            continue
        for d in vio_docs:
            if d.content and q[:120] in d.content:
                good.append({"product": "vio", "source_file": sf, "quote": q})
                break
    return good


def classify_vio_failure(task_id: str, baseline: str = "vio",
                         expected_text: str | None = None,
                         vio_docs=None) -> VioGapResult:
    """对一道 vio 失败题归因:读 vio 交付物 -> Claude 判 exec/capability -> 校验引用.

    expected_text : 任务判定标准原文;None 则用 gap_attribution.load_expected 读。
    vio_docs      : 已读的 ArtifactDoc 列表;None 则用 collect_artifacts 收集。
    无交付物 / LLM 不可用 / 输出不可解析 -> dry_run=True 占位(如实,不伪造)。
    capability-gap 且有有效引用 -> 附一条 Finding(subject=vio),否则 finding=None。
    """
    if expected_text is None:
        expected_text = GA.load_expected(task_id)
    if vio_docs is None:
        vio_docs = GA.collect_artifacts(task_id, baseline)

    if not vio_docs:
        return VioGapResult(
            task_id=task_id, baseline=baseline, verdict=None, headline="",
            detail="", dry_run=True, engine=_ENGINE,
            note="基线交付物缺失或不可读,无法归因(如实标)")

    prompt = (f"# 任务 {task_id}\n\n## 判定标准(expected)\n{expected_text or '(未提供)'}\n\n"
              f"## 基线 {baseline}(Violoop)的交付物(它在本题失败了)\n"
              f"{GA._docs_block(vio_docs)}\n\n"
              "请按 system 指令判断这次失败是 execution-gap 还是 capability-gap,"
              "只输出 JSON。")

    try:
        res = _claude_verdict(prompt)
    except Exception as ex:
        return VioGapResult(
            task_id=task_id, baseline=baseline, verdict=None, headline="",
            detail="", dry_run=True, engine=_ENGINE,
            note=f"归因模型调用失败(如实标): {str(ex)[:160]}")
    if res.get("__dry_run__"):
        return VioGapResult(
            task_id=task_id, baseline=baseline, verdict=None, headline="",
            detail="", dry_run=True, engine=_ENGINE,
            note="未配置 CLAUDE_API_KEY,归因跳过(占位)")
    if res.get("error"):
        return VioGapResult(
            task_id=task_id, baseline=baseline, verdict=None, headline="",
            detail="", dry_run=True, engine=_ENGINE,
            note=f"归因输出不可解析(如实标): {res.get('error')}")

    verdict = str(res.get("verdict", "")).strip()
    if verdict not in _VERDICTS:
        # 判定越界 -> 保守退回 execution-gap(不轻易断言能力空白)。
        verdict = EXECUTION_GAP
    headline = str(res.get("headline", "")).strip()
    detail = str(res.get("detail", "")).strip()
    good_cites = _validate_citations(res.get("citations"), vio_docs)
    conf = "normal" if good_cites else "low_confidence"
    # B: 证据档位 —— vio 交付物里有无执行日志决定过程级 vs 仅成品级;confidence 按档封顶。
    tier = GA.evidence_tier({baseline: vio_docs}, [], baseline=baseline)
    conf = GA._cap_confidence_by_tier(conf, tier)

    result = VioGapResult(
        task_id=task_id, baseline=baseline, verdict=verdict, headline=headline,
        detail=detail, citations=good_cites, confidence=conf, dry_run=False,
        engine=_ENGINE, evidence_tier=tier)

    # 只有「能力空白」且有原文引用支撑,才产出 Finding 送方法沉淀。
    # execution-gap 不产(归 bug/质量轴);无引用(low_confidence)也不产(守铁律)。
    if verdict == CAPABILITY_GAP and good_cites:
        evid = [{"source": "vio-artifact", "ref": f"{c['source_file']}: {c['quote']}"}
                for c in good_cites]
        phen = (f"基线 {baseline} 在该任务失败,归因引擎判为「能力空白」"
                f"(capability-gap): {headline or '根本没有对应能力入口'}")
        f = make_finding(
            task_id=task_id, rule="vio-capability-gap",
            suspected_category=CAPABILITY_GAP, subject=baseline,
            phenomenon=phen, evidence=evid)
        if f is not None:
            result.finding = f.as_dict()
    return result
