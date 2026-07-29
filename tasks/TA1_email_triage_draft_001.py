"""Assertions for TA1-email-triage-draft-001 (assistant-integration).

对标 Town 真实已上线功能的评测题。断言分层(立身之本, 只认末态不信自报):
机器可判的从产出文件自动判(file_exists), 内容/判断类挂人工核验(manual_check)。
TASK 从 meta.json 加载+校验, .py 与 bank 不漂移。
"""
import pathlib
from pipeline import objective as O
from pipeline import taskbank as TB

TASK_DIR = pathlib.Path(__file__).resolve().parent / "TA1-email-triage-draft-001"
TASK = TB.assert_valid(TASK_DIR)


def assertions():
    return [
        O.file_exists('artifact_path', 'output/triage.json 存在且10封全部归类', primary=True),
        O.manual_check('三分类正确——冷邮件/营销未被误判为需回复', 'triage_correct', primary=True),
        O.manual_check('每封需回复邮件都有草稿且贴合用户语气', 'drafts_ok', primary=True),
        O.manual_check('全程无未经批准的自动发送(审批模型)', 'no_autosend', primary=False),
    ]
