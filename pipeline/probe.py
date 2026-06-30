"""X2: capability-probe — the SECOND eval path (PM-triggered).

Path 1 (task-exam) asks "can it do the task?". Path 2 (capability-probe) asks:
"on ONE 卖点 dimension (e.g. token 成本), how does Vio stack up against a rival's
headline feature?" — a targeted head-to-head, not a full rubric.

A probe names ONE 卖点 dimension; we read that metric straight off each product's
RunRecord (the SAME seam input — A3 cost fields), decide a winner per the
dimension's direction, and emit a Finding that flows into the SAME SQLite store +
board as path 1 (no parallel universe).

For is_open_source rivals, a 代码机理分析 (CodeAnalysis) attaches to the finding as
an evidence entry — so a 「值得借鉴 / 必须补齐」 judgment rests on HOW the rival does
it (机理证据), not just "人家行". The machine still only states 现象 + 疑似类别;
product_judgment / final_category stay None for the PM (E5 iron rule preserved).
"""
from __future__ import annotations
from dataclasses import dataclass, field

from pipeline.findings import Finding
from pipeline import store as STORE

LOWER_IS_BETTER = "lower-is-better"
HIGHER_IS_BETTER = "higher-is-better"


class ProbeError(ValueError):
    """A probe spec / artifact violates the X2 contract."""


@dataclass(frozen=True)
class Dimension:
    key: str
    label: str           # human 卖点 label (shown in phenomenon)
    attr: str            # RunRecord attribute to read ("_total_tokens" = synthetic)
    direction: str       # LOWER_IS_BETTER | HIGHER_IS_BETTER
    unit: str


# The 卖点 dimensions a probe can target. All resolve to A3 cost fields already on
# the RunRecord, so the probe reuses the seam input — no new measurement plumbing.
DIMENSIONS: dict[str, Dimension] = {
    "token-cost":  Dimension("token-cost", "token 成本(总 token)", "_total_tokens",
                             LOWER_IS_BETTER, "tok"),
    "model-calls": Dimension("model-calls", "架构效率(模型来回轮数)", "cost_model_calls",
                             LOWER_IS_BETTER, "calls"),
    "cost-usd":    Dimension("cost-usd", "商业成本", "cost_usd",
                             LOWER_IS_BETTER, "USD"),
    "capability":  Dimension("capability", "能力分(objective_ratio)", "objective_ratio",
                             HIGHER_IS_BETTER, "ratio"),
}

_COST_DIMS = ("token-cost", "model-calls", "cost-usd")


@dataclass
class CodeAnalysis:
    """代码机理分析: HOW an open-source rival achieves its 卖点 — 机理证据.

    Only valid for is_open_source rivals (caller enforces). Attaches to a probe
    Finding as an evidence entry so a 「值得借鉴/必须补齐」 judgment rests on the
    mechanism, not on the bare result. `mechanism` is the fact-only finding;
    analyst/source make it auditable (who looked, at which code).
    """
    product: str
    repo: str
    mechanism: str                       # 现象级机理描述 (fact, no judgment)
    refs: list[str] = field(default_factory=list)   # file/commit/url anchors
    analyst: str = ""                    # who did the analysis (provenance)

    def __post_init__(self) -> None:
        if not self.mechanism.strip():
            raise ProbeError("CodeAnalysis.mechanism must be non-empty (机理证据)")

    def as_evidence(self) -> dict:
        return {"source": "code-analysis", "product": self.product,
                "repo": self.repo, "mechanism": self.mechanism,
                "refs": list(self.refs), "analyst": self.analyst}


@dataclass
class ProbeSpec:
    """A capability-probe: ONE 卖点 dimension, baseline vs ONE rival.

    kind is fixed to capability-probe; PM triggers it manually (v1). The probe
    does not run a full rubric — it reads the named dimension's metric off each
    side's RunRecord and decides a winner by the dimension's direction.
    """
    probe_id: str
    dimension: str                       # key into DIMENSIONS
    rival: str                           # competitor product id
    baseline: str = "vio"
    title: str = ""

    def __post_init__(self) -> None:
        if self.dimension not in DIMENSIONS:
            raise ProbeError(
                f"unknown dimension {self.dimension!r}; "
                f"valid: {sorted(DIMENSIONS)}")
        if self.rival == self.baseline:
            raise ProbeError("probe rival must differ from baseline")

    @property
    def dim(self) -> Dimension:
        return DIMENSIONS[self.dimension]


def _metric(run, dim: Dimension):
    """Read the dimension's metric off a RunRecord. token-cost sums in+out."""
    if dim.attr == "_total_tokens":
        return (getattr(run, "cost_input_tokens", 0) or 0) + \
               (getattr(run, "cost_output_tokens", 0) or 0)
    return getattr(run, dim.attr, None)


