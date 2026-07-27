"""端到端真跑一道题 (T1 微信发送): 走多人工场的新链路,真打盲评面板.

目的: 找出 fixture 掩盖的问题。链路 =
  真实 Submission(磁盘日志包 + 人工勾选断言)
    -> intake.translate  (GATE 推导 / 客观断言 / 日志解析 cost)
    -> blind_panel.score_submissions  (打乱标签 + 脱敏 + 真打 DeepSeek+Gemini)
    -> store 落库 (SQLite)
    -> gap_report.from_store  (MR-11 差距报告派生视图)

数据取自两份真实 run: runs/vio_run1.json(真发成功) 与
runs/open_interpreter_run1.json(谎报 TASK COMPLETE, 末态无消息)。
"""
from __future__ import annotations
import json
import pathlib
import sys
import tempfile
import time

# 让脚本可直接 `python scripts/e2e_real_run.py` 跑 (无需手动 PYTHONPATH=.)。
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pipeline import suite as SUITE
from pipeline import intake as IN
from pipeline import blind_panel as BP
from pipeline import store as STORE
from pipeline import findings as FIND
from pipeline import gap_report as GR
from pipeline.registry import default_registry

ROOT = pathlib.Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
TASK_ID = "T1-wechat-send-001"


def _write_log_bundle(dir_: pathlib.Path, name: str, facts: dict) -> str:
    """把一份日志包 manifest 落到磁盘 (intake.LogBundleParser 读的 JSON)."""
    dir_.mkdir(parents=True, exist_ok=True)
    p = dir_ / f"{name}.json"
    p.write_text(json.dumps(facts, ensure_ascii=False, indent=2))
    return str(p)


def _submission_from_run(run: dict, assignment_id: str, log_bundle_path: str,
                         artifact_dir: str) -> IN.Submission:
    """把一份真实 run JSON 转成一份真实 Submission (人工勾选断言取末态标志)."""
    return IN.Submission(
        assignment_id=assignment_id, product=run["product"], task_id=TASK_ID,
        artifact_path=artifact_dir,
        log_bundle_path=log_bundle_path,
        # T1 的三条都是 manual_check -> 人工勾选断言 (末态由受训执行者认定).
        manual_assertions={
            "msg_received": run["msg_received"],
            "text_exact": run["text_exact"],
            "no_collateral": run["no_collateral"],
        },
        claimed_success=run.get("claimed_success"),
        run_idx=1,
        transcript_excerpt=run.get("transcript_excerpt", ""),
        competitor_version=(run.get("env_meta", {}) or {}).get("competitor")
        or "computer-use",
        tested_at=time.time())


def main() -> int:
    reg = default_registry()

    # 加载真实任务 (T1) 的 TaskSpec + assertions (走 suite discover, 不硬编码).
    task_meta = next(t for t in SUITE.discover_tasks()
                     if t.task_spec.task_id == TASK_ID)

    vio_run = json.loads((RUNS / "vio_run1.json").read_text())
    oi_run = json.loads((RUNS / "open_interpreter_run1.json").read_text())

    workdir = pathlib.Path(tempfile.mkdtemp(prefix="e2e-real-"))
    assignment_id = "A-e2e-t1"

    # --- 造真实磁盘日志包 (intake 从磁盘 parse) ---
    # vio: 自报 usage 的健康包 (DeepSeek 计价, 有真实 token). 用 deepseek-v4-pro
    #      让价表能折算 $, 验证 cost_usd 真算得出.
    vio_bundle = _write_log_bundle(workdir / "vio", "logbundle", {
        "input_tokens": 4200, "output_tokens": 1300, "model_calls": 6,
        "model": "deepseek-v4-pro", "cost_source": "self-report",
        "evidence_source": "log",
        "events": ["run.start", "wechat.open", "search.click",
                   "type.message", "press.enter", "verify.bubble", "run.end"],
    })
    # OI: gemini brain — 价表里【没有】gemini -> cost_usd 应诚实标 None (unavailable),
    #     绝不伪装 0. 这是端到端要验证的诚实点之一.
    oi_bundle = _write_log_bundle(workdir / "oi", "logbundle", {
        "input_tokens": 5100, "output_tokens": 800, "model_calls": 4,
        "model": "gemini-2.5-pro", "cost_source": "self-report",
        "evidence_source": "log",
        "events": ["run.start", "screenshot.match.FAILED",
                   "blind.click", "self.narrate.TASK_COMPLETE", "run.end"],
    })

    subs = [
        _submission_from_run(vio_run, assignment_id, vio_bundle,
                             str(workdir / "vio")),
        _submission_from_run(oi_run, assignment_id, oi_bundle,
                             str(workdir / "oi")),
    ]

    print("=== 1. intake.translate (每份 Submission -> RunRecord) ===")
    tr = IN.SubmissionTranslator()
    for s in subs:
        rr = tr.translate(s, task_meta, reg)
        print(f"  {rr.product:18s} gate={rr.gate:16s} "
              f"obj_passed={rr.objective_passed}/{rr.objective_total} "
              f"failed_primary={rr.objective_failed_primary} "
              f"cost_usd={rr.cost_usd} src={rr.cost_source} "
              f"claimed={rr.claimed_success}")

    print("\n=== 2. blind_panel.score_submissions (打乱标签 + 脱敏 + 真打面板) ===")
    ctx_by_product = {
        "vio": {"artifact_summary": vio_run.get("artifact_summary", ""),
                "screenshots_note": vio_run.get("screenshots_note", "")},
        "open_interpreter": {
            "artifact_summary": oi_run.get("artifact_summary", ""),
            "screenshots_note": oi_run.get("screenshots_note", "")},
    }
    blind_scores = BP.score_submissions(
        subs, task_meta, reg, ctx_by_product=ctx_by_product, seed=42)
    for bs in blind_scores:
        sc = bs.score
        print(f"  {bs.product:18s} label={bs.blind_label:10s} "
              f"sample={sc.get('sample_score')} h1={sc.get('h1_honesty')} "
              f"subj={sc.get('subjective')} dry_run={sc.get('dry_run')}")

    print("\n=== 3. 落库 (SQLite) + findings.classify ===")
    db = workdir / "e2e.db"
    con = STORE.connect(db)
    BP.persist_blind_scores(con, blind_scores)
    scores = [bs.score for bs in blind_scores]
    evidence = {
        "vio": [{"source": "screenshot", "ref": "vio.png"}],
        "open_interpreter": [{"source": "transcript",
                              "ref": oi_run.get("transcript_excerpt", "")[:120]}],
    }
    finds = FIND.classify(TASK_ID, scores, evidence=evidence)
    for f in finds:
        STORE.upsert_finding(con, f)
    print(f"  findings: {[ (f.rule, f.subject) for f in finds ]}")

    print("\n=== 4. gap_report.from_store (MR-11 差距报告) ===")
    rep = GR.from_store(con, TASK_ID, registry=reg)
    d = rep.as_dict()
    print(json.dumps(d, ensure_ascii=False, indent=2))

    con.close()
    print(f"\n[workdir] {workdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
