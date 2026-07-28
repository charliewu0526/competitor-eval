"""补齐 T12/T13 剪映任务的视频占位素材(无 ffmpeg)。

写一个极小的合法 MP4 容器(ftyp + 空 mdat): 足够让文件存在、被识别为 .mp4、
任务可领可跑。剪映类任务本就是"给谁跑都难"的高门槛题, 占位视频让链路通;
真要精评画质/剪辑, 后续换成真实拍摄素材即可(占位不影响 GATE/领取/提交流程)。
"""
import pathlib
import struct

ROOT = pathlib.Path(__file__).resolve().parent.parent
TASKS = ROOT / "tasks"


def _minimal_mp4() -> bytes:
    def box(typ: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", 8 + len(payload)) + typ + payload
    ftyp = box(b"ftyp", b"isom" + struct.pack(">I", 0x200) + b"isomiso2mp41")
    mdat = box(b"mdat", b"\x00" * 64)   # 占位媒体数据
    return ftyp + mdat


def _write_mp4(rel: str):
    p = TASKS / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(_minimal_mp4())
    return p


# T12: 单个待裁剪片段
_write_mp4("T12-capcut-trim-001/input/clip.mp4")
# T13: raw-footage/ 下 5 个待调色+转场的片段
for i in range(1, 6):
    _write_mp4(f"T13-capcut-color-render-001/input/raw-footage/clip-{i:02d}.mp4")

print("T12/T13 视频占位素材已生成")

from pipeline import taskbank as TB  # noqa: E402
for t in ["T12-capcut-trim-001", "T13-capcut-color-render-001"]:
    probs = TB.validate_dir(TASKS / t)
    print(f"  {t}: {'OK' if not probs else probs}")