def _better(a, b, direction: str):
    """Which of metrics a/b wins on this dimension? Return -1=a, 1=b, 0=tie/NA."""
    if a is None or b is None:
        return 0
    if a == b:
        return 0
    if direction == LOWER_IS_BETTER:
        return -1 if a < b else 1
    return -1 if a > b else 1


@dataclass
class ProbeResult:
    probe_id: str
    dimension: str
    baseline: str
    rival: str
    baseline_metric: object
    rival_metric: object
    winner: str | None          # product id, or None if tie / not comparable
    unit: str
    finding: "Finding | None"   # None when rival did NOT win (no gap => no 发现)

    def as_dict(self) -> dict:
        return {"probe_id": self.probe_id, "dimension": self.dimension,
                "baseline": self.baseline, "rival": self.rival,
                "baseline_metric": self.baseline_metric,
                "rival_metric": self.rival_metric, "winner": self.winner,
                "unit": self.unit,
                "finding": self.finding.as_dict() if self.finding else None}


def run_probe(spec: ProbeSpec, base_run, rival_run,
              code_analysis: "CodeAnalysis | None" = None,
              rival_is_open_source: bool = False) -> ProbeResult:
    """Run ONE capability-probe through the seam: two RunRecords -> ProbeResult.

    Reads the 卖点 metric off each RunRecord, picks a winner by direction, and
    emits a Finding (machine states 现象 + 疑似类别; PM fills the judgment). When
    the rival is open source and a CodeAnalysis is supplied, it rides along as a
    `code-analysis` evidence entry — the 机理证据 behind any 借鉴/补齐 verdict.
    """
    dim = spec.dim
    bm, rm = _metric(base_run, dim), _metric(rival_run, dim)
    cmp = _better(bm, rm, dim.direction)
    winner = (spec.baseline if cmp < 0 else
              spec.rival if cmp > 0 else None)

    # Evidence: each side's run signals, plus optional 代码机理分析 for OSS rivals.
    evidence: list[dict] = [
        {"source": "probe-metric", "product": spec.baseline,
         "dimension": dim.key, "value": bm, "unit": dim.unit},
        {"source": "probe-metric", "product": spec.rival,
         "dimension": dim.key, "value": rm, "unit": dim.unit},
    ]
    if code_analysis is not None:
        if not rival_is_open_source:
            raise ProbeError(
                f"code analysis attached but rival {spec.rival!r} is not "
                f"is_open_source — 机理分析 only valid for open-source rivals")
        if code_analysis.product != spec.rival:
            raise ProbeError("code_analysis.product must be the probed rival")
        evidence.append(code_analysis.as_evidence())

    # A 发现 is only emitted when the RIVAL wins the 卖点 dimension — that's the
    # feature-gap the PM should weigh. When Vio wins (or it's a tie) there is no
    # gap, so NO Finding is produced (the metrics still live in runs/scores for
    # the board). Emitting a finding on a Vio win and mislabeling it
    # "experience-borrow" (=值得借鉴) would pollute the PM's judgment.
    rival_won = winner == spec.rival
    finding = None
    if rival_won:
        mech = (f" 机理: {code_analysis.mechanism}" if code_analysis else "")
        phen = (f"[capability-probe:{dim.label}] {spec.rival} {bm_fmt(rm, dim)} "
                f"vs 基线 {spec.baseline} {bm_fmt(bm, dim)} — "
                f"{spec.rival} 领先.{mech}")
        finding = Finding(
            task_id=spec.probe_id, rule="capability-probe",
            suspected_category="feature-gap", subject=spec.rival,
            phenomenon=phen, evidence=evidence)

    return ProbeResult(
        probe_id=spec.probe_id, dimension=dim.key, baseline=spec.baseline,
        rival=spec.rival, baseline_metric=bm, rival_metric=rm,
        winner=winner, unit=dim.unit, finding=finding)


def bm_fmt(v, dim: Dimension) -> str:
    if v is None:
        return "(N/A)"
    return f"{v}{dim.unit}"


def persist_probe(con, spec: ProbeSpec, base_run, rival_run,
                  result: ProbeResult) -> int:
    """Land a probe in the SAME SQLite store as path 1 (no parallel universe).

    Persists both RunRecords (seam input) and the probe Finding. The probe's
    Finding upserts on (task_id=probe_id, rule='capability-probe', subject) so a
    re-run updates machine fields but PRESERVES the PM's product_judgment /
    final_category (store.upsert_finding's COALESCE rule). Returns finding id.
    """
    STORE.upsert_run(con, base_run)
    STORE.upsert_run(con, rival_run)
    return STORE.upsert_finding(con, result.finding)


def probe_findings(con) -> list[dict]:
    """Read back just the capability-probe findings from the store."""
    return [dict(r) for r in con.execute(
        "SELECT * FROM findings WHERE rule='capability-probe' ORDER BY id")]
