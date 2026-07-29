"""MR-7 (#43): 服务端文件存储 — 原始产物 + 日志包落盘, 库里只存路径引用.

PRD/ADR-0019 拍板: 文件(原始产物 + 日志包)不进库, 走服务端文件目录; 数据库只
存路径引用, 不塞二进制。对象存储留作后续升级。本模块就是那个「服务端文件目录」的
最薄实现: 把上传的字节按 assignment/product 归档到磁盘, 回传一个稳定的绝对路径,
交给 store.upsert_submission 存引用、交给 intake 解析。

布局(每产品一个目录, 幂等可重传):
    <root>/<assignment_id>/<product>/artifact/<filename>
    <root>/<assignment_id>/<product>/log_bundle/<filename>

root 默认 board/uploads(与 SQLite 库同级, 一起 gitignore); 可用环境变量
COMPETITOR_EVAL_UPLOAD_ROOT 覆盖(部署时指向持久卷)。文件名做基本清洗防目录穿越。
"""
from __future__ import annotations

import os
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_UPLOAD_ROOT = ROOT / "board" / "uploads"


def upload_root() -> pathlib.Path:
    """文件目录根: 环境变量覆盖优先, 否则 board/uploads。"""
    env = os.environ.get("COMPETITOR_EVAL_UPLOAD_ROOT")
    return pathlib.Path(env) if env else DEFAULT_UPLOAD_ROOT


_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_name(name: str | None, *, fallback: str) -> str:
    """清洗上传文件名: 只留字母数字点划线, 去路径分隔与 .. , 防目录穿越。"""
    base = os.path.basename(name or "").strip()
    base = _SAFE.sub("_", base).strip("._") or fallback
    return base[:200]


def _safe_seg(seg: str) -> str:
    """清洗一个路径段(assignment_id / product): 同规则, 不允许空。"""
    s = _SAFE.sub("_", str(seg)).strip("._")
    return s or "_"


def save_upload(*, assignment_id: str, product: str, kind: str,
                filename: str | None, data: bytes,
                root: pathlib.Path | None = None) -> str:
    """把一份上传字节落盘, 回传绝对路径引用(存进 submissions 表的 *_path 列)。

    kind: "artifact"(原始产物)| "log_bundle"(执行日志包)。同 (assignment,
    product, kind, filename) 重传覆盖(幂等, 对齐 Submission 重交覆盖语义)。
    """
    if kind not in ("artifact", "log_bundle"):
        raise ValueError(f"kind 必须是 artifact|log_bundle, got {kind!r}")
    base = (root or upload_root())
    fname = _safe_name(filename, fallback=(kind + ".bin"))
    d = base / _safe_seg(assignment_id) / _safe_seg(product) / kind
    d.mkdir(parents=True, exist_ok=True)
    p = d / fname
    p.write_bytes(data)
    return str(p.resolve())


def has_bytes(data: bytes | None) -> bool:
    """上传是否算「有内容」: 非 None 且非空。空文件不算证据(防空壳上传)。"""
    return bool(data)


# === MR-B (#56): User Report 附件 (截图 / 自动附带的后端日志) ===============
# 复用同一条上传通道 (同 root、同文件名清洗、同「库里只存路径」约定), 不新建通道。
# 与 save_upload 的区别只是归档维度: Submission 按 assignment/product 分, User Report
# 按 report_id 分 (反馈没有 assignment/product 维度)。截图/日志按路径约定与 report
# 关联 —— 不占 user_report 表任何列 (呼应 MR-A「schema 一次性定死、后续票不再 migrate」)。
#
# 布局:
#     <root>/reports/<report_id>/screenshot/<filename>   (用户上传, 可多张)
#     <root>/reports/<report_id>/log/<filename>           (系统自动附带, 仅 owner/AI 可见)
_REPORT_KINDS = ("screenshot", "log")


def save_report_upload(*, report_id: str, kind: str, filename: str | None,
                       data: bytes, root: pathlib.Path | None = None) -> str:
    """把一份 User Report 附件字节落盘, 回传绝对路径引用。

    kind: "screenshot"(用户截图, 可多张)| "log"(系统自动附带的后端日志快照)。
    同 (report_id, kind, filename) 重传覆盖(幂等)。文件名走同一套清洗防目录穿越。
    """
    if kind not in _REPORT_KINDS:
        raise ValueError(f"kind 必须是 {_REPORT_KINDS}, got {kind!r}")
    base = (root or upload_root())
    fname = _safe_name(filename, fallback=(kind + ".bin"))
    d = base / "reports" / _safe_seg(report_id) / kind
    d.mkdir(parents=True, exist_ok=True)
    p = d / fname
    p.write_bytes(data)
    return str(p.resolve())


def list_report_uploads(report_id: str, kind: str,
                        root: pathlib.Path | None = None) -> list[str]:
    """列一条 report 某类附件的全部路径(截图给 owner 看板、日志给 owner/AI 诊断)。

    目录不存在(还没传过)-> 空列表, 不报错。按文件名排序稳定输出。
    """
    if kind not in _REPORT_KINDS:
        raise ValueError(f"kind 必须是 {_REPORT_KINDS}, got {kind!r}")
    d = (root or upload_root()) / "reports" / _safe_seg(report_id) / kind
    if not d.is_dir():
        return []
    return sorted(str(p.resolve()) for p in d.iterdir() if p.is_file())
