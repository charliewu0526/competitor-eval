"""评测套件 (Eval Suite): 批量评测框架.

自动枚举任务库目录 -> 按任务地图标签(能力域 × 任务性质)圈定子集 -> 批量跑
N 道题出聚合排行榜. 复用 taskbank(discover/assert_valid,不另造加载)与
leaderboard(不另造排序). 先搭框架,再慢慢填题、加脏数据.
"""
from __future__ import annotations
import importlib
import pathlib
from dataclasses import dataclass

from pipeline import taskbank as TB
from pipeline import leaderboard as LB
from pipeline.schema import TaskSpec

ROOT = pathlib.Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / "tasks"


@dataclass
class SuiteResult:
    """Outcome of a batch run: the cross-task aggregated leaderboard."""
    leaderboard: dict
    n_tasks: int


def run_suite(scores_by_task: dict, baseline: str = "vio") -> SuiteResult:
    """批量跑 N 道题 -> 跨题聚合排行榜. scores_by_task = {task_id: [score dicts]}.

    Flattens all per-(task,product) scores into ONE list and hands it to
    leaderboard() (复用, 不另造排序) — empty input yields a clean empty board.
    """
    flat = [s for scores in scores_by_task.values() for s in scores]
    return SuiteResult(leaderboard=LB.leaderboard(baseline, flat),
                       n_tasks=len(scores_by_task))


@dataclass
class LoadedTask:
    """A discovered task: its validated TaskSpec + a callable yielding its
    objective assertions (resolved via meta.json's assertions_module)."""
    task_spec: TaskSpec
    assertions: object        # callable returning the assertion list, or None
    task_dir: pathlib.Path


def discover_tasks(tasks_dir=None) -> list[LoadedTask]:
    """Scan the task-bank dir; load+validate each task's TaskSpec and bind its
    assertions callable (meta.json `assertions_module`). 复用 taskbank.discover.
    """
    root = pathlib.Path(tasks_dir) if tasks_dir else TASKS_DIR
    out: list[LoadedTask] = []
    for task_id in TB.discover(root):
        tdir = TB.task_dir(root, task_id)
        spec = TB.assert_valid(tdir)
        meta = TB.load_meta(tdir)
        out.append(LoadedTask(task_spec=spec,
                              assertions=_load_assertions(meta),
                              task_dir=tdir))
    return out


def filter_tasks(tasks, *, app=None, tier=None, kind=None,
                 capability_domain=None, task_nature=None) -> list[LoadedTask]:
    """圈定「这轮测哪类」: keep tasks matching every non-None task-map label.
    None means 'don't filter on this axis'; no args returns all. 能力域 ×
    任务性质 两轴正交 —— 同时给两者就取交集.
    """
    def ok(t) -> bool:
        s = t.task_spec
        return ((app is None or s.app == app)
                and (tier is None or s.tier == tier)
                and (kind is None or s.kind == kind)
                and (capability_domain is None
                     or s.capability_domain == capability_domain)
                and (task_nature is None or s.task_nature == task_nature))
    return [t for t in tasks if ok(t)]


def _load_assertions(meta: dict):
    """Dynamically import the task's assertions() via meta.assertions_module.

    Returns None when no module is declared OR the module can't be imported —
    a single broken task must not crash the whole library scan (graceful skip).
    """
    mod_name = meta.get("assertions_module")
    if not mod_name:
        return None
    try:
        mod = importlib.import_module(mod_name)
    except ImportError:
        return None
    return getattr(mod, "assertions", None)
