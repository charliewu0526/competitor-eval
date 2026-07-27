"""MR-7 (#43): 提交管道 + 原始产物上传 + 缺证据拒收 + 流向 intake.

Run: python -m unittest tests.test_submissions_mr7 -v

Acceptance (issue #43), all OFFLINE (real temp SQLite + real temp upload dir):
  - 一道 Assignment 可为每个产品分别提交 Submission
  - 原始产物文件上传并持久化(服务端目录), 库里只存路径引用
  - 缺原始产物时提交被拒 (无证据不入池, story 17)
  - 提交的 Submission 能流向 #38 intake 接缝 -> RunRecord
外加守卫: 只能给参赛集内产品提交(领取粒度)、非 claimed / 非持有者不能交。
"""
from __future__ import annotations
import pathlib
import tempfile
import unittest

from pipeline import store as STORE
from pipeline import assignments as ASSIGN
from pipeline import submissions as SUB
from pipeline import artifact_store as ART
from pipeline import objective as O
from pipeline.registry_fakes import make_fake_registry
from pipeline.schema import RunRecord, GATE_VALUES, TaskSpec


def _tmp_db():
    return STORE.connect(pathlib.Path(tempfile.mkdtemp()) / "t.db")


# MR-9 (#45) 起日志包强制。MR-7 的「预期成功」用例补一个占位日志包路径,
# 让它们仍验证 MR-7 本职(原始产物 / 领取粒度 / 落库 / 流向 intake),不被
# 新的强制守卫误伤。缺日志包的「拒收」语义由 MR-9 专测覆盖。
_LOG = "/uploads/ASG/vio/log_bundle/log.json"


def _seed_assignment(con, *, products=("vio", "simular"), status="claimed",
                     claimed_by="u-intern-1"):
    """物化一个 Assignment 直接写库到指定状态(绕过 catalog, 测提交策略本身)。"""
    aid = "ASG-mr7-001"
    STORE.upsert_assignment(con, {
        "id": aid, "task_id": "T1-wechat-send-001",
        "products": list(products), "status": status,
        "claimed_by": claimed_by if status != "open" else None,
        "claimed_ts": 1_800_000_000.0 if status != "open" else None,
        "created_ts": 1_800_000_000.0})
    return aid


class _TaskMeta:
    """intake 消费的 duck-typed LoadedTask: T1 三条 manual_check 断言。"""
    def __init__(self, spec):
        self.task_spec = spec

    def assertions(self):
        return [
            O.manual_check("msg received", "msg_received", primary=True),
            O.manual_check("text exact", "text_exact", primary=True),
            O.manual_check("no collateral", "no_collateral", primary=False),
        ]


def _t1_spec():
    return TaskSpec(task_id="T1-wechat-send-001", domain="1", app="wechat",
                    prompt="send msg", core_assertions=["primary"],
                    requires_local_desktop=True, capability_domain="wechat-im")


# =============================================================================
# 每产品各一份 + 落库持久化(库里只存路径引用)
# =============================================================================
class SubmitPerProduct(unittest.TestCase):
    def setUp(self):
        self.con = _tmp_db()
        self.aid = _seed_assignment(self.con)

    def test_submit_one_product_persists_path_ref(self):
        row = SUB.submit_product(
            self.con, assignment_id=self.aid, product="vio",
            artifact_path="/uploads/ASG/vio/artifact/shot.png",
            log_bundle_path="/uploads/ASG/vio/log_bundle/log.json",
            manual_assertions={"msg_received": True}, claimed_success=True,
            submitted_by="u-intern-1")
        self.assertEqual(row["product"], "vio")
        self.assertEqual(row["artifact_path"],
                         "/uploads/ASG/vio/artifact/shot.png")
        # 库里存的是路径引用, 不是二进制
        rows = STORE.submissions_for(self.con, self.aid)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["log_bundle_path"],
                         "/uploads/ASG/vio/log_bundle/log.json")

    def test_each_product_separate_submission(self):
        SUB.submit_product(self.con, assignment_id=self.aid, product="vio",
                           artifact_path="/u/vio.png", log_bundle_path=_LOG,
                           submitted_by="u-intern-1")
        SUB.submit_product(self.con, assignment_id=self.aid, product="simular",
                           artifact_path="/u/sim.png", log_bundle_path=_LOG,
                           submitted_by="u-intern-1")
        prog = SUB.submission_progress(self.con, self.aid)
        self.assertEqual(sorted(prog["submitted"]), ["simular", "vio"])
        self.assertEqual(prog["missing"], [])
        self.assertTrue(prog["complete"])

    def test_progress_reports_missing(self):
        SUB.submit_product(self.con, assignment_id=self.aid, product="vio",
                           artifact_path="/u/vio.png", log_bundle_path=_LOG,
                           submitted_by="u-intern-1")
        prog = SUB.submission_progress(self.con, self.aid)
        self.assertEqual(prog["submitted"], ["vio"])
        self.assertEqual(prog["missing"], ["simular"])
        self.assertFalse(prog["complete"])

    def test_resubmit_same_product_overwrites(self):
        SUB.submit_product(self.con, assignment_id=self.aid, product="vio",
                           artifact_path="/u/old.png", log_bundle_path=_LOG,
                           submitted_by="u-intern-1")
        SUB.submit_product(self.con, assignment_id=self.aid, product="vio",
                           artifact_path="/u/new.png", log_bundle_path=_LOG,
                           submitted_by="u-intern-1")
        rows = STORE.submissions_for(self.con, self.aid)
        self.assertEqual(len(rows), 1)                 # UNIQUE(assignment,product)
        self.assertEqual(rows[0]["artifact_path"], "/u/new.png")


