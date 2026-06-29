"""A2 in-memory fake evidence collector — the offline twin of evidence_client.

Per PRD 「适配器各自用假实现测」: every adapter ships a production impl AND an
in-memory fake honoring the SAME contract. The fake NEVER touches the disk — it
returns a fixed, deterministic evidence pack so tests stay stable + offline.

It STILL obeys the two iron rules:
  1. priority log>screenshot>recording>unavailable, honest evidence_source.
  2. for_completion is hard-wired False (证据绝不判完成度).

Contract (identical to evidence_client):
  {"evidence_source": str, "items": [...],
   "has_process_evidence": bool, "for_completion": False}
"""
from __future__ import annotations

from pipeline.evidence_client import PRIORITY, UNAVAILABLE, _result


class FakeEvidenceCollector:
    """Offline twin: returns a fixed evidence pack for the requested source,
    no disk I/O. `source` defaults to the top priority tier ('log')."""

    def __init__(self, source: str = "log", *, n_items: int = 1):
        self.source = source
        self.n_items = max(0, n_items)

    def collect(self, *, logs=None, screenshots=None, recording=None) -> dict:
        # The fake ignores real paths; it honors the configured source, but
        # still respects the 'unavailable yields no items' rule.
        if self.source == UNAVAILABLE or self.n_items == 0:
            return _result(UNAVAILABLE, [])
        kind = "log" if self.source == "log" else \
            ("frame" if self.source == "screenshot" else "recording")
        items = [{"kind": kind, "ref": f"fake://{self.source}/{i}",
                  "detail": f"fake {self.source} artifact"}
                 for i in range(self.n_items)]
        return _result(self.source, items)

    def collect_from_run(self, run) -> dict:
        return self.collect()


def fake_collect(source: str = "log", *, n_items: int = 1) -> dict:
    """One-shot offline twin of EvidenceCollector.collect()."""
    return FakeEvidenceCollector(source, n_items=n_items).collect()


# Ready-made fakes per tier + the empty/unavailable case.
fake_log = FakeEvidenceCollector("log")
fake_screenshot = FakeEvidenceCollector("screenshot")
fake_recording = FakeEvidenceCollector("recording")
fake_unavailable = FakeEvidenceCollector(UNAVAILABLE)

FAKE_COLLECTORS = {
    "log": fake_log,
    "screenshot": fake_screenshot,
    "recording": fake_recording,
    "unavailable": fake_unavailable,
}

__all__ = [
    "FakeEvidenceCollector", "fake_collect", "fake_log", "fake_screenshot",
    "fake_recording", "fake_unavailable", "FAKE_COLLECTORS", "PRIORITY",
]
