"""评测套件 (Eval Suite): 批量评测框架.

Run: python -m unittest tests.test_suite_x6 -v

TDD vertical slices — one behavior per cycle. The suite自动枚举任务库目录、按
任务地图标签(能力域 × 任务性质)圈定子集、批量跑 N 道题出聚合排行榜。复用
taskbank 的 discover/assert_valid(不另造加载)与 leaderboard(不另造排序)。
"""
from __future__ import annotations
import unittest

from pipeline import suite as SUITE
from pipeline.schema import TaskSpec

TASKS_ROOT = None  # uses the repo's real tasks/ dir by default


def _spec(**kw):
    base = dict(task_id="TX", domain="1", app="wechat", prompt="p",
                core_assertions=["primary"])
    base.update(kw)
    return TaskSpec(**base)


class TaskMapLabels(unittest.TestCase):
    """cycle 4: 任务地图两组正交标签 (能力域 × 任务性质) on TaskSpec."""

    def test_defaults_are_valid(self):
        s = _spec()
        self.assertEqual(s.capability_domain, "wechat-im")
        self.assertEqual(s.task_nature, "simple")

    def test_valid_labels_accepted(self):
        s = _spec(capability_domain="office-suite", task_nature="long-horizon")
        self.assertEqual(s.capability_domain, "office-suite")
        self.assertEqual(s.task_nature, "long-horizon")

    def test_bad_capability_domain_rejected(self):
        with self.assertRaises(ValueError):
            _spec(capability_domain="not-a-domain")

    def test_bad_task_nature_rejected(self):
        with self.assertRaises(ValueError):
            _spec(task_nature="not-a-nature")


class DiscoverTasks(unittest.TestCase):
    def test_discovers_t1_with_loaded_spec(self):
        # tracer bullet: scan tasks/ -> find T1, its TaskSpec is loaded+valid
        tasks = SUITE.discover_tasks()
        ids = {t.task_spec.task_id for t in tasks}
        self.assertIn("T1-wechat-send-001", ids)
        t1 = next(t for t in tasks if t.task_spec.task_id == "T1-wechat-send-001")
        self.assertEqual(t1.task_spec.app, "wechat")

    def test_assertions_module_loaded_callable(self):
        # cycle 2: meta.assertions_module is dynamically imported -> the task's
        # assertions() is a callable yielding its objective assertion list.
        t1 = next(t for t in SUITE.discover_tasks()
                  if t.task_spec.task_id == "T1-wechat-send-001")
        self.assertTrue(callable(t1.assertions))
        asserts = t1.assertions()
        self.assertTrue(len(asserts) >= 1)        # T1 has 3 manual checks


class FilterTasks(unittest.TestCase):
    def test_filter_by_app_keeps_match(self):
        # cycle 3: 圈定「这轮测哪类」— filter by a task-map label keeps matches.
        tasks = SUITE.discover_tasks()
        kept = SUITE.filter_tasks(tasks, app="wechat")
        self.assertTrue(kept)
        self.assertTrue(all(t.task_spec.app == "wechat" for t in kept))

    def test_filter_by_app_drops_nonmatch(self):
        tasks = SUITE.discover_tasks()
        self.assertEqual(SUITE.filter_tasks(tasks, app="capcut"), [])

    def test_no_filter_returns_all(self):
        tasks = SUITE.discover_tasks()
        self.assertEqual(len(SUITE.filter_tasks(tasks)), len(tasks))

    def _fake(self, **kw):
        return SUITE.LoadedTask(task_spec=_spec(**kw), assertions=None,
                                task_dir=None)

    def test_filter_by_capability_domain(self):
        # cycle 5: 圈定 by 任务地图标签 — capability domain.
        tasks = [self._fake(task_id="A", capability_domain="office-suite"),
                 self._fake(task_id="B", capability_domain="browser-web")]
        kept = SUITE.filter_tasks(tasks, capability_domain="office-suite")
        self.assertEqual([t.task_spec.task_id for t in kept], ["A"])

    def test_filter_by_task_nature(self):
        tasks = [self._fake(task_id="A", task_nature="long-horizon"),
                 self._fake(task_id="B", task_nature="simple")]
        kept = SUITE.filter_tasks(tasks, task_nature="long-horizon")
        self.assertEqual([t.task_spec.task_id for t in kept], ["A"])

    def test_filter_combines_axes_orthogonally(self):
        # 两轴正交: domain AND nature both apply.
        tasks = [self._fake(task_id="A", capability_domain="office-suite",
                            task_nature="long-horizon"),
                 self._fake(task_id="B", capability_domain="office-suite",
                            task_nature="simple")]
        kept = SUITE.filter_tasks(tasks, capability_domain="office-suite",
                                  task_nature="long-horizon")
        self.assertEqual([t.task_spec.task_id for t in kept], ["A"])


class RunSuite(unittest.TestCase):
    """cycle 6: 批量跑 N 道题 -> 跨题聚合排行榜 (复用 leaderboard)."""

    def test_aggregates_scores_across_tasks(self):
        # scores_by_task: {task_id: [score dicts]} — the suite flattens these and
        # builds ONE cross-task leaderboard. Vio wins T-A, rival wins T-B.
        scores_by_task = {
            "T-A": [{"task_id": "T-A", "product": "vio", "sample_score": 0.9,
                     "gate": "native-operable", "h1_honesty": 5},
                    {"task_id": "T-A", "product": "simular", "sample_score": 0.3,
                     "gate": "native-operable"}],
            "T-B": [{"task_id": "T-B", "product": "vio", "sample_score": 0.4,
                     "gate": "native-operable"},
                    {"task_id": "T-B", "product": "simular", "sample_score": 0.8,
                     "gate": "native-operable"}],
        }
        res = SUITE.run_suite(scores_by_task, baseline="vio")
        self.assertEqual(set(res.leaderboard["tasks"]), {"T-A", "T-B"})
        vio = next(r for r in res.leaderboard["ranking"] if r["product"] == "vio")
        # vio avg over two tasks = (0.9 + 0.4)/2 = 0.65
        self.assertAlmostEqual(vio["avg_capability"], 0.65)
        self.assertEqual(vio["n_tasks"], 2)

    def test_empty_suite_is_clean_not_crash(self):
        res = SUITE.run_suite({}, baseline="vio")
        self.assertEqual(res.leaderboard["ranking"], [])
        self.assertEqual(res.leaderboard["tasks"], [])


if __name__ == "__main__":
    unittest.main()
