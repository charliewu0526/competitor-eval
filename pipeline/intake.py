"""MR-2 (#38): the intake seam — Submission → RunRecord.

This is the ONE new core seam the multi-runner platform (PRD-0003 #36) adds.
Everything upstream (Web / upload / auth / claim) only has to hand a Submission
to `translate`; everything downstream (GATE → objective → blind panel → H1 →
findings → leaderboard) is the EXISTING scoring core, consumed一字不改.

Iron rules carried across the seam (PRD 立身之本):
  1. GATE is DERIVED via gate.gate_for(competitor, task) from the F2 registry ×
     the F1 task requirement — NEVER trusted from the submission's self-report
     (an intern/竞品 can't self-declare it reached the target).
  2. Machine-verifiable objective assertions (file exists / value equals / a log
     event) are auto-judged; only the human-ticked assertions (「微信消息真发出
     了」) are read from the submission. Both flow through the same
     objective.run_assertions — the split is just which ctx keys each populates.
  3. cost_* comes from PARSING the mandatory log bundle (token/call/timeline),
     folded to $ by the A3 price table — 拿不到 => unavailable, never a fake 0.
  4. claimed_success rides through untouched to feed the H1 honesty axis (E4).
  5. competitor_version + tested_at (ADR-0017 新鲜度) travel onto the RunRecord.

Same shape as the other 5 seam adapters: a production translator that touches
disk + the real price table, and an in-memory fake twin honoring the SAME
contract (a valid RunRecord with the same field set + identical GATE derivation),
so tests stay offline and the seam can't tell them apart.
"""
from __future__ import annotations

import json
import pathlib
import time
from dataclasses import dataclass, field

from pipeline.schema import RunRecord, COST_SOURCE_VALUES, EVIDENCE_SOURCE_VALUES
from pipeline import objective as O
from pipeline.gate import gate_for
from pipeline.cost_client import CostAccountant


# --- the seam INPUT: a Submission (one product, one run of one Assignment) -----
@dataclass
class Submission:
    """What an intern uploads for ONE product on one comparison task.

    Files (artifact + log bundle) stay on disk (ADR-0019); we carry path refs.
    manual_assertions = the human-ticked objective flags a script can't read
    (ctx keys the task's manual_check assertions consume). claimed_success feeds
    H1. competitor_version / tested_at are human-filled in the MVP.
    """
    assignment_id: str
    product: str
    task_id: str
    artifact_path: str | None = None
    log_bundle_path: str | None = None
    manual_assertions: dict = field(default_factory=dict)
    claimed_success: bool | None = None
    run_idx: int = 1
    transcript_excerpt: str = ""
    competitor_version: str | None = None
    tested_at: float | None = None

    @classmethod
    def from_store_row(cls, row: dict) -> "Submission":
        """Adapt a store.submissions row (manual_assertions already parsed)."""
        return cls(
            assignment_id=row["assignment_id"], product=row["product"],
            task_id=row.get("task_id", ""),
            artifact_path=row.get("artifact_path"),
            log_bundle_path=row.get("log_bundle_path"),
            manual_assertions=row.get("manual_assertions") or {},
            claimed_success=row.get("claimed_success"),
            run_idx=row.get("run_idx", 1),
            transcript_excerpt=row.get("transcript_excerpt", ""),
            competitor_version=row.get("competitor_version"),
            tested_at=row.get("tested_at"))


# --- log-bundle parsing: the disk-touching part real/fake differ on -----------
# The parsed facts contract (both parsers return this shape):
#   {"cost_input_tokens", "cost_output_tokens", "cost_model_calls",
#    "model", "cost_source", "evidence_source", "events": [...]}
LOG_FACT_KEYS = {"cost_input_tokens", "cost_output_tokens", "cost_model_calls",
                 "model", "cost_source", "evidence_source", "events"}


def _empty_log_facts() -> dict:
    """No readable bundle -> honest unavailable (never a fake 0-cost success)."""
    return {"cost_input_tokens": 0, "cost_output_tokens": 0,
            "cost_model_calls": 0, "model": None,
            "cost_source": "unavailable", "evidence_source": "unavailable",
            "events": []}


def _coerce_facts(raw: dict) -> dict:
    """Validate + normalize a raw log dict into the LOG_FACT_KEYS contract."""
    src = raw.get("cost_source", "self-report")
    if src not in COST_SOURCE_VALUES:
        raise ValueError(f"cost_source must be one of {COST_SOURCE_VALUES}, got {src!r}")
    ev = raw.get("evidence_source", "log")
    if ev not in EVIDENCE_SOURCE_VALUES:
        raise ValueError(f"evidence_source must be one of {EVIDENCE_SOURCE_VALUES}, got {ev!r}")
    return {
        "cost_input_tokens": int(raw.get("input_tokens", raw.get("cost_input_tokens", 0))),
        "cost_output_tokens": int(raw.get("output_tokens", raw.get("cost_output_tokens", 0))),
        "cost_model_calls": int(raw.get("model_calls", raw.get("cost_model_calls", 0))),
        "model": raw.get("model"),
        "cost_source": src,
        "evidence_source": ev,
        "events": list(raw.get("events", raw.get("timeline", []))),
    }


