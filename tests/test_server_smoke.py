"""冒烟测试: server.app 必须能 import 且 API 能起来能响应.

Run: python -m unittest tests.test_server_smoke -v

背景 (为什么有这个测): 混提 5225f83 曾把 JudgmentIn 的 Literal 用字面 \\n 转义
写进注释, 导致 server/app.py SyntaxError —— 整个 API 从那次提交起一直无法
import。但所有既有单测都直测 pipeline 层、从不 `import server.app`, 所以这个
「API 压根起不来」的致命错在 CI 里一路绿灯。本文件把它挡住:

  1. import 关: `import server.app` 本身必须成功 (语法错 / 导入错当场红)。
  2. 路由关: 关键端点必须注册 (漏挂 @app.post 也算 API 起不来)。
  3. 存活关: TestClient 真发一个请求, 确认 app 能构造能响应 (不只是 import)。

全 OFFLINE: 用临时空库覆盖 _DB_PATH, 不碰 board/ 生产库。
"""
from __future__ import annotations
import importlib
import pathlib
import tempfile
import unittest


# 关键端点契约: (HTTP 方法, 路径)。少一个都说明 API 表面被改坏/漏挂。
# 覆盖各 MR 切片的对外接缝, 尤其 MR-13 复核类三端点 (最新, 最易漏)。
REQUIRED_ROUTES = {
    ("GET", "/api/health"),
    ("GET", "/api/spotcheck"),
    ("GET", "/api/authorizations"),
    ("POST", "/api/register"),
    ("POST", "/api/login"),
    ("GET", "/api/me"),
    # 复核 / 抽查写端点 (鉴权动作)
    ("POST", "/api/findings/{finding_id}/judgment"),
    ("POST", "/api/spotcheck/rebuild"),
    ("POST", "/api/spotcheck/{queue_id}/verdict"),
    # MR-13 (#49) 人工复核队列 + 职责分离 + 重校准
    ("POST", "/api/spotcheck/{queue_id}/assign"),
    ("POST", "/api/spotcheck/{queue_id}/review"),
    ("POST", "/api/spotcheck/{queue_id}/recalibrate"),
    # 用户管理 (MR-4 + 删除成员)
    ("GET", "/api/users"),
    ("POST", "/api/users/{user_id}/role"),
    ("DELETE", "/api/users/{user_id}"),
    # Assignment 状态机 (MR-6) + 撤回已上传产物
    ("GET", "/api/assignments"),
    ("POST", "/api/assignments/{assignment_id}/claim"),
    ("POST", "/api/assignments/{assignment_id}/submit"),
    ("DELETE", "/api/assignments/{assignment_id}/submissions/{product}"),
    # MR-11 (#47) 差距报告前端接缝 (列表 + 单题)
    ("GET", "/api/gap-report"),
    ("GET", "/api/gap-report/{task_id}"),
    # MR-B (#56) 用户反馈: 提交 + 我的状态 + owner 反馈台
    ("POST", "/api/reports"),
    ("GET", "/api/reports/mine"),
    ("GET", "/api/reports/console"),
    # MR-D (#59) 上线闸门: 批准(冒烟金丝雀)/ 拒绝
    ("POST", "/api/reports/{report_id}/approve"),
    ("POST", "/api/reports/{report_id}/reject"),
}


def _route_set(app):
    """{(method, path)} over the app's real routes (methods flattened)."""
    out = set()
    for r in app.routes:
        path = getattr(r, "path", None)
        methods = getattr(r, "methods", None)
        if not path or not methods:
            continue
        for m in methods:
            out.add((m, path))
    return out


class ImportSmoke(unittest.TestCase):
    def test_import_server_app_succeeds(self):
        """server.app 必须能 import —— 语法错/导入错在此当场红 (5225f83 回归防线)."""
        mod = importlib.import_module("server.app")
        importlib.reload(mod)          # 强制重新执行模块体, 不吃缓存
        self.assertTrue(hasattr(mod, "app"), "server.app 缺少 FastAPI `app` 对象")

    def test_required_routes_registered(self):
        """关键端点都在 —— 漏挂 @app.post 也是一种「API 起不来」."""
        from server.app import app
        have = _route_set(app)
        missing = REQUIRED_ROUTES - have
        self.assertEqual(missing, set(), f"缺失路由: {sorted(missing)}")


class LiveSmoke(unittest.TestCase):
    """不止 import: TestClient 真构造 app 并发请求, 确认能启动能响应."""

    def setUp(self):
        from fastapi.testclient import TestClient
        import server.app as APP
        # 指向临时空库, 绝不碰生产 board/competitor_eval.db。
        self._orig_db = APP._DB_PATH
        APP._DB_PATH = str(pathlib.Path(tempfile.mkdtemp()) / "smoke.db")
        self.client = TestClient(APP.app)
        self._APP = APP

    def tearDown(self):
        self._APP._DB_PATH = self._orig_db

    def test_health_endpoint_boots_and_responds(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body.get("ok"))
        self.assertIn("scores", body)          # 建表 + 计数走通 (空库=0)

    def test_me_unauthenticated_is_401_not_500(self):
        """未登录 /api/me 应是干净的 401, 不是穿透成 500 (依赖注入链健康)."""
        r = self.client.get("/api/me")
        self.assertEqual(r.status_code, 401)

    def test_openapi_schema_builds(self):
        """/openapi.json 能生成 = 所有 pydantic 模型 (含 MR-13 的 Literal) 合法."""
        r = self.client.get("/openapi.json")
        self.assertEqual(r.status_code, 200)
        self.assertIn("paths", r.json())


if __name__ == "__main__":
    unittest.main()