# =============================================================================
# 缺证据不入池: 缺原始产物 -> EvidenceMissing (#43 AC3, story 17)
# =============================================================================
class MissingEvidenceRejected(unittest.TestCase):
    def setUp(self):
        self.con = _tmp_db()
        self.aid = _seed_assignment(self.con)

    def test_no_artifact_rejected(self):
        with self.assertRaises(SUB.EvidenceMissing):
            SUB.submit_product(self.con, assignment_id=self.aid, product="vio",
                               artifact_path=None, submitted_by="u-intern-1")

    def test_blank_artifact_rejected(self):
        with self.assertRaises(SUB.EvidenceMissing):
            SUB.submit_product(self.con, assignment_id=self.aid, product="vio",
                               artifact_path="   ", submitted_by="u-intern-1")

    def test_rejected_submission_not_persisted(self):
        try:
            SUB.submit_product(self.con, assignment_id=self.aid, product="vio",
                               artifact_path=None, submitted_by="u-intern-1")
        except SUB.EvidenceMissing:
            pass
        self.assertEqual(STORE.submissions_for(self.con, self.aid), [])

    def test_missing_log_bundle_rejected(self):
        # MR-9 (#45) 起日志包强制: 缺执行日志包 -> LogBundleMissing(无日志包不入池)。
        # (原 MR-7 的「缺日志包放行」占位语义已被 #45 演进——它当年就注明「下一切片强制」。)
        with self.assertRaises(SUB.LogBundleMissing):
            SUB.submit_product(
                self.con, assignment_id=self.aid, product="vio",
                artifact_path="/u/vio.png", log_bundle_path=None,
                submitted_by="u-intern-1")


# =============================================================================
# 领取粒度 + 状态守卫
# =============================================================================
class GranularityAndStateGuards(unittest.TestCase):
    def setUp(self):
        self.con = _tmp_db()

    def test_product_not_in_participating_set_rejected(self):
        aid = _seed_assignment(self.con, products=("vio", "simular"))
        with self.assertRaises(SUB.WrongProduct):
            SUB.submit_product(self.con, assignment_id=aid, product="ghost",
                               artifact_path="/u/x.png", submitted_by="u-intern-1")

    def test_open_assignment_not_submittable(self):
        aid = _seed_assignment(self.con, status="open")
        with self.assertRaises(SUB.NotSubmittable):
            SUB.submit_product(self.con, assignment_id=aid, product="vio",
                               artifact_path="/u/x.png", submitted_by="u-intern-1")

    def test_non_holder_cannot_submit(self):
        aid = _seed_assignment(self.con, claimed_by="u-owner")
        with self.assertRaises(SUB.NotSubmittable):
            SUB.submit_product(self.con, assignment_id=aid, product="vio",
                               artifact_path="/u/x.png", submitted_by="u-intruder")

    def test_unknown_assignment_rejected(self):
        with self.assertRaises(SUB.NotSubmittable):
            SUB.submit_product(self.con, assignment_id="nope", product="vio",
                               artifact_path="/u/x.png", submitted_by="u-intern-1")


