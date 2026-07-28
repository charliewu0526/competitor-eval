"""补齐 T8(Word docx) / T14(收据图) / T15(照片) 的输入素材。

python-docx 未装 -> 直接用 zipfile 写一个最小合法 .docx(OOXML 本质是 zip),
含若干段落 + 章节标题, 供任务"套用标题样式+加页码+导出PDF"。
收据图/照片用 Pillow 造占位图(带可辨识文字), 让文件类任务有真实可操作对象。
"""
import pathlib
import zipfile

from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parent.parent
TASKS = ROOT / "tasks"

# ---------- T8: 最小合法 .docx ----------
_CT = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
       '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
       '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
       '<Default Extension="xml" ContentType="application/xml"/>'
       '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
       '</Types>')
_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
         '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
         '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
         '</Relationships>')


def _para(text, bold=False):
    r = ('<w:pPr><w:rPr><w:b/></w:rPr></w:pPr>' if bold else '')
    return (f'<w:p>{r}<w:r>' + ('<w:rPr><w:b/></w:rPr>' if bold else '') +
            f'<w:t xml:space="preserve">{text}</w:t></w:r></w:p>')


_body = "".join([
    _para("第一章 合作范围", bold=True),
    _para("甲乙双方就软件评测服务达成如下合作。本章约定服务范围与交付物。"),
    _para("第二章 费用与结算", bold=True),
    _para("服务费总额为人民币伍万元整,分两期支付。"),
    _para("第三章 保密条款", bold=True),
    _para("双方对评测数据及结果负有保密义务,未经许可不得对外披露。"),
    _para("第四章 违约责任", bold=True),
    _para("任何一方违约,应赔偿由此给对方造成的实际损失。"),
])
_DOC = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f'<w:body>{_body}<w:sectPr/></w:body></w:document>')

docx_path = TASKS / "T8-word-contract-001/input/contract-draft.docx"
docx_path.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(docx_path, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("[Content_Types].xml", _CT)
    z.writestr("_rels/.rels", _RELS)
    z.writestr("word/document.xml", _DOC)
print("T8 contract-draft.docx 已生成")


def _img(path: pathlib.Path, lines, size=(600, 400), bg=(245, 245, 245)):
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(im)
    y = 30
    for ln in lines:
        d.text((30, y), ln, fill=(20, 20, 20))
        y += 40
    im.save(path)


# ---------- T14: 收据图(脏录入: 金额/日期需人读) ----------
_img(TASKS / "T14-accounting-dirty-entry-001/input/receipts/receipt-01.png",
     ["RECEIPT / 收据", "Date: 2025-07-03", "Item: 办公桌 x2", "Amount: ¥1,280.00", "No.0001"])
_img(TASKS / "T14-accounting-dirty-entry-001/input/receipts/receipt-02.png",
     ["收据", "日期: 2025/7/9", "餐饮招待", "金额: 860 元", "手写潦草-可辨"])
_img(TASKS / "T14-accounting-dirty-entry-001/input/receipts/receipt-03.png",
     ["INVOICE", "07-15-2025", "打车费", "USD 32.50", "#A-7788"])
print("T14 receipts/*.png 已生成")

# ---------- T15: 待重命名的照片 ----------
for i, name in enumerate(["IMG_0001.jpg", "IMG_0002.jpg", "IMG_0003.jpg",
                          "DSC_1010.jpg", "photo (1).jpg"], 1):
    _img(TASKS / f"T15-file-rename-001/input/photos/{name}",
         [f"Photo {i}", f"orig name: {name}", "2025 夏 旅行"], size=(400, 300),
         bg=(210, 225, 240))
print("T15 photos/*.jpg 已生成")

from pipeline import taskbank as TB  # noqa: E402
for t in ["T8-word-contract-001", "T14-accounting-dirty-entry-001",
          "T15-file-rename-001"]:
    probs = TB.validate_dir(TASKS / t)
    print(f"  {t}: {'OK' if not probs else probs}")
