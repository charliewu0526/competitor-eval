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
import random
import time

from pipeline import golden
from pipeline.review_prompt import DIMENSIONS, S5_ANCHORS, ANTI_BIAS


# ---------------------------------------------------------------------------
# Graded authorization thresholds (ADR-0011 v2). v1 had NO threshold (observe
# only); now that we have real data, kappa gates the status. Deliberately LENIENT
# so a genuinely-useful-but-imperfect model is not slammed to rejected:
#   kappa >= 0.4        -> authorized  (agrees with humans well enough)
#   0.2 <= kappa < 0.4  -> observe     (usable but watched + flagged)
#   kappa <  0.2        -> rejected    (退回人工 — do not auto-process)
# kappa=None (undefined, e.g. single label / n==0) -> observe (can't grade, watch).
# ---------------------------------------------------------------------------
AUTHORIZE_THRESHOLD = 0.4
OBSERVE_THRESHOLD = 0.2


def grade_authorization(kappa) -> str:
    """Map a kappa value onto the authorization status tier."""
    if kappa is None:
        return "observe"
    if kappa >= AUTHORIZE_THRESHOLD:
        return "authorized"
    if kappa >= OBSERVE_THRESHOLD:
        return "observe"
    return "rejected"


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
# Weighted (ordinal) kappa — our labels are ORDERED grades, not nominal classes.
# A "high" mislabelled "partial" is a near-miss; "high" -> "fail" is a blunder.
# Plain Cohen's kappa treats both the same. Weighted kappa penalises by DISTANCE
# on the ordinal scale, so it reflects real severity on our tiny label set.
# ---------------------------------------------------------------------------
# Reviewer grades in ascending competence order; "unscored" (cannot-reach) sits
# apart — it is not "worse than fail", so it is placed as its own far bucket only
# when present. Verifier labels (pass/fail) also get a sane order.
_ORDINAL_SCALES = (
    ["fail", "partial", "high"],          # reviewer scored grades
    ["fail", "pass"],                     # verifier verdict
)


def _ordinal_index(labels: list) -> dict | None:
    """Return {label: rank} if the label universe matches a known ordinal scale
    (ignoring the special 'unscored'); else None -> caller falls back to nominal.
    'unscored' is appended as the top rank so it is maximally distant from graded
    buckets (disagreeing on reach vs a real grade is a large error)."""
    universe = {str(x) for x in labels}
    core = universe - {"unscored"}
    for scale in _ORDINAL_SCALES:
        if core <= set(scale):
            ranks = {lbl: i for i, lbl in enumerate(scale)}
            if "unscored" in universe:
                ranks["unscored"] = len(scale)   # far top bucket
            return ranks
    return None


def weighted_cohens_kappa(rater_a: list, rater_b: list, *,
                          weights: str = "quadratic") -> dict:
    """Ordinal (linear/quadratic weighted) kappa for two label sequences.

    Falls back to nominal cohens_kappa when the labels don't form a known
    ordinal scale (so callers get a sensible number either way). weights:
    "quadratic" (default, penalises big gaps hard) or "linear".
    Returns {kappa, agreement, n, weights, ordinal(bool)}.
    """
    if len(rater_a) != len(rater_b):
        raise ValueError("rater label sequences must be equal length")
    n = len(rater_a)
    if n == 0:
        return {"kappa": None, "agreement": None, "n": 0,
                "weights": weights, "ordinal": False}
    ranks = _ordinal_index(list(rater_a) + list(rater_b))
    if ranks is None:
        base = cohens_kappa(rater_a, rater_b)
        base.update({"weights": weights, "ordinal": False})
        return base
    k = len(ranks)
    maxd = (k - 1) or 1

    def w(i, j):
        d = abs(i - j) / maxd
        return d * d if weights == "quadratic" else d

    a = [ranks[str(x)] for x in rater_a]
    b = [ranks[str(x)] for x in rater_b]
    # marginals
    ca = [sum(1 for x in a if x == i) / n for i in range(k)]
    cb = [sum(1 for x in b if x == i) / n for i in range(k)]
    num_o = sum(w(a[t], b[t]) for t in range(n)) / n
    num_e = sum(w(i, j) * ca[i] * cb[j] for i in range(k) for j in range(k))
    kappa = None if num_e == 0 else round(1 - num_o / num_e, 4)
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    return {"kappa": kappa, "agreement": round(po, 4), "n": n,
            "weights": weights, "ordinal": True}


