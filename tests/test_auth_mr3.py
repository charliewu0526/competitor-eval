"""MR-3 (#39): 私发链接自注册登录 — 默认 intern.

Run: python -m unittest tests.test_auth_mr3 -v

Acceptance (issue #39):
  - 持有效链接可自注册, 无链接不能注册
  - 注册成功默认角色为 intern
  - 登录后会话可识别当前用户与角色
  - 端到端: 注册 -> 登录 -> 拿到 intern 身份可验证

评分核心零改动: 仅新增 invites/sessions 两表 + auth 策略层。
"""
from __future__ import annotations
import pathlib
import tempfile
import unittest

from pipeline import store, auth


def _tmpdb():
    return str(pathlib.Path(tempfile.mkdtemp()) / "t.db")


class RegisterViaInvite(unittest.TestCase):
    def test_valid_invite_can_register(self):
        con = store.connect(_tmpdb())
        inv = auth.issue_invite(con, created_by="pm", note="给 Alice")
        res = auth.register(con, invite_token=inv["token"], name="Alice")
        self.assertIsNotNone(res["session_token"])
        self.assertEqual(res["user"]["name"], "Alice")

    def test_no_invite_cannot_register(self):
        # story 2: 无链接不能注册 (不对公网开放).
        con = store.connect(_tmpdb())
        with self.assertRaises(auth.AuthError):
            auth.register(con, invite_token="not-a-real-token", name="Mallory")

    def test_registered_user_defaults_intern(self):
        # story 3 / ADR-0014: 权限从最小开始.
        con = store.connect(_tmpdb())
        inv = auth.issue_invite(con, created_by="pm")
        res = auth.register(con, invite_token=inv["token"], name="Bob")
        self.assertEqual(res["user"]["role"], "intern")

    def test_invite_is_one_time(self):
        # 一次性消费: 同一张链接注册第二次被拒.
        con = store.connect(_tmpdb())
        inv = auth.issue_invite(con, created_by="pm")
        auth.register(con, invite_token=inv["token"], name="First")
        self.assertFalse(store.invite_is_valid(con, inv["token"]))
        with self.assertRaises(auth.AuthError):
            auth.register(con, invite_token=inv["token"], name="Second")

    def test_expired_invite_rejected(self):
        con = store.connect(_tmpdb())
        inv = auth.issue_invite(con, created_by="pm", ttl_seconds=100, now=1000.0)
        # 过期后 (now=2000 > 1000+100) 不能注册.
        self.assertFalse(store.invite_is_valid(con, inv["token"], now=2000.0))
        with self.assertRaises(auth.AuthError):
            auth.register(con, invite_token=inv["token"], name="Late", now=2000.0)

    def test_concurrent_registration_single_winner(self):
        # 两人抢同一张一次性链接, 只有一人成功建号, 另一人被拒且不留脏用户.
        path = _tmpdb()
        con0 = store.connect(path)
        inv = auth.issue_invite(con0, created_by="pm")
        conA = store.connect(path)
        conB = store.connect(path)
        wins, ids = 0, []
        for c, nm in ((conA, "A"), (conB, "B")):
            try:
                r = auth.register(c, invite_token=inv["token"], name=nm)
                wins += 1
                ids.append(r["user"]["id"])
            except auth.AuthError:
                pass
        self.assertEqual(wins, 1)
        # 恰一个用户落库 (被拒的那次已回滚).
        self.assertEqual(len(store.all_users(con0)), 1)


class SessionIdentity(unittest.TestCase):
    def test_session_resolves_user_and_role(self):
        # story 1: 登录后会话可识别当前用户与角色.
        con = store.connect(_tmpdb())
        inv = auth.issue_invite(con, created_by="pm")
        res = auth.register(con, invite_token=inv["token"], name="Carol")
        who = auth.whoami(con, res["session_token"])
        self.assertEqual(who["id"], res["user"]["id"])
        self.assertEqual(who["role"], "intern")

    def test_invalid_token_is_anonymous(self):
        con = store.connect(_tmpdb())
        self.assertIsNone(auth.whoami(con, "garbage"))
        self.assertIsNone(auth.whoami(con, None))

    def test_expired_session_is_anonymous(self):
        con = store.connect(_tmpdb())
        inv = auth.issue_invite(con, created_by="pm")
        auth.register(con, invite_token=inv["token"], name="Dave", now=1000.0)
        u = store.all_users(con)[0]
        token = auth._issue_session(con, u["id"], ttl_seconds=50, now=1000.0)
        self.assertIsNotNone(auth.whoami(con, token, now=1040.0))   # 未过期
        self.assertIsNone(auth.whoami(con, token, now=2000.0))      # 过期

    def test_logout_revokes_session(self):
        con = store.connect(_tmpdb())
        inv = auth.issue_invite(con, created_by="pm")
        res = auth.register(con, invite_token=inv["token"], name="Eve")
        auth.logout(con, res["session_token"])
        self.assertIsNone(auth.whoami(con, res["session_token"]))

    def test_relogin_issues_new_session(self):
        con = store.connect(_tmpdb())
        inv = auth.issue_invite(con, created_by="pm")
        res = auth.register(con, invite_token=inv["token"], name="Frank")
        uid = res["user"]["id"]
        t2 = auth.login(con, user_id=uid)
        self.assertNotEqual(t2, res["session_token"])
        self.assertEqual(auth.whoami(con, t2)["id"], uid)

    def test_login_unknown_user_rejected(self):
        con = store.connect(_tmpdb())
        with self.assertRaises(auth.AuthError):
            auth.login(con, user_id="u_nope")


class EndToEnd(unittest.TestCase):
    def test_register_then_identify_intern(self):
        # 端到端 AC: 注册 -> 登录 -> 拿到 intern 身份可验证.
        con = store.connect(_tmpdb())
        inv = auth.issue_invite(con, created_by="pm", note="onboarding link")
        res = auth.register(con, invite_token=inv["token"], name="Grace")
        # 换发一个新会话 (模拟重新登录), 仍应识别为同一 intern.
        token = auth.login(con, user_id=res["user"]["id"])
        who = auth.whoami(con, token)
        self.assertEqual(who["name"], "Grace")
        self.assertEqual(who["role"], "intern")
        # PM 提升为 reviewer 后, 会话解析出的角色随之更新 (RBAC 数据打通).
        store.set_user_role(con, who["id"], "reviewer")
        self.assertEqual(auth.whoami(con, token)["role"], "reviewer")


if __name__ == "__main__":
    unittest.main()
