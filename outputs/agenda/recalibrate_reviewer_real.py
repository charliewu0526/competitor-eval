"""Real-panel reviewer recalibration against the golden set (#1 fix).

The v1 reviewer kappa (0.8054) was NAME-ONLY真实: golden.score_sample installs
each sample's FIXED FAKE panel, so it measured "does the seam reproduce the human
label given a scripted panel" — NOT whether the LIVE DeepSeek+Gemini panel agrees
with humans. The real panel never read the golden set.

This script runs the REAL production panel (orchestrate.PANELISTS = DeepSeek +
Gemini, live API) over each golden sample's synthetic run, through the SAME seam
(score_run), and grades the resulting reviewer kappa with the 0.4/0.2 tiers.

Note: the golden samples are SYNTHETIC (transcript-only, no real artifact), so the
panel scores on the transcript/end-state we provide. This is a genuine reviewer
calibration on the real models; as real-trace samples backfill (#4), it gets even
more faithful. Requires live keys (DEEPSEEK_API_KEY + GEMINI_API_KEY).
"""
import json, time
from pipeline import golden, authorize as A
from pipeline import store as STORE
from pipeline import orchestrate
from pipeline.review_prompt import DIMENSIONS


def _real_score_fn(sample: dict) -> dict:
    """Score ONE golden sample through the REAL live panel (no fake install).

    Mirrors golden.score_sample's seam call but WITHOUT swapping in the sample's
    fixed fake panel — so orchestrate.PANELISTS (the live DeepSeek+Gemini) does
    the judging. Objective fields still come from the sample's run (the machine
    layer), honouring 'reviewer only scores what objective can't'.
    """
    run = golden._build_run(sample["run"])
    # ctx carries the transcript/evidence the panel reasons over.
    ctx = {
        "artifact_summary": sample.get("title", "(none)"),
        "screenshots_note": run.evidence_source,
    }
    return orchestrate.score_run(golden.GOLDEN_TASK, run, ctx)


def main():
    samples = golden.load_samples()
    print(f"LIVE panel = {orchestrate.PANELISTS}")
    print(f"running REAL panel over {len(samples)} golden samples "
          f"(this hits the network)...")

    ai, human = [], []
    t0 = time.time()
    for s in samples:
        out = _real_score_fn(s)
        ab = A.score_bucket(out.get("sample_score"))
        hb = A.score_bucket(s["expected"].get("sample_score"))
        ai.append(ab); human.append(hb)
        dry = out.get("dry_run")
        print(f"  {s['id']:<14} cat={s['category']:<9} "
              f"ai={ab:<8} human={hb:<8}{'  [DRY-RUN!]' if dry else ''}")

    # Grade + persist through recalibrate, injecting the SAME real score_fn so the
    # recorded kappa is the real-panel number (recalibrate recomputes internally).
    con = STORE.connect()
    rec = A.recalibrate(con, role="reviewer", name="panel",
                        members=orchestrate.PANELISTS, samples=samples,
                        score_fn=_real_score_fn)
    con.close()
    dt = time.time() - t0
    print("\n=== RESULT ===")
    print(f"status={rec['status']}  kappa={rec['kappa']}  "
          f"weighted_kappa={rec['weighted_kappa']}  "
          f"CI=[{rec['kappa_ci_low']},{rec['kappa_ci_high']}]  "
          f"agreement={rec['agreement']}  n={rec['n_samples']}  ({dt:.0f}s)")
    print("confusion:", json.dumps(rec["confusion"], ensure_ascii=False))
    print("bias_profile:", json.dumps(rec["bias_profile"], ensure_ascii=False))


if __name__ == "__main__":
    main()
