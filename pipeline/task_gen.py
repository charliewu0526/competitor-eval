"""候选题自动生成器: 一条已确认 shipped 的竞品能力 -> 一个完整合法的候选题目录.

闭环收口 (PRD 竞品调研全闭环 第2/3步):
  能力普查 census -> LLM 抽 candidate -> 人复核 approve 升 shipped -> **本模块**把该
  shipped 能力脚手架成一道候选题 (provenance=auto-from-census) 灌进任务库。

立身铁律沿袭:
  * 候选题 provenance='auto-from-census' —— prompt/expected 由能力条目 AI 暂定、
    **未经人核验**, 显式标注。它**不进公平主榜单** (leaderboard/domain-board 剔除),
    单列「自动生成候选题」区, 供人真跑核验后转正 human (榜单隔离在 step4)。
  * kind='capability-probe' —— 它探的是「竞品声称有、vio 缺」的能力, 非人工出的考题。
  * 生成的题必带竞品能力条目的 evidence/source 追溯 (README + scoring 里写清出处),
    与 census Finding 同源, 不伪造。
  * 幂等: task_id 按 (rival, 能力文本) 稳定指纹, 已存在则更新不重复造。

生成的目录严格遵守 X1 taskbank 契约 (taskbank.REQUIRED_FILES/REQUIRED_DIRS), 落盘后
可直接 taskbank.assert_valid 通过、suite.discover_tasks 发现。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import time

from pipeline import taskbank as TB

ROOT = pathlib.Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / "tasks"

# 候选题固定标记, 前端/榜单据此识别并隔离。
PROVENANCE = "auto-from-census"
AUTHOR = "ai:task_gen"

_SLUG = re.compile(r"[^a-z0-9]+")
_PUNCT = re.compile(r"[\s、,,。.:：;;/()()\[\]『』「」·\-—_'\"]+")


def _norm(text: str) -> str:
    """能力文本标准化 (与 capability_census._norm 对齐) -> 稳定指纹用。"""
    return _PUNCT.sub("", (text or "").lower())


def _digest(rival: str, capability: str) -> str:
    return hashlib.sha1(f"{rival}:{_norm(capability)}".encode("utf-8")).hexdigest()[:8]


def _slug(text: str, n: int = 24) -> str:
    s = _SLUG.sub("-", (text or "").lower()).strip("-")
    return (s[:n].strip("-")) or "cap"


def candidate_task_id(rival: str, capability: str) -> str:
    """候选题 id: cand-<rival>-<能力slug>-<指纹>. 稳定 -> 幂等更新同一目录。"""
    return f"cand-{_slug(rival, 12)}-{_slug(capability)}-{_digest(rival, capability)}"


# --- 能力域猜测 (只服务分组浏览, 不做判定) ---------------------------------
_DOMAIN_HINTS = {
    "wechat-im": ("微信", "wechat", "im", "聊天", "消息"),
    "office-suite": ("excel", "word", "ppt", "表格", "文档", "幻灯", "office", "spreadsheet"),
    "browser-web": ("网页", "浏览器", "browser", "web", "抓取", "爬", "表单"),
    "computer-control": ("文件", "系统", "桌面", "跨应用", "file", "desktop"),
    "assistant-integration": ("gmail", "slack", "notion", "crm", "api", "邮件",
                              "收件箱", "日历", "集成", "integration", "saas"),
    "professional-workflow": ("工作流", "workflow", "流程", "岗位", "跨 app", "编排"),
}


def _guess_domain(capability: str, entry_domain: str | None) -> str:
    """粗猜能力域: 优先用能力条目自带 domain, 否则按关键词, 兜底 no-api-app。"""
    from pipeline.schema import CAPABILITY_DOMAIN_VALUES
    if entry_domain and entry_domain in CAPABILITY_DOMAIN_VALUES:
        return entry_domain
    low = (capability or "").lower()
    for dom, kws in _DOMAIN_HINTS.items():
        if any(k in low for k in kws):
            return dom
    return "no-api-app"


def _entry_get(entry, key, default=""):
    """能力条目取值: 兼容 CapabilityEntry 对象与 dict。"""
    if isinstance(entry, dict):
        return entry.get(key, default)
    return getattr(entry, key, default)


def generate_candidate_task(capability_entry, rival: str, *,
                            tasks_dir=None, baseline: str = "vio") -> dict:
    """一条 shipped 竞品能力 -> 一道候选题目录 (provenance=auto-from-census).

    capability_entry: CS.CapabilityEntry 或等价 dict(capability/evidence/source/
                      source_url/domain)。rival: 竞品 id。
    幂等: task_id 按 (rival, 能力文本) 指纹稳定 -> 已存在则重写(更新), created=False。
    返回 {task_id, path, created, provenance}。prompt/expected 均为 AI 暂定基准、
    显式标注未经人核验 —— 该题不进公平主榜单(榜单隔离在 leaderboard 层)。
    """
    cap = str(_entry_get(capability_entry, "capability", "")).strip()
    if not cap:
        raise ValueError("capability_entry 缺 capability 文本, 无法生成候选题")
    evidence = str(_entry_get(capability_entry, "evidence", "")).strip()
    source = str(_entry_get(capability_entry, "source", "")).strip()
    source_url = str(_entry_get(capability_entry, "source_url", "")).strip()
    domain = _guess_domain(cap, _entry_get(capability_entry, "domain", None))

    root = pathlib.Path(tasks_dir) if tasks_dir else TASKS_DIR
    task_id = candidate_task_id(rival, cap)
    tdir = root / task_id
    existed = tdir.exists()
    tdir.mkdir(parents=True, exist_ok=True)

    src_label = source_url or source or "竞品能力普查(census)"
    prompt_text = _render_prompt(cap, rival)
    meta = _build_meta(task_id, rival, cap, evidence, src_label, domain, prompt_text)

    # meta.json (机器唯一真源) + 人读三件套 + 四子目录占位。
    (tdir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2))
    (tdir / "README.md").write_text(
        _render_readme(task_id, rival, cap, evidence, src_label, domain, baseline))
    (tdir / "prompt.md").write_text(_render_prompt_md(prompt_text, cap, rival))
    (tdir / "scoring.md").write_text(
        _render_scoring(cap, rival, evidence, src_label))
    for sub, note in (
            ("input", "候选题起始素材占位。人核验转正前请补齐真实素材(禁自建冒充)。"),
            ("expected", None),   # expected/end-state.md 单独写
            ("output", "每次跑的产物落这里(每产品一份)。"),
            ("evidence", "日志/截图/录屏落这里, 喂 S5 过程锚, 不参与判分。")):
        d = tdir / sub
        d.mkdir(exist_ok=True)
        if note is not None:
            (d / ".gitkeep").write_text(note + "\n")
    (tdir / "expected" / "end-state.md").write_text(
        _render_expected(cap, rival, evidence, src_label))

    return {"task_id": task_id, "path": str(tdir),
            "created": not existed, "provenance": PROVENANCE}


# --- 渲染 (prompt/meta/README/scoring/expected) ------------------------------
_UNVERIFIED = ("⚠ AI 暂定基准 · 未经人核验 · 不进公平主榜单。"
               "此题由能力普查差集自动生成, prompt/expected 由 AI 依据竞品能力条目"
               "暂拟, 尚未人工核验。请真跑核验、改成写死正确答案后, 把 provenance "
               "改为 human 才能进公平主榜单。")


def _render_prompt(capability: str, rival: str) -> str:
    """中立标准 Prompt(禁产品专属语法): 让被测产品复现该能力所描述的任务。"""
    return (f"完成以下任务:{capability}。"
            f"请用你自己的方式操作本机完成它, 产出结果保存到 output/, "
            f"过程留痕(日志/截图)放 evidence/。")


def _build_meta(task_id, rival, capability, evidence, src_label, domain,
                prompt_text) -> dict:
    return {
        "schema": "taskbank-v1",
        "task_spec": {
            "task_id": task_id,
            "domain": "1",
            "app": domain,
            "prompt": prompt_text,
            "core_assertions": [
                "primary: 产品完成了该能力所描述的任务(需人核验真跑结果)",
                "secondary: 产出与竞品声称的能力一致",
            ],
            "expects_file": True,
            "tier": "core-common",
            "kind": "capability-probe",
            "requires_local_desktop": True,
            "dirty_data_level": "none",
            "dirty_data_level_suggested": None,
            "known_edge_cases": [],
            "capability_domain": domain,
            "task_nature": "simple",
            "setup": ("自动生成候选题:起始素材尚未落地。人核验转正前请补齐真实、"
                      "统一的起始素材(禁自建冒充), 保证各产品同素材对打可比。"),
            "provenance": PROVENANCE,
        },
        # 候选题不走脏数据两源规则(dirty=none, 无脏数据建议), 只留 final_by 记来源。
        "dirty_data": {
            "final_by": AUTHOR,
            "note": "auto-from-census 候选题, 干净数据; 脏数据档由人核验转正时按需重定。",
        },
        "provenance": {
            "kind": PROVENANCE,
            "rival": rival,
            "capability": capability,
            "evidence": evidence,
            "source": src_label,
            "generated_by": AUTHOR,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "note": _UNVERIFIED,
        },
        "assertions_module": "",     # 候选题暂无绑定断言模块(人核验时补)
        "files": {
            "input": "input/ — 起始素材(候选题待补, 禁自建冒充)",
            "expected": "expected/end-state.md — AI 暂定的正确结果(未核验)",
            "output": "output/ — 每次跑的产品产物",
            "evidence": "evidence/ — 日志/截图/录屏",
        },
    }


def _render_readme(task_id, rival, capability, evidence, src_label, domain,
                   baseline) -> str:
    return f"""# {task_id} — 自动生成候选题(auto-from-census)

