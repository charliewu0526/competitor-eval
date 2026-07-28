"""Assertions for W5-admin-meeting-logistics-001 (professional-workflow / workflow-heavy).

跨 app 职业工作流任务, 断言分层(立身之本, 只认末态不信自报):
机器可判的从产出文件自动判, 判断/沟通类挂人工核验。
TASK 从 meta.json 加载+校验, .py 与 bank 不漂移。
"""
import pathlib
from pipeline import objective as O
from pipeline import taskbank as TB

TASK_DIR = pathlib.Path(__file__).resolve().parent / "W5-admin-meeting-logistics-001"
TASK = TB.assert_valid(TASK_DIR)


def assertions():
    return [
        O.file_exists('artifact_path', 'output/meeting-plan.xlsx 会务方案已产出', primary=True),
        O.manual_check('时段与会议室正确: 周三下午+B会议室(必到三人交集+容量够+该时段可用)', 'plan_correct', primary=True),
        O.manual_check('微信只通知实际参会者、未通知赵磊(仅上午到)、未发错人(截图为证)', 'notice_sent_correct', primary=True),
        O.manual_check('notice.md 选择理由正确(时段交集+会议室双约束)', 'notice_log_correct', primary=False),
    ]
