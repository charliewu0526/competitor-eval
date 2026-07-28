"""补齐缺失的任务输入素材 (task-bank bug: prompt 引用 input/xxx 但文件不存在)。

只造文本/表格/文件夹类可程序生成的素材; 视频(T12/T13)与收据图(T14)另行处理。
每造完一个任务, 用 taskbank.validate_dir 校验。素材统一由系统提供, 保证各竞品
在同一份数据上对打(不让实习生自建, 否则数据不一致对比失真)。
"""
import csv
import io
import pathlib

import openpyxl

ROOT = pathlib.Path(__file__).resolve().parent.parent
TASKS = ROOT / "tasks"


def _w(rel: str, content: str):
    p = TASKS / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# ---- T7 微信脏名单: 含错别字/重复/尾随空格/垃圾行 ----
_w("T7-wechat-dirty-roster-001/input/roster.txt",
   "张伟\n李娜 \n王芳\n张伟\n李娜\n刘洋\n★广告推广★\n陈静\n王芳  \n"
   "赵磊\nasdfghjkl\n陈静\n孙丽\n\n周杰(重复)\n周杰\n")

# ---- T11 Excel脏数据 CSV: 日期格式不一/金额带符号文本/空行/中途重复表头 ----
_w("T11-excel-dirty-clean-001/input/expenses.csv",
   "date,item,amount\n"
   "2025/07/01,办公用品,¥1,200\n"
   "2025-07-03,差旅,3500\n"
   "\n"
   "07/05/2025,招待,$800\n"
   "date,item,amount\n"
   "2025.07.08,快递, 45.50 \n"
   "2025-07-10,软件订阅,¥ 2,000\n"
   "\n"
   "2025/7/12,培训,1500元\n")

# ---- T19 网页表单: 目标URL(本地html) + 个人资料json ----
_w("T19-web-form-001/input/target-url.txt",
   "file://./input/registration.html\n")
_w("T19-web-form-001/input/profile.json",
   '{\n  "name": "陈雨含",\n  "email": "chenyh@example.com",\n'
   '  "phone": "13800001234",\n  "company": "评测组",\n  "role": "实习生"\n}\n')
_w("T19-web-form-001/input/registration.html",
   "<!doctype html><html><head><meta charset='utf-8'><title>注册</title></head>\n"
   "<body><h1>用户注册</h1>\n<form id='reg'>\n"
   "  姓名 <input name='name'><br>\n  邮箱 <input name='email'><br>\n"
   "  电话 <input name='phone'><br>\n  公司 <input name='company'><br>\n"
   "  <button type='submit'>提交</button>\n</form>\n"
   "<div id='ok' style='display:none'>注册成功!</div>\n"
   "<script>document.getElementById('reg').onsubmit=function(e){e.preventDefault();"
   "document.getElementById('ok').style.display='block';};</script>\n"
   "</body></html>\n")

# ---- T20 网页比价: 目标URL(本地html, 带价格) ----
_w("T20-web-price-schedule-001/input/target-url.txt",
   "file://./input/product.html\n")
_w("T20-web-price-schedule-001/input/product.html",
   "<!doctype html><html><head><meta charset='utf-8'><title>商品</title></head>\n"
   "<body><h1>无线鼠标 Pro</h1>\n<div class='price'>¥129.00</div>\n"
   "<div class='stock'>有货</div>\n</body></html>\n")

# ---- T21 脏网页抽取: 价格在span/div混排, 缺评分, 混入广告行 ----
_w("T21-web-dirty-extract-001/input/target-url.txt",
   "file://./input/listing.html\n")
_w("T21-web-dirty-extract-001/input/listing.html",
   "<!doctype html><html><head><meta charset='utf-8'><title>商品列表</title></head><body>\n"
   "<ul>\n"
   "  <li class='product'><h3>机械键盘</h3><span class='price'>¥299</span>"
   "<span class='rating'>4.5</span></li>\n"
   "  <li class='ad'>★赞助广告: 点击领券★</li>\n"
   "  <li class='product'><h3>无线鼠标</h3><div class='cost'>129元</div></li>\n"
   "  <li class='product'><h3>USB集线器</h3><span class='price'>89.9</span>"
   "<span class='rating'>4.0</span></li>\n"
   "  <li class='ad'>广告位招租</li>\n"
   "  <li class='product'><h3>显示器支架</h3><div class='cost'>¥ 259.00</div>"
   "<span class='rating'>4.8</span></li>\n"
   "</ul>\n</body></html>\n")


def _make_xlsx(path: pathlib.Path, header, rows, sheet="Sheet1"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(header)
    for r in rows:
        ws.append(list(r))
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


# ---- T9 Excel合并透视: 12个月度文件 (region/revenue), 分季度可透视 ----
_regions = ["华东", "华北", "华南", "西部"]
for m in range(1, 13):
    rows = [(r, 10000 + m * 300 + i * 777) for i, r in enumerate(_regions)]
    _make_xlsx(TASKS / f"T9-excel-merge-pivot-001/input/sales-by-region/2025-{m:02d}.xlsx",
               ["region", "revenue"], rows, sheet=f"2025-{m:02d}")

# ---- T18 去重脏目录: 嵌套子目录+同内容不同名重复+空目录+.DS_Store ----
base = TASKS / "T18-dedupe-dirty-001/input/messy-dir"
(base / "a").mkdir(parents=True, exist_ok=True)
(base / "b/nested").mkdir(parents=True, exist_ok=True)
(base / "empty-folder").mkdir(parents=True, exist_ok=True)
DUP = "报告正文: 2025 Q3 总结\n营收增长 12%\n"
_w("T18-dedupe-dirty-001/input/messy-dir/a/report.txt", DUP)
_w("T18-dedupe-dirty-001/input/messy-dir/b/report-copy.txt", DUP)          # 同内容不同名
_w("T18-dedupe-dirty-001/input/messy-dir/b/nested/report (1).txt", DUP)     # 又一份重复
_w("T18-dedupe-dirty-001/input/messy-dir/a/notes.txt", "会议记录: 周一评审\n")
_w("T18-dedupe-dirty-001/input/messy-dir/.DS_Store", "\x00\x00junk")        # 垃圾文件
_w("T18-dedupe-dirty-001/input/messy-dir/b/.DS_Store", "\x00junk")

print("文本/表格/文件夹类素材已生成。")

# ---- 校验受影响任务 ----
from pipeline import taskbank as TB  # noqa: E402
for t in ["T7-wechat-dirty-roster-001", "T9-excel-merge-pivot-001",
          "T11-excel-dirty-clean-001", "T18-dedupe-dirty-001",
          "T19-web-form-001", "T20-web-price-schedule-001",
          "T21-web-dirty-extract-001"]:
    probs = TB.validate_dir(TASKS / t)
    print(f"  {t}: {'OK' if not probs else probs}")
