"""批量补任务清单 (走查驱动): 按竞品方向铺开 5 能力域 × task_nature 四性质。

每道题生成一个合法任务目录 (taskbank 要求 README/prompt.md/meta.json/scoring.md
+ input/expected/output/evidence 四子目录) + 一个 assertions 模块 .py。

立身之本: 断言只描述可核查末态 —— 机器可验的用 file_exists/equals/log_event,
只能人看的 (微信消息真发出、GUI 里可见) 用 manual_check。脏数据题带
known_edge_cases (schema 对 heavy 的强制要求)。

用法: python scripts/gen_tasks.py            # 生成/补齐所有缺失任务 (幂等)
      python scripts/gen_tasks.py --force   # 覆盖已存在的题
幂等: 已存在的任务目录默认跳过 (不覆盖 charlie 手工调过的题)。
"""
from __future__ import annotations
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TASKS = ROOT / "tasks"

# 每题: (task_id, domain_num, app, prompt, capability_domain, task_nature,
#        requires_local_desktop, expects_file, dirty_level, known_edge_cases,
#        assertions_spec)
# assertions_spec = list of (kind, *args):
#   ("manual", desc, ctx_key, primary)
#   ("file", path_key, desc, primary)
#   ("equals", ctx_key, expected, desc, primary)
#   ("log", event, desc, primary)
TASK_DEFS = [
    # ============ wechat-im (即时通讯) ============
    ("T4-wechat-forward-001", "1", "wechat",
     "Open WeChat, find the most recent file '季度预算.xlsx' that '张伟' sent you, "
     "and forward it to the group named '财务组'. Do not forward anything else.",
     "wechat-im", "simple", True, False, "none", [],
     [("manual", "the file was forwarded to '财务组'", "file_forwarded", True),
      ("manual", "it is the correct file '季度预算.xlsx'", "correct_file", True),
      ("manual", "no other chat received the file", "no_collateral", False)]),

    ("T5-wechat-followup-001", "1", "wechat",
     "In WeChat, send a polite follow-up reminder to each of these 3 contacts who "
     "haven't replied: '李娜', '王强', '赵敏'. Message: '您好，关于上周的方案，方便今天回复我吗？'",
     "wechat-im", "long-horizon", True, False, "none", [],
     [("manual", "all 3 contacts received the reminder", "all_sent", True),
      ("manual", "message text matches exactly for each", "text_exact", True),
      ("manual", "no unintended contact was messaged", "no_collateral", False)]),

    ("T6-wechat-schedule-001", "1", "wechat",
     "Every workday at 18:00, send the message '今日工作已完成，日报已更新' to the "
     "contact '文件传输助手'. Set this up to run on schedule today.",
     "wechat-im", "scheduled", True, False, "none", [],
     [("manual", "a scheduled/timed send was set up", "schedule_set", True),
      ("log", "schedule.registered", "a schedule registration event exists in the log", True),
      ("manual", "the message content is exactly correct", "text_exact", False)]),

    ("T7-wechat-dirty-roster-001", "1", "wechat",
     "You are given a messy contact list in input/roster.txt (names with typos, "
     "duplicates, and trailing spaces). Send '会议改到明天上午10点' to every UNIQUE "
     "real contact that matches someone in your WeChat. Skip unmatched/garbage entries.",
     "wechat-im", "dirty-data", True, False, "heavy",
     ["duplicate names in roster", "names with trailing whitespace",
      "typo'd names with no WeChat match", "empty lines"],
     [("manual", "each unique matched contact received the message", "unique_sent", True),
      ("manual", "garbage/unmatched entries were skipped", "garbage_skipped", True),
      ("manual", "no duplicate messages sent to the same person", "no_dupes", False)]),

    # ============ office-suite (办公套件) ============
    ("T8-word-contract-001", "1", "word",
     "Open input/contract-draft.docx. Apply heading styles to all section titles, "
     "add page numbers in the footer, and export the result as a PDF to output/contract.pdf.",
     "office-suite", "simple", True, True, "none", [],
     [("file", "artifact_path", "output PDF file was produced", True),
      ("manual", "headings are styled and page numbers present", "formatting_ok", True),
      ("manual", "content unchanged from the draft", "content_intact", False)]),

    ("T9-excel-merge-pivot-001", "1", "excel",
     "Open input/sales-by-region/*.xlsx (12 monthly files). Merge them into one sheet, "
     "then build a pivot table of total revenue by region and quarter. Save as output/pivot.xlsx.",
     "office-suite", "long-horizon", True, True, "none", [],
     [("file", "artifact_path", "output workbook was produced", True),
      ("manual", "all 12 months are merged with no rows lost", "merge_complete", True),
      ("manual", "pivot shows revenue by region x quarter", "pivot_correct", True)]),

    ("T10-excel-schedule-report-001", "1", "excel",
     "Set up a task that, on the last day of each month, opens input/ledger.xlsx, "
     "recalculates the monthly summary sheet, and exports it to output/monthly-report.pdf.",
     "office-suite", "scheduled", True, True, "none", [],
     [("log", "schedule.registered", "a monthly schedule was registered in the log", True),
      ("manual", "the report generation steps are correct", "steps_correct", True),
      ("manual", "export target path is correct", "path_correct", False)]),

    ("T11-excel-dirty-clean-001", "1", "excel",
     "Open input/expenses.csv. It has inconsistent date formats, some amounts stored as "
     "text with currency symbols, blank rows, and a duplicated header mid-file. Clean it "
     "and produce output/expenses-clean.xlsx with a correct SUM of all amounts in cell B1.",
     "office-suite", "dirty-data", True, True, "heavy",
     ["mixed date formats (YYYY-MM-DD vs DD/MM/YYYY)",
      "amounts as text with '¥' / ',' ", "blank rows scattered",
      "a duplicated header row in the middle"],
     [("file", "artifact_path", "cleaned workbook was produced", True),
      ("equals", "sum_b1", 48213.5, "SUM in B1 equals the correct total 48213.5", True),
      ("manual", "dirty rows were correctly normalized", "cleaned_ok", False)]),

    # ============ no-api-app (无接口桌面应用) ============
    ("T12-capcut-trim-001", "1", "capcut",
     "Open CapCut, import input/clip.mp4, trim it to the segment from 00:05 to 00:20, "
     "and export the result as output/trimmed.mp4 at 1080p.",
     "no-api-app", "simple", True, True, "none", [],
     [("file", "artifact_path", "exported video file exists", True),
      ("manual", "the clip is trimmed to 00:05-00:20", "trim_correct", True),
      ("manual", "export is 1080p", "resolution_ok", False)]),

    ("T13-capcut-color-render-001", "1", "capcut",
     "In CapCut, open project input/raw-footage/, apply a consistent color grade across "
     "all 5 clips, add cross-dissolve transitions between them, and render to output/final.mp4.",
     "no-api-app", "long-horizon", True, True, "none", [],
     [("file", "artifact_path", "rendered final video exists", True),
      ("manual", "color grade applied consistently to all clips", "grade_consistent", True),
      ("manual", "transitions present between clips", "transitions_ok", True)]),

    ("T14-accounting-dirty-entry-001", "1", "accounting-app",
     "Open the desktop accounting app. Enter the vouchers from input/receipts/ (a folder "
     "of scanned receipts with inconsistent naming, some blurry, some duplicates). Enter "
     "each unique valid receipt once; flag the unreadable ones instead of guessing.",
     "no-api-app", "dirty-data", True, False, "heavy",
     ["inconsistent file naming", "blurry/unreadable scans",
      "duplicate receipts", "a non-receipt image mixed in"],
     [("manual", "each unique valid receipt entered exactly once", "entries_correct", True),
      ("manual", "unreadable receipts were flagged not guessed", "flagged_unreadable", True),
      ("manual", "no duplicate voucher entries", "no_dupes", False)]),

    # ============ computer-control (电脑操控) ============
    ("T15-file-rename-001", "1", "finder",
     "In the folder input/photos/, rename all .jpg files to the pattern "
     "'YYYY-MM-DD_NNN.jpg' using each file's capture date (from EXIF), NNN a zero-padded "
     "sequence per day. Leave non-image files untouched.",
     "computer-control", "simple", True, True, "none", [],
     [("manual", "all jpgs renamed to the date pattern", "renamed_ok", True),
      ("manual", "sequence numbering is correct per day", "sequence_ok", True),
      ("manual", "non-image files untouched", "others_untouched", False)]),

    ("T16-cross-app-archive-001", "1", "finder",
     "Download the 3 attachments from the email titled 'Q1 材料' , save them into a new "
     "folder ~/Archive/Q1/, then create a zip ~/Archive/Q1.zip of that folder.",
     "computer-control", "long-horizon", True, True, "none", [],
     [("file", "artifact_path", "the Q1.zip archive was created", True),
      ("manual", "all 3 attachments saved into the folder", "all_saved", True),
      ("manual", "zip contains exactly those files", "zip_correct", False)]),

    ("T17-cleanup-schedule-001", "1", "system",
     "Set up a scheduled job that runs every day at 02:00 and deletes files older than "
     "7 days from ~/Downloads/tmp/, logging what it removed to ~/cleanup.log.",
     "computer-control", "scheduled", True, False, "none", [],
     [("log", "schedule.registered", "a daily schedule was registered in the log", True),
      ("manual", "deletion criteria (>7 days) is correct", "criteria_ok", True),
      ("manual", "it logs removed files", "logs_ok", False)]),

    ("T18-dedupe-dirty-001", "1", "finder",
     "The folder input/messy-dir/ has nested subfolders with duplicate files (same content, "
     "different names), empty folders, and .DS_Store junk. Produce a deduplicated flat copy "
     "in output/clean-dir/ keeping one copy of each unique file; remove junk.",
     "computer-control", "dirty-data", True, True, "heavy",
     ["identical content under different filenames", "empty nested folders",
      ".DS_Store / Thumbs.db junk", "deeply nested structure"],
     [("manual", "each unique file kept exactly once", "dedup_correct", True),
      ("manual", "junk files removed", "junk_removed", True),
      ("manual", "no unique file lost", "no_loss", False)]),

    # ============ browser-web (网页任务) ============
    ("T19-web-form-001", "1", "browser",
     "Go to the registration form at input/target-url.txt. Fill it using the profile in "
     "input/profile.json, submit it, and save a screenshot of the confirmation page to "
     "output/confirmation.png.",
     "browser-web", "long-horizon", False, True, "none", [],
     [("file", "artifact_path", "confirmation screenshot was saved", True),
      ("manual", "the form was submitted successfully", "submitted_ok", True),
      ("manual", "fields match the profile data", "fields_correct", True)]),

    ("T20-web-price-schedule-001", "1", "browser",
     "Set up a task that checks the price of the product at input/target-url.txt every "
     "morning at 09:00 and appends '{date},{price}' to output/price-history.csv.",
     "browser-web", "scheduled", False, True, "none", [],
     [("log", "schedule.registered", "a daily price-check schedule was registered", True),
      ("manual", "it extracts the correct price element", "price_selector_ok", True),
      ("manual", "it appends to the CSV in the right format", "csv_format_ok", False)]),

    ("T21-web-dirty-extract-001", "1", "browser",
     "Open the messy product listing page at input/target-url.txt. Extract name, price, "
     "and rating for all products into output/products.csv. The HTML is inconsistent: "
     "some prices in spans, some in divs, missing ratings, and ad rows mixed in.",
     "browser-web", "dirty-data", False, True, "heavy",
     ["prices in varying tags (span/div)", "some products missing ratings",
      "advertisement rows interleaved", "inconsistent currency formatting"],
     [("file", "artifact_path", "products.csv was produced", True),
      ("manual", "all real products extracted, ads skipped", "extract_correct", True),
      ("manual", "missing ratings handled gracefully", "missing_handled", False)]),
]

