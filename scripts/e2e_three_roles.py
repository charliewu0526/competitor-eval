"""端到端真跑「三身份全生命周期」: intern / reviewer / owner 各自职责边界 + 越权负例.

对照测试用例 docs/testplan/0001-three-roles-e2e.md 的 A–G 段逐条断言。全走真实 HTTP
表面 (FastAPI TestClient) + 真鉴权 + 真落库, 离线临时库不碰生产 board/。

上真人前的最后一道验收: 先看用例文档, 再用本脚本真穿通。任一断言失败即阻断上真人。

Run:  python scripts/e2e_three_roles.py   (repo 根目录; 脚本自带 sys.path 自举)
"""
from __future__ import annotations
import io
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

_PASS = 0
_FAIL = 0


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _ok(label: str, cond: bool, detail: str = "") -> None:
    global _PASS, _FAIL
    mark = "PASS" if cond else "FAIL"
    if cond:
        _PASS += 1
    else:
        _FAIL += 1
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail else ""))


TASK_ID = "T1-wechat-send-001"
LOG_BUNDLE = json.dumps({
    "input_tokens": 4200, "output_tokens": 1300, "model_calls": 6,
    "model": "deepseek-v4-pro", "cost_source": "self-report",
    "evidence_source": "log",
    "events": ["run.start", "wechat.open", "type.message", "press.enter",
               "verify.bubble", "run.end"],
}, ensure_ascii=False)


def _submit_one(client, aid, intern_tok, product, received):
    files = {
        "artifact": (f"{product}.png", io.BytesIO(b"\x89PNG fake"), "image/png"),
        "log_bundle": (f"{product}-log.json", io.BytesIO(LOG_BUNDLE.encode()),
                       "application/json"),
    }
    data = {
        "product": product,
        "manual_assertions": json.dumps({
            "msg_received": received, "text_exact": received, "no_collateral": True}),
        "claimed_success": "true",
        "competitor_version": "computer-use" if product == "vio" else "0.4.3",
    }
    return client.post(f"/api/assignments/{aid}/submissions",
                       data=data, files=files, headers=_hdr(intern_tok))


def main() -> int:
    import server.app as APP
    from pipeline import store, auth as AUTH
    APP._DB_PATH = str(pathlib.Path(tempfile.mkdtemp(prefix="e2e-3roles-")) / "t.db")
    APP._migrated_for = None
    client = TestClient(APP.app)

    con = store.connect(APP._DB_PATH)
    store.upsert_user(con, {"id": "owner1", "name": "PM", "role": "owner"})

    # === A. owner 建场 =====================================================
    print("=== A. owner(PM)建场 ===")
    r = client.post("/api/login", json={"user_id": "owner1"})
    owner_tok = r.json().get("session_token", "")
    _ok("A1 owner 登录", r.status_code == 200, str(r.status_code))
    r = client.get("/api/me", headers=_hdr(owner_tok))
    _ok("A1 /me role=owner", r.json().get("role") == "owner", str(r.json()))

    r = client.post("/api/invites", json={"note": "给实习生小A"},
                    headers=_hdr(owner_tok))
    _ok("A2 owner 签发注册链接", r.status_code == 200, str(r.status_code))
    invite = r.json().get("token", "")

    r = client.post("/api/assignments/materialize", json={"task_id": TASK_ID},
                    headers=_hdr(owner_tok))
    _ok("A3 owner 物化 T1", r.status_code == 200, str(r.status_code))
    asg = r.json()
    aid, products = asg.get("id"), asg.get("products") or []
    _ok("A3 参赛集非空", bool(products), str(products))
    print(f"      assignment={aid} products={products}")

    # === B. intern 自注册 + 领取 + 提交 ====================================
    print("\n=== B. intern(实习生)自注册 + 领取 + 提交 ===")
    r = client.post("/api/register", json={"invite_token": invite, "name": "小A"})
    _ok("B1 intern 注册", r.status_code == 200, str(r.status_code))
    reg = r.json()
    intern_tok = reg["session_token"]
    intern_id = reg["user"]["id"]
    _ok("B1 默认 intern", reg["user"]["role"] == "intern", str(reg["user"]))

    r = client.get("/api/assignments", headers=_hdr(intern_tok))
    _ok("B2 open 清单含该题", any(a["id"] == aid for a in r.json()), str(r.status_code))

    r = client.post(f"/api/assignments/{aid}/claim", headers=_hdr(intern_tok))
    _ok("B3 intern 领取", r.status_code == 200 and
        r.json().get("claimed_by") == intern_id, str(r.status_code))

    r = client.post(f"/api/assignments/{aid}/submissions",
                    data={"product": products[0], "claimed_success": "true"},
                    headers=_hdr(intern_tok))
    _ok("B4 缺证据被拒 400", r.status_code == 400, str(r.status_code))

    for prod in products:
        r = _submit_one(client, aid, intern_tok, prod, received=(prod == "vio"))
        _ok(f"B5 提交 {prod}", r.status_code == 200, f"{r.status_code} {r.text[:100]}")
    r = client.get(f"/api/assignments/{aid}/submissions", headers=_hdr(intern_tok))
    _ok("B5 整组 complete", r.json().get("complete") is True, str(r.json()))

    r = client.post(f"/api/assignments/{aid}/submit", headers=_hdr(intern_tok))
    _ok("B6 收口 submitted", r.status_code == 200 and
        r.json().get("status") == "submitted", str(r.status_code))

    # C–G 段接续同一 client / 同一库。
    _rest(client, con, store, AUTH, owner_tok, intern_tok, intern_id, products)

    print(f"\n[汇总] PASS={_PASS}  FAIL={_FAIL}")
    if _FAIL:
        print("[阻断] 有断言失败 —— 不可上真人, 先修。")
        return 1
    print("[OK] 三身份全生命周期端到端穿通, 职责边界 + 立身之本全部守住。")
    return 0


