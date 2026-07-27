"""MR-11 (#47): 差距报告派生视图 (ADR-0012).

Run: python -m unittest tests.test_gap_report_mr11 -v

Acceptance (issue #47), all OFFLINE + pure(无 DB/网络):
  AC1 一道 Assignment(task_id)产出一份差距报告
  AC2 报告含 Violoop vs 各竞品分数差
  AC3 大差距自动生成 Finding(现象,机器只标不下结论)
  AC4 开源竞品附源码机理分析(带 repo 链接)

派生视图铁律:只读既有 scores/findings 组装,不新造判定;PM-fillable 字段原样带出;
cannot-reach 不当 0 参与作差;闭源/未分析的机理如实标 None。
"""
from __future__ import annotations
import unittest

from pipeline import gap_report as GR
from pipeline import findings as FIND
from pipeline.registry_fakes import make_fake_registry


def _score(product, task_id="T1", sample=0.5, gate="native-operable",
           scored=True, reason=None, h1=None, **kw):
    d = {"task_id": task_id, "product": product, "run_idx": 0,
         "gate": gate, "sample_score": sample, "scored": scored,
         "reason": reason, "h1_honesty": h1}
    d.update(kw)
    return d


class ScoreDiffs(unittest.TestCase):
    def test_baseline_vs_competitor_diff(self):
        # AC2: 分数差 = 竞品 - 基线(算术).
        scores = [_score("vio", sample=0.4),
                  _score("simular", sample=0.7)]
        rep = GR.build_report("T1", scores, [])
        sim = next(d for d in rep.score_diffs if d.product == "simular")
        self.assertEqual(sim.baseline_score, 0.4)
        self.assertEqual(sim.sample_score, 0.7)
        self.assertAlmostEqual(sim.diff, 0.3)
        self.assertTrue(sim.big_gap)          # 0.3 >= 0.15 CAPABILITY_LEAD

    def test_baseline_row_has_no_diff(self):
        scores = [_score("vio", sample=0.4), _score("simular", sample=0.7)]
        rep = GR.build_report("T1", scores, [])
        base = next(d for d in rep.score_diffs if d.is_baseline)
        self.assertIsNone(base.diff)
        self.assertIsNone(base.baseline_score)

    def test_small_gap_not_flagged_big(self):
        scores = [_score("vio", sample=0.5), _score("simular", sample=0.55)]
        rep = GR.build_report("T1", scores, [])
        sim = next(d for d in rep.score_diffs if d.product == "simular")
        self.assertAlmostEqual(sim.diff, 0.05)
        self.assertFalse(sim.big_gap)

    def test_cannot_reach_not_counted_as_zero(self):
        # cannot-reach = 没参赛,非差 —— diff 不可比(None),绝不当 0 拉低差距.
        scores = [_score("vio", sample=0.6),
                  _score("simular", sample=None, gate="cannot-reach",
                         scored=False, reason="cannot-reach")]
        rep = GR.build_report("T1", scores, [])
        sim = next(d for d in rep.score_diffs if d.product == "simular")
        self.assertTrue(sim.cannot_reach)
        self.assertIsNone(sim.diff)
        self.assertFalse(sim.big_gap)

    def test_diffs_sorted_baseline_first_then_lead_desc(self):
        scores = [_score("vio", sample=0.4),
                  _score("a", sample=0.5),
                  _score("b", sample=0.9)]
        rep = GR.build_report("T1", scores, [])
        order = [d.product for d in rep.score_diffs]
        self.assertEqual(order[0], "vio")            # 基线最前
        self.assertEqual(order[1:], ["b", "a"])      # 领先最多的先呈现

    def test_freshness_fields_carried(self):
        scores = [_score("vio", sample=0.4),
                  _score("simular", sample=0.7,
                         competitor_version="build-42", tested_at=1234.0,
                         stale=1)]
        rep = GR.build_report("T1", scores, [])
        sim = next(d for d in rep.score_diffs if d.product == "simular")
        self.assertEqual(sim.competitor_version, "build-42")
        self.assertEqual(sim.tested_at, 1234.0)
        self.assertTrue(sim.stale)


