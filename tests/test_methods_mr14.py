"""MR-14 (#50): 方法初稿提炼 + 复核闸 + 导出.

Run: python -m unittest tests.test_methods_mr14 -v

Acceptance (issue #50), all OFFLINE (real temp SQLite):
  - intern 能在差距证据包上创建 Method 初稿 (draft)
  - draft 未经把关不能导出 (复核闸拦截)
  - reviewer/PM 可把关 draft->approved (intern 被拒)
  - approved 的 Method 可导出为研发可读格式 (竞品为何强 + Violoop 落地建议)

评分核心零改动: 本切片只加 pipeline/methods.py 策略/渲染层 + server 端点, 复用
MR-1 的 methods 表与 MR-4 的 gate_method 权限。
"""
from __future__ import annotations
import pathlib
import tempfile
import unittest

from pipeline import store, methods as METH, rbac as RBAC


def _tmpdb():
    return store.connect(str(pathlib.Path(tempfile.mkdtemp()) / "t.db"))


def _u(role, uid=None):
    return {"id": uid or f"u_{role}", "name": role, "role": role}


def _seed_gap(con, task="T1", product="manus"):
    """种一点差距证据: 基线 vio 与竞品各一条分数, 让导出文档能派生出分数差。"""
    for prod, sc in ((("vio"), 0.5), ((product), 0.8)):
        store.upsert_score(con, {
            "task_id": task, "product": prod, "run_idx": 1,
            "gate": "native-operable", "scored": True, "reason": None,
            "objective_ratio": 1.0, "sample_score": sc, "h1_honesty": None,
            "subjective": {"S1": 4}, "disagreement_flagged": [], "defects": []})


# =============================================================================
# 1. intern 创建方法初稿 (draft) — AC1
# =============================================================================
class DraftCreation(unittest.TestCase):
    def test_intern_can_draft(self):
        con = _tmpdb()
        m = METH.draft_method(con, author=_u("intern"), task_id="T1",
                              product="manus", draft="竞品用 X 手法, Violoop 落地 Y")
        self.assertEqual(m["status"], METH.DRAFT)
        self.assertEqual(m["product"], "manus")
        # 落库可复读
        self.assertEqual(store.get_method(con, m["id"])["status"], "draft")

    def test_author_recorded(self):
        # #6 修复: 方法初稿记录作者 id, 好追溯是谁提炼的。
        con = _tmpdb()
        m = METH.draft_method(con, author=_u("intern", uid="u_lin"), task_id="T1",
                              product="manus", draft="竞品用 X, Violoop 落地 Y")
        self.assertEqual(m["author"], "u_lin")
        # 落库可复读作者
        self.assertEqual(store.get_method(con, m["id"])["author"], "u_lin")

    def test_reviewer_and_owner_can_also_draft(self):
        con = _tmpdb()
        for role in ("reviewer", "owner"):
            m = METH.draft_method(con, author=_u(role), task_id="T1",
                                  product="manus", draft="x")
            self.assertEqual(m["status"], METH.DRAFT)

    def test_anonymous_cannot_draft(self):
        con = _tmpdb()
        with self.assertRaises(RBAC.PermissionDenied):
            METH.draft_method(con, author=None, task_id="T1",
                              product="manus", draft="x")

    def test_empty_draft_rejected(self):
        con = _tmpdb()
        with self.assertRaises(METH.MethodError):
            METH.draft_method(con, author=_u("intern"), task_id="T1",
                              product="manus", draft="   ")


# =============================================================================
# 2. draft 未经把关不能导出 — AC2 (复核闸核心)
# =============================================================================
class GateBlocksExport(unittest.TestCase):
    def test_draft_export_refused(self):
        con = _tmpdb()
        m = METH.draft_method(con, author=_u("intern"), task_id="T1",
                              product="manus", draft="x")
        with self.assertRaises(METH.NotApproved):
            METH.export_method(con, actor=_u("owner"), method_id=m["id"])
        # 状态未被推进 (仍 draft)
        self.assertEqual(store.get_method(con, m["id"])["status"], "draft")

    def test_export_missing_method_404like(self):
        con = _tmpdb()
        with self.assertRaises(METH.MethodNotFound):
            METH.export_method(con, actor=_u("owner"), method_id=999)