> **{_UNVERIFIED}**

机器可读单一真源是 `meta.json`。本题由竞品能力普查差集**自动生成**。

**Task id:** `{task_id}`
**来源竞品:** `{rival}` · **能力域(猜测):** `{domain}` · **Kind:** capability-probe
**基线:** `{baseline}`

## 能力空白(为什么生成这道题)
竞品 `{rival}` 已上线能力:

> {capability}

基线 `{baseline}` 能力清单未登记该能力入口 —— 疑似能力空白, 自动出成候选题探底。

## 证据 / 出处
- 证据:{evidence or "(能力条目未附证据)"}
- 出处:{src_label}

## 转正流程(候选 → 正式)
1. 人真跑一遍, 核验这道题问的能力是否真实、prompt 是否合理。
2. 把 prompt / expected 改成**写死的正确答案**、补齐 `input/` 真实素材、绑定 `assertions_module`。
3. meta.json 的 `task_spec.provenance` 改为 `human`、`kind` 改为 `task-exam`。
4. 之后它才进公平主榜单。转正前它只在「自动生成候选题」区展示, 不参与排名。
"""


def _render_prompt_md(prompt_text, capability, rival) -> str:
    return f"""# Prompt(自动生成候选题 · 未经人核验)

> {_UNVERIFIED}

