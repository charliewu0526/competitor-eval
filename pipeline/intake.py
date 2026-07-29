"""MR-2 (#38): the intake seam — Submission → RunRecord.

This is the ONE new core seam the multi-runner platform (PRD-0003 #36) adds.
Everything upstream (Web / upload / auth / claim) only has to hand a Submission
to `translate`; everything downstream (GATE → objective → blind panel → H1 →
findings → leaderboard) is the EXISTING scoring core, consumed一字不改.

Iron rules carried across the seam (PRD 立身之本):
  1. GATE is DERIVED via gate.gate_for(competitor, task) from the F2 registry ×
     the F1 task requirement — NEVER trusted from the submission's self-report
     (an intern/竞品 can't self-declare it reached the target).
  2. Machine-verifiable objective assertions (file exists / value equals / a log
     event) are auto-judged from AUTHORITATIVE sources (server-resolved artifact
     path, parsed log events) — never from an intern's self-report; only the
     human-ticked assertions (「微信消息真发出了」) are read from the submission.
     MR-8 (#44) enforces this: an intern who ticks a key owned by a MACHINE
     assertion is REJECTED (AssertionScopeError). Both kinds still flow through
     the one objective.run_assertions; the split is the SOURCE of each ctx key.
  3. cost_* comes from PARSING the mandatory log bundle (token/call/timeline),
     folded to $ by the A3 price table — 拿不到 => unavailable, never a fake 0.
  4. claimed_success rides through untouched to feed the H1 honesty axis (E4).
  5. competitor_version + tested_at (ADR-0017 新鲜度) travel onto the RunRecord.

Same shape as the other 5 seam adapters: a production translator that touches
disk + the real price table, and an in-memory fake twin honoring the SAME
contract (a valid RunRecord with the same field set + identical GATE derivation),
so tests stay offline and the seam can't tell them apart.
"""
from __future__ import annotations

import json
import pathlib
import time
from dataclasses import dataclass, field

from pipeline.schema import RunRecord, COST_SOURCE_VALUES, EVIDENCE_SOURCE_VALUES
from pipeline import objective as O
from pipeline.gate import gate_for
from pipeline.cost_client import CostAccountant
from pipeline.logview import derive_views, LogViews


class AssertionScopeError(ValueError):
    """intern 试图手勾一个本该机器判的断言 (#44 立身之本守卫)。

    机器可验断言(文件存在 / 某格值 / 日志有无某事件)必须由脚本自动判,不落人手。
    若 submission.manual_assertions 里带了 MACHINE 断言拥有的 ctx 键,说明 intern
    想自报一个可核查的事实 —— 这会稀释「只看末态、机器判现象」的立身之本,拒收。
    """


# --- the seam INPUT: a Submission (one product, one run of one Assignment) -----
@dataclass
class Submission:
    """What an intern uploads for ONE product on one comparison task.

    Files (artifact + log bundle) stay on disk (ADR-0019); we carry path refs.
    manual_assertions = the human-ticked objective flags a script can't read
    (ctx keys the task's manual_check assertions consume). claimed_success feeds
    H1. competitor_version / tested_at are human-filled in the MVP.
    """
    assignment_id: str
    product: str
    task_id: str
    artifact_path: str | None = None
    log_bundle_path: str | None = None
    manual_assertions: dict = field(default_factory=dict)
    machine_ctx: dict = field(default_factory=dict)  # 服务端从产物/日志派生的机器输入(人碰不到)
    claimed_success: bool | None = None
    run_idx: int = 1
    transcript_excerpt: str = ""
    competitor_version: str | None = None
    tested_at: float | None = None

    @classmethod
    def from_store_row(cls, row: dict) -> "Submission":
        """Adapt a store.submissions row (manual_assertions already parsed)."""
        return cls(
            assignment_id=row["assignment_id"], product=row["product"],
            task_id=row.get("task_id", ""),
            artifact_path=row.get("artifact_path"),
            log_bundle_path=row.get("log_bundle_path"),
            manual_assertions=row.get("manual_assertions") or {},
            machine_ctx=row.get("machine_ctx") or {},
            claimed_success=row.get("claimed_success"),
            run_idx=row.get("run_idx", 1),
            transcript_excerpt=row.get("transcript_excerpt", ""),
            competitor_version=row.get("competitor_version"),
            tested_at=row.get("tested_at"))


