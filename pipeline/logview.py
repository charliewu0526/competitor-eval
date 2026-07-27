"""MR-9 (#45): log-bundle → redacted / raw 双视图 (ADR-0013).

一份日志包派生两个视图:
  * raw:      完整原始 —— 给成本统计 + 人工抽查(cost/token/model/timeline 全留)。
  * redacted: 洗掉品牌 / 模型指纹 —— 喂盲评面板,盲评不被日志泄底(ADR-0012)。

立身之本:脱敏只洗「能泄露产品身份的指纹」(品牌名、模型名),绝不改动
「是否真完成 / 花了多少」这类事实 —— 事实归 raw 视图与客观层,脱敏不篡改结论。

指纹词典是 DERIVED 的,不硬编码:品牌来自 F2 registry 的 display_name + id,
模型来自 A3 price table 的 model keys。加竞品 / 加模型 = 改数据不改脱敏代码 ——
与 registry blind_label「加竞品改表不改码」同构。

MVP(ADR-0019):脱敏用确定性字符串替换实现,双视图数据结构就位;更强的语义
脱敏(改写句式)留后续。缺字段照 unavailable 透传,绝不伪造。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

REDACTED = "[REDACTED]"
REDACTED_MODEL = "[REDACTED-MODEL]"


def _brand_terms(registry) -> set[str]:
    """品牌指纹 = 每个 competitor 的 display_name + id(去空、去纯符号)。"""
    terms: set[str] = set()
    if registry is None:
        return terms
    try:
        comps = registry.competitors()
    except Exception:
        return terms
    for c in comps:
        for t in (getattr(c, "display_name", None), getattr(c, "id", None)):
            if t and str(t).strip():
                terms.add(str(t).strip())
    return terms


def _model_terms(price_table) -> set[str]:
    """模型指纹 = price table 里所有 model key。"""
    if price_table is None:
        return set()
    models = getattr(price_table, "_models", None)
    if not isinstance(models, dict):
        return set()
    return {m for m in models if m and str(m).strip()}


class Redactor:
    """确定性字符串脱敏器:把一组指纹词(品牌 / 模型)洗成占位符。

    大小写不敏感;长词优先替换(先长后短,避免「Open Interpreter」被「Open」切碎
    后残留半截指纹)。词按整词边界匹配不了中文,故用普通子串替换 + 长度降序兜底。
    """

    def __init__(self, terms, *, replacement: str = REDACTED):
        self.replacement = replacement
        # 去空 + 去重 + 长度降序:先替换最长的指纹,防子串残留。
        self._terms = sorted({str(t).strip() for t in terms if str(t).strip()},
                             key=len, reverse=True)
        self._patterns = [(re.compile(re.escape(t), re.IGNORECASE), t)
                          for t in self._terms]

    @property
    def terms(self) -> list[str]:
        return list(self._terms)

    def redact_text(self, s):
        """洗一段文本里的所有指纹词。非字符串原样返回。"""
        if not isinstance(s, str) or not s:
            return s
        out = s
        for pat, _ in self._patterns:
            out = pat.sub(self.replacement, out)
        return out

    def redact_events(self, events):
        """洗事件时间线里的指纹(事件名 / 事件里的字符串字段)。

        事件可能是 str(事件名)或 dict(带 event/desc/ts 等字段)。只洗字符串,
        数值(token / ts)原样保留 —— 脱敏不改事实,只抹身份。
        """
        if not events:
            return []
        out = []
        for e in events:
            if isinstance(e, str):
                out.append(self.redact_text(e))
            elif isinstance(e, dict):
                out.append({k: (self.redact_text(v) if isinstance(v, str) else v)
                           for k, v in e.items()})
            else:
                out.append(e)
        return out


# --- the two-view contract ---------------------------------------------------
@dataclass
class LogViews:
    """一份日志包派生出的两视图(ADR-0013)。

    raw:      完整事实(cost/token/model/timeline 全留)—— 成本统计 + 人工抽查。
    redacted: 洗净品牌 / 模型指纹 —— 喂盲评面板(盲评不被日志泄底)。
    两视图共享同一套「花了多少 / 事件次数」的事实数值,只在「身份指纹」上分叉。
    """
    raw: dict
    redacted: dict


# raw 视图里保留但脱敏视图必须抹掉的「模型身份」键。
_MODEL_IDENTITY_KEY = "model"


def derive_views(log_facts: dict, *, registry=None, price_table=None,
                 redactor: "Redactor | None" = None) -> LogViews:
    """从解析出的 log_facts 派生 raw / redacted 双视图 (#45 AC3/AC4)。

    raw = log_facts 原样(浅拷贝,含 model 名 + 完整 events)。
    redacted = 抹掉 model 指纹(整键 -> [REDACTED-MODEL])+ 洗 events 里的品牌 /
               模型串,但保留全部成本数值(token/calls/cost_source)—— 事实不变,
               只抹身份。

    脱敏词典 DERIVED:品牌来自 registry.display_name/id,模型来自 price_table
    的 model keys + 本包实际用的 model 名(即使不在价表也要洗,防漏)。可传入
    预建的 redactor 覆盖(测试 / 自定义词典用)。
    """
    raw = dict(log_facts)

    if redactor is None:
        terms = _brand_terms(registry) | _model_terms(price_table)
        # 本包实际用的 model 名也纳入指纹(闭源竞品可能用价表没有的模型)。
        m = log_facts.get(_MODEL_IDENTITY_KEY)
        if m and str(m).strip():
            terms.add(str(m).strip())
        redactor = Redactor(terms)

    redacted = dict(log_facts)
    # 1. 模型身份键:非空即抹成占位符(区别于 unavailable —— 是「有但盲掉」)。
    if redacted.get(_MODEL_IDENTITY_KEY):
        redacted[_MODEL_IDENTITY_KEY] = REDACTED_MODEL
    # 2. 事件时间线:洗掉品牌 / 模型串,保留数值事实。
    redacted["events"] = redactor.redact_events(log_facts.get("events", []))
    # 3. 成本数值 / source 照搬(事实,不脱敏)。已在 dict(log_facts) 里。

    return LogViews(raw=raw, redacted=redacted)