README_TMPL = """# {task_id}

Capability domain: **{cap}** · Task nature: **{nature}**

## Scenario
{prompt}

## Notes
This task is part of the auto-seeded task bank (scripts/gen_tasks.py). The
neutral standard prompt (below, ADR-0016) is what every product receives — no
product-specific syntax. End-state assertions live in `{module}`.
{dirty_note}
"""

SCORING_TMPL = """# Scoring — {task_id}

Objective assertions (end-state facts, per立身之本 — not self-report):

{assertion_lines}

Primary-goal failures gate the whole run. Machine-verifiable assertions are
auto-judged from artifacts/logs; human-only end-states are ticked by the
trained runner and re-checked on spot-check.
"""


def _assertion_py(spec) -> str:
    """把 assertions_spec 翻成 assertions() 的 Python 源码行。"""
    lines = []
    for a in spec:
        kind = a[0]
        if kind == "manual":
            _, desc, key, primary = a
            lines.append(f'        O.manual_check({desc!r}, {key!r}, primary={primary}),')
        elif kind == "file":
            _, key, desc, primary = a
            lines.append(f'        O.file_exists({key!r}, {desc!r}, primary={primary}),')
        elif kind == "equals":
            _, key, expected, desc, primary = a
            lines.append(f'        O.equals({key!r}, {expected!r}, {desc!r}, primary={primary}),')
        elif kind == "log":
            _, event, desc, primary = a
            lines.append(f'        O.log_event({event!r}, {desc!r}, primary={primary}),')
    return "\n".join(lines)