# --- log-bundle parsing: the disk-touching part real/fake differ on -----------
# The parsed facts contract (both parsers return this shape):
#   {"cost_input_tokens", "cost_output_tokens", "cost_model_calls",
#    "model", "cost_source", "evidence_source", "events": [...]}
LOG_FACT_KEYS = {"cost_input_tokens", "cost_output_tokens", "cost_model_calls",
                 "model", "cost_source", "evidence_source", "events"}


def _empty_log_facts() -> dict:
    """No readable bundle -> honest unavailable (never a fake 0-cost success)."""
    return {"cost_input_tokens": 0, "cost_output_tokens": 0,
            "cost_model_calls": 0, "model": None,
            "cost_source": "unavailable", "evidence_source": "unavailable",
            "events": []}


def _coerce_facts(raw: dict) -> dict:
    """Validate + normalize a raw log dict into the LOG_FACT_KEYS contract."""
    src = raw.get("cost_source", "self-report")
    if src not in COST_SOURCE_VALUES:
        raise ValueError(f"cost_source must be one of {COST_SOURCE_VALUES}, got {src!r}")
    ev = raw.get("evidence_source", "log")
    if ev not in EVIDENCE_SOURCE_VALUES:
        raise ValueError(f"evidence_source must be one of {EVIDENCE_SOURCE_VALUES}, got {ev!r}")
    # None-safe: 诚实的 "unavailable" 日志会显式带 input_tokens=None(键存在但值为
    # None, dict.get 的默认参数不生效)。把 None / 缺失 / 空串统一归 0 ——「拿不到」
    # 这个事实由 cost_source=unavailable 承载, 不伪装成真花了 0 (与 skill 诚实原则同源)。
    def _int0(*keys):
        for k in keys:
            v = raw.get(k)
            if v is not None and v != "":
                return int(v)
        return 0
    return {
        "cost_input_tokens": _int0("input_tokens", "cost_input_tokens"),
        "cost_output_tokens": _int0("output_tokens", "cost_output_tokens"),
        "cost_model_calls": _int0("model_calls", "cost_model_calls"),
        "model": raw.get("model"),
        "cost_source": src,
        "evidence_source": ev,
        "events": list(raw.get("events", raw.get("timeline", []))),
    }


class LogBundleParser:
    """Production parser: read the mandatory log bundle (a JSON manifest) off disk.

    A missing / unreadable bundle yields honest 'unavailable' facts rather than
    inventing a free run — 拿不到 != 免费成功. (The Web layer already refused the
    submission if no bundle was uploaded; this is defence-in-depth.)
    """

    def parse(self, log_bundle_path: str | None) -> dict:
        if not log_bundle_path:
            return _empty_log_facts()
        p = pathlib.Path(log_bundle_path).expanduser()
        if not p.exists():
            return _empty_log_facts()
        try:
            raw = json.loads(p.read_text())
        except (OSError, ValueError):
            return _empty_log_facts()
        return _coerce_facts(raw)


