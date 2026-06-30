"""X1: Task-bank directory standard + dirty-data declaration regime.

A task = one fixed directory. Humans read the .md files; machines read meta.json
— the SINGLE machine-readable source, kept field-consistent with F1's TaskSpec
(pipeline/schema.py). Dirty-data is a declared, audited property, not a vibe:

  * dirty_data_level in {none,light,heavy}; heavy REQUIRES known_edge_cases.
  * the generator-AI proposes dirty_data_level_suggested + candidate edge cases;
    a human/verifier sets the FINAL dirty_data_level. Both values coexist and
    MUST come from different sources — AI never self-certifies (the OI lesson).
  * cross-checked against tier: a `stress` task with pristine data is rejected.

This keeps the 「材料可假、脏数据必真」rule enforceable without bureaucracy.
"""
from __future__ import annotations
import json, pathlib
import dataclasses as _dc
from dataclasses import fields as dc_fields
from pipeline import schema as S

# --- canonical per-task layout (人读 md / 机器读 meta.json) ---
REQUIRED_FILES = ("README.md", "prompt.md", "meta.json", "scoring.md")
REQUIRED_DIRS = ("input", "expected", "output", "evidence")

# meta.json's task_spec block mirrors TaskSpec exactly — derived, never drifts.
TASKSPEC_FIELDS = {f.name for f in dc_fields(S.TaskSpec)}
TASKSPEC_REQUIRED = {f.name for f in dc_fields(S.TaskSpec)
                     if f.default is _dc.MISSING and f.default_factory is _dc.MISSING}


def task_dir(root, task_id) -> pathlib.Path:
    return pathlib.Path(root) / task_id


def load_meta(tdir) -> dict:
    return json.loads((pathlib.Path(tdir) / "meta.json").read_text())


def taskspec_from_meta(meta: dict) -> S.TaskSpec:
    """Build a validated TaskSpec from meta.json's task_spec block (F1 runs)."""
    return S.TaskSpec(**dict(meta.get("task_spec") or {}))


# ---------------------------------------------------------------------------
# Dirty-data declaration regime
# ---------------------------------------------------------------------------
class TaskBankError(ValueError):
    """A task directory or its declaration violates the X1 contract."""


def validate_meta(meta: dict) -> list[str]:
    """Validate a meta.json dict (machine source). Returns the list of problems
    (empty == valid). Does NOT touch the filesystem — pure declaration audit.

    Rules:
      1. meta.task_spec must carry every TaskSpec-required field and no unknown
         keys, and reconstruct into a valid TaskSpec (re-runs F1 invariants:
         enum checks, heavy⇒known_edge_cases).
      2. heavy ⇒ non-empty known_edge_cases (story 31, also F1-enforced).
      3. tier cross-check: a `stress` task may not declare dirty_data_level=none
         (stress without dirty data is mislabeled); conversely heavy dirty data
         on a `core-common` task is allowed but flagged as a notable mismatch.
      4. suggested vs final two-source rule (story 32): if a suggestion exists,
         dirty_data.suggested_by and dirty_data.final_by must both be present
         and be DIFFERENT sources — AI proposes, human/verifier disposes. AI
         never both suggests and finalizes (no self-certification).
    """
    problems: list[str] = []
    spec = meta.get("task_spec")
    if not isinstance(spec, dict):
        return ["meta.task_spec missing or not an object"]

    keys = set(spec)
    missing = TASKSPEC_REQUIRED - keys
    if missing:
        problems.append(f"task_spec missing required fields: {sorted(missing)}")
    unknown = keys - TASKSPEC_FIELDS
    if unknown:
        problems.append(f"task_spec has unknown fields (drift from F1 schema): {sorted(unknown)}")
    if missing or unknown:
        return problems  # can't trust further checks until shape is right

    try:
        ts = S.TaskSpec(**spec)
    except ValueError as e:
        problems.append(f"task_spec invalid per F1 schema: {e}")
        return problems

    # 任务地图: every task card must EXPLICITLY declare both orthogonal labels
    # (能力域 × 任务性质). They carry schema defaults so old synthetic RunRecords
    # still load, but a task BANK entry that omits them would be silently filed
    # under the default class — breaking suite圈定. So require them in meta.json.
    for label in ("capability_domain", "task_nature"):
        if label not in spec:
            problems.append(f"task_spec missing '{label}' — every 任务卡 must "
                            f"declare its 任务地图 label explicitly (不靠默认值)")

    # 3. tier × dirty-data cross-check
    if ts.tier == "stress" and ts.dirty_data_level == "none":
        problems.append("tier='stress' but dirty_data_level='none' — a stress "
                        "task must exercise dirty data (declare light/heavy)")
    if ts.tier == "core-common" and ts.dirty_data_level == "heavy":
        problems.append("tier='core-common' with dirty_data_level='heavy' — "
                        "heavy dirty data usually belongs to a stress task; "
                        "reclassify tier or downgrade dirty_data_level")

    # 4. suggested vs final two-source provenance
    prov = meta.get("dirty_data") or {}
    suggested_by = prov.get("suggested_by")
    final_by = prov.get("final_by")
    if ts.dirty_data_level_suggested is not None:
        if not suggested_by:
            problems.append("dirty_data_level_suggested set but dirty_data.suggested_by missing")
        if not final_by:
            problems.append("dirty_data_level_suggested set but dirty_data.final_by missing "
                            "(human/verifier must set the final value)")
        if suggested_by and final_by and suggested_by == final_by:
            problems.append(f"dirty_data.suggested_by == final_by ({suggested_by!r}) — "
                            "AI cannot self-certify; final must come from a different source")
    elif final_by and suggested_by and suggested_by == final_by:
        problems.append(f"dirty_data.suggested_by == final_by ({suggested_by!r})")

    return problems


def validate_dir(tdir) -> list[str]:
    """Validate a task directory on disk: required layout + meta.json contract."""
    d = pathlib.Path(tdir)
    problems: list[str] = []
    if not d.is_dir():
        return [f"task dir not found: {d}"]
    for f in REQUIRED_FILES:
        if not (d / f).is_file():
            problems.append(f"missing required file: {f}")
    for sub in REQUIRED_DIRS:
        if not (d / sub).is_dir():
            problems.append(f"missing required dir: {sub}/")
    if (d / "meta.json").is_file():
        try:
            meta = load_meta(d)
        except json.JSONDecodeError as e:
            return problems + [f"meta.json is not valid JSON: {e}"]
        # meta.task_id should match the directory name (single source of truth)
        spec = meta.get("task_spec") or {}
        if isinstance(spec, dict) and spec.get("task_id") and spec["task_id"] != d.name:
            problems.append(f"task_spec.task_id ({spec['task_id']!r}) != dir name ({d.name!r})")
        problems += validate_meta(meta)
    return problems


def assert_valid(tdir) -> S.TaskSpec:
    """Validate a task dir and return its TaskSpec, or raise TaskBankError."""
    problems = validate_dir(tdir)
    if problems:
        raise TaskBankError(f"{pathlib.Path(tdir).name}: " + "; ".join(problems))
    return taskspec_from_meta(load_meta(tdir))


def discover(root) -> list[str]:
    """List task ids under a task-bank root (dirs containing a meta.json)."""
    r = pathlib.Path(root)
    if not r.is_dir():
        return []
    return sorted(p.name for p in r.iterdir()
                  if p.is_dir() and (p / "meta.json").is_file())
