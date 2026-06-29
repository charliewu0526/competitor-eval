"""A2: evidence-capture adapter (production). 全自动采证，无需人工录屏。

The 6th seam adapter. Given the raw artifacts a run left behind, collect process
evidence in a STRICT priority order and honestly stamp where it came from:

    log  >  screenshot  >  recording  >  unavailable

Two iron rules from the issue (#20):
  1. 诚实标源: evidence_source is set to the HIGHEST-priority source that yielded
     real items. Nothing found -> 'unavailable'. 拿不到证据 NEVER masquerades as
     an empty success or a 0 — it is explicitly 'unavailable' (源于「拿不到」!=「差」).
  2. 证据只还原过程喂 S5，绝不判完成度: this adapter feeds the SUBJECTIVE S5
     experience axis only. for_completion is hard-wired False; objective
     completion is decided elsewhere (E2), never from these logs/frames.

Contract dict (shared by production EvidenceCollector + FakeEvidenceCollector):
  {"evidence_source": str,          # log|screenshot|recording|unavailable
   "items": [{"kind": str, "ref": str, "detail": str}],
   "has_process_evidence": bool,    # drops straight into aggregate.has_*  (S5)
   "for_completion": False}         # invariant — evidence never judges完成度

The output dict is shaped so it can be passed directly as the `ctx` to
aggregate.aggregate_subjective(): it carries both `evidence_source` and
`has_process_evidence`, the two keys S5 gating reads.
"""
from __future__ import annotations
import os
import pathlib

# Strict priority: structured logs first (best for reconstructing process),
# auto screenshots next, recording only as a black-box last resort.
PRIORITY = ("log", "screenshot", "recording")
UNAVAILABLE = "unavailable"

# Tie this adapter's vocabulary to the schema's EVIDENCE_SOURCE_VALUES.
from pipeline.schema import EVIDENCE_SOURCE_VALUES


def _exists(p) -> bool:
    try:
        return bool(p) and pathlib.Path(p).expanduser().exists()
    except OSError:
        return False


def _norm(paths) -> list[str]:
    """Normalize a None | str | iterable[str] into a flat list of strings."""
    if paths is None:
        return []
    if isinstance(paths, (str, os.PathLike)):
        return [str(paths)]
    return [str(p) for p in paths if p]


def _result(source: str, items: list[dict]) -> dict:
    """Build the shared contract dict. has_process_evidence is True iff a real
    source produced items; for_completion is the hard-wired False invariant."""
    if source not in EVIDENCE_SOURCE_VALUES:
        raise ValueError(f"evidence_source must be one of "
                         f"{EVIDENCE_SOURCE_VALUES}, got {source!r}")
    return {
        "evidence_source": source,
        "items": items,
        "has_process_evidence": source != UNAVAILABLE,
        "for_completion": False,            # invariant: 证据绝不判完成度
    }


class EvidenceCollector:
    """Production collector: probes real artifacts on disk in priority order.

    Each source is given as paths the harness recorded for a run. The FIRST
    priority tier that has at least one EXISTING artifact wins and sets
    evidence_source; lower tiers are ignored (we don't mix sources — the stamp
    must mean 'the best evidence we actually have').
    """

    def __init__(self, *, require_exists: bool = True):
        # require_exists=False lets callers register refs that aren't on this
        # box (e.g. a remote log URL) and still count them as present.
        self.require_exists = require_exists

    def _present(self, ref: str) -> bool:
        return _exists(ref) if self.require_exists else bool(ref)

    def collect(self, *, logs=None, screenshots=None, recording=None) -> dict:
        """Collect evidence for ONE run. Returns the shared contract dict.

        logs/screenshots/recording: a path, list of paths, or None. Probed in
        the fixed PRIORITY order; the highest tier with a present artifact wins.
        """
        tiers = {
            "log": _norm(logs),
            "screenshot": _norm(screenshots),
            "recording": _norm(recording),
        }
        for source in PRIORITY:
            present = [r for r in tiers[source] if self._present(r)]
            if present:
                kind = "log" if source == "log" else \
                    ("frame" if source == "screenshot" else "recording")
                items = [{"kind": kind, "ref": r,
                          "detail": f"{source} artifact"} for r in present]
                return _result(source, items)
        return _result(UNAVAILABLE, [])

    def collect_from_run(self, run) -> dict:
        """Convenience: pull evidence refs straight off a RunRecord-like object.

        Maps RunRecord fields onto the tiers:
          env_meta['log_path'] / env_meta['logs']  -> log
          screenshots                              -> screenshot
          env_meta['recording']                    -> recording
        transcript_excerpt alone is NOT a captured artifact here (E3 already
        infers process evidence from a transcript); this adapter is about
        externally-captured logs/frames/recordings.
        """
        env = getattr(run, "env_meta", None) or {}
        logs = env.get("log_path") or env.get("logs")
        screenshots = getattr(run, "screenshots", None)
        recording = env.get("recording")
        return self.collect(logs=logs, screenshots=screenshots,
                            recording=recording)
