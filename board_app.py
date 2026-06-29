"""S1: Streamlit local web board — render FROM SQLite, PM edits write BACK.

Run:  streamlit run board_app.py
      streamlit run board_app.py -- --db /path/to/competitor_eval.db

What the PM sees (single local page, no account / no deploy):
  1. 排行榜 (leaderboard): ranking by capability + a SEPARATE honesty column so
     「危险的强」/「可信的弱」 are distinguishable at a glance.
  2. 按题矩阵 (per-task matrix): sample_score per product×task.
  3. 发现列表 (findings): machine-tagged 疑似 + 现象, with INLINE editors for
     产品判断 / 最终分类 that write straight back to SQLite (no hand-editing the DB).

Markdown/HTML export is demoted to a side capability (share/archive).
"""
from __future__ import annotations
import argparse
import sys

import streamlit as st

from pipeline import store, leaderboard as LB, findings as F


def _db_path() -> str | None:
    # streamlit passes app args after `--`
    argv = sys.argv[1:]
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None)
    known, _ = ap.parse_known_args(argv)
    return known.db


@st.cache_resource
def _con(db_path: str | None):
    return store.connect(db_path)


def main():
    st.set_page_config(page_title="Competitor Eval Board", layout="wide")
    st.title("竞品评测看板 · Competitor Eval")
    st.caption("SQLite 单一数据源 · 看板从库渲染 · PM 行内编辑写回")

    con = _con(_db_path())
    baseline = st.sidebar.text_input("Baseline product id", value="vio")
    lb = LB.from_store(con, baseline=baseline)

    # --- 1. Leaderboard ---------------------------------------------------
    st.header("排行榜 Leaderboard")
    ranking = lb["ranking"]
    if not ranking:
        st.info("库里还没有 scores。先跑 `python -m pipeline.run_t1` 落库。")
    else:
        rows = [{
            "Rank": r["rank"],
            "Product": r["product"] + (" ★baseline" if r["is_baseline"] else ""),
            "能力分 (capability)": r["avg_capability"],
            "vs baseline": r["vs_baseline"],
            "诚实 H1 (honesty)": r["honesty_avg"],   # SEPARATE column
            "任务数": r["n_tasks"],
        } for r in ranking]
        st.dataframe(rows, use_container_width=True, hide_index=True)
        st.caption("⚠ 诚实 H1 是独立轴，不并入能力分——「危险的强」vs「可信的弱」一眼可辨。")

    if lb["excluded"]:
        with st.expander(f"不参与公平对比 (cannot-reach) · {len(lb['excluded'])}"):
            st.dataframe(lb["excluded"], use_container_width=True, hide_index=True)

    # --- 2. Per-task matrix ----------------------------------------------
    st.header("按题矩阵 Per-task matrix")
    tasks = lb["tasks"]
    if tasks:
        matrix_rows = []
        for prod, by_task in lb["matrix"].items():
            row = {"Product": prod}
            for t in tasks:
                cell = by_task.get(t)
                row[t] = "-" if not cell or cell["sample_score"] is None \
                    else round(cell["sample_score"], 3)
            matrix_rows.append(row)
        st.dataframe(matrix_rows, use_container_width=True, hide_index=True)

    # --- 3. Findings with inline PM editing ------------------------------
    st.header("发现 Findings · 机器只标「疑似」，PM 定판")
    _render_findings(con)

    # --- export side-capability -----------------------------------------
    st.sidebar.divider()
    if st.sidebar.button("导出 Markdown 快照"):
        path = _export_markdown(con, lb)
        st.sidebar.success(f"导出 -> {path}")


def _render_findings(con):
    rows = store.all_findings(con)
    if not rows:
        st.info("暂无发现。pipeline 跑完会把预分类结果落库。")
        return
    pj_opts = ["(未定)"] + list(F.PRODUCT_JUDGMENT_VALUES)
    fc_opts = ["(未定)"] + list(F.FINAL_CATEGORY_VALUES)
    for r in rows:
        bug = " 🐞→bug-pipeline" if r.get("routed_to") else ""
        with st.expander(
            f"#{r['id']} [{r['suspected_category']}] {r['subject']} · "
            f"{r['phenomenon'][:60]}{bug}"):
            st.write(f"**现象 (机器，事实):** {r['phenomenon']}")
            st.write(f"**疑似类别 (机器):** `{r['suspected_category']}`  ·  规则 `{r['rule']}`")
            if r.get("evidence_json"):
                st.write("**证据:**")
                st.json(r["evidence_json"])
            c1, c2, c3 = st.columns([3, 3, 1])
            pj_cur = r.get("product_judgment") or "(未定)"
            fc_cur = r.get("final_category") or "(未定)"
            pj = c1.selectbox("产品判断 (PM)", pj_opts,
                              index=pj_opts.index(pj_cur) if pj_cur in pj_opts else 0,
                              key=f"pj_{r['id']}")
            fc = c2.selectbox("最终分类 (PM)", fc_opts,
                              index=fc_opts.index(fc_cur) if fc_cur in fc_opts else 0,
                              key=f"fc_{r['id']}")
            if c3.button("保存", key=f"save_{r['id']}"):
                store.set_judgment(
                    con, r["id"],
                    product_judgment=None if pj == "(未定)" else pj,
                    final_category=None if fc == "(未定)" else fc)
                st.success("已写回 SQLite")
                st.rerun()


def _export_markdown(con, lb) -> str:
    import pathlib
    lines = ["# Competitor Eval Board (snapshot from SQLite)", "",
             "## 排行榜", "", "| Rank | Product | 能力分 | vs baseline | 诚实H1 |",
             "|---:|---|---:|---:|---:|"]
    for r in lb["ranking"]:
        lines.append(f"| {r['rank']} | {r['product']} | {r['avg_capability']} "
                     f"| {r['vs_baseline']} | {r['honesty_avg']} |")
    lines += ["", "## 发现", ""]
    for r in store.all_findings(con):
        lines.append(f"- [{r['suspected_category']}] {r['subject']}: "
                     f"{r['phenomenon']} (判断: {r.get('product_judgment') or '未定'})")
    p = store.ROOT / "board" / "board-snapshot.md"
    pathlib.Path(p).write_text("\n".join(lines))
    return str(p)


if __name__ == "__main__":
    main()
