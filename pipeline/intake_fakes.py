"""MR-2 (#38) in-memory fake twin of the intake seam — offline, no disk.

Per PRD 「适配器各自用假实现测」: the intake seam ships a production translator
AND an in-memory fake honoring the SAME contract (produces a valid RunRecord via
the SAME GATE derivation). The fake NEVER touches the disk or the price table:
its log-bundle "parse" returns fixed facts, its accountant is the offline A3
FakeCostAccountant. So the seam can't tell prod and fake apart, and the tracer
bullet runs with zero I/O.

It STILL obeys the iron rules:
  * GATE is derived from the registry, never self-reported (shared code path).
  * 拿不到日志 -> unavailable cost/evidence, never a fake 0-cost success.
"""
from __future__ import annotations

from pipeline.intake import (
    SubmissionTranslator, Submission, _coerce_facts, _empty_log_facts,
)
from pipeline.cost_fakes import FakeCostAccountant


class FakeLogBundleParser:
    """Offline twin: ignore the path, return fixed log facts.

    Defaults model a healthy self-reported bundle (a priced run with one log
    event). Pass source='unavailable' to model a black-box竞品 whose bundle
    yielded nothing readable — the seam then stamps cost/evidence unavailable.
    """

    def __init__(self, *, input_tokens: int = 1000, output_tokens: int = 500,
                 model_calls: int = 1, model: str | None = "fake-model",
                 cost_source: str = "self-report",
                 evidence_source: str = "log",
                 events: list | None = None):
        if cost_source == "unavailable":
            self._facts = _empty_log_facts()
        else:
            self._facts = _coerce_facts({
                "input_tokens": input_tokens, "output_tokens": output_tokens,
                "model_calls": model_calls, "model": model,
                "cost_source": cost_source, "evidence_source": evidence_source,
                "events": events if events is not None else ["run.start", "run.end"],
            })

    def parse(self, log_bundle_path=None) -> dict:
        return dict(self._facts)


def make_fake_translator(*, cost_source: str = "self-report",
                         cost_usd: float | None = 0.001) -> SubmissionTranslator:
    """A fully offline intake translator: fixed log facts + fake price table."""
    parser = FakeLogBundleParser(cost_source=cost_source)
    accountant = FakeCostAccountant(cost_source=cost_source, cost_usd=cost_usd)
    return SubmissionTranslator(log_parser=parser, accountant=accountant)


# Ready-made fixed Submission (the tracer bullet input): a WeChat-send run that
# a human verified succeeded on all three T1 assertions, self-reported success.
def make_fake_submission(product: str = "vio", task_id: str = "T1-wechat-send-001",
                         *, claimed_success: bool = True,
                         msg_received: bool = True, text_exact: bool = True,
                         no_collateral: bool = True) -> Submission:
    return Submission(
        assignment_id="ASG-tracer-001", product=product, task_id=task_id,
        artifact_path=None,
        log_bundle_path="fake://log-bundle/tracer",
        manual_assertions={"msg_received": msg_received,
                           "text_exact": text_exact,
                           "no_collateral": no_collateral},
        claimed_success=claimed_success, run_idx=1,
        transcript_excerpt="opened WeChat, sent the message.",
        competitor_version="fake-build-2026.07", tested_at=1_800_000_000.0)


__all__ = [
    "FakeLogBundleParser", "make_fake_translator", "make_fake_submission",
    "Submission",
]
