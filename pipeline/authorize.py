"""G2 (#25): golden-set authorization + Cohen's kappa + recalibration triggers.

The trust seam: an AI reviewer/verifier must clear the golden set BEFORE it is
authorized to auto-process real tasks. We compute Cohen's kappa (panel-vs-human
on the golden labels) and a 宽严 bias profile — but per ADR-0011 / ADR-0005 the
FIRST version sets NO hard threshold: we only RECORD agreement + the bias
profile, and the bias profile NEVER writes back into any sample_score.

Authorization lifecycle (acceptance criteria):
  - recalibrate(): runs the golden set through the seam, computes kappa, RECORDS
    it, and (no-threshold v1) marks the subject `authorized`.
  - check_authorization(): the on-every-real-task gate. If the live model/rubric
    fingerprint drifted from the calibrated one, or an audit anomaly was flagged,
    authorization is AUTO-REVOKED (status -> revoked) and the subject must
    recalibrate again to recover.

Two subjects:
  - reviewer (the scoring panel): label = sample_score bucketed into an ordinal
    grade; compared to the human expected sample_score bucket.
  - verifier (A4 pass/fail): label = pass/fail; compared to the human verdict
    derived from the golden category (success -> pass, otherwise fail).

Everything here is OFFLINE — it drives golden.score_sample (fixed fake panel),
never the network.
"""
from __future__ import annotations
import hashlib
import time

from pipeline import golden
from pipeline.review_prompt import DIMENSIONS, S5_ANCHORS, ANTI_BIAS


# ---------------------------------------------------------------------------
# Cohen's kappa — nominal, two raters (AI vs human) over shared sample labels.
# ---------------------------------------------------------------------------
def cohens_kappa(rater_a: list, rater_b: list) -> dict:
    """Cohen's kappa for two equal-length label sequences.

    Returns {kappa, agreement(po), expected(pe), n, confusion}. kappa is None
    when undefined (n==0, or pe==1 i.e. a single label fills both raters — then
    we report agreement only, never a fake 0/1 kappa).
    """
    if len(rater_a) != len(rater_b):
        raise ValueError("rater label sequences must be equal length")
    n = len(rater_a)
    if n == 0:
        return {"kappa": None, "agreement": None, "expected": None,
                "n": 0, "confusion": {}}
    labels = sorted({str(x) for x in rater_a} | {str(x) for x in rater_b})
    confusion: dict = {a: {b: 0 for b in labels} for a in labels}
    for a, b in zip(rater_a, rater_b):
        confusion[str(a)][str(b)] += 1
    po = sum(1 for a, b in zip(rater_a, rater_b) if str(a) == str(b)) / n
    # expected agreement from marginals
    ca = {lbl: sum(str(x) == lbl for x in rater_a) for lbl in labels}
    cb = {lbl: sum(str(x) == lbl for x in rater_b) for lbl in labels}
    pe = sum((ca[l] / n) * (cb[l] / n) for l in labels)
    kappa = None if pe >= 1.0 else round((po - pe) / (1 - pe), 4)
    return {"kappa": kappa, "agreement": round(po, 4),
            "expected": round(pe, 4), "n": n, "confusion": confusion}


# ---------------------------------------------------------------------------
# Fingerprints — change ANY of these and the old authorization is stale.
# ---------------------------------------------------------------------------
def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def rubric_fingerprint() -> str:
    """Hash of the scoring rubric: dims + weights + the S5 / anti-bias anchors.
    Changing the rubric (new S5/H1, reweighting) changes this -> recalibrate."""
    dims = ";".join(f"{c}:{w}" for c, _, w in DIMENSIONS)
    return _hash(dims + "|" + S5_ANCHORS + "|" + ANTI_BIAS)


def model_fingerprint(members) -> str:
    """Hash of the model identity behind a subject: ordered member names +
    their model versions. Swapping a model or bumping a version changes this."""
    return _hash("|".join(str(m) for m in members))


# ---------------------------------------------------------------------------
# Label derivation — map seam output + human label onto comparable classes.
# ---------------------------------------------------------------------------
# Reviewer: bucket a 0..1 sample_score into an ordinal grade. None -> "unscored"
# (cannot-reach). Coarse buckets keep kappa meaningful on a 24-sample set.
def score_bucket(sample_score) -> str:
    if sample_score is None:
        return "unscored"
    if sample_score <= 0.0:
        return "fail"        # 0   -> capability failure
    if sample_score < 0.75:
        return "partial"     # (0,0.75)
    return "high"            # [0.75,1]


def reviewer_labels(samples=None) -> tuple[list, list]:
    """(ai_labels, human_labels) of score buckets over the golden set.

    AI = bucket of the seam's real sample_score; human = bucket of the
    expected sample_score. Both are derived through the SAME bucketing so the
    comparison is apples-to-apples.
    """
    samples = samples or golden.load_samples()
    ai, human = [], []
    for s in samples:
        out = golden.score_sample(s)
        ai.append(score_bucket(out.get("sample_score")))
        human.append(score_bucket(s["expected"].get("sample_score")))
    return ai, human


