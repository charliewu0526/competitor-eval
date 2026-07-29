"""Assertions for TB2-proactive-latent-todo-001 (assistant-integration / rival-signature 竞品卖点验证题).

把 Town 的宣传话术拆成可证伪末态。断言分层(立身之本, 只认末态不信自报):
产物存在=机器判(file_exists), 话术是否兑现=受训 intern 人核勾选(manual_check)。
不预填结果——实习生真跑真传。TASK 从 meta.json 加载+校验, .py 与 bank 不漂移。
"""
import pathlib
from pipeline import objective as O
from pipeline import taskbank as TB

TASK_DIR = pathlib.Path(__file__).resolve().parent / "TB2-proactive-latent-todo-001"
TASK = TB.assert_valid(TASK_DIR)


def assertions():
    return [
        O.file_exists('artifact_path', '产出 output/proactive.md 主动行动结果', primary=True),
        O.manual_check('主动发现隐含截止日待办并起草/建提醒', 'found_latent_todo', primary=True),
        O.manual_check('主动提示日历冲突', 'flagged_conflict', primary=True),
        O.manual_check('未把营销/无关邮件误当待办处理(反噪声)', 'no_false_positive', primary=False),
    ]
