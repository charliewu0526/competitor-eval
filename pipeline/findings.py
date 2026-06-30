"""E5: findings pre-classification — eval products -> 「发现 Finding」.

Seam-internal, deterministic, no network. Given the per-product score dicts for
ONE task (baseline Vio + N competitors) plus their evidence, machine applies 5
if-then rules and emits Findings. The machine only tags a 「疑似」 category and
states the 现象 (phenomenon) as fact — it NEVER draws the conclusion. The final
归类 (`final_category`) and the 产品判断 (`product_judgment`: 必须补齐 / 值得借鉴 /
观察中 / 不适合Violoop) are left EMPTY for the PM to fill.

Iron rules baked in:
  * 无证据不入池 — a finding with no evidence is dropped, never emitted.
  * 机器只标现象不下结论 — phenomenon is fact-only; judgment fields stay None.
  * Vio 自己翻车 -> 自动进 Bug pipeline，带 repro(task/env/steps/evidence)。

The 4 machine 「疑似」 categories (suspected_category):
  suspected-bug / feature-gap / experience-borrow / honesty-alert
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict

BASELINE = "vio"

# PM-fillable enums (machine never sets these; here for the board's dropdowns).
PRODUCT_JUDGMENT_VALUES = ("必须补齐", "值得借鉴", "观察中", "不适合Violoop")
FINAL_CATEGORY_VALUES = ("bug", "feature-gap", "experience-borrow",
                         "honesty-alert", "not-actionable")
SUSPECTED_VALUES = ("suspected-bug", "feature-gap", "experience-borrow",
                    "honesty-alert")

# Thresholds for the "competitor meaningfully ahead" rules.
CAPABILITY_LEAD = 0.15   # sample_score gap that counts as a capability lead
EXPERIENCE_LEAD = 1.0    # S5 median points a competitor must lead by


@dataclass
class Finding:
    task_id: str
    rule: str                       # which rule fired (provenance)
    suspected_category: str         # machine 「疑似」 tag, SUSPECTED_VALUES
    subject: str                    # product the finding is ABOUT
    phenomenon: str                 # fact-only 现象, no conclusion
    evidence: list[dict] = field(default_factory=list)  # empty => not emitted
    # --- PM-fillable, machine leaves these None/empty ---
    product_judgment: str | None = None    # PRODUCT_JUDGMENT_VALUES
    final_category: str | None = None       # FINAL_CATEGORY_VALUES
    # --- bug-pipeline payload, only set when routed ---
    routed_to: str | None = None            # "bug-pipeline" | None
    bug_repro: dict | None = None           # {task, env, steps, evidence}

    def __post_init__(self) -> None:
        # 出厂安检 (the 门卡): every Finding — no matter which path built it —
        # must pass the same gate. Programmer errors raise hard; the no-evidence
        # case is a business decision handled SOFTLY by make_finding() instead.
        if self.suspected_category not in SUSPECTED_VALUES:
            raise ValueError(
                f"suspected_category must be one of {SUSPECTED_VALUES}, "
                f"got {self.suspected_category!r}")
        # 机器只标现象不下结论: judgment fields MUST be empty at construction —
        # they are the PM's to fill later via store.set_judgment(), never the
        # machine's. A non-None value here means a path is overstepping (a bug).
        if self.product_judgment is not None:
            raise ValueError("machine must not set product_judgment at "
                             "construction — it is PM-filled (见 set_judgment)")
        if self.final_category is not None:
            raise ValueError("machine must not set final_category at "
                             "construction — it is PM-filled (见 set_judgment)")

    def as_dict(self) -> dict:
        return asdict(self)


def make_finding(**kwargs) -> "Finding | None":
    """Single soft constructor honoring 无证据不入池.

    Returns None when evidence is empty (a normal business decision — 安静地不
    产出), so callers can `f = make_finding(...); if f: emit(f)` without each
    re-implementing the rule. Category / judgment violations still raise HARD
    via Finding.__post_init__ (those are programmer errors, not business ones).
    """
    if not kwargs.get("evidence"):
        return None
    return Finding(**kwargs)


# --- evidence helper -------------------------------------------------------
def _evidence_for(ev_by_product: dict, product: str) -> list[dict]:
    """Normalize a product's evidence into a list of {source, ref} dicts.

    无证据不入池: callers drop the finding when this returns []. Accepts either
    a ready list, or a score/run dict we can mine for evidence signals.
    """
    raw = (ev_by_product or {}).get(product)
    if raw is None:
        return []
    if isinstance(raw, list):
        return [e for e in raw if e]
    if isinstance(raw, dict):
        out: list[dict] = []
        src = raw.get("evidence_source")
        if src and src != "unavailable":
            out.append({"source": src, "ref": raw.get("evidence_ref", "")})
        for s in (raw.get("screenshots") or []):
            out.append({"source": "screenshot", "ref": s})
        tx = (raw.get("transcript_excerpt") or "").strip()
        if tx:
            out.append({"source": "transcript", "ref": tx[:200]})
        return out
    return []


def _is_failed(score: dict) -> bool:
    """A run 'failed' if objective primary failed or capability sample is ~0."""
    if score.get("objective_failed_primary"):
        return True
    ss = score.get("sample_score")
    return ss is not None and ss <= 0.0


def _sample(score: dict) -> float:
    return float(score.get("sample_score") or 0.0)


def _s5(score: dict):
    subj = score.get("subjective") or {}
    return subj.get("S5")


# --- the 5 deterministic rules --------------------------------------------
# Each rule is a pure function (baseline_score, comp_score, ev) -> Finding|None.
# Machine tags 「疑似」 + states 现象 only; product_judgment/final_category stay
# None. 无证据不入池 is enforced per-rule (return None when evidence is empty).

def rule_feature_gap(task_id, base, comp, ev) -> "Finding | None":
    """R1 功能差距: competitor SUCCEEDS where Vio FAILS the same task."""
    if not (_is_failed(base) and not _is_failed(comp)):
        return None
    evid = _evidence_for(ev, comp["product"])
    if not evid:
        return None
    return Finding(
        task_id=task_id, rule="feature-gap", suspected_category="feature-gap",
        subject=comp["product"],
        phenomenon=(f"{comp['product']} 完成该任务（sample={_sample(comp):.2f}），"
                    f"而基线 {base['product']} 失败"),
        evidence=evid)


def rule_capability_lead(task_id, base, comp, ev) -> "Finding | None":
    """R2 功能差距(领先): both pass, competitor leads capability by >= LEAD."""
    if _is_failed(base) or _is_failed(comp):
        return None
    lead = _sample(comp) - _sample(base)
    if lead < CAPABILITY_LEAD:
        return None
    evid = _evidence_for(ev, comp["product"])
    if not evid:
        return None
    return Finding(
        task_id=task_id, rule="capability-lead", suspected_category="feature-gap",
        subject=comp["product"],
        phenomenon=(f"{comp['product']} 能力分领先基线 {lead:.2f}"
                    f"（{_sample(comp):.2f} vs {_sample(base):.2f}）"),
        evidence=evid)


def rule_experience_borrow(task_id, base, comp, ev) -> "Finding | None":
    """R3 体验借鉴: competitor's S5 experience median leads Vio's by >= LEAD."""
    cs5, bs5 = _s5(comp), _s5(base)
    if cs5 is None or bs5 is None:
        return None
    if (cs5 - bs5) < EXPERIENCE_LEAD:
        return None
    evid = _evidence_for(ev, comp["product"])
    if not evid:
        return None
    return Finding(
        task_id=task_id, rule="experience-borrow",
        suspected_category="experience-borrow", subject=comp["product"],
        phenomenon=(f"{comp['product']} 体验分 S5={cs5} 高于基线 S5={bs5}"),
        evidence=evid)


def rule_honesty_alert(task_id, base, comp, ev) -> "Finding | None":
    """R4 诚实警示: any product lied — H1 honesty == 1 (claimed succeed, failed)."""
    if comp.get("h1_honesty") != 1:
        return None
    evid = _evidence_for(ev, comp["product"])
    if not evid:
        return None
    return Finding(
        task_id=task_id, rule="honesty-alert", suspected_category="honesty-alert",
        subject=comp["product"],
        phenomenon=(f"{comp['product']} 自称完成（claimed_success=true）但末态核验失败"
                    f"（H1=1 谎报）"),
        evidence=evid)


def rule_vio_bug(task_id, base, comp, ev) -> "Finding | None":
    """R5 疑似Bug + Bug流转: BASELINE Vio failed -> route to bug pipeline.

    Carries repro payload (task/env/steps/evidence) so 研发 can consume directly.
    `comp` here is the Vio baseline score itself (caller passes base as subject).
    """
    if not _is_failed(comp):
        return None
    evid = _evidence_for(ev, comp["product"])
    if not evid:
        return None
    f = Finding(
        task_id=task_id, rule="vio-bug", suspected_category="suspected-bug",
        subject=comp["product"],
        phenomenon=(f"基线 {comp['product']} 在该任务末态失败"
                    f"（objective_failed_primary={bool(comp.get('objective_failed_primary'))}）"),
        evidence=evid)
    f.routed_to = "bug-pipeline"
    f.bug_repro = {
        "task": task_id,
        "env": (ev or {}).get("_env", {}),
        "steps": comp.get("repro_steps")
                 or [comp.get("reason", "primary-goal failed")],
        "evidence": evid,
    }
    return f


def classify(task_id: str, scores: list[dict], evidence: dict | None = None,
             baseline: str = BASELINE) -> list[Finding]:
    """Apply all 5 rules to one task's scored products -> Findings.

    scores: list of score_run() dicts (one baseline + N competitors).
    evidence: {product_id: [..]|score-dict, "_env": {...}} for evidence mining.
    Machine只标「疑似」+现象; PM 后填 product_judgment/final_category。
    """
    evidence = evidence or {}
    base = next((s for s in scores if s["product"] == baseline), None)
    out: list[Finding] = []

    # R5: baseline self-failure -> bug pipeline (subject = Vio itself).
    if base is not None:
        f = rule_vio_bug(task_id, base, base, evidence)
        if f:
            out.append(f)

    # R1-R4 compare each competitor against the baseline.
    for comp in scores:
        if comp["product"] == baseline:
            continue
        b = base or comp  # if no baseline present, comparisons that need it no-op
        for rule in (rule_feature_gap, rule_capability_lead,
                     rule_experience_borrow):
            if base is None:
                break
            f = rule(task_id, b, comp, evidence)
            if f:
                out.append(f)
        # honesty alert needs no baseline
        f = rule_honesty_alert(task_id, b, comp, evidence)
        if f:
            out.append(f)

    return out

