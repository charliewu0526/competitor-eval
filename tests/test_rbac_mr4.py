"""MR-4 (#40): 三级角色 RBAC 的权限边界 (ADR-0014).

Run: python -m unittest tests.test_rbac_mr4 -v

Acceptance (issue #40):
  - owner 能把 intern 提升为 reviewer
  - 校准/评委授权类操作仅 owner 可调用, reviewer/intern 被拒
  - 复核类入口 intern 被拒, reviewer/owner 放行
  - 权限边界有针对性测试 (每种角色 × 每类操作)

评分核心零改动: 本切片只加 pipeline/rbac.py 判定层 + server 两端点, 复用 MR-1
的 users 表与 set_user_role。
"""
from __future__ import annotations
import pathlib
import tempfile
import unittest

from pipeline import store, rbac


def _tmpdb():
    return str(pathlib.Path(tempfile.mkdtemp()) / "t.db")


def _u(role):
    return {"id": f"u_{role}", "name": role, "role": role}


# 每类操作的「最低放行角色」期望值 —— 与 rbac.PERMISSIONS 对齐的独立事实表,
# 用来跑「每种角色 × 每类操作」的全矩阵, 而非只抽查几个点。
_MIN_ROLE = {
    "promote_user": "owner",
    "delete_user": "owner",
    "issue_invite": "owner",
    "calibrate_golden": "owner",
    "authorize_reviewer": "owner",
    "manage_task_catalog": "owner",
    "manage_desensitization": "owner",
    "review": "reviewer",
    "gate_method": "reviewer",
    "claim_assignment": "intern",
    "submit": "intern",
    "submit_report": "intern",
    "view_report_console": "owner",
    "approve_patch": "owner",
}
_RANK = {"intern": 0, "reviewer": 1, "owner": 2}


class PermissionMatrix(unittest.TestCase):
    def test_every_role_x_every_action(self):
        # 全矩阵: 3 角色 × 每类操作, can() 必须与「最低角色」阈值一致。
        for action, min_role in _MIN_ROLE.items():
            for role in ("intern", "reviewer", "owner"):
                expect = _RANK[role] >= _RANK[min_role]
                self.assertEqual(
                    rbac.can(role, action), expect,
                    f"{role} × {action} 期望 {expect}")

    def test_permissions_table_matches_expectations(self):
        # 防漂移: rbac 内部登记表与本测试的独立事实表必须覆盖同一批操作。
        self.assertEqual(set(rbac.PERMISSIONS), set(_MIN_ROLE))
        for action, min_role in _MIN_ROLE.items():
            self.assertEqual(rbac.PERMISSIONS[action], min_role)

    def test_anonymous_denied_everything(self):
        for action in _MIN_ROLE:
            self.assertFalse(rbac.can(None, action))
            self.assertFalse(rbac.can("ghost", action))

    def test_unknown_action_fails_fast(self):
        # 拼错权限名不能静默放行, 必须炸。
        with self.assertRaises(ValueError):
            rbac.can("owner", "nuke_everything")


class OwnerOnlySwitches(unittest.TestCase):
    """story 5: 校准/评委授权/任务清单/脱敏/角色提升 owner 独占。"""
    def test_reviewer_and_intern_cannot_touch_calibration(self):
        for action in ("calibrate_golden", "authorize_reviewer",
                       "manage_task_catalog", "manage_desensitization",
                       "promote_user", "issue_invite"):
            self.assertTrue(rbac.can("owner", action))
            self.assertFalse(rbac.can("reviewer", action),
                             f"reviewer 不该能 {action}")
            self.assertFalse(rbac.can("intern", action),
                             f"intern 不该能 {action}")

    def test_require_raises_for_non_owner(self):
        with self.assertRaises(rbac.PermissionDenied):
            rbac.require(_u("reviewer"), "calibrate_golden")
        with self.assertRaises(rbac.PermissionDenied):
            rbac.require(_u("intern"), "authorize_reviewer")
        # owner 放行且回传 user
        self.assertEqual(rbac.require(_u("owner"), "calibrate_golden")["role"],
                         "owner")


class ReviewBoundary(unittest.TestCase):
    """story 6 / AC3: 复核类 intern 被拒, reviewer/owner 放行。"""
    def test_intern_cannot_review(self):
        self.assertFalse(rbac.can("intern", "review"))
        with self.assertRaises(rbac.PermissionDenied):
            rbac.require(_u("intern"), "review")

    def test_reviewer_and_owner_can_review(self):
        self.assertTrue(rbac.can("reviewer", "review"))
        self.assertTrue(rbac.can("owner", "review"))
        self.assertEqual(rbac.require(_u("reviewer"), "review")["role"],
                         "reviewer")

    def test_method_gate_needs_reviewer(self):
        self.assertFalse(rbac.can("intern", "gate_method"))
        self.assertTrue(rbac.can("reviewer", "gate_method"))
        self.assertTrue(rbac.can("owner", "gate_method"))


class BaseActionsForAll(unittest.TestCase):
    """基础动作 intern 起, 三角色都能领取/提交。"""
    def test_all_roles_can_claim_and_submit(self):
        for role in ("intern", "reviewer", "owner"):
            self.assertTrue(rbac.can(role, "claim_assignment"))
            self.assertTrue(rbac.can(role, "submit"))
        self.assertFalse(rbac.can(None, "claim_assignment"))


class PromoteFlow(unittest.TestCase):
    """AC1: owner 能把 intern 提升为 reviewer (真落库)。"""
    def _seed(self):
        con = store.connect(_tmpdb())
        store.upsert_user(con, {"id": "owner1", "name": "PM", "role": "owner"})
        store.upsert_user(con, {"id": "intern1", "name": "Alice",
                                "role": "intern"})
        return con

    def test_owner_promotes_intern_to_reviewer(self):
        con = self._seed()
        out = rbac.promote(con, actor=_u("owner"),
                           target_user_id="intern1", new_role="reviewer")
        self.assertEqual(out["role"], "reviewer")
        # 落库可复读
        self.assertEqual(store.get_user(con, "intern1")["role"], "reviewer")

    def test_non_owner_cannot_promote(self):
        con = self._seed()
        with self.assertRaises(rbac.PermissionDenied):
            rbac.promote(con, actor=_u("reviewer"),
                         target_user_id="intern1", new_role="reviewer")
        with self.assertRaises(rbac.PermissionDenied):
            rbac.promote(con, actor=_u("intern"),
                         target_user_id="intern1", new_role="reviewer")
        # 未被提升
        self.assertEqual(store.get_user(con, "intern1")["role"], "intern")

    def test_promote_rejects_illegal_role(self):
        con = self._seed()
        with self.assertRaises(ValueError):
            rbac.promote(con, actor=_u("owner"),
                         target_user_id="intern1", new_role="superadmin")

    def test_promote_rejects_unknown_user(self):
        con = self._seed()
        with self.assertRaises(ValueError):
            rbac.promote(con, actor=_u("owner"),
                         target_user_id="ghost", new_role="reviewer")

    def test_owner_can_demote_reviewer_back(self):
        # 降权也是 owner 独占 (评委降权 story 5)。
        con = self._seed()
        rbac.promote(con, actor=_u("owner"),
                     target_user_id="intern1", new_role="reviewer")
        rbac.promote(con, actor=_u("owner"),
                     target_user_id="intern1", new_role="intern")
        self.assertEqual(store.get_user(con, "intern1")["role"], "intern")


if __name__ == "__main__":
    unittest.main()
