"""MR-5 (#41): 任务清单目录 — 按能力域分组的只读派生视图.

这不是新核心接缝, 而是一个派生视图 (同 leaderboard / 差距报告的定位): 从既有
X1 任务库 + F2 registry + E1 GATE 三处读数拼装, 让 intern「看得到题、看得到该
发的中立 Prompt、看得到同域谁参赛」。它不落库、不改评分核心、不含领取动作
(领取在 #42) —— 纯读。

分组轴 = capability_domain (能力域, F1 TaskSpec). 「同域才同台」由此支撑:
每道题的参赛竞品由 GATE 派生 (gate.gate_for), cannot-reach 的产品不列入该题
参赛集 —— 够不着不是差, 不硬拉进来打 0 (立身之本 corollary).

中立标准 Prompt (ADR-0016): 直接取 TaskSpec.prompt (禁用产品专属语法的那条),
每个产品发的是同一条, 榜单不被质疑偏向自家母语。
"""
from __future__ import annotations
import pathlib

from pipeline import suite as SUITE
from pipeline import taskbank as TB
from pipeline import gate as GATE
from pipeline.registry import default_registry
from pipeline.schema import CAPABILITY_DOMAIN_VALUES

# 人话原则: 机器枚举值 -> 给 intern 看的中文域名 + 一句说明.
DOMAIN_LABELS: dict[str, dict] = {
    "wechat-im": {"label": "即时通讯 (微信等)",
                  "hint": "在微信这类聊天软件里操作: 发消息、找人、转发。"},
    "office-suite": {"label": "办公套件 (Excel/Word/PPT)",
                     "hint": "在表格/文档/幻灯片里操作: 填数、算公式、排版、导出。"},
    "no-api-app": {"label": "无接口桌面应用",
                   "hint": "没有对外 API 的桌面软件, 只能靠 GUI 直接操作。"},
    "computer-control": {"label": "电脑操控",
                         "hint": "跨应用的桌面操控: 文件、系统设置、多窗口协同。"},
    "browser-web": {"label": "网页任务",
                    "hint": "在浏览器里操作网页: 检索、填表、下单、抓取。"},
}


def _competitor_entry(comp, task_spec) -> dict:
    """一个产品在某题上的参赛资格 (GATE 派生, 不信自报)."""
    g = GATE.gate_for(comp, task_spec)
    return {
        "id": comp.id,
        "display_name": comp.display_name,
        "gate": g,
        "reachable": not GATE.is_excluded(g),   # cannot-reach => 不参赛 (非差)
        "cross_layer": g == "api-or-integration",
    }


def _human_assertions(loaded) -> list[dict]:
    """抽出该题**只能人看**的客观断言 (HUMAN kind), 给提交表单渲染勾选框用。

    走查 BUG-1 修复: 微信/桌面类任务的核心判定点是脚本读不了的末态 (消息真发出没),
    必须由受训 intern 勾选。这里把这些断言的 {key, desc, primary} 暴露给前端, 前端据
    此渲染勾选框, 提交时组装成 manual_assertions —— 否则 intake 收不到人工断言,
    manual 断言型任务恒判 0 分 (走查头号阻断 bug)。机器可验断言 (MACHINE) 不在此列
    (它们由脚本从产物/日志自动判, 不落人手, 立身之本)。
    """
    fn = getattr(loaded, "assertions", None)
    if not callable(fn):
        return []
    out = []
    try:
        for a in fn():
            if getattr(a, "kind", None) == "human" and getattr(a, "ctx_key", None):
                out.append({"key": a.ctx_key, "desc": a.desc,
                            "primary": bool(a.primary)})
    except Exception:
        return []
    return out


def _task_card(loaded, registry) -> dict:
    """把一个 discover 出来的 LoadedTask 拼成给人看的清单卡片."""
    s = loaded.task_spec
    competitors = [_competitor_entry(c, s) for c in registry.competitors()]
    participating = [c for c in competitors if c["reachable"]]
    readme = ""
    try:
        readme = (pathlib.Path(loaded.task_dir) / "README.md").read_text()
    except Exception:
        readme = ""
    return {
        "task_id": s.task_id,
        "app": s.app,
        "tier": s.tier,
        "kind": s.kind,
        "capability_domain": s.capability_domain,
        "task_nature": s.task_nature,
        "requires_local_desktop": s.requires_local_desktop,
        "prompt": s.prompt,                 # 中立标准 Prompt (ADR-0016)
        "core_assertions": list(s.core_assertions),
        "human_assertions": _human_assertions(loaded),  # 人工勾选断言(提交表单用)
        "expects_file": s.expects_file,
        "readme": readme,                   # 详细说明 (人读)
        "competitors": competitors,         # 全部产品 + 各自 GATE
        "participating": [c["id"] for c in participating],  # 同域实际参赛集
    }


def build_catalog(tasks_dir=None, registry=None) -> list[dict]:
    """按能力域分组的任务清单. 复用 suite.discover_tasks (X1 校验一并做掉).

    返回 [{domain, label, hint, tasks:[card...]}], 域顺序 = CAPABILITY_DOMAIN_VALUES,
    空域不返回 (清单只列有题的域)。
    """
    reg = registry or default_registry()
    loaded = SUITE.discover_tasks(tasks_dir)
    by_domain: dict[str, list[dict]] = {}
    for t in loaded:
        by_domain.setdefault(t.task_spec.capability_domain, []).append(
            _task_card(t, reg))
    groups: list[dict] = []
    for dom in CAPABILITY_DOMAIN_VALUES:
        cards = by_domain.get(dom)
        if not cards:
            continue
        meta = DOMAIN_LABELS.get(dom, {"label": dom, "hint": ""})
        groups.append({
            "domain": dom,
            "label": meta["label"],
            "hint": meta["hint"],
            "tasks": sorted(cards, key=lambda c: c["task_id"]),
        })
    return groups


def task_detail(task_id: str, tasks_dir=None, registry=None) -> dict | None:
    """单题详情 (含中立 Prompt + 说明 + 参赛竞品). 找不到返回 None."""
    reg = registry or default_registry()
    for t in SUITE.discover_tasks(tasks_dir):
        if t.task_spec.task_id == task_id:
            return _task_card(t, reg)
    return None
