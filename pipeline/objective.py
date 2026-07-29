"""Objective assertion layer (rubric §1). No AI — pass/fail on artifact + end-state.

Each task supplies concrete assertion callables. This module provides reusable
checkers and the runner that produces the objective ratio + primary-goal flag.

MR-8 (#44) 断言翻译分工: 每条断言标 `kind`——
  * "machine": 脚本/规则可自动判定(文件存在、某格值、日志有无某事件)。这类断言
    的输入只能来自权威来源(服务端落盘的产物路径、从日志包解析出的事件),
    绝不落人手——立身之本: intern 不能手勾一个本该机器判的断言。
  * "human":  只能人看的末态(如「微信消息真发出了」),由受训 intern 勾选进 ctx。
`ctx_key` 显式暴露该断言读哪个 ctx 键,intake 据此把「机器该填的」与「人该勾的」
分流到不同来源,并守卫 intern 只能提交 human 断言的键。
"""
from __future__ import annotations
import pathlib
from dataclasses import dataclass
from typing import Callable

MACHINE = "machine"   # 脚本/规则自动判定, 输入来自权威来源, 不落人手
HUMAN = "human"       # 只能人看的末态, 由 intern 勾选
KIND_VALUES = (MACHINE, HUMAN)


@dataclass
class Assertion:
    desc: str
    primary: bool                 # is this a 1a "primary goal end-state" check?
    check: Callable[[dict], bool] # ctx -> bool
    kind: str = MACHINE           # MACHINE (auto-judged) | HUMAN (intern-ticked)
    ctx_key: str | None = None    # which ctx key this assertion reads (分流依据)

    def __post_init__(self) -> None:
        if self.kind not in KIND_VALUES:
            raise ValueError(f"kind must be one of {KIND_VALUES}, got {self.kind!r}")


# --- reusable checkers (return Assertion factories) ---
# Machine checkers: judged from authoritative context a script populates. NEVER
# from an intern's self-report — that is the whole point of the machine/human split.

def file_exists(path_key: str, desc: str, primary: bool = True) -> Assertion:
    def _c(ctx: dict) -> bool:
        p = ctx.get(path_key)
        return bool(p) and pathlib.Path(p).expanduser().exists()
    return Assertion(desc, primary, _c, kind=MACHINE, ctx_key=path_key)


def file_nonempty(path_key: str, desc: str, primary: bool = False) -> Assertion:
    def _c(ctx: dict) -> bool:
        p = ctx.get(path_key)
        return bool(p) and pathlib.Path(p).expanduser().is_file() \
            and pathlib.Path(p).expanduser().stat().st_size > 0
    return Assertion(desc, primary, _c, kind=MACHINE, ctx_key=path_key)


def equals(ctx_key: str, expected, desc: str, primary: bool = True) -> Assertion:
    return Assertion(desc, primary, lambda ctx: ctx.get(ctx_key) == expected,
                     kind=MACHINE, ctx_key=ctx_key)


def log_event(event: str, desc: str, primary: bool = False,
              events_key: str = "log_events") -> Assertion:
    """机器可验「日志有无某事件」(#44): 事件名出现在解析出的日志事件列表里则通过。

    输入是从日志包解析出的 events(权威来源, 非自报), 故 kind=machine。
    """
    def _c(ctx: dict) -> bool:
        return event in (ctx.get(events_key) or [])
    return Assertion(desc, primary, _c, kind=MACHINE, ctx_key=events_key)


def manual_check(desc: str, ctx_key: str, primary: bool = True) -> Assertion:
    """Human-verified end-state recorded into ctx[ctx_key] as True/False.
    Used for closed-app states a script can't read (e.g. 'message visible in WeChat')."""
    return Assertion(desc, primary, lambda ctx: ctx.get(ctx_key) is True,
                     kind=HUMAN, ctx_key=ctx_key)


def artifact_filenames_equal(expected: set[str], desc: str, *,
                             primary: bool = True,
                             names_key: str = "artifact_filenames") -> Assertion:
    """机器可验「产物里的文件名集合 == 标准答案集合」(#T15 判定自动化)。

    输入 ctx[names_key] = 服务端从提交产物(zip/文件夹)提取出的**文件名集合**
    (basename,去目录前缀),权威来源、人碰不到。expected = 从任务 expected/ 结构化
    读出的标准答案(不硬编码)。集合完全相等才通过 —— 少一个、多一个、名字错一个
    都 fail。这样文件重命名这类「产物即答案」的任务无需人工核对即可自动判。

    立身之本: 判的是末态产物文件名这个客观事实, 不看竞品/实习生自述。缺 names_key
    (没提取到产物文件名) -> 判 False(未验证 != 通过, 不伪装成功)。
    """
    want = {str(x) for x in expected}

    def _c(ctx: dict) -> bool:
        got = ctx.get(names_key)
        if got is None:
            return False
        return {str(x) for x in got} == want
    return Assertion(desc, primary, _c, kind=MACHINE, ctx_key=names_key)


def artifact_filenames_superset(expected: set[str], desc: str, *,
                                primary: bool = False,
                                names_key: str = "artifact_filenames") -> Assertion:
    """机器可验「产物里包含全部标准答案文件名」(允许有额外文件, 如非图片文件保留)。

    用于 secondary 断言: 只要标准答案的文件名都在产物里即通过, 不因产物多出无关
    文件(如未动的非图片文件被一起打包)而误判失败。
    """
    want = {str(x) for x in expected}

    def _c(ctx: dict) -> bool:
        got = ctx.get(names_key)
        if got is None:
            return False
        return want <= {str(x) for x in got}
    return Assertion(desc, primary, _c, kind=MACHINE, ctx_key=names_key)


def machine_keys(assertions: list[Assertion]) -> set[str]:
    """The ctx keys owned by MACHINE assertions — must be fed from authoritative
    sources, never from an intern's manual_assertions (intake enforces this)."""
    return {a.ctx_key for a in assertions if a.kind == MACHINE and a.ctx_key}


def human_keys(assertions: list[Assertion]) -> set[str]:
    """The ctx keys an intern is allowed to tick (HUMAN assertions)."""
    return {a.ctx_key for a in assertions if a.kind == HUMAN and a.ctx_key}


def run_assertions(assertions: list[Assertion], ctx: dict) -> dict:
    results = [(a.desc, a.primary, bool(a.check(ctx))) for a in assertions]
    passed = sum(1 for _, _, ok in results if ok)
    primary_fail = any(p and not ok for _, p, ok in results)
    return {
        "results": results,
        "passed": passed,
        "total": len(results),
        "failed_primary": primary_fail,
    }
