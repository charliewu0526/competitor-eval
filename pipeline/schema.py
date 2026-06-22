"""T1 pipeline data model. One eval = task x product x run.

GATE -> OBJECTIVE -> SUBJECTIVE, per rubric-v0-domain1.md.
"""
from __future__ import annotations
import json, time, pathlib
from dataclasses import dataclass, field, asdict

GATE_VALUES = ("native-operable", "api-or-integration", "cannot-reach")


@dataclass
class TaskSpec:
    task_id: str
    domain: str                 # "1" for closed-source desktop app op
    app: str                    # e.g. "wechat", "capcut"
    prompt: str                 # the instruction given to each product
    core_assertions: list[str]  # 1a assertion descriptions (primary-goal etc.)
    expects_file: bool = False  # whether an artifact file is produced


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

    @property
    def objective_ratio(self) -> float:
        return self.objective_passed / self.objective_total if self.objective_total else 0.0


def save(obj, path: str) -> str:
    p = pathlib.Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(asdict(obj), ensure_ascii=False, indent=2))
    return str(p)


def load_json(path: str) -> dict:
    return json.loads(pathlib.Path(path).read_text())
