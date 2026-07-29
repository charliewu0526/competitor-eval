"""Assertions for TB1-voice-match-nopromopt-001 (assistant-integration / rival-signature 竞品卖点验证题).

把 Town 的宣传话术拆成可证伪末态。断言分层(立身之本, 只认末态不信自报):
产物存在=机器判(file_exists), 话术是否兑现=受训 intern 人核勾选(manual_check)。
不预填结果——实习生真跑真传。TASK 从 meta.json 加载+校验, .py 与 bank 不漂移。
"""
import pathlib
from pipeline import objective as O
from pipeline import taskbank as TB

TASK_DIR = pathlib.Path(__file__).resolve().parent / "TB1-voice-match-nopromopt-001"
TASK = TB.assert_valid(TASK_DIR)


def assertions():
    return [
        O.file_exists('artifact_path', '产出 output/draft.txt 回复草稿', primary=True),
        O.manual_check('草稿语气/句式贴合 voice-corpus 用户风格、非通用AI腔', 'voice_match', primary=True),
        O.manual_check('沿用用户既有签名/落款、非默认签名', 'signature_match', primary=True),
        O.manual_check('未追问风格偏好即完成(验证免调教话术)', 'no_style_ask', primary=False),
    ]
