"""MR-B (#56): 提交反馈 + 截图 + 反馈台只读骨架.

验证外部行为, 不验实现细节 (prior art: test_submissions_mr7 / test_rbac_mr4):
  * 登录用户可提交反馈 (文字 + 截图 + 自动附日志), 记录进 submitted -> queued.
  * 截图经 artifact_store 复用通道存储并与 report 关联 (不新建上传通道).
  * 提交者可列出自己的反馈及状态; 返回中不含 diff/诊断字段 (story 5 边界).
  * owner 反馈台可列出全部反馈 + 状态 (只读).
  * RBAC: 未登录不能提交; intern 不能看反馈台; 提交者只读自己的状态.

真实 temp SQLite + 真实 temp upload dir + TestClient 全 OFFLINE, 不碰 board/ 生产库.

Run: python -m unittest tests.test_reports_submit_mrb -v
"""
from __future__ import annotations
import io
import pathlib
import tempfile
import unittest

from fastapi.testclient import TestClient

from pipeline import store
from pipeline import reports as R
from pipeline import artifact_store as ART


def _tmpdb():
    return str(pathlib.Path(tempfile.mkdtemp()) / "t.db")


# =============================================================================
# pipeline 层: 视图裁剪 (提交者看不到 diff/诊断; 反馈台看全量)
# =============================================================================
class SubmitterViewHidesInternals(unittest.TestCase):
    """story 5: 提交者只见状态, 内部诊断字段一律不带出。"""

    def _report_with_internals(self):
        con = store.connect(_tmpdb())
        r = R.create(con, "u1", "看板白屏")
        # 推到 patch-ready 并塞满所有内部字段 (模拟 C 干完的样子)。
        R.enqueue(con, r["id"])
        R.start_ai(con, r["id"], branch_name="fix/ur-x")
        R.mark_patch_ready(con, r["id"], diff_ref="/uploads/reports/x/diff.patch",
                           test_result="3 passed")
        return con, R.get(con, r["id"])

    def test_submitter_view_omits_all_internal_fields(self):
        _, row = self._report_with_internals()
        v = R.submitter_view(row)
        for leaked in ("branch_name", "diagnosis", "diff_ref",
                       "test_result", "good_commit"):
            self.assertNotIn(leaked, v, f"提交者视图泄露了内部字段 {leaked!r}")

    def test_submitter_view_keeps_status_and_human_label(self):
        _, row = self._report_with_internals()
        v = R.submitter_view(row)
        self.assertEqual(v["status"], "patch-ready")
        self.assertEqual(v["status_label"], "处理中")   # 内部态名不外泄, 只给人话
        self.assertIn("id", v)
        self.assertIn("text", v)

    def test_console_view_keeps_internals(self):
        _, row = self._report_with_internals()
        v = R.console_view(row)
        self.assertEqual(v["diff_ref"], "/uploads/reports/x/diff.patch")
        self.assertEqual(v["branch_name"], "fix/ur-x")

    def test_status_labels_cover_all_states(self):
        # 每个状态都必须有人话标签 (不能给提交者暴露原始态名或落空)。
        for s in R.STATES:
            self.assertIn(s, R._SUBMITTER_STATUS_LABEL, f"状态 {s!r} 缺人话标签")


class ListViewsTrimByRole(unittest.TestCase):
    def test_list_for_submitter_only_mine_and_trimmed(self):
        con = store.connect(_tmpdb())
        R.create(con, "alice", "问题A")
        R.create(con, "bob", "问题B")
        # alice 只应看到自己那条, 且不含 diff/诊断。
        mine = R.list_for_submitter(con, "alice")
        self.assertEqual([m["submitter"] for m in mine], ["alice"])
        self.assertNotIn("diff_ref", mine[0])
        self.assertIn("status_label", mine[0])

    def test_list_for_console_has_all(self):
        con = store.connect(_tmpdb())
        R.create(con, "alice", "问题A")
        R.create(con, "bob", "问题B")
        rows = R.list_for_console(con)
        self.assertEqual({r["submitter"] for r in rows}, {"alice", "bob"})


# =============================================================================
# artifact_store 复用通道: report 截图/日志按 report_id 归档
# =============================================================================
class ReportUploadChannel(unittest.TestCase):
    def test_save_and_list_screenshots(self):
        root = pathlib.Path(tempfile.mkdtemp())
        p1 = ART.save_report_upload(report_id="ur-1", kind="screenshot",
                                    filename="a.png", data=b"img1", root=root)
        p2 = ART.save_report_upload(report_id="ur-1", kind="screenshot",
                                    filename="b.png", data=b"img2", root=root)
        self.assertTrue(pathlib.Path(p1).is_file())
        got = ART.list_report_uploads("ur-1", "screenshot", root=root)
        self.assertEqual(len(got), 2)
        self.assertIn(p1, got)
        self.assertIn(p2, got)

    def test_list_empty_when_none(self):
        root = pathlib.Path(tempfile.mkdtemp())
        self.assertEqual(ART.list_report_uploads("nope", "log", root=root), [])

    def test_bad_kind_rejected(self):
        root = pathlib.Path(tempfile.mkdtemp())
        with self.assertRaises(ValueError):
            ART.save_report_upload(report_id="ur-1", kind="diff",
                                   filename="x", data=b"y", root=root)

    def test_filename_sanitized_no_traversal(self):
        root = pathlib.Path(tempfile.mkdtemp())
        p = ART.save_report_upload(report_id="ur-1", kind="screenshot",
                                   filename="../../etc/passwd", data=b"x",
                                   root=root)
        # 落点仍在 reports/ur-1/screenshot/ 下, 未穿越出去。
        self.assertIn("/reports/ur-1/screenshot/", p)
        self.assertNotIn("..", pathlib.Path(p).name)


