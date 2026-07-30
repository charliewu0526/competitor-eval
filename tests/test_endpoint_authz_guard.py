"""回归防线: 每个写端点匿名访问必须被干净拒绝 (401/403), 绝不 500 或放行.

Run: python -m unittest tests.test_endpoint_authz_guard -v

背景 (为什么有这个测): M-1 用 rbac() dependency factory 消 22 处样板时, 有两个
端点 (claim_assignment / materialize_assignment) 的函数签名漏改 —— try/RBAC.require
块被删了, 签名却还停在 user=Depends(current_user)。结果鉴权凭空消失: 匿名/任意人
都能领取/物化, 且 user["id"] 对 None 取值直接崩 500。三身份 e2e 抓到了它。

这类"漏鉴权"错误没有任何编译/普通单测提示 —— 端点照常返回 200。本文件把它挡住:
对所有需要鉴权的写端点, 用**匿名请求**(无 Bearer)断言必得 401/403, 绝不 200
(放行) 也绝不 500 (裸穿透)。任何新写端点忘记挂 rbac()/鉴权都会在这里当场红。

全 OFFLINE: 临时空库覆盖 _DB_PATH, 不碰生产 board/。
"""
from __future__ import annotations
import pathlib
import tempfile
import unittest


# (HTTP 方法, 路径, 表单/JSON) —— 所有"必须先鉴权"的写端点。匿名访问预期 401/403。
# 只读展示端点 (/api/overview /api/leaderboard 等) 不在此列; /api/me 允许匿名->401。
GUARDED_WRITES = [
    ("POST", "/api/invites", {"json": {"note": "x"}}),
    ("POST", "/api/users/u1/role", {"json": {"role": "owner"}}),
    ("POST", "/api/assignments/materialize", {"json": {"task_id": "T1"}}),
    ("POST", "/api/assignments/as-x/claim", {}),
    ("POST", "/api/assignments/as-x/abandon", {}),
    ("POST", "/api/assignments/as-x/submit", {}),
    ("POST", "/api/assignments/reclaim-stale", {}),
    ("POST", "/api/assignments/as-x/submissions", {"data": {"product": "vio"}}),
    ("POST", "/api/findings/1/judgment",
     {"json": {"product_judgment": "必须补齐", "final_category": "feature-gap"}}),
    ("POST", "/api/spotcheck/rebuild", {}),
    ("POST", "/api/spotcheck/1/assign", {"json": {"reviewer_id": "rv1"}}),
    ("POST", "/api/spotcheck/1/review", {"json": {"verdict": "reasonable"}}),
    ("POST", "/api/spotcheck/1/recalibrate", {}),
    ("POST", "/api/spotcheck/1/suspect", {"json": {}}),
    ("POST", "/api/spotcheck/1/exclude", {"json": {}}),
    ("POST", "/api/spotcheck/1/override", {"json": {"sample_score": 0.5}}),
    ("POST", "/api/methods", {"json": {"task_id": "T1", "product": "vio", "draft": "d"}}),
    ("POST", "/api/methods/1/approve", {}),
    ("POST", "/api/methods/1/export", {}),
    ("GET", "/api/methods", {}),
    ("GET", "/api/users", {}),
    ("GET", "/api/assignments", {}),
]


class AnonymousDeniedOnGuardedWrites(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        import server.app as APP
        self._APP = APP
        self._orig = APP._DB_PATH
        APP._DB_PATH = str(pathlib.Path(tempfile.mkdtemp()) / "authz.db")
        APP._migrated_for = None
        self.client = TestClient(APP.app)

    def tearDown(self):
        self._APP._DB_PATH = self._orig
        self._APP._migrated_for = None

    def test_anonymous_is_denied_never_200_never_500(self):
        bad = []
        for method, path, kw in GUARDED_WRITES:
            r = self.client.request(method, path, **kw)   # 无 Authorization 头
            # 干净拒绝 = 401(未登录) 或 403(无权)。绝不能 200(放行)或 5xx(裸穿透)。
            if r.status_code not in (401, 403):
                bad.append(f"{method} {path} -> {r.status_code}")
        self.assertEqual(bad, [], f"这些写端点匿名访问未被干净拒绝(漏鉴权/裸穿透): {bad}")


if __name__ == "__main__":
    unittest.main()
