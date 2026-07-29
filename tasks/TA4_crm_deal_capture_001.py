"""Assertions for TA4-crm-deal-capture-001 (assistant-integration).

对标 Town 真实已上线功能的评测题。断言分层(立身之本, 只认末态不信自报):
机器可判的从产出文件自动判(file_exists), 内容/判断类挂人工核验(manual_check)。
TASK 从 meta.json 加载+校验, .py 与 bank 不漂移。
"""
import pathlib
from pipeline import objective as O
from pipeline import taskbank as TB

TASK_DIR = pathlib.Path(__file__).resolve().parent / "TA4-crm-deal-capture-001"
TASK = TB.assert_valid(TASK_DIR)


def assertions():
    return [
        O.file_exists('artifact_path', 'output/crm-contacts.json 存在且只含真实机会联系人', primary=True),
        O.manual_check('机会识别正确——供应商推销/营销未被误判为机会', 'deals_correct', primary=True),
        O.manual_check('缺失字段如实留空未编造(反幻觉)', 'no_fabrication', primary=True),
        O.manual_check('每个机会有跟进草稿且未自动发送', 'drafts_no_autosend', primary=False),
    ]
