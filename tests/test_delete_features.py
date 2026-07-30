"""删除功能守卫测试: 撤回已上传产物(submissions.delete_product) + 删除成员(rbac.remove_user)。

覆盖用户反馈 ur-c8e74c24300c(收口前可删产物)与新增的删除成员功能。守卫是安全边界,
必须有独立断言: 谁能删、什么状态可删、末位 owner / 删自己被挡住。
"""
import os
import tempfile
import unittest

from pipeline import store, submissions as SUB, rbac as RBAC, artifact_store as ART


def _mkcon():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    con = store.connect(db_path=path)
    return con


class DeleteSubmissionGuards(unittest.TestCase):
    def setUp(self):
        self.con = _mkcon()
        store.upsert_user(self.con, {"id": "u1", "name": "Intern One", "role": "intern"})
        store.upsert_user(self.con, {"id": "u2", "name": "Intern Two", "role": "intern"})
        store.upsert_assignment(self.con, {
            "id": "a1", "task_id": "T1", "products": ["vio"], "status": "open"})

    def _claim_and_submit(self):
        store.claim_assignment(self.con, "a1", "u1")
        store.upsert_submission(self.con, {
            "id": "s1", "assignment_id": "a1", "product": "vio",
            "artifact_path": "/tmp/x.zip", "log_bundle_path": "/tmp/l.zip",
            "submitted_by": "u1"})

    def test_holder_can_delete_when_claimed(self):
        self._claim_and_submit()
        paths = SUB.delete_product(self.con, assignment_id="a1", product="vio",
                                   requested_by="u1")
        self.assertIsNotNone(paths)
        self.assertEqual(paths["artifact_path"], "/tmp/x.zip")
        # 删后进度里该产品消失。
        prog = SUB.submission_progress(self.con, "a1")
        self.assertNotIn("vio", prog["submitted"])

    def test_non_holder_cannot_delete(self):
        self._claim_and_submit()
        with self.assertRaises(SUB.NotSubmittable):
            SUB.delete_product(self.con, assignment_id="a1", product="vio",
                               requested_by="u2")

    def test_cannot_delete_after_submitted(self):
        self._claim_and_submit()
        store.set_assignment_status(self.con, "a1", "submitted")
        with self.assertRaises(SUB.NotSubmittable):
            SUB.delete_product(self.con, assignment_id="a1", product="vio",
                               requested_by="u1")

    def test_delete_missing_is_idempotent(self):
        store.claim_assignment(self.con, "a1", "u1")
        # 没提交过 -> 返回 None, 不报错。
        self.assertIsNone(SUB.delete_product(
            self.con, assignment_id="a1", product="vio", requested_by="u1"))


class RemoveUserGuards(unittest.TestCase):
    def setUp(self):
        self.con = _mkcon()
        store.upsert_user(self.con, {"id": "owner1", "name": "PM", "role": "owner"})
        store.upsert_user(self.con, {"id": "owner2", "name": "PM2", "role": "owner"})
        store.upsert_user(self.con, {"id": "i1", "name": "Intern", "role": "intern"})
        self.owner = {"id": "owner1", "role": "owner"}
        self.intern = {"id": "i1", "role": "intern"}

    def test_owner_can_remove_intern(self):
        removed = RBAC.remove_user(self.con, actor=self.owner, target_user_id="i1")
        self.assertEqual(removed["id"], "i1")
        self.assertIsNone(store.get_user(self.con, "i1"))

    def test_non_owner_denied(self):
        with self.assertRaises(RBAC.PermissionDenied):
            RBAC.remove_user(self.con, actor=self.intern, target_user_id="owner2")

    def test_cannot_delete_self(self):
        with self.assertRaises(RBAC.PermissionDenied):
            RBAC.remove_user(self.con, actor=self.owner, target_user_id="owner1")

    def test_cannot_delete_last_owner(self):
        # 先删 owner2, 只剩 owner1; 再让另一 owner 视角删最后一个 owner 被挡。
        store.delete_user(self.con, "owner2")
        actor = {"id": "i-admin", "role": "owner"}  # 不同 id 的 owner 视角
        with self.assertRaises(RBAC.PermissionDenied):
            RBAC.remove_user(self.con, actor=actor, target_user_id="owner1")

    def test_missing_user_raises(self):
        with self.assertRaises(ValueError):
            RBAC.remove_user(self.con, actor=self.owner, target_user_id="ghost")


if __name__ == "__main__":
    unittest.main()
