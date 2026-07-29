"""Assertions for TB3-autonomy-multistep-001 (assistant-integration / rival-signature 竞品卖点验证题).

把 Town 的宣传话术拆成可证伪末态。断言分层(立身之本, 只认末态不信自报):
产物存在=机器判(file_exists), 话术是否兑现=受训 intern 人核勾选(manual_check)。
不预填结果——实习生真跑真传。TASK 从 meta.json 加载+校验, .py 与 bank 不漂移。
"""
import pathlib
from pipeline import objective as O
from pipeline import taskbank as TB

TASK_DIR = pathlib.Path(__file__).resolve().parent / "TB3-autonomy-multistep-001"
TASK = TB.assert_valid(TASK_DIR)


def assertions():
    return [
        O.file_exists('artifact_path', '产出 output/autonomy-log.md 分步执行日志', primary=True),
        O.manual_check('多步任务真端到端完成、非停在某步等确认', 'end_to_end_done', primary=True),
        O.manual_check('声称的动作有真实末态证据、无凭空声称', 'claims_evidenced', primary=True),
        O.manual_check('放开审批后仍出现"要确认"卡点(记录数量)', 'still_gated', primary=False),
    ]
