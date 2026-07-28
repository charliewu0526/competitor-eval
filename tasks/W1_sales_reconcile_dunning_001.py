"""Assertions for W1-sales-reconcile-dunning-001 (professional-workflow / workflow-heavy).

跨 app 职业工作流样板任务。断言分层(立身之本, 只认末态不信自报):
  - 机器可判: 催收表 unpaid.xlsx 存在(file_exists)。
  - 人工核验: 未到账判断正确、微信只发对两家、消息措辞 —— 跨 app 判断/沟通类
    无法机器判, 由受训 runner 勾选末态, 抽查复核。
TASK 从 meta.json 加载+校验, .py 与 bank 不漂移。
"""
import pathlib
from pipeline import objective as O
from pipeline import taskbank as TB

TASK_DIR = pathlib.Path(__file__).resolve().parent / "W1-sales-reconcile-dunning-001"
TASK = TB.assert_valid(TASK_DIR)


def assertions():
    return [
        # 机器可判: 催收表产出存在。
        O.file_exists('artifact_path',
                      'output/unpaid.xlsx 催收表已产出', primary=True),
        # 人工核验: 跨 app 判断链正确 —— 恰好识别两家未到账(户名模糊+干扰流水都判对)。
        O.manual_check('未到账判断正确: 恰好海通贸易+本立设计两家(户名模糊匹配、'
                       '干扰流水未误判、金额核对)', 'unpaid_correct', primary=True),
        # 人工核验: 微信催款末态 —— 只发对两家正确联系人, 未发错人、未发已到账客户。
        O.manual_check('微信催款只发给海通张总+本立陈工两位, 未发错人、'
                       '未发给已到账客户(截图为证)', 'dunning_sent_correct', primary=True),
        # 机器可辅判: 小结数字(secondary)。
        O.manual_check('summary.md 小结数字正确(4笔/已到账2/未到账2/合计21300)',
                       'summary_correct', primary=False),
    ]
