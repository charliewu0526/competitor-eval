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
CAPABILITY_DOMAIN_VALUES = ("wechat-im", "office-suite", "no-api-app",
                            "computer-control", "browser-web")
TASK_NATURE_VALUES = ("simple", "long-horizon", "scheduled", "dirty-data")
COST_SOURCE_VALUES = ("self-report", "proxy", "unavailable")
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