# =============================================================================
# server 层: 提交 -> queued, RBAC 边界, 反馈台
# =============================================================================
class _ServerCase(unittest.TestCase):
    def setUp(self):
        import server.app as APP
        self._APP = APP
        self._orig_db = APP._DB_PATH
        self._orig_upload = ART.os.environ.get("COMPETITOR_EVAL_UPLOAD_ROOT")
        d = pathlib.Path(tempfile.mkdtemp())
        APP._DB_PATH = str(d / "t.db")
        ART.os.environ["COMPETITOR_EVAL_UPLOAD_ROOT"] = str(d / "uploads")
        self.client = TestClient(APP.app)
        # 直接在库里 seed 一个 owner + 一个 intern (无自举 owner 端点, 部署时植入)。
        con = APP._con()
        import time as _t
        store.upsert_user(con, {"id": "owner1", "name": "PM", "role": "owner",
                                "created_ts": _t.time()})
        store.upsert_user(con, {"id": "intern1", "name": "In", "role": "intern",
                                "created_ts": _t.time()})
        from pipeline import auth as AUTH
        self.owner_tok = AUTH.login(con, user_id="owner1")
        self.intern_tok = AUTH.login(con, user_id="intern1")

    def tearDown(self):
        self._APP._DB_PATH = self._orig_db
        if self._orig_upload is None:
            ART.os.environ.pop("COMPETITOR_EVAL_UPLOAD_ROOT", None)
        else:
            ART.os.environ["COMPETITOR_EVAL_UPLOAD_ROOT"] = self._orig_upload

    def _h(self, tok):
        return {"Authorization": f"Bearer {tok}"}


class SubmitFlow(_ServerCase):
    def test_intern_submits_with_screenshot_lands_queued(self):
        r = self.client.post(
            "/api/reports",
            data={"text": "任务页点提交没反应"},
            files=[("screenshots", ("shot.png", io.BytesIO(b"PNGDATA"), "image/png"))],
            headers=self._h(self.intern_tok))
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        # 提交即入队 (submitted -> queued), 提交者视图不含内部字段。
        self.assertEqual(body["status"], "queued")
        self.assertEqual(body["screenshots"], 1)
        self.assertNotIn("diff_ref", body)
        self.assertNotIn("diagnosis", body)

    def test_screenshot_persisted_via_artifact_store(self):
        r = self.client.post(
            "/api/reports",
            data={"text": "x"},
            files=[("screenshots", ("a.png", io.BytesIO(b"AAA"), "image/png"))],
            headers=self._h(self.intern_tok))
        rid = r.json()["id"]
        shots = ART.list_report_uploads(rid, "screenshot")
        self.assertEqual(len(shots), 1)
        self.assertTrue(pathlib.Path(shots[0]).is_file())

    def test_submit_without_screenshot_ok(self):
        # 截图非强制 (反馈只有文字也能提)。
        r = self.client.post("/api/reports", data={"text": "纯文字反馈"},
                             headers=self._h(self.intern_tok))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["screenshots"], 0)

    def test_anonymous_cannot_submit(self):
        r = self.client.post("/api/reports", data={"text": "匿名想报"})
        self.assertEqual(r.status_code, 403)


class MineAndConsole(_ServerCase):
    def _submit_as(self, tok, text):
        return self.client.post("/api/reports", data={"text": text},
                                headers=self._h(tok)).json()

    def test_submitter_lists_only_own_without_internals(self):
        self._submit_as(self.intern_tok, "我的问题1")
        self._submit_as(self.owner_tok, "owner也报一条")
        r = self.client.get("/api/reports/mine", headers=self._h(self.intern_tok))
        self.assertEqual(r.status_code, 200)
        rows = r.json()
        self.assertEqual([x["submitter"] for x in rows], ["intern1"])
        self.assertNotIn("diff_ref", rows[0])
        self.assertIn("status_label", rows[0])

    def test_mine_requires_login(self):
        r = self.client.get("/api/reports/mine")
        self.assertEqual(r.status_code, 401)

    def test_owner_console_lists_all(self):
        self._submit_as(self.intern_tok, "问题1")
        self._submit_as(self.owner_tok, "问题2")
        r = self.client.get("/api/reports/console", headers=self._h(self.owner_tok))
        self.assertEqual(r.status_code, 200, r.text)
        rows = r.json()
        self.assertEqual({x["submitter"] for x in rows}, {"intern1", "owner1"})
        # 只读骨架附截图/日志计数。
        self.assertIn("screenshot_count", rows[0])
        self.assertIn("has_log", rows[0])

    def test_intern_cannot_see_console(self):
        r = self.client.get("/api/reports/console", headers=self._h(self.intern_tok))
        self.assertEqual(r.status_code, 403)

    def test_console_requires_login(self):
        r = self.client.get("/api/reports/console")
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
