"""Assertions for W3-finance-expense-audit-001 (professional-workflow / workflow-heavy).

跨 app 职业工作流任务, 断言分层(立身之本, 只认末态不信自报):
机器可判的从产出文件自动判, 判断/沟通类挂人工核验。
TASK 从 meta.json 加载+校验, .py 与 bank 不漂移。
"""
import pathlib
from pipeline import objective as O
from pipeline import taskbank as TB

TASK_DIR = pathlib.Path(__file__).resolve().parent / "W3-finance-expense-audit-001"
TASK = TB.assert_valid(TASK_DIR)


def assertions():
    return [
        O.file_exists('artifact_path', 'output/approved.xlsx 通过清单已产出', primary=True),
        O.manual_check('审核判断正确: 通过李强/孙婷/郑楠(去重), 打回吴迪(无票)/钱多(超额)/郑楠重复项', 'audit_correct', primary=True),
        O.manual_check('微信打回通知只发被打回者、原因正确, 未发错人、未通知通过者(截图为证)', 'reject_notice_correct', primary=True),
        O.manual_check('rejected.md 每笔打回原因正确(无票/超额/重复)', 'rejected_log_correct', primary=False),
    ]
