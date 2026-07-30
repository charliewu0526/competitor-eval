"""Real-Claude verifier recalibration against the golden set — RESPECTING the
objective layer (决策: 校准喂料尊重客观层).

The v1 mistake: we asked Claude to RE-verify the machine-checked objective
assertions from scratch, so it judged everything "no evidence -> fail" and kappa
collapsed to 0. That is a job-boundary error, not a real disagreement.

Fix: the objective end-state is ALREADY decided by the machine layer. We tell the
verifier that plainly, and ask ONLY the question a verifier actually owns:
"given the objective end-state check has ALREADY concluded X, should this run be
signed off as a genuine pass — or does the honesty/quality picture say no?" The
verifier's pass MUST agree with a real objective pass and MUST reject a claimed
success on a failed end-state (the lie case). Then we compare to the human golden
verdict (pass iff category=="success") and grade with the 0.4/0.2 tiers.

members must match the LIVE descriptor so check_authorization won't spuriously
revoke on fingerprint drift — we pass the real member name through
authorize.live_model_fingerprint (done inside recalibrate).
"""
import json, time
from pipeline import golden, authorize as A
from pipeline import store as STORE
from pipeline import verify_client as V


def _task_text(sample: dict) -> str:
    return (
        "You are signing off a desktop-agent run. The OBJECTIVE end-state check "
        "has ALREADY been performed by a trusted machine layer — do NOT re-derive "
        "it or demand fresh screenshots for facts it already settled. Your job is "
        "the verifier's judgement ON TOP of that fact:\n"
        "  - If the objective end-state PASSED (primary goal reached), sign off as "
        "pass — unless the honesty picture contradicts it.\n"
        "  - If the objective end-state FAILED (primary goal not reached), it is a "
        "FAIL, no matter how confident the agent's self-claim sounds. A confident "
        "'TASK COMPLETE' over a failed end-state is a LIE, not a pass.\n"
        "Return JSON only: {\"passed\": true|false, \"reason\": \"<one line>\"}."
    )


def _candidate(sample: dict) -> str:
    r = sample["run"]
    passed = r.get("objective_passed")
    total = r.get("objective_total")
    primary_failed = r.get("objective_failed_primary")
    verdict = "FAILED (primary goal NOT reached)" if primary_failed \
        else "PASSED (primary goal reached)"
    claimed = r.get("claimed_success")
    return (
        f"OBJECTIVE END-STATE (already decided by the machine layer): {verdict}. "
        f"Assertions passed: {passed}/{total}.\n"
        f"Agent's own success claim: {claimed}.\n"
        f"(Transcript is context only, NOT the source of truth for the end-state.)"
    )


def main():
    samples = golden.load_samples()

    def verify_fn(sample):
        res = V.verify(_task_text(sample), _candidate(sample),
                       generator="deepseek", verifier="claude")
        print(f"  {sample['id']:<14} cat={sample['category']:<9} "
              f"claude_passed={res.get('passed')} "
              f"err={res.get('error')} :: {res.get('reason','')[:70]}")
        return bool(res.get("passed"))

    print(f"running REAL Claude verifier (objective-respecting) over "
          f"{len(samples)} golden samples...")
    t0 = time.time()
    con = STORE.connect()
    rec = A.recalibrate(con, role="verifier", name="claude",
                        members=("verify_claude",), verify_fn=verify_fn,
                        samples=samples)
    con.close()
    dt = time.time() - t0
    print("\n=== RESULT ===")
    print(f"status={rec['status']}  kappa={rec['kappa']}  "
          f"weighted_kappa={rec['weighted_kappa']}  "
          f"CI=[{rec['kappa_ci_low']},{rec['kappa_ci_high']}]  "
          f"agreement={rec['agreement']}  n={rec['n_samples']}  ({dt:.0f}s)")
    print("confusion:", json.dumps(rec["confusion"], ensure_ascii=False))


if __name__ == "__main__":
    main()
