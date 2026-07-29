"""Assertions for TA3-meeting-prep-001 (assistant-integration).

对标 Town 真实已上线功能的评测题。断言分层(立身之本, 只认末态不信自报):
机器可判的从产出文件自动判(file_exists), 内容/判断类挂人工核验(manual_check)。
TASK 从 meta.json 加载+校验, .py 与 bank 不漂移。
"""
import pathlib
from pipeline import objective as O
from pipeline import taskbank as TB

TASK_DIR = pathlib.Path(__file__).resolve().parent / "TA3-meeting-prep-001"
TASK = TB.assert_valid(TASK_DIR)


def assertions():
    return [
        O.file_exists('artifact_path', 'output/prep.md 存在(含对方背景/上次要点/注意事项)', primary=True),
        O.manual_check('简报内容与往来邮件一致、未张冠李戴或编造', 'prep_faithful', primary=True),
    ]