class FindingsPassthrough(unittest.TestCase):
    def test_big_gap_finding_surfaced(self):
        # AC3: 大差距自动生成的 Finding 被归拢进报告(现象事实,机器不下结论).
        scores = [_score("vio", sample=0.0, reason="objective primary-goal failed",
                         objective_failed_primary=True),
                  _score("simular", sample=0.8)]
        # findings.classify 产出 feature-gap 类发现(竞品成功、基线失败).
        finds = [f.as_dict() for f in FIND.classify(
            "T1",
            [{"task_id": "T1", "product": "vio", "sample_score": 0.0,
              "objective_failed_primary": True},
             {"task_id": "T1", "product": "simular", "sample_score": 0.8}],
            evidence={"simular": [{"source": "screenshot", "ref": "s.png"}],
                      "vio": [{"source": "log", "ref": "v.log"}]})]
        rep = GR.build_report("T1", scores, finds, registry=make_fake_registry())
        self.assertTrue(rep.findings)
        # 机器只标现象不下结论:PM-fillable 字段仍为空.
        for f in rep.findings:
            self.assertIsNone(f.get("product_judgment"))
            self.assertIsNone(f.get("final_category"))
            self.assertTrue(f.get("phenomenon"))

    def test_only_this_tasks_findings(self):
        finds = [{"task_id": "T1", "rule": "x", "subject": "a", "phenomenon": "p1"},
                 {"task_id": "T2", "rule": "x", "subject": "a", "phenomenon": "p2"}]
        rep = GR.build_report("T1", [_score("vio")], finds)
        self.assertEqual([f["phenomenon"] for f in rep.findings], ["p1"])


class Mechanisms(unittest.TestCase):
    def test_open_source_mechanism_with_repo(self):
        # AC4: 开源竞品附源码机理分析 + repo 链接(机理来自 finding 的 code-analysis 证据).
        scores = [_score("vio", sample=0.4),
                  _score("open_interpreter", sample=0.8)]
        finds = [{"task_id": "T1", "rule": "capability-probe",
                  "subject": "open_interpreter", "phenomenon": "领先",
                  "evidence": [{"source": "code-analysis",
                                "product": "open_interpreter",
                                "repo": "https://github.com/OpenInterpreter/open-interpreter",
                                "mechanism": "用 exec 沙箱直接跑代码",
                                "refs": ["core/core.py#L1"], "analyst": "charlie"}]}]
        rep = GR.build_report("T1", scores, finds, registry=make_fake_registry())
        oi = next(m for m in rep.mechanisms if m.product == "open_interpreter")
        self.assertTrue(oi.is_open_source)
        self.assertEqual(oi.repo,
                         "https://github.com/OpenInterpreter/open-interpreter")
        self.assertEqual(oi.mechanism, "用 exec 沙箱直接跑代码")
        self.assertEqual(oi.refs, ["core/core.py#L1"])
        self.assertEqual(oi.analyst, "charlie")

    def test_closed_source_mechanism_unavailable(self):
        # 闭源竞品拿不到源码 -> mechanism=None(如实标 unavailable,不伪造).
        scores = [_score("vio", sample=0.4), _score("simular", sample=0.8)]
        rep = GR.build_report("T1", scores, [], registry=make_fake_registry())
        sim = next(m for m in rep.mechanisms if m.product == "simular")
        self.assertFalse(sim.is_open_source)
        self.assertIsNone(sim.mechanism)
        self.assertIsNone(sim.repo)

    def test_open_source_but_not_analyzed_is_none(self):
        # 开源但本题没做机理分析 -> mechanism=None(未分析),绝不编造.
        scores = [_score("vio", sample=0.4),
                  _score("open_interpreter", sample=0.8)]
        rep = GR.build_report("T1", scores, [], registry=make_fake_registry())
        oi = next(m for m in rep.mechanisms if m.product == "open_interpreter")
        self.assertTrue(oi.is_open_source)
        self.assertIsNone(oi.mechanism)     # repo 仍带出(元数据),但机理留空
        self.assertEqual(oi.repo,
                         "https://github.com/OpenInterpreter/open-interpreter")

    def test_no_mechanism_row_for_baseline(self):
        scores = [_score("vio", sample=0.4), _score("simular", sample=0.8)]
        rep = GR.build_report("T1", scores, [], registry=make_fake_registry())
        self.assertNotIn("vio", [m.product for m in rep.mechanisms])


class ReportShape(unittest.TestCase):
    def test_as_dict_serializable(self):
        import json
        scores = [_score("vio", sample=0.4), _score("simular", sample=0.8)]
        rep = GR.build_report("T1", scores, [], registry=make_fake_registry())
        d = rep.as_dict()
        self.assertEqual(d["task_id"], "T1")
        self.assertEqual(d["baseline"], "vio")
        json.dumps(d)   # must round-trip without raising

    def test_one_assignment_one_report(self):
        # AC1: 一道对比任务(一个 task_id)= 一份报告.
        scores = [_score("vio", sample=0.4), _score("simular", sample=0.8)]
        rep = GR.build_report("T1", scores, [])
        self.assertEqual(rep.task_id, "T1")
        self.assertIsInstance(rep, GR.GapReport)


if __name__ == "__main__":
    unittest.main()
