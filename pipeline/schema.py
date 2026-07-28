"""T1 pipeline data model. One eval = task x product x run.

GATE -> OBJECTIVE -> SUBJECTIVE, per rubric-v0-domain1.md.
v2 (F1): TaskSpec gains tier/kind/desktop/dirty-data fields; RunRecord gains
cost + evidence_source + claimed_success (feeds H1). New fields default so old
synthetic RunRecords still load. Enum fields are validated; heavy dirty-data
requires known_edge_cases.
"""
from __future__ import annotations
import json, time, pathlib
from dataclasses import dataclass, field, asdict, fields as dc_fields

GATE_VALUES = ("native-operable", "api-or-integration", "cannot-reach")
TIER_VALUES = ("core-common", "vio-key", "rival-signature", "stress")
KIND_VALUES = ("task-exam", "capability-probe")
DIRTY_VALUES = ("none", "light", "heavy")
# 任务地图: 两组正交标签 (CONTEXT.md「任务地图」). 能力域=在哪操作; 任务性质=多硬.
# professional-workflow (2026-07 新增): 跨多个本地 app 的真实职业工作流 (取数→
# 交叉核对→判断→产出→沟通), 模拟一个岗位的一段完整工作. 天然跨 app, 只有真能
# 操控本地全套桌面的产品够得着 (GATE 按域收窄, 云端/单一浏览器产品判 cannot-reach,
# 非差). 与现有单一能力域正交并存: 原子任务留作基线, 高阶职业任务拉真实差距.
CAPABILITY_DOMAIN_VALUES = ("wechat-im", "office-suite", "no-api-app",
                            "computer-control", "browser-web",
                            "professional-workflow")
# workflow-heavy (2026-07 新增): 跨 app、含判断分叉的高阶职业任务. 与 stress
# 的区别: stress 压的是脏数据, workflow-heavy 压的是流程复杂度 + 跨 app + 判断.
TASK_NATURE_VALUES = ("simple", "long-horizon", "scheduled", "dirty-data",
                      "workflow-heavy")
# native = 我们自家原生产品无 LLM 环路执行, 成本确实为 0 (既非"拿不到"unavailable,
# 也非竞品"自报"self-report)。零成本是可核查的事实, cost_usd 记 0.0 而非 None。
COST_SOURCE_VALUES = ("self-report", "proxy", "unavailable", "native")
EVIDENCE_SOURCE_VALUES = ("log", "screenshot", "recording", "unavailable")


def _check(name: str, val, allowed: tuple) -> None:
    if val not in allowed:
        raise ValueError(f"{name} must be one of {allowed}, got {val!r}")


@dataclass
class TaskSpec:
    task_id: str
    domain: str                 # "1" for closed-source desktop app op
    app: str                    # e.g. "wechat", "capcut"
    prompt: str                 # the instruction given to each product
    core_assertions: list[str]  # 1a assertion descriptions (primary-goal etc.)
    expects_file: bool = False  # whether an artifact file is produced
    # --- v2 fields ---
    tier: str = "core-common"               # TIER_VALUES; v1 only fills core-common
    kind: str = "task-exam"                 # KIND_VALUES
    requires_local_desktop: bool = True     # feeds GATE derivation (E1)
    dirty_data_level: str = "none"          # DIRTY_VALUES; human/verifier-set final
    dirty_data_level_suggested: str | None = None  # generator-AI proposal (coexists)
    known_edge_cases: list[str] = field(default_factory=list)  # required iff heavy
    # --- 任务地图: 两组正交标签 (能力域 × 任务性质), 用于评测套件圈定 ---
    capability_domain: str = "wechat-im"    # CAPABILITY_DOMAIN_VALUES; 在哪操作
    task_nature: str = "simple"             # TASK_NATURE_VALUES; 任务多硬
    # --- 起始状态/前置准备 (owner 统一写, 实习生只读) ---
    # 说明"这道题从什么环境/素材开始跑", 消除实习生"我没文件、要不要自建"的困惑,
    # 并强调起始状态由系统统一提供、禁止自建, 保证各竞品在同一份素材上对打(可比)。
    # 只是中性上手提示 + 不可改约束, 不改变任务数据本身。
    setup: str | None = None

    def __post_init__(self) -> None:
        _check("tier", self.tier, TIER_VALUES)
        _check("kind", self.kind, KIND_VALUES)
        _check("dirty_data_level", self.dirty_data_level, DIRTY_VALUES)
        _check("capability_domain", self.capability_domain, CAPABILITY_DOMAIN_VALUES)
        _check("task_nature", self.task_nature, TASK_NATURE_VALUES)
        if self.dirty_data_level_suggested is not None:
            _check("dirty_data_level_suggested", self.dirty_data_level_suggested, DIRTY_VALUES)
        if self.dirty_data_level == "heavy" and not self.known_edge_cases:
            raise ValueError("dirty_data_level='heavy' requires non-empty known_edge_cases")


@dataclass
class RunRecord:
    task_id: str
    product: str                # "vio" | "simular"
    run_idx: int
    gate: str                   # one of GATE_VALUES
    objective_passed: int = 0
    objective_total: int = 0
    objective_failed_primary: bool = False
    artifact_path: str | None = None
    screenshots: list[str] = field(default_factory=list)
    transcript_excerpt: str = ""
    env_meta: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    # --- v2 fields (default => old synthetic RunRecords still load) ---
    cost_input_tokens: int = 0
    cost_output_tokens: int = 0
    cost_model_calls: int = 0
    cost_usd: float | None = None           # None => not computed yet
    cost_source: str = "unavailable"        # COST_SOURCE_VALUES
    evidence_source: str = "unavailable"    # EVIDENCE_SOURCE_VALUES
    claimed_success: bool | None = None      # self-report; feeds H1 (E4)
    # --- MR-1 (#37) 数据新鲜度 ADR-0017: 每条分数绑竞品版本 + 测试日期, 超期标陈旧 ---
    competitor_version: str | None = None   # 闭源竞品版本不透明时可留空, 记 build 标识
    tested_at: float | None = None          # 该次测试的时间(epoch); None => 未记录
    stale: bool = False                     # 超过新鲜度窗口 => 标陈旧, 不冒充现状

    def __post_init__(self) -> None:
        _check("gate", self.gate, GATE_VALUES)
        _check("cost_source", self.cost_source, COST_SOURCE_VALUES)
        _check("evidence_source", self.evidence_source, EVIDENCE_SOURCE_VALUES)

    @property
    def objective_ratio(self) -> float:
        return self.objective_passed / self.objective_total if self.objective_total else 0.0


def save(obj, path: str) -> str:
    p = pathlib.Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(asdict(obj), ensure_ascii=False, indent=2))
    return str(p)


def load_json(path: str) -> dict:
    return json.loads(pathlib.Path(path).read_text())
