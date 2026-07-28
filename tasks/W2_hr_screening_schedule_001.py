"""Assertions for W2-hr-screening-schedule-001 (professional-workflow / workflow-heavy).

跨 app 职业工作流任务, 断言分层(立身之本, 只认末态不信自报):
机器可判的从产出文件自动判, 判断/沟通类挂人工核验。
TASK 从 meta.json 加载+校验, .py 与 bank 不漂移。
"""
import pathlib
from pipeline import objective as O
from pipeline import taskbank as TB

TASK_DIR = pathlib.Path(__file__).resolve().parent / "W2-hr-screening-schedule-001"
TASK = TB.assert_valid(TASK_DIR)


def assertions():
    return [
        O.file_exists('artifact_path', 'output/shortlist.xlsx 入围名单已产出', primary=True),
        O.manual_check('入围判断正确: 恰好陈昊一人(王朔超预算刷、林悦经验不足、赵雪技能低、残缺行跳过)', 'shortlist_correct', primary=True),
        O.manual_check('微信约面只发给入围者陈昊, 未发错人、未发未入围者(截图为证)', 'invite_sent_correct', primary=True),
        O.manual_check('interviews.md 小结正确(有效候选4/入围1/淘汰理由清楚)', 'summary_correct', primary=False),
    ]
