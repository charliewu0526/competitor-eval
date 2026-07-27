"""MR-3 (#39): 私发链接自注册登录 — 账号系统最薄的一刀.

只到「能登录、有身份」。业务规则从 store 的裸 CRUD 抽到这里:
  * 无有效链接不能注册 (story 2: 不对公网开放, 数据源可控).
  * 注册成功默认 intern (ADR-0014: 权限从最小开始).
  * 登录颁发会话令牌, 会话可识别当前用户与角色 (story 1).

刻意不做 (ADR-0019 最薄闭环 / 后续工单):
  * 密码/口令校验 — 第一版链接即凭证, 持链接者信任内部人 (story 2 数据源可控靠私发).
  * OAuth / 邮箱验证 / 找回 — MVP 不需要.
  * 角色提升 UI — set_user_role 已在 store, PM 手动提 reviewer 走 #4 后续.

评分引擎零改动: 本模块只读写 users/invites/sessions 三张地基表, 不碰 runs/scores/findings.
"""
from __future__ import annotations

import os
import secrets
import time

from pipeline import store


# 令牌默认寿命 (安全护栏, env 可覆盖). 永不过期的令牌一旦泄露就是永久后门,
# 故给会话/链接都设默认 TTL; 显式传 ttl_seconds 仍可覆盖 (含 <=0 表示永久, 见下)。
DEFAULT_SESSION_TTL_SECONDS = float(
    os.environ.get("SESSION_TTL_SECONDS", 7 * 24 * 3600))   # 7 天
DEFAULT_INVITE_TTL_SECONDS = float(
    os.environ.get("INVITE_TTL_SECONDS", 72 * 3600))         # 72 小时


class AuthError(Exception):
    """注册/登录被拒 (无效链接、令牌失效…). Web 层翻成 4xx."""


def _token(nbytes: int = 24) -> str:
    """URL-safe 随机令牌 (不可猜)。链接凭证与会话令牌共用。"""
    return secrets.token_urlsafe(nbytes)


def _expiry(ts: float, ttl_seconds: float | None, default_ttl: float) -> float | None:
    """算过期时间戳。ttl_seconds=None -> 用默认 TTL; ttl_seconds<=0 -> 永不过期
    (显式关闭, 供内部长期令牌等特例); 否则 ts+ttl。"""
    ttl = default_ttl if ttl_seconds is None else ttl_seconds
    if ttl <= 0:
        return None
    return ts + ttl


# --- PM 侧: 签发私发注册链接 --------------------------------------------
def issue_invite(con, *, created_by: str | None = None, note: str | None = None,
                 ttl_seconds: float | None = None, now: float | None = None) -> dict:
    """PM 生成一张私发注册链接。返回 {token, ...}; token 拼进注册 URL 私发给内部人。

    ttl_seconds=None -> 不过期。一次性: 被一个人注册消费后即失效。
    """
    ts = now or time.time()
    token = _token()
    store.create_invite(con, {
        "token": token, "note": note, "created_by": created_by,
        "created_ts": ts,
        "expires_ts": _expiry(ts, ttl_seconds, DEFAULT_INVITE_TTL_SECONDS),
    })
    return store.get_invite(con, token)


# --- 内部人侧: 自注册 -> 登录 -------------------------------------------
def register(con, *, invite_token: str, name: str | None = None,
             now: float | None = None) -> dict:
    """持有效链接自注册。成功返回 {user, session_token}。

    无链接 / 链接失效 / 已被用 -> AuthError (story 2: 无链接不能注册)。
    新用户默认 intern (ADR-0014)。注册即登录, 直接给会话令牌。
    """
    ts = now or time.time()
    if not store.invite_is_valid(con, invite_token, now=ts):
        raise AuthError("注册链接无效、已过期或已被使用")

    user_id = "u_" + _token(9)
    # 先建用户, 再原子消费链接; 消费失败 (并发被人抢先) 则回滚这次注册。
    store.upsert_user(con, {"id": user_id, "name": name, "role": "intern",
                            "created_ts": ts})
    if not store.consume_invite(con, invite_token, user_id, now=ts):
        # 并发下另一人抢先消费了同一张链接: 撤销刚建的用户, 拒绝。
        try:
            con.execute("DELETE FROM users WHERE id=?", (user_id,))
            con.commit()
        except Exception:
            pass
        raise AuthError("注册链接刚被他人使用")

    session_token = _issue_session(con, user_id, now=ts)
    return {"user": store.get_user(con, user_id), "session_token": session_token}


def _issue_session(con, user_id: str, *, ttl_seconds: float | None = None,
                   now: float | None = None) -> str:
    ts = now or time.time()
    token = _token()
    store.create_session(con, {
        "token": token, "user_id": user_id, "created_ts": ts,
        "expires_ts": _expiry(ts, ttl_seconds, DEFAULT_SESSION_TTL_SECONDS),
    })
    return token


def login(con, *, user_id: str, now: float | None = None) -> str:
    """已注册用户重新登录, 颁发新会话令牌。用户不存在 -> AuthError。

    第一版链接即凭证、无密码 (ADR-0019 最薄); 主路径是 register 注册即登录。
    这个 login 供「已有身份、换设备/新会话」用。
    """
    if not store.get_user(con, user_id):
        raise AuthError("用户不存在")
    return _issue_session(con, user_id, now=now)


def whoami(con, session_token: str | None, now: float | None = None) -> dict | None:
    """解析会话令牌 -> 当前用户 (id/name/role)。无/失效令牌 -> None。

    这是「会话可识别当前用户与角色」(story 1 AC) 的唯一入口, Web 依赖注入用它。
    """
    if not session_token:
        return None
    return store.session_user(con, session_token, now=now)


def logout(con, session_token: str) -> None:
    store.delete_session(con, session_token)
