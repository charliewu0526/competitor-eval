"""MR-15 (#52): 客户端交付物打包器 + 校验器 —— 提交链 (#43/#44/#45) 的离线前置。

实习生不懂怎么把「原始产物 + 执行日志包」收成服务端 intake(#38)认得的形状。
本模块在实习生机器上把一次运行收成一个**标准压缩包**:解开 = 一份 Submission
(intake.Submission)的离线载体。上传后服务端 intake 解包翻译成 RunRecord,评分核心
一字不改复用。

定位(#52):**一键自动导出为目标,优雅降级为底线。** 每家竞品导出机制不同 —— vio
自家能导完整轨迹 + 精确 token;闭源竞品只能拿它愿意给的。故形态 =
  通用打包器(本模块) + 每竞品导出配方(packaging/recipes/*.json,数据不是代码) +
  校验器(本模块 —— 真正降低出错率的地方)。

三条不能违反的边界:
  1. **缺数据如实标 unavailable** —— 闭源竞品拿不到的 token/日志标 unavailable,
     校验器放行;绝不伪装成 0(呼应 cost_source 诚实原则,与 intake 同源)。
  2. **只收证据,不下判定** —— 末态是否达成由实习生人工勾选(manual_assertions,
     #44),绝不从竞品自述日志「读出成功」。claimed_success 只是自报占位,喂 H1。
  3. **manifest 标产品身份** —— 压缩包 manifest.json 明确标这是哪个产品,好让服务端
     intake 知道怎么脱敏(ADR-0013);脱敏在服务端做,skill/本模块只收原始 + 如实标。

压缩包标准结构(= intake.Submission 契约的序列化,与 #37 store.submissions 对齐):
    <bundle>/
      manifest.json   —— 产品身份 + 任务/Assignment 引用 + claimed_success 占位 +
                          各字段 availability + 人工勾选断言 + 新鲜度(version/tested_at)
      artifacts/      —— 原始产物(截图 / 导出文件 / AI 对话记录);非空
      logs/log.json   —— 执行日志包(token/calls/timeline,或字段标 unavailable);
                          文件强制在(#45 AC1),包内字段拿不到照 unavailable 透传
"""
from __future__ import annotations

import json
import pathlib
import time
import zipfile

from pipeline.schema import COST_SOURCE_VALUES, EVIDENCE_SOURCE_VALUES

# 压缩包内固定路径(服务端 intake 解包时按同一约定找)。
MANIFEST_NAME = "manifest.json"
ARTIFACTS_DIR = "artifacts"
LOGS_DIR = "logs"
LOG_FILE = "logs/log.json"

# manifest.json 的固定形状版本 —— 服务端解包按此判方言。
MANIFEST_SCHEMA = "submission-bundle/v1"

# 日志包内每个成本字段的合法「拿不到」标记 —— 缺失照实标,绝不填 0 冒充。
UNAVAILABLE = "unavailable"

# 校验器认得的成本字段(要么给真值,要么显式标 unavailable)。
COST_FIELDS = ("input_tokens", "output_tokens", "model_calls")


class PackError(Exception):
    """打包/校验被拒的基类。skill 层翻成「当场拒绝出包」的报错。"""


class LogBundleMissing(PackError):
    """缺执行日志包文件 —— 无日志包不出包(镜像服务端 #45 AC1)。"""


class EvidenceMissing(PackError):
    """缺原始产物 —— 无可核查实体不出包(镜像服务端 #43 AC3)。"""


class FieldUnavailableUnmarked(PackError):
    """字段拿不到却没如实标 unavailable —— 沉默的缺失会被误当 0(#52 边界1)。"""


class ManifestInvalid(PackError):
    """manifest 结构/产品身份不合法 —— 服务端 intake 无法解包翻译。"""


# === 每竞品导出配方 (recipe) =================================================
# 配方是**数据/文档**,不是硬编码:随竞品增加只加 JSON 文件,打包器代码不动。
# 每份配方声明该产品能自动拿到哪些字段、拿不到的默认标 unavailable、以及给
# 实习生的半自动/手动导出指引(steps)。配方不做判定,只描述「怎么把证据收齐」。
RECIPE_DIR = pathlib.Path(__file__).resolve().parent.parent / "packaging" / "recipes"