def _artifact_filenames(artifact_path: str | None) -> set[str] | None:
    """从提交产物提取「文件名集合」(basename, 去目录前缀), 供机器断言比对。

    产物可能是: (a) .zip 压缩包 -> 读条目名; (b) 目录 -> 递归取文件名;
    (c) 单个文件 -> 该文件名本身。取不到(路径空/不存在/读失败) -> None
    (调用方据此不设 ctx 键, 让断言判 False —— 未验证 != 通过)。

    只取叶子文件名(basename), 忽略目录条目 —— 竞品把结果打包时目录结构各异
    (有的 input/photos/xxx, 有的直接 xxx), 判定只关心「产出了哪些文件名」。
    """
    if not artifact_path:
        return None
    p = pathlib.Path(artifact_path).expanduser()
    if not p.exists():
        return None
    try:
        if p.is_file() and p.suffix.lower() == ".zip":
            import zipfile
            with zipfile.ZipFile(p) as zf:
                names = set()
                for n in zf.namelist():
                    if n.endswith("/"):
                        continue  # 目录条目
                    names.add(pathlib.PurePosixPath(n).name)
                return names
        if p.is_dir():
            return {f.name for f in p.rglob("*") if f.is_file()}
        if p.is_file():
            return {p.name}
    except Exception:
        return None
    return None


def _build_ctx(submission: Submission, log_facts: dict,
               assertions: list) -> dict:
    """Assemble the objective-assertion ctx by SPLITTING inputs by source (#44).

    机器可验断言(MACHINE)的输入只从权威来源填,人绝不经手:
      * 产物路径(file_exists/file_nonempty)= 服务端落盘的 artifact_path。
      * 日志事件(log_event 的「日志有无某事件」)= 从日志包解析出的 events。
      * 某格值(equals)= 从产物/日志派生的 machine_ctx(MVP 暂无自动提取器时缺该
        键 -> 断言判 False,即「未验证 != 通过」,不伪装成功)。
    人工勾选断言(HUMAN)才从 submission.manual_assertions 读。

    守卫: intern 若在 manual_assertions 里带了 MACHINE 断言的 ctx 键(想手报一个
    可核查事实),raise AssertionScopeError —— 机器该判的不落人手。
    """
    manual = dict(submission.manual_assertions or {})
    machine_keys = O.machine_keys(assertions)
    human_keys = O.human_keys(assertions)

    trespass = machine_keys & set(manual)
    if trespass:
        raise AssertionScopeError(
            f"manual_assertions 携带了机器可验断言的键 {sorted(trespass)} —— "
            f"这些必须由脚本自动判定,不落人手。intern 只能勾选人工断言 "
            f"{sorted(human_keys)}")

    # 1. 人工勾选断言: 只取 HUMAN 断言拥有的键(其余无关键忽略,不污染 ctx)。
    ctx = {k: manual[k] for k in human_keys if k in manual}
    # 2. 机器可验断言的权威输入(人碰不到)。
    ctx["artifact_path"] = submission.artifact_path
    ctx["log_events"] = log_facts.get("events", [])
    # 产物文件名集合: 从服务端落盘的产物(zip/文件夹/单文件)提取 basename 集合,
    # 供 artifact_filenames_equal/superset 这类「产物即答案」的机器断言自动比对
    # (如 T15 文件重命名)。权威来源、人碰不到。提不到 -> 不设键(断言判 False)。
    names = _artifact_filenames(submission.artifact_path)
    if names is not None:
        ctx["artifact_filenames"] = names
    # 3. 从产物/日志派生的机器上下文(MVP: 无自动提取器 -> 缺键 -> equals 判 False)。
    for k, v in (submission.machine_ctx or {}).items():
        ctx.setdefault(k, v)
    return ctx