def _rest(client, con, store, AUTH, owner_tok, intern_tok, intern_id, products):
    # === C. intern 越权负例 ===============================================
    print("\n=== C. intern 越权负例(职责边界下沿)===")
    r = client.post("/api/invites", json={"note": "x"}, headers=_hdr(intern_tok))
    _ok("C1 intern 签链接被拒 403", r.status_code == 403, str(r.status_code))
    r = client.post("/api/assignments/materialize", json={"task_id": TASK_ID},
                    headers=_hdr(intern_tok))
    _ok("C2 intern 物化被拒 403", r.status_code == 403, str(r.status_code))
    r = client.post(f"/api/users/{intern_id}/role", json={"role": "owner"},
                    headers=_hdr(intern_tok))
    _ok("C3 intern 提升自己被拒 403", r.status_code == 403, str(r.status_code))
    r = client.post("/api/spotcheck/rebuild", headers=_hdr(intern_tok))
    _ok("C4 intern 复核类被拒 403", r.status_code == 403, str(r.status_code))

    # === D. intern 提炼方法初稿 ===========================================
    print("\n=== D. intern 提炼方法初稿(方法闸入口)===")
    prod0 = products[1] if len(products) > 1 else products[0]
    r = client.post("/api/methods", json={
        "task_id": TASK_ID, "product": prod0,
        "draft": "竞品多步规划更稳; Violoop 建议引入显式计划树 + 末态自检"},
        headers=_hdr(intern_tok))
    _ok("D1 intern 创建 draft", r.status_code == 200, str(r.status_code))
    mid = r.json().get("id")
    r = client.post(f"/api/methods/{mid}/export", headers=_hdr(intern_tok))
    # intern 无 gate_method -> 403 优先; 若放行到策略层则 409。两者都算"未把关不进研发"。
    _ok("D2 intern 导出未把关 draft 被拒", r.status_code in (403, 409), str(r.status_code))
    # C5: intern 把关自己的方法 -> 403
    r = client.post(f"/api/methods/{mid}/approve", headers=_hdr(intern_tok))
    _ok("C5 intern 把关方法被拒 403", r.status_code == 403, str(r.status_code))

    # === E. reviewer 复核 + 方法把关 ======================================
    print("\n=== E. reviewer(审核员)复核 + 方法把关 ===")
    # owner 造一个 reviewer(职责分离: 换个人把关, 不自批自己作业)。
    store.upsert_user(con, {"id": "rv1", "name": "审核员", "role": "reviewer"})
    rv_tok = AUTH.login(con, user_id="rv1")
    r = client.get("/api/me", headers=_hdr(rv_tok))
    _ok("E1 reviewer 身份", r.json().get("role") == "reviewer", str(r.json()))

    r = client.post(f"/api/methods/{mid}/approve", headers=_hdr(rv_tok))
    _ok("E2 reviewer 把关 approved", r.status_code == 200 and
        r.json().get("status") == "approved", str(r.status_code))
    r = client.post(f"/api/methods/{mid}/export", headers=_hdr(rv_tok))
    doc = r.json().get("document", "") if r.status_code == 200 else ""
    _ok("E3 reviewer 导出 exported", r.status_code == 200 and
        r.json()["method"]["status"] == "exported", str(r.status_code))
    _ok("E3 文档含落地建议+差距证据",
        "显式计划树" in doc and "差距证据" in doc, doc[:80])
    r = client.post("/api/invites", json={"note": "x"}, headers=_hdr(rv_tok))
    _ok("E4 reviewer 签链接被拒 403", r.status_code == 403, str(r.status_code))
    r = client.post(f"/api/users/{intern_id}/role", json={"role": "owner"},
                    headers=_hdr(rv_tok))
    _ok("E5 reviewer 提升角色被拒 403", r.status_code == 403, str(r.status_code))

    # === F. owner 治理 + 末位保护 =========================================
    print("\n=== F. owner 治理 + 末位 owner 保护 ===")
    r = client.post("/api/users/rv1/role", json={"role": "intern"},
                    headers=_hdr(owner_tok))
    _ok("F1 owner 降 reviewer 回 intern", r.status_code == 200 and
        r.json().get("role") == "intern", str(r.status_code))
    r = client.post("/api/users/owner1/role", json={"role": "intern"},
                    headers=_hdr(owner_tok))
    _ok("F2 降走最后一个 owner 被拒", r.status_code >= 400, str(r.status_code))

    # === G. 匿名负例 ======================================================
    print("\n=== G. 匿名负例 ===")
    r = client.get("/api/me")
    _ok("G1 匿名 /me 401", r.status_code == 401, str(r.status_code))
    r = client.post("/api/assignments/xx/claim")
    _ok("G2 匿名领取被拒 403", r.status_code == 403, str(r.status_code))


if __name__ == "__main__":
    raise SystemExit(main())
