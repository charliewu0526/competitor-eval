"""Assertions for TA5-doc-deck-gen-001 (assistant-integration).

对标 Town 真实已上线功能的评测题。断言分层(立身之本, 只认末态不信自报):
机器可判的从产出文件自动判(file_exists), 内容/判断类挂人工核验(manual_check)。
TASK 从 meta.json 加载+校验, .py 与 bank 不漂移。
"""
import pathlib
from pipeline import objective as O
from pipeline import taskbank as TB

TASK_DIR = pathlib.Path(__file__).resolve().parent / "TA5-doc-deck-gen-001"
TASK = TB.assert_valid(TASK_DIR)


def assertions():
    return [
        O.file_exists('artifact_path', 'output/compare-doc.md 存在(按outline含三家对比+结论)', primary=True),
        O.manual_check('output/deck.md 存在且分页结构完整(封面/每家一页/总结)', 'deck_structure_ok', primary=True),
        O.manual_check('内容忠于notes、缺失数据如实标注未编造(反幻觉)', 'faithful_no_fab', primary=True),
    ]
