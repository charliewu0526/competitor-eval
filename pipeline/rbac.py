"""MR-4 (#40): 三级角色 RBAC 的权限边界 (ADR-0014).

只做「角色与权限判定」这一薄层 —— 谁能做哪类操作、owner 怎么提升 intern。
不含具体复核 / 校准 / 脱敏的业务逻辑 (那在各自的复核切片 I13),这里只回答
「你这个角色被允许触发这类操作吗」。

角色层级 (权限从最小开始, ADR-0014):
    intern(实习生, rank 0) < reviewer(审核员, rank 1) < owner(PM, rank 2)

危险开关 (黄金集校准 / 评委授权降权 / 任务清单 / 脱敏规则 / 角色提升) owner 独占
—— 校准这个开关绝不落到新人甚至审核员手里 (PRD story 5)。复核类 reviewer 起
(intern 不能复核, story 6 / AC3)。领取、提交这类基础动作 intern 起。

注意: 本模块的 `authorize`-无关 —— pipeline/authorize.py 是 G2「AI 评委黄金集
授权」的另一个概念 (评委清没清黄金集), 与这里的「用户角色能不能点这个按钮」
不是一回事, 故独立成 rbac.py 避免混淆。
"""
from __future__ import annotations

from pipeline import store


ROLES = ("intern", "reviewer", "owner")
_RANK = {"intern": 0, "reviewer": 1, "owner": 2}


class PermissionDenied(Exception):
    """角色不足以执行该操作。Web 层翻成 403。"""


# 每类操作 -> 允许触发它所需的「最低角色」。owner 是顶层, 故 min="owner"
# 等价于「owner 独占」。未登记的操作一律 fail fast (拒绝 + 报错), 不默认放行。
PERMISSIONS: dict[str, str] = {
    # --- owner 独占的危险开关 (story 5, ADR-0014) --------------------------
    "promote_user":          "owner",   # 角色提升 / 降权 (story 4)
    "issue_invite":          "owner",   # 签发私发注册链接 (story 2)
    "calibrate_golden":      "owner",   # 黄金集校准 / 重校准 (story 5/33)
    "authorize_reviewer":    "owner",   # 评委授权 / 降权 (story 5)
    "manage_task_catalog":   "owner",   # 任务清单维护 (story 5/7)
    "manage_desensitization": "owner",  # 脱敏规则 (story 5)
    # --- 复核层: reviewer 起, intern 被拒 (story 6, AC3) -------------------
    "review":                "reviewer",  # 复核 AI 报告 (story 31)
    "gate_method":           "reviewer",  # 方法初稿把关 draft->approved (story 35)
    # --- 基础层: 任意已登录用户 (intern 起) -------------------------------
    "claim_assignment":      "intern",    # 领取任务 (story 8)
    "submit":                "intern",    # 提交交付物 (story 14)
}


def can(role: str | None, action: str) -> bool:
    """角色 role 是否被允许执行 action。

    未知 action -> ValueError (fail fast: 拼错权限名不能静默放行)。
    未知 / 缺失 role -> False (无身份即无权)。
    """
    if action not in PERMISSIONS:
        raise ValueError(f"未登记的操作: {action!r}")
    if role not in _RANK:
        return False
    return _RANK[role] >= _RANK[PERMISSIONS[action]]


def require(user: dict | None, action: str) -> dict:
    """守卫: user 必须有权执行 action, 否则 raise。放行时回传 user 便于链式。

    user = whoami 出来的 {id,name,role} 或 None (未登录)。
    未登录 -> PermissionDenied (Web -> 403; 未认证细分留给上层, 这里统一拒)。
    """
    role = (user or {}).get("role")
    if not can(role, action):
        who = role or "匿名"
        raise PermissionDenied(f"角色 {who} 无权执行 {action!r}")
    return user  # type: ignore[return-value]


def promote(con, *, actor: dict | None, target_user_id: str,
            new_role: str) -> dict:
    """owner 把某用户设为 new_role (主用例: intern -> reviewer, story 4)。

    - actor 必须有 promote_user 权限 (owner) —— 否则 PermissionDenied。
    - new_role 必须是合法角色 —— 否则 ValueError。
    - 目标用户必须存在 —— 否则 ValueError。
    返回提升后的 user dict。
    """
    require(actor, "promote_user")
    if new_role not in ROLES:
        raise ValueError(f"非法角色: {new_role!r} (合法: {ROLES})")
    target = store.get_user(con, target_user_id)
    if target is None:
        raise ValueError(f"用户不存在: {target_user_id!r}")
    store.set_user_role(con, target_user_id, new_role)
    return store.get_user(con, target_user_id)
