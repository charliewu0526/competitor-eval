"""T3 pilot task: extract the 3 most-recent article titles into titles.txt.

Domain browser-web. Like T2 (Excel), T3 produces a FILE artifact (titles.txt),
so the primary end-state IS machine-checkable — no intern self-report on the
core goal. The machine assertion reads ctx['artifact_path'] (the server-side
saved artifact, authoritative, populated by intake._build_ctx).

Primary checks (both MACHINE):
  1. titles.txt exists (artifact saved).
  2. titles.txt holds exactly THREE non-empty lines, no numbering/bullets —
     i.e. the shape the task demanded (3 titles, one per line). A product that
     didn't run (e.g. a "(not run)" placeholder) or dumped junk fails this,
     so 未验证 != 通过 and 做对的产物拿到 objective_ratio=1.

We intentionally check SHAPE (exactly 3 clean title lines) rather than exact
string equality: the neutral prompt hands each product the same page and the
end-state is "the 3 most-recent titles, top-to-bottom"; the blind review panel
judges title CONTENT/quality. The machine layer guarantees the artifact is a
well-formed 3-title file so a correct run is not multiplied to 0.
"""
import pathlib
from pipeline import objective as O


def _titles_well_formed(ctx: dict) -> bool:
    p = ctx.get("artifact_path")
    if not p:
        return False
    fp = pathlib.Path(p).expanduser()
    if not fp.is_file():
        return False
    try:
        text = fp.read_text(encoding="utf-8")
    except OSError:
        return False
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    # exactly three non-empty lines, none looking like a "not run" placeholder
    # or carrying list numbering/bullets (the task forbids extra formatting).
    if len(lines) != 3:
        return False
    for ln in lines:
        if ln.lower() in ("(not run)", "not run", "n/a", "none"):
            return False
        if ln[0] in "-*•" or (len(ln) > 1 and ln[0].isdigit() and ln[1] in ".)"):
            return False
    return True


def assertions():
    """T3's concrete assertions. Both primary end-state checks are MACHINE:
    the artifact file is read directly, nothing falls to intern self-report."""
    return [
        O.file_exists("artifact_path",
                      "titles.txt was saved (artifact exists)", primary=True),
        O.Assertion(
            desc="titles.txt holds exactly three clean title lines",
            primary=True,
            check=_titles_well_formed,
            kind=O.MACHINE,
            ctx_key="artifact_path"),
    ]
