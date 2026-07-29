"""功能B: 竞品能力清单数据源 —— 细粒度能力条目(带证据 + 真实/宣传状态).

功能A/差距报告都只在「我们出的题」上比。功能B 换个视角:独立盘一份每个竞品**自己
声称/已上线的能力清单**(它的功能菜单/卖点/文档),和 vio 的能力清单做差集,差出来
的就是候选新功能。

粒度:比 registry 的 7 个能力域(domain)细得多 —— 这里是**具体能力条目**
(capability entry),如「专属邮箱入口」「预置定时 Routines」「Town Decks 生成演示」。

每条能力带 status,沿袭 competitor-town-ai.md 的「真实 vs 宣传」切分铁律:
  shipped   —— docs/changelog/一手体验可验证的已上线能力(差集只认这一档为候选)。
  limited   —— 部分真实 / 有明显限制(宣传常略过);记录但不当候选(避免抄进坑)。
  marketing —— 纯宣传话术, 无功能支撑;记录但绝不当候选(防被营销叙事带偏)。
  candidate —— LLM/人抽取出的**待复核**条目, 复核确认前不当已上线(AI/人复核闸)。

每条必须带 evidence(为什么这么标)+ source(出处), 否则加载即报错 —— 无证据的能力
声明不入清单(呼应 findings「无证据不入池」)。纯读数据源, 无副作用。
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field, asdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
CAP_DIR = ROOT / "registry" / "capabilities"

STATUS_VALUES = ("shipped", "limited", "marketing", "candidate")
# 差集只把「已上线」当候选新功能 —— limited/marketing/candidate 不算 vio「该补的」。
CANDIDATE_STATUS = "shipped"


@dataclass
class CapabilityEntry:
    """一条具体能力(带证据 + 真实/宣传状态), 出处可追溯.

    capability : 能力条目一句话(如「专属邮箱入口, 可在 Slack/WhatsApp 里调用」)。
    status     : STATUS_VALUES —— 真实/宣传切分。
    evidence   : 为什么这么标(docs/changelog/一手体验/官网 features 页)。
    source     : 出处标识(URL / 文件 / "官网 features/decks")。
    domain     : 可选, 归入哪个能力域(与 schema.CAPABILITY_DOMAIN_VALUES 对齐);留空可。
    tags       : 可选自由标签, 便于差集时同义归并。
    source_url : (D 自动调研)该能力抽自哪个链接(官网/新闻/社媒),可追溯。留空可。
    fetched_at : (D 自动调研)来源抓取时间(ISO 串),判新鲜度用。留空可。
    向后兼容: source_url/fetched_at 默认空, 旧 json(无这两字段)照常加载不报错。
    """
    capability: str
    status: str
    evidence: str
    source: str = ""
    domain: str | None = None
    tags: list[str] = field(default_factory=list)
    source_url: str = ""
    fetched_at: str | None = None

    def __post_init__(self) -> None:
        if not self.capability.strip():
            raise ValueError("capability 文本不能为空")
        if self.status not in STATUS_VALUES:
            raise ValueError(f"status must be one of {STATUS_VALUES}, got {self.status!r}")
        # 无证据不入清单: shipped/limited/marketing 都必须给出处依据。candidate 是
        # 待复核的机器抽取, 允许 evidence 暂为抽取出处(仍需非空, 记来源)。
        if not (self.evidence and self.evidence.strip()):
            raise ValueError(f"能力条目 {self.capability!r} 缺 evidence(无证据不入清单)")

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class CapabilityList:
    product: str
    entries: list[CapabilityEntry]
    updated: str | None = None
    note: str | None = None

    def shipped(self) -> list[CapabilityEntry]:
        return [e for e in self.entries if e.status == CANDIDATE_STATUS]

    def as_dict(self) -> dict:
        return {"product": self.product, "updated": self.updated,
                "note": self.note, "entries": [e.as_dict() for e in self.entries]}


def _path_for(product: str) -> pathlib.Path:
    return CAP_DIR / f"{product}.json"


def load_capabilities(product: str) -> CapabilityList:
    """读某产品的能力清单(registry/capabilities/<product>.json)。

    文件缺失 -> 空清单(如实, 不伪造)。字段非法 -> CapabilityEntry.__post_init__ 报错。
    """
    p = _path_for(product)
    if not p.exists():
        return CapabilityList(product=product, entries=[], note="未登记能力清单")
    data = json.loads(p.read_text())
    entries = [CapabilityEntry(**e) for e in data.get("entries", [])]
    return CapabilityList(product=product, entries=entries,
                          updated=data.get("updated"), note=data.get("note"))


def save_capabilities(clist: CapabilityList) -> str:
    """落盘一份能力清单(LLM 抽取/人工编辑后持久化)。"""
    CAP_DIR.mkdir(parents=True, exist_ok=True)
    p = _path_for(clist.product)
    p.write_text(json.dumps(clist.as_dict(), ensure_ascii=False, indent=2))
    return str(p)


def list_products() -> list[str]:
    """列出已登记能力清单的产品 id(按文件名)。"""
    if not CAP_DIR.exists():
        return []
    return sorted(p.stem for p in CAP_DIR.glob("*.json"))