def kappa_confidence_interval(rater_a: list, rater_b: list, *,
                              weighted: bool = True, n_boot: int = 1000,
                              seed: int = 12345, alpha: float = 0.05) -> dict:
    """Bootstrap CI for kappa: resample sample-pairs with replacement n_boot
    times, recompute kappa, report the alpha/2 .. 1-alpha/2 percentiles.

    Small golden sets make a point kappa noisy; the CI shows how noisy. Returns
    {low, high, point, n_boot, degenerate_frac} (degenerate = resamples where
    kappa was undefined, e.g. a single label filled the resample)."""
    n = len(rater_a)
    if n != len(rater_b):
        raise ValueError("rater label sequences must be equal length")
    fn = (lambda x, y: weighted_cohens_kappa(x, y)["kappa"]) if weighted \
        else (lambda x, y: cohens_kappa(x, y)["kappa"])
    point = fn(rater_a, rater_b) if n else None
    if n == 0:
        return {"low": None, "high": None, "point": None,
                "n_boot": 0, "degenerate_frac": None}
    rng = random.Random(seed)
    vals = []
    degenerate = 0
    for _ in range(n_boot):
        idx = [rng.randrange(n) for _ in range(n)]
        ka = fn([rater_a[i] for i in idx], [rater_b[i] for i in idx])
        if ka is None:
            degenerate += 1
        else:
            vals.append(ka)
    if not vals:
        return {"low": None, "high": None, "point": point,
                "n_boot": n_boot, "degenerate_frac": 1.0}
    vals.sort()

    def _pct(p):
        pos = p * (len(vals) - 1)
        lo = int(pos)
        frac = pos - lo
        hi = min(lo + 1, len(vals) - 1)
        return vals[lo] + (vals[hi] - vals[lo]) * frac

    return {"low": round(_pct(alpha / 2), 4),
            "high": round(_pct(1 - alpha / 2), 4),
            "point": point, "n_boot": n_boot,
            "degenerate_frac": round(degenerate / n_boot, 4)}


# ---------------------------------------------------------------------------
# Fingerprints — change ANY of these and the old authorization is stale.
# ---------------------------------------------------------------------------
def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _prompt_templates() -> str:
    """The exact instruction TEXT sent to graders — reviewer panel prompt AND
    verifier prompt. Editing either prompt changes how a model judges, so it
    MUST invalidate the calibration. Built with fixed placeholder args so the
    hash tracks the template shape, not any one task's content."""
    from pipeline.review_prompt import build_prompt
    from pipeline import verify_client
    rev = build_prompt("<task>", "<label>", "<artifact>", "<shots>", "<transcript>")
    ver = verify_client._build_prompt("<task>", "<candidate>")
    return rev + "\x1e" + ver


def rubric_fingerprint() -> str:
    """Hash of the scoring rubric AND the grader prompt templates.

    Covers: dims + weights + S5 / anti-bias anchors (the rubric), PLUS the actual
    reviewer + verifier prompt templates. Changing the rubric (new S5/H1,
    reweighting) OR editing a grader prompt changes this -> recalibrate.
    """
    dims = ";".join(f"{c}:{w}" for c, _, w in DIMENSIONS)
    return _hash(dims + "|" + S5_ANCHORS + "|" + ANTI_BIAS
                 + "|" + _prompt_templates())


def model_fingerprint(members) -> str:
    """Hash of the model identity behind a subject: ordered member DESCRIPTORS.

    A descriptor may be a bare name ("review_deepseek") OR a fully-qualified
    "name@model@temp" string (what live_model_fingerprint builds). Swapping a
    model, bumping its version, or changing its temperature changes the string
    and therefore the fingerprint -> the old authorization goes stale.
    """
    return _hash("|".join(str(m) for m in members))


# Which env vars carry the live model version + temperature for each grader.
# (verify_client hardcodes temperature=0; review clients likewise deterministic.)
_MODEL_ENV = {
    "review_deepseek": ("DEEPSEEK_MODEL", "deepseek-v4-pro"),
    "review_glm": ("GLM_MODEL", "glm-5.2"),
    "review_claude": ("CLAUDE_MODEL", "claude-opus-4-8"),
    "review_gemini": ("GEMINI_MODEL", "gemini-2.5-pro"),
    "verify_deepseek": ("DEEPSEEK_MODEL", "deepseek-v4-pro"),
    "verify_glm": ("GLM_MODEL", "glm-5.2"),
    "verify_claude": ("CLAUDE_MODEL", "claude-opus-4-8"),
    "claude": ("CLAUDE_MODEL", "claude-opus-4-8"),
    "deepseek": ("DEEPSEEK_MODEL", "deepseek-v4-pro"),
    "glm": ("GLM_MODEL", "glm-5.2"),
}
_TEMP_ENV = {  # per-family temperature env override (all default deterministic 0)
    "review_deepseek": "DEEPSEEK_TEMPERATURE", "verify_deepseek": "DEEPSEEK_TEMPERATURE",
    "deepseek": "DEEPSEEK_TEMPERATURE",
    "review_glm": "GLM_TEMPERATURE", "verify_glm": "GLM_TEMPERATURE",
    "glm": "GLM_TEMPERATURE",
    "review_claude": "CLAUDE_TEMPERATURE", "verify_claude": "CLAUDE_TEMPERATURE",
    "claude": "CLAUDE_TEMPERATURE",
    "review_gemini": "GEMINI_TEMPERATURE",
}


