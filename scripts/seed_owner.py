"""Bootstrap: 幂等确保系统至少有一个 owner (PM)。

背景: auth.register 需要 owner 签发的邀请链接才能自注册, 但第一版无自举
owner 端点 (owner 由部署时植入)。空库里一个 owner 都没有 => 谁都签发不了
链接、谁都登不进能写的角色 => 前端登录页形同虚设。本脚本把「部署时植入
owner」这一步落成可重复执行的一刀:

  * 已有 owner  -> 不新建, 打印现有 owner 的 user_id (供 /api/login 换发会话)。
  * 没有 owner  -> upsert 一个 role=owner 的用户, 打印其 user_id。

幂等: 反复跑不会造出多个 owner。评分引擎零改动, 只写 users 地基表。

用法:
    python scripts/seed_owner.py                 # 默认 board/competitor_eval.db
    python scripts/seed_owner.py --name "Charlie" # 指定显示名
    python scripts/seed_owner.py --db /path/to.db
"""
from __future__ import annotations

import argparse
import sys
import time

# 允许直接 `python scripts/seed_owner.py` (把仓库根加入 import 路径)。
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pipeline import store  # noqa: E402


def ensure_owner(con, *, name: str | None = None) -> dict:
    """返回 {user_id, name, role, created: bool}。已有 owner 则复用第一个。"""
    owners = [u for u in store.all_users(con) if u.get("role") == "owner"]
    if owners:
        o = owners[0]
        return {"user_id": o["id"], "name": o.get("name"),
                "role": "owner", "created": False}
    user_id = "owner1"
    # 极小概率 id 撞已存在的非 owner 用户: 换一个带时间戳的 id。
    if store.get_user(con, user_id):
        user_id = f"owner_{int(time.time())}"
    store.upsert_user(con, {"id": user_id, "name": name or "PM",
                            "role": "owner", "created_ts": time.time()})
    return {"user_id": user_id, "name": name or "PM",
            "role": "owner", "created": True}


def main() -> int:
    ap = argparse.ArgumentParser(description="幂等植入第一个 owner")
    ap.add_argument("--db", default=None, help="SQLite 路径 (默认 board/competitor_eval.db)")
    ap.add_argument("--name", default=None, help="owner 显示名 (默认 PM)")
    args = ap.parse_args()

    con = store.connect(args.db)
    res = ensure_owner(con, name=args.name)
    verb = "已植入新 owner" if res["created"] else "已存在 owner (复用)"
    print(f"{verb}: user_id={res['user_id']} name={res['name']} role=owner")
    print("登录方式: POST /api/login {\"user_id\": \"%s\"} 换发会话令牌。" % res["user_id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
