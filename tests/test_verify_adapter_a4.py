"""A4 (#... ): AI-verification adapter — 出题≠核验，不自评，pass->自动入库.

Run: python -m unittest tests.test_verify_adapter_a4 -v

Acceptance (issue A4), all OFFLINE — no network:
  - production verifier clients return the contract dict (via missing-key DRY-RUN
    stub path; real API calls are NOT made in tests)
  - in-memory fake verifier returns a fixed verdict, no network
  - BOTH impls satisfy the SAME contract (shared assertion over fake + stub-prod)
  - generator-family == verifier-family is REJECTED (强制不自评)
  - a PASS result carries auto_ingest=True (自动入库，无人工签字闸门);
    a FAIL carries auto_ingest=False
"""
from __future__ import annotations
import os
import unittest

from pipeline import verify_client as VC
from pipeline import verify_fakes as VF


def _assert_contract(tc: unittest.TestCase, r: dict):
    """The shared adapter contract every verifier (prod or fake) must satisfy."""
    tc.assertIn("verifier", r)
    tc.assertIsInstance(r["verifier"], str)
    tc.assertIn("model_family", r)
    tc.assertIn("dry_run", r)
    tc.assertIn("passed", r)
    tc.assertIsInstance(r["passed"], bool)
    tc.assertIn("reason", r)
    tc.assertIsInstance(r["reason"], str)
    tc.assertIn("auto_ingest", r)
    tc.assertIsInstance(r["auto_ingest"], bool)
    # the core invariant linking the two: ingest iff passed
    tc.assertEqual(r["auto_ingest"], r["passed"])


# =============================================================================
# 强制不自评 — verifier family must differ from generator family.
# =============================================================================
class NoSelfEval(unittest.TestCase):
    def test_family_resolution(self):
        self.assertEqual(VC.family_of("deepseek"), "deepseek")
        self.assertEqual(VC.family_of("glm"), "zhipu")
        self.assertEqual(VC.family_of("claude"), "anthropic")
        # unknown verifier resolves to itself -> still can't self-eval its twin
        self.assertEqual(VC.family_of("mystery"), "mystery")

    def test_same_family_rejected_before_network(self):
        with self.assertRaises(VC.SelfEvalError):
            VC.assert_not_self_eval("deepseek", "deepseek")

    def test_same_family_rejected_via_verify_entrypoint(self):
        # production verify() must refuse a self-eval up front (no network).
        with self.assertRaises(VC.SelfEvalError):
            VC.verify("task", "candidate", generator="claude", verifier="claude")

    def test_fake_also_enforces_no_self_eval(self):
        # the fake honors the SAME rule — seam can't tell them apart on it.
        with self.assertRaises(VC.SelfEvalError):
            VF.fake_verify("t", "c", generator="glm", verifier="glm")

    def test_different_family_allowed(self):
        # generator deepseek, verifier claude -> fine
        r = VF.fake_verify("t", "c", generator="deepseek", verifier="claude")
        self.assertEqual(r["verifier"], "claude")
        self.assertTrue(r["passed"])


# =============================================================================
# Production clients — exercised in DRY-RUN (no keys) so no network is hit.
# =============================================================================
class ProductionStubContract(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.pop(k, None) for k in (
            "DEEPSEEK_API_KEY", "ZHIPU_API_KEY", "GLM_API_KEY",
            "CLAUDE_API_KEY", "ANTHROPIC_API_KEY")}

    def tearDown(self):
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v

    def test_deepseek_stub_contract(self):
        r = VC.verify_deepseek("p")
        self.assertEqual(r["verifier"], "deepseek")
        self.assertTrue(r["dry_run"])
        _assert_contract(self, r)

    def test_glm_stub_contract(self):
        r = VC.verify_glm("p")
        self.assertEqual(r["verifier"], "glm")
        self.assertTrue(r["dry_run"])
        _assert_contract(self, r)

    def test_claude_stub_contract(self):
        r = VC.verify_claude("p")
        self.assertEqual(r["verifier"], "claude")
        self.assertTrue(r["dry_run"])
        _assert_contract(self, r)

    def test_verify_dispatches_to_stub_when_keys_absent(self):
        # cross-family, no keys -> stub pass, contract holds, no network
        r = VC.verify("send a message", "I sent it",
                      generator="deepseek", verifier="claude")
        self.assertTrue(r["dry_run"])
        _assert_contract(self, r)

    def test_unknown_verifier_rejected(self):
        with self.assertRaises(ValueError):
            VC.verify("t", "c", generator="deepseek", verifier="nope")


# =============================================================================
# In-memory fake verifier — fixed verdict, offline.
# =============================================================================
class FakeVerifierContract(unittest.TestCase):
    def test_each_fake_satisfies_contract(self):
        for fn in VF.FAKE_VERIFIERS.values():
            _assert_contract(self, fn("ignored prompt"))

    def test_fake_returns_fixed_pass(self):
        r = VF.fake_claude("anything")
        self.assertTrue(r["passed"])
        self.assertTrue(r["dry_run"])
        # deterministic
        self.assertEqual(VF.fake_claude("other")["passed"], True)

    def test_fake_fail_verdict(self):
        r = VF.fake_claude_fail("x")
        self.assertFalse(r["passed"])
        self.assertFalse(r["auto_ingest"])
        _assert_contract(self, r)


# =============================================================================
# Auto-ingest semantics: pass -> ingest, fail -> NOT ingest (无人工签字闸门).
# =============================================================================
class AutoIngestGate(unittest.TestCase):
    def test_pass_auto_ingests(self):
        r = VF.fake_verify("t", "c", generator="deepseek", verifier="claude",
                           passed=True)
        self.assertTrue(r["passed"])
        self.assertTrue(r["auto_ingest"])

    def test_fail_does_not_ingest(self):
        r = VF.fake_verify("t", "c", generator="deepseek", verifier="claude",
                           passed=False)
        self.assertFalse(r["passed"])
        self.assertFalse(r["auto_ingest"])

    def test_no_human_gate_field_present(self):
        # the whole point: a pass needs NO extra human sign-off field — auto_ingest
        # is the single machine gate. Assert it's purely a function of passed.
        for passed in (True, False):
            r = VF.fake_verify("t", "c", generator="glm", verifier="claude",
                               passed=passed)
            self.assertEqual(r["auto_ingest"], passed)


if __name__ == "__main__":
    unittest.main()