# =============================================================================
# 3. reviewer/PM 把关 draft->approved — AC3
# =============================================================================
class ApprovalGate(unittest.TestCase):
    def _draft(self, con):
        return METH.draft_method(con, author=_u("intern"), task_id="T1",
                                 product="manus", draft="x")

    def test_reviewer_approves(self):
        con = _tmpdb()
        m = self._draft(con)
        out = METH.approve_method(con, reviewer=_u("reviewer", "rv1"),
                                  method_id=m["id"])
        self.assertEqual(out["status"], METH.APPROVED)
        self.assertEqual(out["gated_by"], "rv1")   # 把关人落审计

    def test_owner_can_also_approve(self):
        con = _tmpdb()
        m = self._draft(con)
        out = METH.approve_method(con, reviewer=_u("owner"), method_id=m["id"])
        self.assertEqual(out["status"], METH.APPROVED)

    def test_intern_cannot_approve(self):
        con = _tmpdb()
        m = self._draft(con)
        with self.assertRaises(RBAC.PermissionDenied):
            METH.approve_method(con, reviewer=_u("intern"), method_id=m["id"])
        self.assertEqual(store.get_method(con, m["id"])["status"], "draft")

    def test_cannot_reapprove_non_draft(self):
        con = _tmpdb()
        m = self._draft(con)
        METH.approve_method(con, reviewer=_u("reviewer"), method_id=m["id"])
        with self.assertRaises(METH.IllegalMethodState):
            METH.approve_method(con, reviewer=_u("reviewer"), method_id=m["id"])


# =============================================================================
# 4. approved 可导出为研发可读格式 — AC4
# =============================================================================
class ExportRender(unittest.TestCase):
    def _approved(self, con):
        _seed_gap(con)
        m = METH.draft_method(con, author=_u("intern"), task_id="T1",
                              product="manus",
                              draft="竞品的多步规划更稳; Violoop 建议引入显式计划树")
        return METH.approve_method(con, reviewer=_u("reviewer", "rv1"),
                                   method_id=m["id"])

    def test_export_moves_to_exported_and_renders(self):
        con = _tmpdb()
        m = self._approved(con)
        out = METH.export_method(con, actor=_u("owner"), method_id=m["id"])
        self.assertEqual(out["method"]["status"], METH.EXPORTED)
        doc = out["document"]
        # 研发可读: 含竞品身份 + 人写的落地建议 + 机器派生的分数差
        self.assertIn("manus", doc)
        self.assertIn("Violoop", doc)
        self.assertIn("显式计划树", doc)
        self.assertIn("差距证据", doc)
        self.assertIn("+0.300", doc)   # 0.8 - 0.5 分数差派生

    def test_export_is_idempotent_after_exported(self):
        con = _tmpdb()
        m = self._approved(con)
        METH.export_method(con, actor=_u("owner"), method_id=m["id"])
        # 再导出不炸, 仍 exported, 文档照出
        out = METH.export_method(con, actor=_u("owner"), method_id=m["id"])
        self.assertEqual(out["method"]["status"], METH.EXPORTED)
        self.assertIn("manus", out["document"])

    def test_intern_cannot_export(self):
        con = _tmpdb()
        m = self._approved(con)
        with self.assertRaises(RBAC.PermissionDenied):
            METH.export_method(con, actor=_u("intern"), method_id=m["id"])

    def test_missing_evidence_marked_unavailable(self):
        # 没种分数 -> 分数差如实标 unavailable, 绝不编造 0。
        con = _tmpdb()
        m = METH.draft_method(con, author=_u("intern"), task_id="ZZ",
                              product="ghost", draft="x")
        METH.approve_method(con, reviewer=_u("reviewer"), method_id=m["id"])
        out = METH.export_method(con, actor=_u("owner"), method_id=m["id"])
        self.assertIn("unavailable", out["document"])

    def test_preview_does_not_change_state(self):
        con = _tmpdb()
        _seed_gap(con)
        m = METH.draft_method(con, author=_u("intern"), task_id="T1",
                              product="manus", draft="x")
        doc = METH.preview_export(con, m["id"])
        self.assertIn("manus", doc)
        # 预览不推进状态 (仍 draft, 未导出)
        self.assertEqual(store.get_method(con, m["id"])["status"], "draft")


if __name__ == "__main__":
    unittest.main()
