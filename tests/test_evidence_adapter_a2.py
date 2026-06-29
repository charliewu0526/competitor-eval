"""A2 (#20): evidence-capture adapter — log > screenshot > recording > unavailable.

Run: python -m unittest tests.test_evidence_adapter_a2 -v

Acceptance (issue #20), all OFFLINE:
  - production: collect by priority log>screenshot>recording, stamp evidence_source
  - in-memory fake: returns fixed evidence pack + source
  - both impls satisfy the SAME contract
  - 拿不到证据 -> evidence_source='unavailable' (not faked as empty/0)
  - S5 needs process evidence: adapter output drops into aggregate gating
"""
from __future__ import annotations
import os
import tempfile
import pathlib
import unittest

from pipeline import evidence_client as EC
from pipeline import evidence_fakes as EF
from pipeline import aggregate as AG
from pipeline.schema import RunRecord, EVIDENCE_SOURCE_VALUES


CONTRACT_KEYS = {"evidence_source", "items", "has_process_evidence",
                 "for_completion"}


def _touch(d, name):
    p = pathlib.Path(d) / name
    p.write_text("x")
    return str(p)


# =============================================================================
# Production priority + honest source stamping.
# =============================================================================
class ProductionPriority(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.col = EC.EvidenceCollector()

    def test_log_wins_over_screenshot_and_recording(self):
        log = _touch(self.d, "run.log")
        shot = _touch(self.d, "f1.png")
        rec = _touch(self.d, "cap.mov")
        out = self.col.collect(logs=log, screenshots=shot, recording=rec)
        self.assertEqual(out["evidence_source"], "log")
        self.assertTrue(out["has_process_evidence"])
        self.assertEqual(out["items"][0]["kind"], "log")

    def test_screenshot_wins_when_no_log(self):
        shot = _touch(self.d, "f1.png")
        rec = _touch(self.d, "cap.mov")
        out = self.col.collect(screenshots=shot, recording=rec)
        self.assertEqual(out["evidence_source"], "screenshot")
        self.assertEqual(out["items"][0]["kind"], "frame")

    def test_recording_is_last_resort(self):
        rec = _touch(self.d, "cap.mov")
        out = self.col.collect(recording=rec)
        self.assertEqual(out["evidence_source"], "recording")

    def test_missing_files_ignored_falls_through(self):
        # paths given but none exist -> unavailable (not a false 'log' stamp).
        out = self.col.collect(logs="/nope/a.log", screenshots="/nope/b.png")
        self.assertEqual(out["evidence_source"], "unavailable")
        self.assertFalse(out["has_process_evidence"])
        self.assertEqual(out["items"], [])

    def test_multiple_logs_all_collected(self):
        l1 = _touch(self.d, "a.log")
        l2 = _touch(self.d, "b.log")
        out = self.col.collect(logs=[l1, l2])
        self.assertEqual(out["evidence_source"], "log")
        self.assertEqual(len(out["items"]), 2)

    def test_require_exists_false_counts_remote_refs(self):
        col = EC.EvidenceCollector(require_exists=False)
        out = col.collect(logs="https://logs.example/run/1")
        self.assertEqual(out["evidence_source"], "log")
        self.assertTrue(out["has_process_evidence"])


# =============================================================================
# 拿不到证据 -> unavailable, never faked.
# =============================================================================
class Unavailable(unittest.TestCase):
    def test_nothing_given_is_unavailable(self):
        out = EC.EvidenceCollector().collect()
        self.assertEqual(out["evidence_source"], "unavailable")
        self.assertFalse(out["has_process_evidence"])
        self.assertEqual(out["items"], [])

    def test_unavailable_source_is_a_valid_schema_value(self):
        out = EC.EvidenceCollector().collect()
        self.assertIn(out["evidence_source"], EVIDENCE_SOURCE_VALUES)


# =============================================================================
# Evidence NEVER judges完成度.
# =============================================================================
class NeverForCompletion(unittest.TestCase):
    def test_for_completion_always_false(self):
        d = tempfile.mkdtemp()
        log = _touch(d, "run.log")
        for out in (EC.EvidenceCollector().collect(logs=log),
                    EC.EvidenceCollector().collect(),
                    EF.fake_log.collect(),
                    EF.fake_unavailable.collect()):
            self.assertIs(out["for_completion"], False)


# =============================================================================
# In-memory fake: fixed pack + same contract.
# =============================================================================
class FakeContract(unittest.TestCase):
    def test_fake_returns_fixed_pack_per_source(self):
        for src in ("log", "screenshot", "recording"):
            out = EF.FakeEvidenceCollector(src).collect()
            self.assertEqual(out["evidence_source"], src)
            self.assertTrue(out["has_process_evidence"])
            self.assertEqual(len(out["items"]), 1)

    def test_fake_unavailable_has_no_items(self):
        out = EF.fake_unavailable.collect()
        self.assertEqual(out["evidence_source"], "unavailable")
        self.assertEqual(out["items"], [])
        self.assertFalse(out["has_process_evidence"])

    def test_fake_is_deterministic(self):
        a = EF.fake_log.collect()
        b = EF.fake_log.collect()
        self.assertEqual(a, b)

    def test_both_impls_same_contract_keys(self):
        d = tempfile.mkdtemp()
        log = _touch(d, "run.log")
        prod = EC.EvidenceCollector().collect(logs=log)
        fake = EF.fake_log.collect()
        self.assertEqual(set(prod), CONTRACT_KEYS)
        self.assertEqual(set(fake), CONTRACT_KEYS)
        # same source => structurally interchangeable for the seam
        self.assertEqual(prod["evidence_source"], fake["evidence_source"])
        self.assertEqual(prod["has_process_evidence"],
                         fake["has_process_evidence"])

    def test_collect_from_run_maps_fields(self):
        d = tempfile.mkdtemp()
        log = _touch(d, "run.log")
        rr = RunRecord(task_id="T1", product="vio", run_idx=1,
                       gate="native-operable", env_meta={"log_path": log})
        out = EC.EvidenceCollector().collect_from_run(rr)
        self.assertEqual(out["evidence_source"], "log")


# =============================================================================
# S5 gating: adapter output drops straight into aggregate.has_process_evidence.
# =============================================================================
class FeedsS5Gate(unittest.TestCase):
    def _panel(self):
        return [
            {"panelist": "deepseek", "S5": 4,
             "justifications": {"S5": "smooth flow"}},
            {"panelist": "gemini", "S5": 4,
             "justifications": {"S5": "few detours"}},
        ]

    def test_evidence_present_unlocks_s5(self):
        d = tempfile.mkdtemp()
        log = _touch(d, "run.log")
        ctx = EC.EvidenceCollector().collect(logs=log)
        self.assertTrue(AG.has_process_evidence(ctx))
        agg = AG.aggregate_subjective(self._panel(), ctx)
        self.assertIsNotNone(agg["medians"]["S5"])

    def test_unavailable_keeps_s5_none(self):
        ctx = EC.EvidenceCollector().collect()           # unavailable
        self.assertFalse(AG.has_process_evidence(ctx))
        agg = AG.aggregate_subjective(self._panel(), ctx)
        self.assertIsNone(agg["medians"]["S5"])           # 拿不到 != 差


if __name__ == "__main__":
    unittest.main()
