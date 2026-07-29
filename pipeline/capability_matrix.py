"""C: 多竞品能力域对比矩阵 —— 把「vio 单产品失败反转」扩成「按域横向普查」.

功能A 原来只盯 vio 自己失败的题(线上仅 2 题,弹药太少)。本模块换视角:在**一个能力
域**里,把该域所有题 × 所有参赛产品的评测结果聚成一张矩阵,回答:

  这个域里,每个能力(题)——谁做到了、谁没做到、vio 处在什么位置?

矩阵里「有竞品做到、vio 没做到」的格子 = capability-gap 候选(该补的新功能);
「vio 做到、竞品普遍没做到」= vio 领先项(对称呈现,别漏看优势面)。

铁律沿袭:
  * cannot-reach 不算失败(没参赛、非差),不进空白判定。
  * 单次失败 ≠ 没能力:一道题失败前,先看该产品在**同域其他题**是否具备该能力
    ——具备则视为偶发失败,不判能力空白(降低误判)。
  * 机器只标疑似 capability-gap + 现象,不下结论;final_category 留空由 PM/AI 复核。
  * 纯派生,无副作用;粒度到能力域(PRD OQ2 拍板)。
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field, asdict

from pipeline.findings import make_finding

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TASKS_DIR = os.path.join(REPO, "tasks")

# 一道题的产品结果分类(矩阵格子取值)
DID = "did"                    # 做到了(有分且未失败)
DID_NOT = "did-not"            # 没做到(失败 / 0 分)
NOT_REACH = "cannot-reach"     # 够不着(没参赛,非差,不进空白判定)
NO_DATA = "no-data"            # 该产品这题没跑(无数据)


# --- task -> 能力域映射(读 meta.json 的 task_spec.capability_domain) ----------
_DOMAIN_CACHE: dict[str, str | None] = {}


def task_domain(task_id: str) -> str | None:
    """读 tasks/<id>/meta.json 的 task_spec.capability_domain。缺失 -> None(如实)。"""
    if task_id in _DOMAIN_CACHE:
        return _DOMAIN_CACHE[task_id]
    dom = None
    p = os.path.join(TASKS_DIR, task_id, "meta.json")
    try:
        with open(p, encoding="utf-8") as f:
            meta = json.load(f)
        dom = (meta.get("task_spec") or {}).get("capability_domain")
    except Exception:
        dom = None
    _DOMAIN_CACHE[task_id] = dom
    return dom


def tasks_in_domain(domain: str, all_task_ids) -> list[str]:
    """给定题号集合,筛出属于该能力域的题。"""
    return sorted(t for t in set(all_task_ids) if task_domain(t) == domain)


# --- 矩阵结构 --------------------------------------------------------------
def _is_cannot_reach(sc: dict) -> bool:
    return sc.get("gate") == "cannot-reach" or sc.get("reason") == "cannot-reach"


def _classify(sc: dict | None) -> str:
    """一个产品在一道题的结果分类。无记录 -> no-data;cannot-reach 单列;
    失败或 0 分 -> did-not;其余(有分)-> did。"""
    if sc is None:
        return NO_DATA
    if _is_cannot_reach(sc):
        return NOT_REACH
    val = sc.get("sample_score")
    if sc.get("objective_failed_primary") or (val is not None and float(val) <= 0.0):
        return DID_NOT
    if val is None and not sc.get("scored", True):
        return NO_DATA
    return DID


@dataclass
class MatrixCell:
    task_id: str
    product: str
    status: str                 # did | did-not | cannot-reach | no-data
    sample_score: float | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class CapabilityMatrix:
    domain: str
    baseline: str
    products: list[str]
    task_ids: list[str]
    cells: dict                 # task_id -> {product -> MatrixCell.as_dict()}
    gaps: list[dict] = field(default_factory=list)      # 竞品做到、vio 没做到
    leads: list[dict] = field(default_factory=list)     # vio 做到、竞品普遍没做到

    def as_dict(self) -> dict:
        return {"domain": self.domain, "baseline": self.baseline,
                "products": self.products, "task_ids": self.task_ids,
                "cells": self.cells, "gaps": self.gaps, "leads": self.leads}


def _product_has_capability_in_domain(product: str, domain: str,
                                      scores_by_task: dict, exclude_task: str) -> bool:
    """该产品在同域**其他题**是否具备能力(至少一题 did)。用于「单次失败≠没能力」守卫。"""
    for tid, sc_map in scores_by_task.items():
        if tid == exclude_task:
            continue
        if _classify(sc_map.get(product)) == DID:
            return True
    return False


def build_matrix(all_scores: list[dict], domain: str,
                 baseline: str = "vio") -> CapabilityMatrix:
    """按能力域聚合 scores 成矩阵(纯派生)。

    all_scores : store.all_scores(con) 全量分数行。
    只纳入该域的题;产品集合 = 该域内出现过的所有产品(注册顺序无关,按名排序,baseline 置首)。
    gaps: 某题竞品 did、vio did-not/no-data,且**该竞品在同域确有此能力**(排除偶发失败),
          且 vio 在同域其他题也没证明具备 -> capability-gap 候选(竞品维度)。
    leads: 某题 vio did、其余竞品普遍 did-not -> vio 领先项(对称呈现)。
    """
    dom_tasks = tasks_in_domain(domain, (s.get("task_id") for s in all_scores))
    scores_by_task: dict[str, dict] = {}
    products: set[str] = set()
    for s in all_scores:
        tid = s.get("task_id")
        if tid not in dom_tasks:
            continue
        scores_by_task.setdefault(tid, {})[s.get("product")] = s
        products.add(s.get("product"))
    prod_list = ([baseline] if baseline in products else []) + \
        sorted(p for p in products if p != baseline)

    cells: dict = {}
    for tid in dom_tasks:
        sc_map = scores_by_task.get(tid, {})
        cells[tid] = {}
        for p in prod_list:
            sc = sc_map.get(p)
            cells[tid][p] = MatrixCell(
                task_id=tid, product=p, status=_classify(sc),
                sample_score=(sc or {}).get("sample_score")).as_dict()

    gaps, leads = [], []
    for tid in dom_tasks:
        sc_map = scores_by_task.get(tid, {})
        vio_status = _classify(sc_map.get(baseline))
        # --- gaps: 竞品做到、vio 没做到 ---
        if vio_status in (DID_NOT, NO_DATA):
            # vio 在同域其他题若已证明具备该能力 -> 视为这题偶发失败, 不判空白(守卫)。
            vio_has_elsewhere = _product_has_capability_in_domain(
                baseline, domain, scores_by_task, tid)
            if not vio_has_elsewhere:
                for p in prod_list:
                    if p == baseline:
                        continue
                    # 竞品这题 did(确有能力)-> 记一条候选。竞品这题就是做到了,
                    # 本身即证据, 不再要求它在同域他题也做到(那会漏掉只这题会的竞品)。
                    if _classify(sc_map.get(p)) == DID:
                        gaps.append({"task_id": tid, "rival": p,
                                     "rival_score": (sc_map.get(p) or {}).get("sample_score"),
                                     "vio_status": vio_status})
        # --- leads: vio 做到、竞品普遍没做到 ---
        if vio_status == DID:
            rivals = [p for p in prod_list if p != baseline]
            if rivals and all(_classify(sc_map.get(p)) in (DID_NOT, NO_DATA, NOT_REACH)
                              for p in rivals):
                leads.append({"task_id": tid, "vio_score": (sc_map.get(baseline) or {}).get("sample_score")})

    return CapabilityMatrix(domain=domain, baseline=baseline, products=prod_list,
                            task_ids=dom_tasks, cells=cells, gaps=gaps, leads=leads)


def matrix_to_capability_gap_findings(matrix: CapabilityMatrix) -> list[dict]:
    """把矩阵的 gap 格子(竞品做到、vio 没做到)转成 capability-gap Finding.

    每条候选独立 task_id(matrix-<domain>-<指纹>),findings UNIQUE / methods 去重键
    都以 task_id 区分,避免同域多条塌成一条。指纹按 (域, 竞品, 原题) 稳定 -> 重跑幂等。
    subject=竞品。证据带原题 + 竞品分数 + 域。
    """
    out: list[dict] = []
    for g in matrix.gaps:
        rival = g["rival"]
        src_task = g["task_id"]
        key = f"{matrix.domain}|{rival}|{src_task}"
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]
        evid = [{"source": "capability-matrix",
                 "ref": f"[{rival}] 在能力域『{matrix.domain}』的题 {src_task} 做到了"
                        f"(分 {g.get('rival_score')}),基线 {matrix.baseline} 未做到"
                        f"({g.get('vio_status')})"}]
        phen = (f"能力域『{matrix.domain}』横向对比:{rival} 在 {src_task} 做到了,"
                f"基线 {matrix.baseline} 没做到,且在同域其他题也未证明具备该能力 —— "
                f"疑似能力空白, 候选新功能")
        f = make_finding(
            task_id=f"matrix-{matrix.domain}-{digest}", rule="capability-matrix",
            suspected_category="capability-gap", subject=rival,
            phenomenon=phen, evidence=evid)
        if f is not None:
            out.append(f.as_dict())
    return out