class SubmissionTranslator:
    """Production seam: Submission (+ its on-disk log bundle) -> RunRecord.

    Injectable log_parser + accountant default to the real disk/price-table
    impls; the fake twin swaps them for offline fixtures (see intake_fakes).
    """

    def __init__(self, *, log_parser=None, accountant=None):
        self.log_parser = log_parser or LogBundleParser()
        self.accountant = accountant or CostAccountant()

    def translate(self, submission: Submission, task_meta, registry) -> RunRecord:
        """Translate ONE Submission into a scoring-core-ready RunRecord.

        task_meta: duck-typed carrier of .task_spec (F1 TaskSpec) + .assertions
                   (callable -> list[objective.Assertion]). suite.LoadedTask fits.
        registry:  F2 registry (real or fake) — used ONLY to derive GATE + look
                   up competitor version; the submission never self-declares gate.
        """
        spec = task_meta.task_spec
        assertions = task_meta.assertions() if callable(task_meta.assertions) else []

        # 1. GATE — derived, never self-reported. Unregistered product => the
        #    seam refuses to fabricate a gate (can't fairly place an unknown).
        try:
            competitor = registry.get(submission.product)
        except KeyError as e:
            raise ValueError(
                f"product {submission.product!r} not in registry — cannot derive "
                f"GATE for an unregistered competitor") from e
        gate = gate_for(competitor, spec)

        # 2. Objective assertions — machine + human, one runner, split BY SOURCE.
        #    _build_ctx enforces the #44 guard: intern-ticked flags feed only
        #    HUMAN assertions; MACHINE assertions read authoritative refs only.
        log_facts = self.log_parser.parse(submission.log_bundle_path)
        ctx = _build_ctx(submission, log_facts, assertions)
        obj = O.run_assertions(assertions, ctx)

        # 3. Cost — folded from the PARSED log facts via the A3 price table.
        cost = self.accountant.account(
            model=log_facts["model"],
            input_tokens=log_facts["cost_input_tokens"],
            output_tokens=log_facts["cost_output_tokens"],
            model_calls=log_facts["cost_model_calls"],
            cost_source=log_facts["cost_source"])

        # 4. Freshness (ADR-0017): version from submission, else competitor build.
        version = submission.competitor_version
        tested_at = submission.tested_at if submission.tested_at is not None \
            else (submission.submitted_ts if hasattr(submission, "submitted_ts")
                  else time.time())

        return RunRecord(
            task_id=spec.task_id, product=submission.product,
            run_idx=submission.run_idx, gate=gate,
            objective_passed=obj["passed"], objective_total=obj["total"],
            objective_failed_primary=obj["failed_primary"],
            artifact_path=submission.artifact_path,
            transcript_excerpt=submission.transcript_excerpt,
            cost_input_tokens=cost["cost_input_tokens"],
            cost_output_tokens=cost["cost_output_tokens"],
            cost_model_calls=cost["cost_model_calls"],
            cost_usd=cost["cost_usd"], cost_source=cost["cost_source"],
            evidence_source=log_facts["evidence_source"],
            claimed_success=submission.claimed_success,
            competitor_version=version, tested_at=tested_at)


def log_views(submission: Submission, *, log_parser=None, registry=None,
              price_table=None) -> LogViews:
    """从一份 Submission 的日志包派生 raw / redacted 双视图 (#45 AC3/AC4, ADR-0013).

    raw = 完整解析事实(cost/token/model/timeline)—— 成本统计 + 人工抽查。
    redacted = 洗掉品牌 / 模型指纹 —— 喂盲评面板(盲评不被日志泄底)。

    脱敏词典 DERIVED:品牌来自 registry(缺省用生产 FileRegistry),模型来自
    price_table(缺省用 A3 生产价表)+ 本包实际用的 model 名。这样加竞品 / 加模型
    = 改数据不改脱敏代码。两视图共享同一套成本事实数值,只在身份指纹上分叉。
    """
    parser = log_parser or LogBundleParser()
    facts = parser.parse(submission.log_bundle_path)
    if registry is None:
        try:
            from pipeline.registry import default_registry
            registry = default_registry()
        except Exception:
            registry = None
    if price_table is None:
        try:
            from pipeline.cost_client import PriceTable
            price_table = PriceTable.load()
        except Exception:
            price_table = None
    return derive_views(facts, registry=registry, price_table=price_table)


# --- module-level convenience matching the AC signature ----------------------
_DEFAULT = SubmissionTranslator()


def translate(submission: Submission, task_meta, registry) -> RunRecord:
    """AC signature: translate(submission, task_meta, registry) -> RunRecord.

    Uses the default production translator (real disk parse + real price table).
    """
    return _DEFAULT.translate(submission, task_meta, registry)
