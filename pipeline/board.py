"""Board generator: renders scored evals into a markdown trend board.

For T1 this is a single snapshot row. The trend/derivative view (across version
events) is built out in T6; here we lay the schema so T6 just appends rows.
"""
from __future__ import annotations
import json, pathlib, datetime


def render_board(gap: dict, evals: list[dict], out_path: str,
                 version_label: str = "T1-pilot") -> str:
    lines = [
        "# Competitor Eval Board — Domain #1 (closed-source desktop app)",
        "",
        f"_Generated: {datetime.datetime.now().isoformat(timespec='seconds')} | snapshot: {version_label}_",
        "",
        "## Gap (Vio vs competitor)",
        "",
        "| Vio score | Competitor score | Gap (Vio - comp) |",
        "|---:|---:|---:|",
        f"| {gap['vio']:.3f} | {gap['competitor']:.3f} | {gap['gap']:+.3f} |",
        "",
        "## Per-eval detail",
        "",
        "| Product | Run | GATE | Obj ratio | Subj(0-1) | Sample | Flags |",
        "|---|---:|---|---:|---:|---:|---|",
    ]
    for e in evals:
        flags = []
        if e.get("cross_layer"): flags.append("cross-layer")
        if e.get("disagreement_flagged"): flags.append("disagree:" + ",".join(e["disagreement_flagged"]))
        if e.get("defects"): flags.append(f"defects:{len(e['defects'])}")
        if e.get("dry_run"): flags.append("DRY-RUN")
        if not e.get("scored"): flags.append("not-scored:" + e.get("reason", ""))
        subj = e.get("subjective")
        # E3: subjective is dim->median (S5 may be None). Normalize over the
        # non-None capability dims only.
        cap_vals = [] if not subj else [subj[d] for d in ("S1", "S2", "S3", "S4")
                                        if subj.get(d) is not None]
        subj_norm = "-" if not cap_vals else f"{(sum(cap_vals)/len(cap_vals)-1)/4:.2f}"
        lines.append(
            f"| {e['product']} | {e['run_idx']} | {e['gate']} | "
            f"{e['objective_ratio']:.2f} | {subj_norm} | "
            f"{e.get('sample_score','-')} | {'; '.join(flags) or '-'} |"
        )
    lines += ["", "> Note: cross-layer / cannot-reach rows are NOT fair head-to-head "
              "(see rubric §0 iron rule). DRY-RUN = no API key, stub scores.", ""]
    p = pathlib.Path(out_path); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines))
    return str(p)