def load_recipe(product: str, recipe_dir: pathlib.Path | None = None) -> dict:
    """读一个产品的导出配方。找不到 -> 退到 _default 配方(全字段手动 + 默认 unavailable),
    保证「没配方的新竞品也能打包」这一优雅降级底线。"""
    root = recipe_dir or RECIPE_DIR
    p = (root / f"{product}.json")
    if p.exists():
        data = json.loads(p.read_text())
        data.setdefault("product", product)
        return data
    dflt = root / "_default.json"
    if dflt.exists():
        data = json.loads(dflt.read_text())
        data["product"] = product
        data["_fallback"] = True
        return data
    # 连 _default 都没有(测试隔离场景)-> 内建最保守配方。
    return {"product": product, "_fallback": True, "auto_fields": [],
            "cost_source": "self-report", "evidence_source": "log", "steps": []}


def list_recipes(recipe_dir: pathlib.Path | None = None) -> list[str]:
    """已就绪的配方产品 id 列表(不含 _default)。"""
    root = recipe_dir or RECIPE_DIR
    if not root.exists():
        return []
    return sorted(p.stem for p in root.glob("*.json") if not p.stem.startswith("_"))


# === manifest 构造 ===========================================================

def build_manifest(*, product: str, assignment_id: str, task_id: str,
                   claimed_success: bool | None,
                   manual_assertions: dict | None = None,
                   cost: dict | None = None,
                   model: str | None = None,
                   cost_source: str = "self-report",
                   evidence_source: str = "log",
                   competitor_version: str | None = None,
                   tested_at: float | None = None,
                   run_idx: int = 1,
                   transcript_excerpt: str = "",
                   recipe: dict | None = None) -> dict:
    """组装 manifest.json 内容(= 序列化的 Submission 契约 + availability 元数据)。

    cost: {"input_tokens": int|"unavailable", "output_tokens": ..., "model_calls": ...}
          拿不到的字段传字符串 "unavailable"(而非 0)—— 缺失是信息,不伪装。
    每个字段的 available 标记由值是否 == "unavailable"/None 自动派生,写进
    manifest.availability,供人一眼看清「哪些是真数据、哪些如实缺」。
    """
    if cost_source not in COST_SOURCE_VALUES:
        raise ManifestInvalid(
            f"cost_source 必须是 {COST_SOURCE_VALUES} 之一,得到 {cost_source!r}")
    if evidence_source not in EVIDENCE_SOURCE_VALUES:
        raise ManifestInvalid(
            f"evidence_source 必须是 {EVIDENCE_SOURCE_VALUES} 之一,得到 {evidence_source!r}")

    cost = dict(cost or {})
    availability = {}
    log_cost = {}
    for f in COST_FIELDS:
        v = cost.get(f, UNAVAILABLE)
        avail = not (v is None or v == UNAVAILABLE)
        availability[f] = avail
        log_cost[f] = int(v) if avail else UNAVAILABLE
    availability["model"] = bool(model)
    availability["competitor_version"] = bool(competitor_version)

    return {
        "schema": MANIFEST_SCHEMA,
        "product": product,
        "assignment_id": assignment_id,
        "task_id": task_id,
        "run_idx": run_idx,
        # 立身之本:自报占位,仅喂 H1;末态达成由 manual_assertions 人工勾选认定。
        "claimed_success": claimed_success,
        "manual_assertions": dict(manual_assertions or {}),
        "transcript_excerpt": transcript_excerpt,
        # 成本/过程如实标:拿不到的字段是 "unavailable" 字符串,不是 0。
        "cost": log_cost,
        "model": model,
        "cost_source": cost_source,
        "evidence_source": evidence_source,
        # 新鲜度 (ADR-0017)。
        "competitor_version": competitor_version,
        "tested_at": tested_at if tested_at is not None else time.time(),
        # 各字段是否真拿到 —— 缺失如实标,校验器据此放行 unavailable。
        "availability": availability,
        "recipe": (recipe or {}).get("product", product),
        "packed_ts": time.time(),
    }


# === 校验器 —— #52 的核心价值(在实习生机器上当场拦缺证据,而非传到服务端才发现)===

