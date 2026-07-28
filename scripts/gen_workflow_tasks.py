"""批量生成 professional-workflow 高阶职业任务 (跨 app + 判断分叉)。

数据驱动: 每个任务一条记录, 循环产出标准 7 件套 (input 数据 + prompt.md +
meta.json + scoring.md + README.md + expected/end-state.md + 断言 .py)。
生成后由 taskbank.validate_dir 校验, 不合格即报错, 不出脏任务。

任务定义在 WORKFLOW_TASKS.py (同目录), 分文件避免单文件过大。
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TASKS_DIR = ROOT / "tasks"

from scripts.WORKFLOW_TASKS import WORKFLOW_TASKS  # noqa: E402
from pipeline import taskbank as TB  # noqa: E402


def _mod_name(task_id: str) -> str:
    # W2-hr-screening-001 -> tasks.W2_hr_screening_001
    return "tasks." + task_id.replace("-", "_")


def _assertion_src(alist) -> str:
    lines = []
    for a in alist:
        if a[0] == "file_exists":
            lines.append(f"        O.file_exists('artifact_path', {a[1]!r}, primary={a[2]}),")
        else:  # manual
            lines.append(f"        O.manual_check({a[1]!r}, {a[2]!r}, primary={a[3]}),")
    return "\n".join(lines)


def gen_one(t: dict) -> pathlib.Path:
    tid = t["id"]
    d = TASKS_DIR / tid
    for sub in ("input", "expected", "output", "evidence"):
        (d / sub).mkdir(parents=True, exist_ok=True)

    # input 数据文件 (支持子目录如 pages/rival-a.html)
    for fname, content in t["input_files"].items():
        fp = d / "input" / fname
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")

    # prompt.md
    (d / "prompt.md").write_text(t["prompt"], encoding="utf-8")

    # README.md
    (d / "README.md").write_text(t["readme"], encoding="utf-8")

    # expected/end-state.md
    (d / "expected" / "end-state.md").write_text(t["expected"], encoding="utf-8")

    # scoring.md
    (d / "scoring.md").write_text(t["scoring"], encoding="utf-8")

    # meta.json
    meta = {
        "schema": "taskbank-v1",
        "task_spec": {
            "task_id": tid,
            "domain": "1",
            "app": "multi",
            "prompt": t["meta_prompt"],
            "core_assertions": t["core_assertions"],
            "expects_file": True,
            "tier": "stress",
            "kind": "task-exam",
            "requires_local_desktop": True,
            "dirty_data_level": t["dirty_level"],
            "dirty_data_level_suggested": t["dirty_level"],
            "known_edge_cases": t["known_edge_cases"],
            "capability_domain": "professional-workflow",
            "task_nature": "workflow-heavy",
        },
        "dirty_data": {
            "suggested_by": "ai:gen_tasks",
            "final_by": "human:charlie",
            "note": t["dirty_note"],
        },
        "assertions_module": _mod_name(tid),
        "files": {
            "input": "input/ — " + t["input_desc"],
            "expected": "expected/end-state.md — 正确末态",
            "output": "output/ — " + t["output_desc"],
            "evidence": "evidence/ — 每次运行的日志/截图/录屏",
        },
    }
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                 encoding="utf-8")

    # 断言 .py (放在 tasks/ 下, 模块名匹配 assertions_module)
    mod_file = TASKS_DIR / (tid.replace("-", "_") + ".py")
    src = f'''"""Assertions for {tid} (professional-workflow / workflow-heavy).

跨 app 职业工作流任务, 断言分层(立身之本, 只认末态不信自报):
机器可判的从产出文件自动判, 判断/沟通类挂人工核验。
TASK 从 meta.json 加载+校验, .py 与 bank 不漂移。
"""
import pathlib
from pipeline import objective as O
from pipeline import taskbank as TB

TASK_DIR = pathlib.Path(__file__).resolve().parent / "{tid}"
TASK = TB.assert_valid(TASK_DIR)


def assertions():
    return [
{_assertion_src(t["assertions"])}
    ]
'''
    mod_file.write_text(src, encoding="utf-8")
    return d


def main():
    ok, bad = [], []
    for t in WORKFLOW_TASKS:
        d = gen_one(t)
        probs = TB.validate_dir(d)
        if probs:
            bad.append((t["id"], probs))
        else:
            ok.append(t["id"])
    print("生成通过:", ok)
    if bad:
        print("校验失败:")
        for tid, probs in bad:
            print(" ", tid, "->", probs)
        sys.exit(1)


if __name__ == "__main__":
    main()
