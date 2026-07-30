"""补齐 T8(Word docx) / T14(收据图) / T15(照片) 的输入素材。

python-docx 未装 -> 直接用 zipfile 写一个最小合法 .docx(OOXML 本质是 zip),
含若干段落 + 章节标题, 供任务"套用标题样式+加页码+导出PDF"。
收据图/照片用 Pillow 造占位图(带可辨识文字), 让文件类任务有真实可操作对象。
"""
import pathlib
import zipfile

from PIL import Image, ImageDraw, ImageFont

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


# 可读中英字体: Helvetica(拉丁) + STHeiti(中文)。缺字体时回退默认位图字体。
def _load_font(size, *, cjk=False):
    candidates = (
        ["/System/Library/Fonts/STHeiti Medium.ttc",
         "/System/Library/Fonts/PingFang.ttc"] if cjk else
        ["/System/Library/Fonts/Helvetica.ttc",
         "/System/Library/Fonts/Supplemental/Arial.ttf"])
    for p in candidates:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _img(path: pathlib.Path, lines, *, size=(700, 460), bg=(250, 250, 250),
         blur=False):
    """画一张收据图。lines=[(text, is_cjk, is_header)]。

    blur=True: 故意做成模糊/缺字段的脏样本(该被 flag, 不该猜)。清晰样本字号大、
    字段全(supplier/date/amount/currency/ref), 让每个可录收据都能被客观核验。
    """
    from PIL import ImageFilter
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(im)
    # 收据外框, 更像真实扫描件。
    d.rectangle([12, 12, size[0] - 12, size[1] - 12], outline=(120, 120, 120), width=2)
    y = 38
    for item in lines:
        # 兼容两种写法: 纯字符串(旧 T15 调用)或 (text, is_cjk, is_header) 元组。
        if isinstance(item, str):
            text, is_cjk, is_header = item, any(ord(c) > 127 for c in item), False
        else:
            text, is_cjk, is_header = item
        fsize = 40 if is_header else 30
        font = _load_font(fsize, cjk=is_cjk)
        d.text((36, y), text, fill=(15, 15, 15), font=font)
        y += 56 if is_header else 46
    if blur:
        # 轻度模糊 + 降对比, 模拟真实"拍糊/字迹不清"的不可辨认扫描件。
        im = im.filter(ImageFilter.GaussianBlur(radius=2.4))
    im.save(path)


# ---------- T14: 收据图(脏录入: 部分清晰可录, 一张模糊应被 flag) ----------
_R = TASKS / "T14-accounting-dirty-entry-001/input/receipts"
# receipt-01: 清晰、字段齐全(供应商/日期/用途/金额/币种/单号)—— 应被录入。
_img(_R / "receipt-01.png", [
    ("RECEIPT / 收据", False, True),
    ("Supplier / 供应商: 宜家家居 (Beijing)", True, False),
    ("Date / 日期: 2025-07-03", False, False),
    ("Purpose / 用途: 办公桌 x2", True, False),
    ("Amount / 金额: CNY 1,280.00", False, False),
    ("Ref No. / 单号: No.0001", False, False),
])
# receipt-03: 清晰、字段齐全(英文发票)—— 应被录入。
_img(_R / "receipt-03.png", [
    ("INVOICE", False, True),
    ("Supplier: City Taxi Co., Ltd.", False, False),
    ("Date: 2025-07-15", False, False),
    ("Purpose: Airport transfer (打车费)", True, False),
    ("Amount: USD 32.50", False, False),
    ("Ref No.: A-7788", False, False),
])
# receipt-02: 模糊 + 供应商/用途不可辨认 —— 这是"脏数据", 应被 flag 而非猜。
_img(_R / "receipt-02.png", [
    ("收据 (扫描不清)", True, True),
    ("供应商: ▓▓▓▓ (字迹不清)", True, False),
    ("日期: 2025/7/9", False, False),
    ("用途: ▓▓▓▓", True, False),
    ("金额: 860 (币种不明)", True, False),
], blur=True)
print("T14 receipts/*.png 已生成(01/03 清晰全字段, 02 模糊应 flag)")

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
