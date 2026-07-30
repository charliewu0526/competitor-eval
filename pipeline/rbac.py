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
    "delete_user":           "owner",   # 从成员名单删除用户 (owner 独占)
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
    # --- MR-B (#56) 用户反馈 (PRD #54, ADR-0020) --------------------------
    "submit_report":         "intern",    # 提交反馈: 仅登录用户可提, 可追责 (story 1/6)
    "view_report_console":   "owner",     # 反馈台: owner 专属页面, 不塞进现有看板 (story 21)
    # --- MR-D (#59) 上线闸门 (PRD #54, ADR-0023) --------------------------
    "approve_patch":         "owner",     # 批准/拒绝候选补丁 + 走金丝雀上线 (story 14-19)
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
    action 拼错 (未登记) -> 也翻成 PermissionDenied 而非 ValueError, 让 Web 层统一
    回 403 而不是 500 暴露内部错误 (体检 BUG-11)。
    """
    role = (user or {}).get("role")
    try:
        allowed = can(role, action)
    except ValueError:
        raise PermissionDenied(f"未知操作类型: {action!r}")
    if not allowed:
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
    # 末位 owner 保护: 降走系统最后一个 owner 会导致谁都签发不了链接、提升不了人,
    # 系统被永久锁死 (体检 BUG-10)。降权前确保还留有其他 owner。
    if target["role"] == "owner" and new_role != "owner":
        other_owners = [u for u in store.all_users(con)
                        if u["role"] == "owner" and u["id"] != target_user_id]
        if not other_owners:
            raise PermissionDenied("系统至少需保留一位 owner, 不能降走最后一个")
    store.set_user_role(con, target_user_id, new_role)
    return store.get_user(con, target_user_id)


def remove_user(con, *, actor: dict | None, target_user_id: str) -> dict:
    """owner 从成员名单删除一个用户。返回被删用户 dict(供 Web 层回显)。

    守卫(fail fast):
    - actor 必须有 delete_user 权限(owner)—— 否则 PermissionDenied。
    - 不能删自己 —— 防 owner 手滑把自己删掉丢失管理权(PermissionDenied)。
    - 目标用户必须存在 —— 否则 ValueError。
    - 不能删系统最后一个 owner —— 否则谁都提升不了人/签发不了链接, 系统锁死
      (与 promote 的末位 owner 保护同源, PermissionDenied)。
    该用户历史领取/提交记录保留(store.delete_user 只删 users 行), 追责痕迹不蒸发。
    """
    actor = require(actor, "delete_user")
    target = store.get_user(con, target_user_id)
    if target is None:
        raise ValueError(f"用户不存在: {target_user_id!r}")
    if actor and actor.get("id") == target_user_id:
        raise PermissionDenied("不能删除自己(避免误删丢失管理权)")
    if target["role"] == "owner":
        other_owners = [u for u in store.all_users(con)
                        if u["role"] == "owner" and u["id"] != target_user_id]
        if not other_owners:
            raise PermissionDenied("系统至少需保留一位 owner, 不能删走最后一个")
    store.delete_user(con, target_user_id)
    return target
