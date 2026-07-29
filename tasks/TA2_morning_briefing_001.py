"""Assertions for TA2-morning-briefing-001 (assistant-integration).

对标 Town 真实已上线功能的评测题。断言分层(立身之本, 只认末态不信自报):
机器可判的从产出文件自动判(file_exists), 内容/判断类挂人工核验(manual_check)。
TASK 从 meta.json 加载+校验, .py 与 bank 不漂移。
"""
import pathlib
from pipeline import objective as O
from pipeline import taskbank as TB

TASK_DIR = pathlib.Path(__file__).resolve().parent / "TA2-morning-briefing-001"
TASK = TB.assert_valid(TASK_DIR)


def assertions():
    return [
        O.file_exists('artifact_path', 'output/briefing.md 存在(含日程/优先事项/冲突三部分)', primary=True),
        O.manual_check('晨报内容与素材一致、日程冲突被正确识别', 'briefing_correct', primary=True),
        O.manual_check('未修改任何原始日历事件或邮件(只读)', 'readonly_ok', primary=False),
    ]
