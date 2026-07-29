"""Seed missing starting materials for tasks whose input/ was empty.

Only T4 (forwarded xlsx must pre-exist) and T16 (3 email attachments the
assertions check) genuinely need materials. T1/T5/T6/T17 need none by design.
Run from repo root: python3 scripts/seed_missing_inputs.py
"""
import pathlib
import openpyxl

ROOT = pathlib.Path(__file__).resolve().parent.parent


def seed_t4():
    d = ROOT / "tasks/T4-wechat-forward-001/input"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Q2预算"
    ws.append(["部门", "科目", "Q2预算(元)", "已用(元)", "备注"])
    rows = [
        ["市场部", "品牌推广", 120000, 83500, ""],
        ["市场部", "活动执行", 60000, 60000, "已用满"],
        ["研发部", "云服务", 90000, 74210, ""],
        ["研发部", "测试设备", 45000, 0, "待采购"],
        ["行政部", "办公用品", 18000, 12300, ""],
        ["行政部", "团建", 30000, 0, ""],
    ]
    for r in rows:
        ws.append(r)
    ws.append([])
    ws.append(["合计", "", sum(r[2] for r in rows), sum(r[3] for r in rows), ""])
    wb.save(d / "季度预算.xlsx")


def seed_t16():
    d = ROOT / "tasks/T16-cross-app-archive-001/input"
    wb = openpyxl.Workbook()
    s = wb.active
    s.title = "Q1汇总"
    s.append(["月份", "收入(元)", "支出(元)", "净额(元)"])
    for m, inc, exp in [("1月", 320000, 210000), ("2月", 280000, 195000), ("3月", 410000, 260000)]:
        s.append([m, inc, exp, inc - exp])
    wb.save(d / "Q1财务汇总.xlsx")

    (d / "Q1客户名单.csv").write_text(
        "客户编号,客户名称,签约金额,负责人\n"
        "C001,蓝海科技,180000,张伟\n"
        "C002,远景传媒,95000,李娜\n"
        "C003,恒通物流,240000,王强\n"
        "C004,\u3000星辰教育 ,120000,赵敏\n",
        encoding="utf-8")

    (d / "Q1工作总结.txt").write_text(
        "Q1 工作总结\n\n"
        "1. 完成新客户签约 4 家，合计约 63.5 万元。\n"
        "2. 市场活动 3 场，品牌曝光提升。\n"
        "3. 研发按期交付 v2.1，遗留 2 个已知问题待 Q2 修复。\n\n"
        "附：详细数据见《Q1财务汇总.xlsx》与《Q1客户名单.csv》。\n",
        encoding="utf-8")


if __name__ == "__main__":
    seed_t4()
    seed_t16()
    for p in [
        "tasks/T4-wechat-forward-001/input/季度预算.xlsx",
        "tasks/T16-cross-app-archive-001/input/Q1财务汇总.xlsx",
        "tasks/T16-cross-app-archive-001/input/Q1客户名单.csv",
        "tasks/T16-cross-app-archive-001/input/Q1工作总结.txt",
    ]:
        f = ROOT / p
        print("OK" if f.exists() else "MISSING", f.stat().st_size if f.exists() else "-", p)
