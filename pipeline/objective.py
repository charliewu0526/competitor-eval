"""Objective assertion layer (rubric §1). No AI — pass/fail on artifact + end-state.

Each task supplies concrete assertion callables. This module provides reusable
checkers and the runner that produces the objective ratio + primary-goal flag.
"""
from __future__ import annotations
import pathlib
from dataclasses import dataclass
from typing import Callable


@dataclass
class Assertion:
    desc: str
    primary: bool                 # is this a 1a "primary goal end-state" check?
    check: Callable[[dict], bool] # ctx -> bool


# --- reusable checkers (return Assertion factories) ---

def file_exists(path_key: str, desc: str, primary: bool = True) -> Assertion:
    def _c(ctx: dict) -> bool:
        p = ctx.get(path_key)
        return bool(p) and pathlib.Path(p).expanduser().exists()
    return Assertion(desc, primary, _c)


def file_nonempty(path_key: str, desc: str, primary: bool = False) -> Assertion:
    def _c(ctx: dict) -> bool:
        p = ctx.get(path_key)
        return bool(p) and pathlib.Path(p).expanduser().is_file() \
            and pathlib.Path(p).expanduser().stat().st_size > 0
    return Assertion(desc, primary, _c)


def equals(ctx_key: str, expected, desc: str, primary: bool = True) -> Assertion:
    return Assertion(desc, primary, lambda ctx: ctx.get(ctx_key) == expected)


def manual_check(desc: str, ctx_key: str, primary: bool = True) -> Assertion:
    """Human-verified end-state recorded into ctx[ctx_key] as True/False.
    Used for closed-app states a script can't read (e.g. 'message visible in WeChat')."""
    return Assertion(desc, primary, lambda ctx: ctx.get(ctx_key) is True)


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
