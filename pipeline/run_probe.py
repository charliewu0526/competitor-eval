"""X2 driver: PM manually triggers a capability-probe (path 2).

Usage:
  python -m pipeline.run_probe --demo    # token-cost probe: vio vs open_interpreter

A real probe reads two operator-filled RunRecords (baseline + rival) carrying the
A3 cost fields, picks the 卖点 winner, attaches an optional 代码机理分析 for an
open-source rival, and lands the Finding in the SAME SQLite store as path 1. The
rival's is_open_source flag is read from the F2 registry — 机理分析 is only allowed
for open-source rivals (the registry decides, not the caller).
"""
from __future__ import annotations
import sys, json

from pipeline.schema import RunRecord
from pipeline import probe as P
from pipeline import store as STORE
from pipeline.registry import default_registry

REGISTRY = default_registry()


def _rr(d: dict) -> RunRecord:
    return RunRecord(
        task_id=d["probe_id"], product=d["product"], run_idx=d.get("run_idx", 1),
        gate=d.get("gate", "native-operable"),
        objective_passed=d.get("objective_passed", 0),
        objective_total=d.get("objective_total", 0),
        cost_input_tokens=d.get("cost_input_tokens", 0),
        cost_output_tokens=d.get("cost_output_tokens", 0),
        cost_model_calls=d.get("cost_model_calls", 0),
        cost_usd=d.get("cost_usd"),
        transcript_excerpt=d.get("transcript_excerpt", ""))


def trigger(spec: P.ProbeSpec, base_d: dict, rival_d: dict,
            code_analysis: P.CodeAnalysis | None = None,
            con=None) -> P.ProbeResult:
    """Run + persist one probe. is_open_source is resolved from the registry."""
    base, rival = _rr(base_d), _rr(rival_d)
    oss = False
    try:
        oss = REGISTRY.get(spec.rival).is_open_source
    except KeyError:
        oss = False
    result = P.run_probe(spec, base, rival, code_analysis=code_analysis,
                         rival_is_open_source=oss)
    con = con or STORE.connect()
    P.persist_probe(con, spec, base, rival, result)
    return result


DEMO_SPEC = P.ProbeSpec("PB-token-001", "token-cost", "open_interpreter",
                        title="省 token 卖点对打")
DEMO_BASE = {"probe_id": "PB-token-001", "product": "vio",
             "cost_input_tokens": 4200, "cost_output_tokens": 1100,
             "cost_model_calls": 9}
DEMO_RIVAL = {"probe_id": "PB-token-001", "product": "open_interpreter",
              "cost_input_tokens": 850, "cost_output_tokens": 260,
              "cost_model_calls": 3}
DEMO_CA = P.CodeAnalysis(
    product="open_interpreter",
    repo="https://github.com/OpenInterpreter/open-interpreter",
    mechanism="单进程内联执行生成的代码、无逐步 agent 规划循环，省去多轮 reflection token",
    refs=["interpreter/core/core.py"], analyst="charlie")


def main():
    if "--demo" not in sys.argv:
        print("provide --demo, or import trigger() with your own RunRecords.")
        return
    r = trigger(DEMO_SPEC, DEMO_BASE, DEMO_RIVAL, code_analysis=DEMO_CA)
    print(f"probe -> db {STORE.DEFAULT_DB}")
    print(json.dumps(r.as_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