{prompt_text}

---
生成依据(不属于 prompt 正文):
- 来源竞品:{rival}
- 竞品声称能力:{capability}
"""


def _render_scoring(capability, rival, evidence, src_label) -> str:
    return f"""# Scoring — 自动生成候选题(未经人核验)

> {_UNVERIFIED}

本题的判定尚未人工敲定。下面是 AI 依据竞品能力暂拟的判定方向, **不可**直接用于
给所有产品打分(它会失真)—— 必须人核验、写死正确答案后转正。

| 维度 | 暂拟判定 | primary? |
|------|----------|----------|
| 主目标 | 产品完成了该能力所描述的任务(需人核验真跑) | ✅ primary |
| 一致性 | 产出与竞品声称的能力一致 | secondary |

## 出处
- 竞品:{rival}
- 能力:{capability}
- 证据:{evidence or "(无)"}
- 来源:{src_label}
"""


def _render_expected(capability, rival, evidence, src_label) -> str:
    return f"""# 期望结果(AI 暂定基准 · 未经人核验)

> {_UNVERIFIED}

依据竞品 `{rival}` 声称的能力暂拟:产品应当能完成 ——

> {capability}

并产出对应结果到 `output/`。

**注意:这是 AI 暂拟的期望, 尚未人工核验、也未写死正确答案。** 请人真跑该能力、
确认正确末态后, 用真实的写死答案替换本文件, 再把该题 provenance 转 human。

## 出处
- 证据:{evidence or "(无)"}
- 来源:{src_label}
"""
