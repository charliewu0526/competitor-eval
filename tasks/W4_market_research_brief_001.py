"""Assertions for W4-market-research-brief-001 (professional-workflow / workflow-heavy).

跨 app 职业工作流任务, 断言分层(立身之本, 只认末态不信自报):
机器可判的从产出文件自动判, 判断/沟通类挂人工核验。
TASK 从 meta.json 加载+校验, .py 与 bank 不漂移。
"""
import pathlib
from pipeline import objective as O
from pipeline import taskbank as TB

TASK_DIR = pathlib.Path(__file__).resolve().parent / "W4-market-research-brief-001"
TASK = TB.assert_valid(TASK_DIR)


def assertions():
    return [
        O.file_exists('artifact_path', 'output/compare.xlsx 竞品对比表已产出', primary=True),
        O.manual_check('三家信息提取正确且 rival-c 价格如实标"未公开"、未编造价格', 'extract_correct', primary=True),
        O.manual_check('output/brief.md 简报正文存在且含三家定位差异总结+我方建议', 'brief_written', primary=True),
        O.manual_check('微信仅发给张总监告知完成、未发错人(截图为证)', 'notify_correct', primary=False),
    ]
