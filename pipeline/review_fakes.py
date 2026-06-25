"""A1 in-memory fake panel — the offline twin of review_client production clients.

Per PRD "适配器各自用假实现测": every adapter ships a production impl AND an
in-memory fake. Both honor the SAME contract dict so the seam (score_run) can't
tell them apart. The fake NEVER touches the network — it returns fixed,
deterministic scores so tests are stable and offline.

Contract (identical to review_client):
  {"panelist": str, "dry_run": True,
   "S1":int,"S2":int,"S3":int,"S4":int,"S5":int|null,
   "justifications": {"S1":str,...}, "defects": [str]}
"""
from __future__ import annotations

_DIMS = ("S1", "S2", "S3", "S4", "S5")


def make_fake(name: str, scores: dict | None = None,
              defects: list | None = None,
              justify: tuple = _DIMS):
    """Return a panelist function ignoring its prompt, yielding fixed scores.

    scores: dim -> 1-5 (defaults all 4). Only dims in `justify` get a
    justification — omit one to exercise the "unjustified score is dropped"
    contract. A dim set to None is emitted as null (e.g. S5 with no evidence).
    """
    fixed = {d: 4 for d in _DIMS}
    if scores:
        fixed.update(scores)

    def _panelist(prompt: str) -> dict:
        out = {"panelist": name, "dry_run": True,
               "justifications": {d: f"{name} fixed reason" for d in justify},
               "defects": list(defects or [])}
        out.update({d: fixed[d] for d in _DIMS})
        return out

    return _panelist


# A ready-made offline panel mirroring the production members
# (deepseek + glm + claude). DeepSeek is the strict one — it carries a defect.
fake_deepseek = make_fake("deepseek", {"S1": 4, "S2": 3, "S3": 4, "S4": 4, "S5": 4},
                          defects=["minor: edge case not handled"])
fake_glm = make_fake("glm", {"S1": 4, "S2": 4, "S3": 4, "S4": 4, "S5": 4})
fake_claude = make_fake("claude", {"S1": 5, "S2": 4, "S3": 4, "S4": 4, "S5": 4})

# Members keyed by the SAME names production code resolves through
# orchestrate.PANELISTS, so a test can install the whole fake panel at once.
FAKE_PANEL = {
    "review_deepseek": fake_deepseek,
    "review_glm": fake_glm,
    "review_claude": fake_claude,
}