def validate_manifest(manifest: dict) -> list[str]:
    """纯结构校验 manifest(不碰磁盘)。返回问题列表,空 = 合格。

    只校「服务端 intake 解包翻译必需」的骨架 + 诚实边界,不判末态、不改数据。
    """
    problems: list[str] = []
    if manifest.get("schema") != MANIFEST_SCHEMA:
        problems.append(
            f"manifest.schema 必须是 {MANIFEST_SCHEMA!r}(服务端据此解包),"
            f"得到 {manifest.get('schema')!r}")
    for k in ("product", "assignment_id", "task_id"):
        if not str(manifest.get(k) or "").strip():
            problems.append(f"manifest.{k} 缺失 —— 服务端 intake 无法定位这是哪个产品/任务")
    cs = manifest.get("cost_source")
    if cs not in COST_SOURCE_VALUES:
        problems.append(f"manifest.cost_source={cs!r} 非法(须 {COST_SOURCE_VALUES})")
    es = manifest.get("evidence_source")
    if es not in EVIDENCE_SOURCE_VALUES:
        problems.append(f"manifest.evidence_source={es!r} 非法(须 {EVIDENCE_SOURCE_VALUES})")

    # 诚实边界:每个成本字段要么是真 int,要么显式标 unavailable —— 不许沉默缺失、
    # 不许把拿不到写成 0。(0 是一个断言「这次真花了 0」,与「拿不到」语义不同。)
    cost = manifest.get("cost") or {}
    for f in COST_FIELDS:
        if f not in cost:
            problems.append(f"cost.{f} 既没给真值也没标 unavailable —— 缺失必须如实标")
            continue
        v = cost[f]
        if v == UNAVAILABLE:
            continue
        if not isinstance(v, int) or isinstance(v, bool):
            problems.append(f"cost.{f}={v!r} 必须是整数或 {UNAVAILABLE!r}")

    # cost_source 与数据自洽:标了 unavailable 的 source 却给出真 token,自相矛盾。
    if cs == "unavailable":
        real = [f for f in COST_FIELDS if cost.get(f) not in (UNAVAILABLE, None)]
        if real:
            problems.append(
                f"cost_source=unavailable 却给出真实成本字段 {real} —— 自相矛盾,"
                f"要么给 source,要么全标 unavailable")
    return problems


def validate_bundle_dir(bundle_dir: str | pathlib.Path) -> list[str]:
    """校验一个**已铺好的**打包目录(碰磁盘)。返回问题列表,空 = 合格可出包。

    三关(镜像服务端拒收,但在实习生机器上就拦住):
      1. 缺日志包文件 logs/log.json -> LogBundleMissing 级(#45 AC1)。
      2. artifacts/ 为空(无任何原始产物)-> EvidenceMissing 级(#43 AC3)。
      3. manifest 结构 + 诚实边界不合格(validate_manifest)。
    """
    root = pathlib.Path(bundle_dir).expanduser()
    problems: list[str] = []
    if not root.exists():
        return [f"打包目录不存在: {root}"]

    manifest_p = root / MANIFEST_NAME
    if not manifest_p.exists():
        problems.append(f"缺 {MANIFEST_NAME} —— 无产品身份,服务端无法脱敏/翻译")
    else:
        try:
            manifest = json.loads(manifest_p.read_text())
            problems.extend(validate_manifest(manifest))
        except (OSError, ValueError) as e:
            problems.append(f"{MANIFEST_NAME} 读不动/非合法 JSON: {e}")

    # 日志包文件强制(#45 AC1):文件必须在;包内字段拿不到照 unavailable(上面已校)。
    log_p = root / LOG_FILE
    if not log_p.exists() or log_p.stat().st_size == 0:
        problems.append(f"缺执行日志包 {LOG_FILE}(或为空)—— 无日志包不出包(#45 AC1)")

    # 原始产物强制(#43 AC3):artifacts/ 下至少一个非空实体。
    art_dir = root / ARTIFACTS_DIR
    real_artifacts = [p for p in art_dir.rglob("*")
                      if p.is_file() and p.stat().st_size > 0] if art_dir.exists() else []
    if not real_artifacts:
        problems.append(
            f"{ARTIFACTS_DIR}/ 无任何非空原始产物 —— 无可核查实体不出包(#43 AC3)")
    return problems


# === 打包 —— 把散落的证据铺成标准目录,校验,压成压缩包 =======================

