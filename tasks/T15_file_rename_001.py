"""Assertions for T15-file-rename-001 (computer-control / simple).

判定自动化(治本): 文件重命名是「产物即答案」的任务 —— 机器完全能核对产物里的
文件名是否等于标准答案, 无需人工。故两条 primary 从 manual_check 改为机器断言
artifact_filenames_equal, 标准答案从 meta.json 的 expected_artifact_filenames
结构化读取(不硬编码, 改题=改数据不改代码)。

立身之本: 判的是末态产物文件名这个客观事实, 不看竞品/实习生自述; 提不到产物
文件名 -> 断言判 False(未验证 != 通过)。
"""
import json
import pathlib
from pipeline import objective as O
from pipeline import taskbank as TB

TASK_DIR = pathlib.Path(__file__).resolve().parent / "T15-file-rename-001"
TASK = TB.assert_valid(TASK_DIR)

_META = json.loads((TASK_DIR / "meta.json").read_text())
# 标准答案文件名集合(机器判定基准)。含日期(考 EXIF)+ 当天序号(考排序)。
EXPECTED_FILENAMES = set(_META.get("expected_artifact_filenames") or [])


def assertions():
    return [
        # primary: 5 个文件名必须与标准答案完全一致(日期错/序号错/漏一个都 fail)。
        # 一条机器断言同时覆盖「按日期命名」+「当天序号正确」两个 primary 目标 ——
        # 因为标准答案本身就编码了这两点, 集合完全相等即两者都对。
        O.artifact_filenames_equal(
            EXPECTED_FILENAMES,
            "all jpgs renamed to the correct 'YYYY-MM-DD_NNN.jpg' (date+sequence)",
            primary=True),
        # secondary: 标准答案文件名都在产物里(允许非图片文件一并保留, 不误判)。
        O.artifact_filenames_superset(
            EXPECTED_FILENAMES,
            "renamed files present; non-image files may remain untouched",
            primary=False),
    ]
