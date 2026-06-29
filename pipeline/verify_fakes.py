"""A4 in-memory fake verifier — the offline twin of verify_client.

Per PRD 「适配器各自用假实现测」: every adapter ships a production impl AND an
in-memory fake honoring the SAME contract. The fake NEVER touches the network —
it returns a fixed, deterministic verdict so tests stay stable + offline.

It STILL enforces 不自评 (delegates to verify_client.assert_not_self_eval), so
the seam can't tell prod and fake apart on the one rule that matters most.

Contract (identical to verify_client):
  {"verifier": str, "model_family": str, "dry_run": True,
   "passed": bool, "reason": str, "auto_ingest": bool}
"""
from __future__ import annotations

from pipeline.verify_client import (
    family_of, assert_not_self_eval, SelfEvalError,
)


def make_fake_verifier(verifier: str, passed: bool = True,
                       reason: str | None = None):
    """Return a verifier function ignoring its prompt, yielding a fixed verdict.

    passed: the fixed pass/fail this fake always returns.
    A pass -> auto_ingest=True, mirroring production (无人工签字闸门).
    """
    fixed_reason = reason or (
        "fake: candidate meets task requirement" if passed
        else "fake: candidate fails task requirement")

    def _verifier(prompt: str) -> dict:
        return {"verifier": verifier, "model_family": family_of(verifier),
                "dry_run": True, "passed": passed, "reason": fixed_reason,
                "auto_ingest": bool(passed)}

    return _verifier


def fake_verify(task_text: str, candidate: str, *, generator: str,
                verifier: str, passed: bool = True,
                reason: str | None = None) -> dict:
    """Offline twin of verify_client.verify: enforces 不自评 then returns a
    fixed verdict, no network."""
    assert_not_self_eval(generator, verifier)
    return make_fake_verifier(verifier, passed=passed, reason=reason)("ignored")


# Ready-made fakes mirroring the production verifier names.
fake_deepseek = make_fake_verifier("deepseek")
fake_glm = make_fake_verifier("glm")
fake_claude = make_fake_verifier("claude")
# A failing verifier, for the "fail -> not ingested" path.
fake_claude_fail = make_fake_verifier("claude", passed=False)

FAKE_VERIFIERS = {
    "verify_deepseek": fake_deepseek,
    "verify_glm": fake_glm,
    "verify_claude": fake_claude,
}

__all__ = [
    "make_fake_verifier", "fake_verify", "fake_deepseek", "fake_glm",
    "fake_claude", "fake_claude_fail", "FAKE_VERIFIERS", "SelfEvalError",
]