class LogBundleParser:
    """Production parser: read the mandatory log bundle (a JSON manifest) off disk.

    A missing / unreadable bundle yields honest 'unavailable' facts rather than
    inventing a free run — 拿不到 != 免费成功. (The Web layer already refused the
    submission if no bundle was uploaded; this is defence-in-depth.)
    """

    def parse(self, log_bundle_path: str | None) -> dict:
        if not log_bundle_path:
            return _empty_log_facts()
        p = pathlib.Path(log_bundle_path).expanduser()
        if not p.exists():
            return _empty_log_facts()
        try:
            raw = json.loads(p.read_text())
        except (OSError, ValueError):
            return _empty_log_facts()
        return _coerce_facts(raw)


def _build_ctx(submission: Submission, log_facts: dict) -> dict:
    """Merge the objective-assertion ctx: human ticks + machine-readable refs.

    Human-ticked flags (manual_check) live in submission.manual_assertions.
    Machine assertions read artifact_path (file_exists), any ctx values the
    intern recorded, and log events (「日志有无某事件」).
    """
    ctx = dict(submission.manual_assertions or {})
    ctx.setdefault("artifact_path", submission.artifact_path)
    ctx.setdefault("log_events", log_facts.get("events", []))
    return ctx


class SubmissionTranslator:
    """Production seam: Submission (+ its on-disk log bundle) -> RunRecord.

    Injectable log_parser + accountant default to the real disk/price-table
    impls; the fake twin swaps them for offline fixtures (see intake_fakes).
    """

    def __init__(self, *, log_parser=None, accountant=None):
        self.log_parser = log_parser or LogBundleParser()
        self.accountant = accountant or CostAccountant()

    def translate(self, submission: Submission, task_meta, registry) -> RunRecord:
        """Translate ONE Submission into a scoring-core-ready RunRecord.

        task_meta: duck-typed carrier of .task_spec (F1 TaskSpec) + .assertions
                   (callable -> list[objective.Assertion]). suite.LoadedTask fits.
        registry:  F2 registry (real or fake) — used ONLY to derive GATE + look
                   up competitor version; the submission never self-declares gate.
        """
        spec = task_meta.task_spec
        assertions = task_meta.assertions() if callable(task_meta.assertions) else []

        # 1. GATE — derived, never self-reported. Unregistered product => the
        #    seam refuses to fabricate a gate (can't fairly place an unknown).
        try:
            competitor = registry.get(submission.product)
        except KeyError as e:
            raise ValueError(
                f"product {submission.product!r} not in registry — cannot derive "
                f"GATE for an unregistered competitor") from e
        gate = gate_for(competitor, spec)

        # 2. Objective assertions — machine + human, one runner, split by ctx.
        log_facts = self.log_parser.parse(submission.log_bundle_path)
        ctx = _build_ctx(submission, log_facts)
        obj = O.run_assertions(assertions, ctx)

        # 3. Cost — folded from the PARSED log facts via the A3 price table.
        cost = self.accountant.account(
            model=log_facts["model"],
            input_tokens=log_facts["cost_input_tokens"],
            output_tokens=log_facts["cost_output_tokens"],
            model_calls=log_facts["cost_model_calls"],
            cost_source=log_facts["cost_source"])

        # 4. Freshness (ADR-0017): version from submission, else competitor build.
        version = submission.competitor_version
        tested_at = submission.tested_at if submission.tested_at is not None \
            else (submission.submitted_ts if hasattr(submission, "submitted_ts")
                  else time.time())

        return RunRecord(
            task_id=spec.task_id, product=submission.product,
            run_idx=submission.run_idx, gate=gate,
            objective_passed=obj["passed"], objective_total=obj["total"],
            objective_failed_primary=obj["failed_primary"],
            artifact_path=submission.artifact_path,
            transcript_excerpt=submission.transcript_excerpt,
            cost_input_tokens=cost["cost_input_tokens"],
            cost_output_tokens=cost["cost_output_tokens"],
            cost_model_calls=cost["cost_model_calls"],
            cost_usd=cost["cost_usd"], cost_source=cost["cost_source"],
            evidence_source=log_facts["evidence_source"],
            claimed_success=submission.claimed_success,
            competitor_version=version, tested_at=tested_at)


# --- module-level convenience matching the AC signature ----------------------
_DEFAULT = SubmissionTranslator()


def translate(submission: Submission, task_meta, registry) -> RunRecord:
    """AC signature: translate(submission, task_meta, registry) -> RunRecord.

    Uses the default production translator (real disk parse + real price table).
    """
    return _DEFAULT.translate(submission, task_meta, registry)