def member_descriptor(name: str) -> str:
    """Resolve a grader member name to a fully-qualified "name@model@temp"
    descriptor from the LIVE env config. Unknown names pass through unchanged
    (so a caller can still pass hand-crafted descriptors in tests)."""
    import os
    if name not in _MODEL_ENV:
        return name
    env_key, default_model = _MODEL_ENV[name]
    model = os.environ.get(env_key, default_model)
    temp = os.environ.get(_TEMP_ENV.get(name, ""), "0")
    return f"{name}@{model}@{temp}"


def live_model_fingerprint(members) -> str:
    """model_fingerprint over the LIVE descriptors (name@model@temp) of members.

    Use this at calibration/check time so a silent model-version or temperature
    change is caught. Pass the SAME members to recalibrate + check_authorization.
    """
    return model_fingerprint([member_descriptor(str(m)) for m in members])


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


def reviewer_labels(samples=None, score_fn=None) -> tuple[list, list]:
    """(ai_labels, human_labels) of score buckets over the golden set.

    AI = bucket of the seam's sample_score; human = bucket of the expected
    sample_score. Both are derived through the SAME bucketing so the comparison
    is apples-to-apples.

    score_fn(sample) -> score-dict (must carry a 'sample_score' key). Defaults to
    golden.score_sample (the OFFLINE fixed-fake-panel twin — a replica, NOT the
    live panel). Pass a score_fn that runs the REAL production panel to get a
    genuine reviewer kappa (see outputs/agenda/recalibrate_reviewer_real.py).
    """
    samples = samples or golden.load_samples()
    score_fn = score_fn or golden.score_sample
    ai, human = [], []
    for s in samples:
        out = score_fn(s)
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
                verify_fn=None, samples=None, score_fn=None) -> dict:
    """Run the golden set, RECORD kappa + bias, and GRADE the subject.

    ADR-0011 v2: kappa now GATES the status via grade_authorization (0.4/0.2
    lenient tiers) instead of the v1 unconditional 'authorized'. We record BOTH
    the nominal kappa AND the ordinal WEIGHTED kappa (labels are ordered grades)
    plus a bootstrap confidence interval (the golden set is small — the CI shows
    how noisy the point estimate is). The grade is driven by the weighted kappa
    when available (it is the fairer number on ordinal labels), else the nominal.
    bias_profile stays RECORD-ONLY (never feeds back into a sample_score).
    Every recalibrate also APPENDS an immutable history row (drift trend).
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
    wk = weighted_cohens_kappa(ai, human)
    ci = kappa_confidence_interval(ai, human, weighted=wk["ordinal"])
    # Grade on the weighted kappa when the labels were ordinal; else nominal.
    grading_kappa = wk["kappa"] if wk["ordinal"] else k["kappa"]
    status = grade_authorization(grading_kappa)
    rec = {
        "subject": _subject_key(role, name), "role": role,
        "status": status,                       # v2: graded by kappa
        "kappa": k["kappa"], "agreement": k["agreement"],
        "weighted_kappa": wk["kappa"], "weights": wk["weights"],
        "grading_kappa": grading_kappa,
        "kappa_ci_low": ci["low"], "kappa_ci_high": ci["high"],
        "n_samples": k["n"],
        "model_fingerprint": live_model_fingerprint(members),
        "rubric_fingerprint": rubric_fingerprint(),
        "bias_profile": bias_profile(samples) if role == "reviewer" else {},
        "confusion": k["confusion"],
        "calibrated_ts": time.time(), "revoked_reason": None,
    }
    store.upsert_authorization(con, rec)
    store.append_authorization_history(con, rec)
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
    if live_model_fingerprint(members) != rec["model_fingerprint"]:
        reason = "model/version changed since calibration"
    elif rubric_fingerprint() != rec["rubric_fingerprint"]:
        reason = "rubric changed since calibration"
    elif anomaly:
        reason = "audit anomaly flagged"

    if reason:
        store.set_authorization_status(con, subject, "revoked", reason)
        return {"authorized": False, "status": "revoked", "reason": reason}
    return {"authorized": True, "status": "authorized", "reason": None}
