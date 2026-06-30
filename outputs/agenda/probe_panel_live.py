"""探活: 实测各评审 panelist 现在是否真能用 (带超时隔离, 不卡主流程).

每个 panelist 在独立子进程里跑, 各给 25s 墙钟超时 -> 超时/报错/dry_run 都
判定不可用. 输出一行 JSON 汇总, 供主程序决定用哪个面板组合跑真实评测.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys

PANELISTS = ["review_deepseek", "review_glm", "review_claude", "review_gemini"]
PROMPT = ('Return ONLY this JSON, nothing else: '
          '{"S1":4,"S2":4,"S3":4,"S4":4,"S5":4,'
          '"justifications":{"S1":"ok","S2":"ok","S3":"ok","S4":"ok","S5":"ok"},'
          '"defects":[]}')

CHILD = r'''
import json, sys
from pipeline import review_client as RC
fn = getattr(RC, sys.argv[1])
out = fn(%r)
print("RESULT:" + json.dumps(out, ensure_ascii=False))
''' % PROMPT


def probe_one(name: str) -> dict:
    try:
        p = subprocess.run(
            [sys.executable, "-c", CHILD, name],
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            capture_output=True, text=True, timeout=25)
    except subprocess.TimeoutExpired:
        return {"panelist": name, "alive": False, "why": "timeout>25s"}
    line = next((l for l in p.stdout.splitlines()
                 if l.startswith("RESULT:")), None)
    if not line:
        return {"panelist": name, "alive": False,
                "why": (p.stderr or p.stdout or "no output")[-160:]}
    out = json.loads(line[len("RESULT:"):])
    if out.get("dry_run"):
        return {"panelist": name, "alive": False, "why": "no key (dry-run stub)"}
    if "error" in out:
        return {"panelist": name, "alive": False, "why": out["error"][:160]}
    has_scores = all(k in out for k in ("S1", "S2", "S3", "S4", "S5"))
    return {"panelist": name, "alive": has_scores,
            "why": "ok" if has_scores else f"no scores: {list(out)}"}


def main():
    results = [probe_one(n) for n in PANELISTS]
    alive = [r["panelist"] for r in results if r["alive"]]
    print(json.dumps({"alive": alive, "detail": results},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