# Verifier: a binary pass/fail. Human truth from the golden category: only the
# `success` category is a genuine pass; failure/lied/ambiguous are not-pass.
def human_verdict(sample: dict) -> str:
    return "pass" if sample["category"] == "success" else "fail"


def verifier_labels(verify_fn, samples=None) -> tuple[list, list]:
    """(ai_labels, human_labels) of pass/fail over the golden set.

    verify_fn(sample) -> bool (the AI verifier's verdict for that sample). Kept
    injectable so the offline fake (A4) drives this with no network.
    """
    samples = samples or golden.load_samples()
    ai, human = [], []
    for s in samples:
        ai.append("pass" if verify_fn(s) else "fail")
        human.append(human_verdict(s))
    return ai, human


# ---------------------------------------------------------------------------
# Bias profile — per-model 宽严 offset vs the panel median. RECORD ONLY.
# ---------------------------------------------------------------------------
def bias_profile(samples=None) -> dict:
    """Per-panelist mean signed deviation from the per-sample panel median,
    across S1-S4. Positive = that model scores HIGHER (宽/lenient), negative =
    LOWER (严/strict). This is DIAGNOSTIC ONLY — ADR-0005: never auto-corrects a
    score, so a strict reviewer's real signal is not flattened away.
    """
    import statistics
    samples = samples or golden.load_samples()
    dims = ("S1", "S2", "S3", "S4")
    sums: dict[str, list] = {}
    for s in samples:
        for d in dims:
            vals = [(p["panelist"], p[d]) for p in s["panel"]
                    if isinstance(p.get(d), (int, float))
                    and not isinstance(p.get(d), bool)]
            if len(vals) < 2:
                continue
            med = statistics.median(v for _, v in vals)
            for name, v in vals:
                sums.setdefault(name, []).append(v - med)
    return {name: round(sum(devs) / len(devs), 4)
            for name, devs in sums.items() if devs}


# ---------------------------------------------------------------------------
# The authorization lifecycle.
# ---------------------------------------------------------------------------
def _subject_key(role: str, name: str) -> str:
    return f"{role}:{name}"


def recalibrate(con, *, role: str, name: str, members,
                verify_fn=None, samples=None) -> dict:
    """Run the golden set, RECORD kappa + bias, and authorize the subject.

    No hard threshold (ADR-0011 v1): clearing the run = authorized, whatever the
    kappa. The kappa/agreement/bias are persisted for observation so a threshold
    can be set later from real data.
    """
    from pipeline import store
    samples = samples or golden.load_samples()
    if role == "reviewer":
        ai, human = reviewer_labels(samples)
    elif role == "verifier":
        if verify_fn is None:
            raise ValueError("verifier recalibration needs a verify_fn")
        ai, human = verifier_labels(verify_fn, samples)
    else:
        raise ValueError(f"unknown role {role!r}")

    k = cohens_kappa(ai, human)
    rec = {
        "subject": _subject_key(role, name), "role": role,
        "status": "authorized",                 # v1: no threshold gate
        "kappa": k["kappa"], "agreement": k["agreement"],
        "n_samples": k["n"],
        "model_fingerprint": model_fingerprint(members),
        "rubric_fingerprint": rubric_fingerprint(),
        "bias_profile": bias_profile(samples) if role == "reviewer" else {},
        "confusion": k["confusion"],
        "calibrated_ts": time.time(), "revoked_reason": None,
    }
    store.upsert_authorization(con, rec)
    return rec


def check_authorization(con, *, role: str, name: str, members,
                        anomaly: bool = False) -> dict:
    """The on-every-real-task gate. Returns {authorized: bool, status, reason}.

    Auto-REVOKES (and persists the revoke) when any recalibration trigger fired:
      1. model/version drift  (live members != calibrated fingerprint)
      2. rubric drift          (live rubric != calibrated fingerprint)
      3. audit anomaly flagged (caller passes anomaly=True)
    A revoked subject only recovers by recalibrate() — never silently.
    """
    from pipeline import store
    subject = _subject_key(role, name)
    rec = store.get_authorization(con, subject)
    if rec is None:
        return {"authorized": False, "status": "uncalibrated",
                "reason": "never calibrated on the golden set"}
    if rec["status"] != "authorized":
        return {"authorized": False, "status": rec["status"],
                "reason": rec.get("revoked_reason") or rec["status"]}

    reason = None
    if model_fingerprint(members) != rec["model_fingerprint"]:
        reason = "model/version changed since calibration"
    elif rubric_fingerprint() != rec["rubric_fingerprint"]:
        reason = "rubric changed since calibration"
    elif anomaly:
        reason = "audit anomaly flagged"

    if reason:
        store.set_authorization_status(con, subject, "revoked", reason)
        return {"authorized": False, "status": "revoked", "reason": reason}
    return {"authorized": True, "status": "authorized", "reason": None}