def _core_assertions(spec) -> list[str]:
    out = []
    for a in spec:
        kind = a[0]
        if kind in ("manual", "file", "log"):
            desc = a[1] if kind != "file" else a[2]
            if kind == "file":
                desc = a[2]
            elif kind == "log":
                desc = a[2]
            else:
                desc = a[1]
            primary = a[-1]
        else:  # equals
            desc = a[3]
            primary = a[-1]
        prefix = "primary: " if primary else "secondary: "
        out.append(prefix + desc)
    return out


def gen_one(d, force=False) -> str:
    (task_id, domain_num, app, prompt, cap, nature, req_desktop, expects_file,
     dirty, edges, spec) = d
    module = f"tasks.{task_id.replace('-', '_')}"
    tdir = TASKS / task_id
    if tdir.exists() and not force:
        return f"skip (exists): {task_id}"
    for sub in ("input", "expected", "output", "evidence"):
        (tdir / sub).mkdir(parents=True, exist_ok=True)
        readme = tdir / sub / "README.md"
        if not readme.exists():
            readme.write_text(f"# {sub}/ for {task_id}\n\nStarting materials / "
                              f"end-state / per-run artifacts / evidence.\n")

    # taskbank 立身之本守卫: heavy 脏数据属压力任务, 不能挂 core-common tier。
    tier = "stress" if dirty == "heavy" else "core-common"
    task_spec = {
        "task_id": task_id, "domain": domain_num, "app": app, "prompt": prompt,
        "core_assertions": _core_assertions(spec),
        "expects_file": expects_file, "tier": tier, "kind": "task-exam",
        "requires_local_desktop": req_desktop, "dirty_data_level": dirty,
        "dirty_data_level_suggested": dirty, "known_edge_cases": edges,
        "capability_domain": cap, "task_nature": nature,
    }
    meta = {
        "schema": "taskbank-v1", "task_spec": task_spec,
        "dirty_data": {"suggested_by": "ai:gen_tasks", "final_by": "human:charlie",
                       "note": f"Auto-seeded {nature} task for {cap}."},
        "assertions_module": module,
        "files": {"input": "input/ — starting materials (may be faked)",
                  "expected": "expected/end-state.md — correct outcome",
                  "output": "output/ — per-run product artifacts",
                  "evidence": "evidence/ — logs / screenshots / recordings"},
    }
    (tdir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    (tdir / "prompt.md").write_text(f"# Neutral standard prompt — {task_id}\n\n{prompt}\n")
    dirty_note = ("\n## Dirty data (铁律: 材料可假, 脏数据必真)\n"
                  + "\n".join(f"- {e}" for e in edges) + "\n") if edges else ""
    (tdir / "README.md").write_text(README_TMPL.format(
        task_id=task_id, cap=cap, nature=nature, prompt=prompt, module=module,
        dirty_note=dirty_note))
    (tdir / "expected" / "end-state.md").write_text(
        f"# Expected end-state — {task_id}\n\n{prompt}\n\nAll primary assertions must hold.\n")
    alines = "\n".join(f"- {a}" for a in task_spec["core_assertions"])
    (tdir / "scoring.md").write_text(SCORING_TMPL.format(
        task_id=task_id, assertion_lines=alines))

    # assertions module .py
    mod_path = TASKS / f"{task_id.replace('-', '_')}.py"
    mod_src = f'''"""Auto-seeded assertions for {task_id} ({cap} / {nature}).

Generated by scripts/gen_tasks.py. End-state assertions only (立身之本):
machine-verifiable via file/log, human-only via manual_check. TASK is loaded
+ validated from meta.json so the .py and bank never drift.
"""
import pathlib
from pipeline import objective as O
from pipeline import taskbank as TB

TASK_DIR = pathlib.Path(__file__).resolve().parent / "{task_id}"
TASK = TB.assert_valid(TASK_DIR)


def assertions():
    return [
{_assertion_py(spec)}
    ]
'''
    mod_path.write_text(mod_src)
    return f"created: {task_id}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    for d in TASK_DEFS:
        print(gen_one(d, force=args.force))
    return 0


if __name__ == "__main__":
    sys.exit(main())