def stage_bundle(bundle_dir, *, manifest: dict,
                 artifact_paths=None, log_facts=None) -> pathlib.Path:
    """把 manifest + 原始产物 + 日志包铺成标准目录结构(不压缩、不校验)。

    artifact_paths: 原始产物文件/目录路径列表;逐个拷进 artifacts/(目录递归拷)。
    log_facts: 日志包内容 dict(token/calls/timeline 或标 unavailable);写成 logs/log.json。
               默认取 manifest 里已组装好的 cost/model/source/events。
    返回铺好的目录路径。
    """
    import shutil
    root = pathlib.Path(bundle_dir).expanduser()
    (root / ARTIFACTS_DIR).mkdir(parents=True, exist_ok=True)
    (root / LOGS_DIR).mkdir(parents=True, exist_ok=True)

    (root / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2))

    # 日志包:默认从 manifest 派生(cost/model/source),可被显式 log_facts 覆盖。
    # 关键对齐(intake 契约):log.json 的 token 字段必须是**可解析的数字**,
    # 「拿不到」这个事实由 cost_source="unavailable" 承载(镜像 intake._empty_log_facts:
    # tokens=0 + cost_source=unavailable)。manifest 里保留 "unavailable" 字符串 +
    # availability 标记供人/脱敏看清,但喂给服务端解析器的日志包不塞非数字 sentinel。
    if log_facts is None:
        def _num(f):
            v = manifest["cost"].get(f, UNAVAILABLE)
            return 0 if (v is None or v == UNAVAILABLE) else int(v)
        log_facts = {
            "input_tokens": _num("input_tokens"),
            "output_tokens": _num("output_tokens"),
            "model_calls": _num("model_calls"),
            "model": manifest.get("model"),
            "cost_source": manifest.get("cost_source", "self-report"),
            "evidence_source": manifest.get("evidence_source", "log"),
            "events": manifest.get("events", []),
        }
    (root / LOG_FILE).write_text(
        json.dumps(log_facts, ensure_ascii=False, indent=2))

    for src in (artifact_paths or []):
        sp = pathlib.Path(src).expanduser()
        if not sp.exists():
            raise EvidenceMissing(f"声明的原始产物不存在: {sp}")
        dest = root / ARTIFACTS_DIR / sp.name
        if sp.is_dir():
            shutil.copytree(sp, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(sp, dest)
    return root


def zip_bundle(bundle_dir, out_zip=None) -> pathlib.Path:
    """把一个**已校验合格**的打包目录压成 .zip(服务端 intake 解包的载体)。
    先跑校验:不合格 raise,当场拒绝出包(#52 核心 —— 不把缺证据的包传上去)。"""
    root = pathlib.Path(bundle_dir).expanduser()
    problems = validate_bundle_dir(root)
    if problems:
        raise PackError("打包目录未通过校验,拒绝出包:\n  - " + "\n  - ".join(problems))
    out = pathlib.Path(out_zip).expanduser() if out_zip \
        else root.with_suffix(".zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(root.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(root))
    return out


def pack(*, bundle_dir, product, assignment_id, task_id,
         claimed_success, artifact_paths, log_facts=None,
         manual_assertions=None, cost=None, model=None,
         cost_source="self-report", evidence_source="log",
         competitor_version=None, tested_at=None, run_idx=1,
         transcript_excerpt="", recipe_dir=None, out_zip=None) -> dict:
    """一步到位:按配方组装 manifest -> 铺目录 -> 校验 -> 出 zip。

    返回 {"manifest", "bundle_dir", "zip", "problems"}。problems 非空表示未出包
    (校验挡下),zip 为 None。这是 skill/CLI 的主入口。
    """
    recipe = load_recipe(product, recipe_dir)
    # 配方可为「拿不到」的字段兜底默认 unavailable / 定 source。
    cost_source = cost_source or recipe.get("cost_source", "self-report")
    evidence_source = evidence_source or recipe.get("evidence_source", "log")

    manifest = build_manifest(
        product=product, assignment_id=assignment_id, task_id=task_id,
        claimed_success=claimed_success, manual_assertions=manual_assertions,
        cost=cost, model=model, cost_source=cost_source,
        evidence_source=evidence_source, competitor_version=competitor_version,
        tested_at=tested_at, run_idx=run_idx,
        transcript_excerpt=transcript_excerpt, recipe=recipe)

    stage_bundle(bundle_dir, manifest=manifest,
                 artifact_paths=artifact_paths, log_facts=log_facts)
    problems = validate_bundle_dir(bundle_dir)
    result = {"manifest": manifest, "bundle_dir": str(pathlib.Path(bundle_dir).expanduser()),
              "zip": None, "problems": problems}
    if not problems:
        result["zip"] = str(zip_bundle(bundle_dir, out_zip))
    return result