# =============================================================================
# 流向 #38 intake 接缝 -> RunRecord (#43 AC4)
# =============================================================================
class FlowsToIntakeSeam(unittest.TestCase):
    def setUp(self):
        self.con = _tmp_db()
        self.aid = _seed_assignment(self.con)
        self.reg = make_fake_registry()
        self.meta = _TaskMeta(_t1_spec())

    def test_submission_translates_to_runrecord(self):
        SUB.submit_product(
            self.con, assignment_id=self.aid, product="vio",
            artifact_path="/u/vio.png", log_bundle_path=_LOG,
            manual_assertions={"msg_received": True, "text_exact": True,
                               "no_collateral": True},
            claimed_success=True, submitted_by="u-intern-1",
            competitor_version="v1", tested_at=1_800_000_000.0)
        rr = SUB.to_run_record(self.con, assignment_id=self.aid, product="vio",
                               task_meta=self.meta, registry=self.reg)
        self.assertIsInstance(rr, RunRecord)
        self.assertEqual(rr.task_id, "T1-wechat-send-001")
        self.assertEqual(rr.product, "vio")
        self.assertIn(rr.gate, GATE_VALUES)
        # 人工勾选断言穿过 intake 落到客观层
        self.assertEqual(rr.objective_passed, 3)
        self.assertIs(rr.claimed_success, True)
        # 新鲜度字段随 Submission 透传(ADR-0017)
        self.assertEqual(rr.competitor_version, "v1")
        self.assertEqual(rr.tested_at, 1_800_000_000.0)

    def test_unreadable_log_bundle_yields_unavailable_not_fake_zero(self):
        # MR-9 起日志「文件」强制上传(交了包),但包内字段拿不到(黑箱竞品/坏包)
        # -> intake 标 cost/evidence unavailable(诚实, 不伪造 0-cost 成功)。
        # 这里交一个指向不存在文件的路径: 文件强制过关(有路径), 解析拿不到 -> unavailable。
        SUB.submit_product(
            self.con, assignment_id=self.aid, product="vio",
            artifact_path="/u/vio.png",
            log_bundle_path="/nope/does-not-exist.json",
            manual_assertions={"msg_received": True, "text_exact": True,
                               "no_collateral": True},
            submitted_by="u-intern-1")
        rr = SUB.to_run_record(self.con, assignment_id=self.aid, product="vio",
                               task_meta=self.meta, registry=self.reg)
        self.assertEqual(rr.cost_source, "unavailable")
        self.assertIsNone(rr.cost_usd)

    def test_to_run_record_missing_submission_raises(self):
        with self.assertRaises(SUB.SubmissionError):
            SUB.to_run_record(self.con, assignment_id=self.aid, product="vio",
                              task_meta=self.meta, registry=self.reg)


# =============================================================================
# 文件存储: 落盘 + 路径清洗防目录穿越
# =============================================================================
class ArtifactStorePersists(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())

    def test_save_and_read_back(self):
        p = ART.save_upload(assignment_id="ASG-1", product="vio",
                            kind="artifact", filename="shot.png",
                            data=b"PNGDATA", root=self.root)
        self.assertTrue(pathlib.Path(p).exists())
        self.assertEqual(pathlib.Path(p).read_bytes(), b"PNGDATA")

    def test_path_traversal_sanitized(self):
        p = ART.save_upload(assignment_id="../etc", product="vio",
                            kind="log_bundle", filename="../../evil.json",
                            data=b"{}", root=self.root)
        rp = pathlib.Path(p).resolve()
        # 落点必须仍在 root 之内(不被 ../ 穿越出去)
        self.assertTrue(str(rp).startswith(str(self.root.resolve())))
        self.assertNotIn("..", pathlib.Path(p).name)

    def test_invalid_kind_rejected(self):
        with self.assertRaises(ValueError):
            ART.save_upload(assignment_id="A", product="vio", kind="bogus",
                            filename="x", data=b"x", root=self.root)

    def test_empty_bytes_not_evidence(self):
        self.assertFalse(ART.has_bytes(b""))
        self.assertFalse(ART.has_bytes(None))
        self.assertTrue(ART.has_bytes(b"x"))


if __name__ == "__main__":
    unittest.main()
