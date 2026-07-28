"""给 T15 重命名题的 5 张照片写入真实 EXIF 拍摄日期。

实习生反馈: 同样文件同样提示词, Violoop 拿"文件修改日期"当新名 —— 真凶是占位图
没有 EXIF 拍摄日期(题目要求按 EXIF capture date 重命名)。这不是产品问题, 是素材
缺基准。这里给 5 张图写入不同的拍摄日期, 让"按天分组+当天序号"有明确正确答案。

设计(按天分组, 制造"同一天多张"考验序号逻辑):
  IMG_0001.jpg -> 2025-07-15 09:12:03   \
  IMG_0002.jpg -> 2025-07-15 14:30:00    > 2025-07-15 两张
  IMG_0003.jpg -> 2025-07-16 08:05:00   -> 2025-07-16 一张
  DSC_1010.jpg -> 2025-08-01 20:00:00    \
  photo (1).jpg-> 2025-08-01 21:15:00    > 2025-08-01 两张
天内序号 NNN 按拍摄时间先后(次选原文件名)零填充。
"""
import pathlib
import piexif
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
PDIR = ROOT / "tasks" / "T15-file-rename-001" / "input" / "photos"

# (文件名, 拍摄时间 EXIF 格式 "YYYY:MM:DD HH:MM:SS")
SHOTS = [
    ("IMG_0001.jpg", "2025:07:15 09:12:03"),
    ("IMG_0002.jpg", "2025:07:15 14:30:00"),
    ("IMG_0003.jpg", "2025:07:16 08:05:00"),
    ("DSC_1010.jpg", "2025:08:01 20:00:00"),
    ("photo (1).jpg", "2025:08:01 21:15:00"),
]


def write_exif(path: pathlib.Path, dt: str):
    # 确保是合法 JPEG(占位图已是 jpg)。写 DateTimeOriginal + DateTimeDigitized + DateTime。
    exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
    exif_dict["0th"][piexif.ImageIFD.DateTime] = dt
    exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = dt
    exif_dict["Exif"][piexif.ExifIFD.DateTimeDigitized] = dt
    exif_bytes = piexif.dump(exif_dict)
    im = Image.open(path)
    im.save(path, "jpeg", exif=exif_bytes)


for name, dt in SHOTS:
    p = PDIR / name
    write_exif(p, dt)
    # 回读验证
    ex = piexif.load(str(p))
    got = ex["Exif"].get(piexif.ExifIFD.DateTimeOriginal, b"").decode() or "无"
    print(f"{name}: 写入拍摄日期={dt} | 回读={got}")

print("\nT15 EXIF 注入完成。")
