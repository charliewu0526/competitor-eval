"""Subjective review prompt builder (rubric §2 + §3 anti-bias guards).

Produces the exact prompt sent to each panelist (Gemini, Codex). The anti-bias
guards are baked in as explicit instructions. Products are pre-blinded by the
orchestrator (labelled A/B/C) before reaching here.
"""
from __future__ import annotations

DIMENSIONS = [
    ("S1", "Output quality / fidelity", 0.4),
    ("S2", "Efficiency", 0.2),
    ("S3", "Robustness / recovery", 0.2),
    ("S4", "Autonomy", 0.2),
]

ANTI_BIAS = """ANTI-BIAS RULES (mandatory):
- LENGTH: do NOT reward verbosity. A shorter artifact/transcript that achieves the goal is not inferior. Judge outcome, not volume.
- CONFIDENCE: do NOT reward confident tone. The agent's self-narration ("I successfully...") is NOT evidence. Score only the verifiable artifact/end-state.
- IDENTITY: the product is blinded (Product A/B/...). Do not guess or favor any identity.
- EVIDENCE: every score needs a one-line justification grounded in the artifact/screenshots."""


S5_ANCHORS = """S5 EXPERIENCE — score ONLY from process evidence (transcript/screenshots), using anchors:
  5 = fully observable & controllable throughout (every step knowable, interruptible)
  3 = partial black-box (some steps opaque)
  1 = total black-box (you cannot tell what it did)
If there is NO process evidence at all, OMIT S5 (leave it null) rather than guessing — "拿不到" is not "差"."""

DEFECTS_RULE = """DEFECTS (scoring/defect split): list EVERY concrete flaw you spot in `defects` as short
one-line strings, even on an otherwise high-scoring run. Defects are recorded separately and do
NOT lower the scores — so do not depress a score to "punish" a flaw; score the dimension honestly
AND report the flaw. Each numeric score still needs a one-line justification or it is discarded."""


def build_prompt(task_prompt: str, blinded_label: str, artifact_summary: str,
                 screenshots_note: str, transcript_excerpt: str) -> str:
    dims = "\n".join(f"- {c} {name} (weight {w})" for c, name, w in DIMENSIONS)
    return f"""You are a strict evaluator of desktop-agent task outputs. Score ONLY what
objective assertions cannot judge. Return JSON:
{{"S1":int,"S2":int,"S3":int,"S4":int,"S5":int|null,
"justifications":{{"S1":str,"S2":str,"S3":str,"S4":str,"S5":str}},
"defects":[str]}}. Each score 1-5 (1=poor,3=acceptable,5=excellent).

TASK GIVEN TO THE AGENT:
{task_prompt}

PRODUCT UNDER REVIEW: {blinded_label}

ARTIFACT SUMMARY:
{artifact_summary}

SCREENSHOTS:
{screenshots_note}

TRIMMED TRANSCRIPT (not raw — excerpt only):
{transcript_excerpt}

CAPABILITY DIMENSIONS TO SCORE:
{dims}

{S5_ANCHORS}

{DEFECTS_RULE}

{ANTI_BIAS}
"""


def weighted_subjective(scores: dict) -> float:
    """scores like {"S1":4,...} -> 0..1 normalized weighted mean."""
    total = sum(scores[c] * w for c, _, w in DIMENSIONS)
    return (total - 1) / 4  # map 1..5 -> 0..1
