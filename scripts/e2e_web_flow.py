"""端到端真跑「Web 前台完整闭环」: 注册→领取→提交→复核→方法闸导出.

scripts/e2e_real_run.py 只走了引擎半条 (intake→盲评→落库→差距报告)。这个脚本补
另一半 —— PRD-0003 v1 验收真正要证明的「实习生真跑一道题」的完整多人流程, 全走
真实 HTTP 表面 (FastAPI TestClient), 离线临时库, 绝不碰生产 board/。

链路 (每步都是真 HTTP 请求 + 真鉴权 + 真落库):
  1. owner 登录 (seed 一个 owner, 换发会话令牌)
  2. owner 签发私发注册链接 (issue_invite)
  3. intern 持链接自注册 -> 默认 intern + 会话令牌
  4. owner 把清单里的 T1 物化成可领取 Assignment (含同域参赛产品集)
  5. intern 领取该 Assignment (并发领取锁)
  6. intern 为参赛集里每个产品各提交一份 Submission (真上传原始产物 + 日志包)
     - 缺证据当场被拒 (无证据不入池) —— 负例验证
  7. intern 收口整组 -> submitted
  8. reviewer 复核 + 方法闸: intern 提炼方法初稿 -> reviewer 把关 -> 导出研发可读

RBAC 负例贯穿: intern 不能签链接 / 不能物化 / 不能把关方法, 越权一律 403。
"""
from __future__ import annotations
import io
import json
import pathlib
import sys
import tempfile

# 让脚本可直接 `python scripts/e2e_web_flow.py` 跑 (无需手动 PYTHONPATH=.)。
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _ok(label: str, cond: bool, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail else ""))
    if not cond:
        raise SystemExit(f"端到端断言失败: {label} {detail}")


def main() -> int:
    import server.app as APP
    # 指向临时空库, 绝不碰生产 board/competitor_eval.db。
    APP._DB_PATH = str(pathlib.Path(tempfile.mkdtemp(prefix="e2e-web-")) / "web.db")
    client = TestClient(APP.app)

    # 直接在库里 seed 一个 owner (第一版无自举 owner 端点, owner 由部署时植入)。
    from pipeline import store, auth as AUTH
    con = store.connect(APP._DB_PATH)
    store.upsert_user(con, {"id": "owner1", "name": "PM", "role": "owner"})

    print("=== 1. owner 登录 (换发会话令牌) ===")
    r = client.post("/api/login", json={"user_id": "owner1"})
    _ok("owner login 200", r.status_code == 200, str(r.status_code))
    owner_tok = r.json()["session_token"]
    r = client.get("/api/me", headers=_hdr(owner_tok))
    _ok("owner /me role=owner", r.json().get("role") == "owner", str(r.json()))

    print("\n=== 2. owner 签发私发注册链接 (RBAC: 仅 owner) ===")
    r = client.post("/api/invites", json={"note": "给实习生小A"},
                    headers=_hdr(owner_tok))
    _ok("issue invite 200", r.status_code == 200, str(r.status_code))
    invite = r.json()["token"]

    print("\n=== 3. intern 持链接自注册 -> 默认 intern ===")
    r = client.post("/api/register", json={"invite_token": invite, "name": "小A"})
    _ok("register 200", r.status_code == 200, str(r.status_code))
    reg = r.json()
    intern_tok = reg["session_token"]
    intern_id = reg["user"]["id"]
    _ok("新用户默认 intern", reg["user"]["role"] == "intern", str(reg["user"]))
    # 负例: intern 不能签发链接 (越权 403)
    r = client.post("/api/invites", json={"note": "x"}, headers=_hdr(intern_tok))
    _ok("intern 签链接被拒 403", r.status_code == 403, str(r.status_code))

    print("\n=== 4. owner 把 T1 物化成可领取 Assignment ===")
    task_id = "T1-wechat-send-001"
    # 负例: intern 不能物化 (manage_task_catalog owner 独占)
    r = client.post("/api/assignments/materialize", json={"task_id": task_id},
                    headers=_hdr(intern_tok))
    _ok("intern 物化被拒 403", r.status_code == 403, str(r.status_code))
    r = client.post("/api/assignments/materialize", json={"task_id": task_id},
                    headers=_hdr(owner_tok))
    _ok("materialize 200", r.status_code == 200, str(r.status_code))
    asg = r.json()
    aid, products = asg["id"], asg["products"]
    _ok("参赛产品集非空", bool(products), str(products))
    print(f"      assignment={aid} products={products}")

    print("\n=== 5. intern 领取该 Assignment (并发领取锁) ===")
    r = client.get("/api/assignments", headers=_hdr(intern_tok))
    _ok("open 清单含该题", any(a["id"] == aid for a in r.json()), str(r.json()))
    r = client.post(f"/api/assignments/{aid}/claim", headers=_hdr(intern_tok))
    _ok("claim 200", r.status_code == 200, str(r.status_code))
    _ok("claimed_by=intern", r.json().get("claimed_by") == intern_id, str(r.json()))
    # 负例: owner 再抢同一道 -> 已锁定 409
    r = client.post(f"/api/assignments/{aid}/claim", headers=_hdr(owner_tok))
    _ok("并发再领被拒 409", r.status_code == 409, str(r.status_code))

    print("\n=== 6. intern 为每个产品各提交一份 Submission (真上传) ===")
    # 负例先行: 缺原始产物 -> 无证据不入池 400
    r = client.post(
        f"/api/assignments/{aid}/submissions",
        data={"product": products[0], "claimed_success": "true"},
        headers=_hdr(intern_tok))
    _ok("缺证据提交被拒 400", r.status_code == 400, str(r.status_code))

    log_bundle = json.dumps({
        "input_tokens": 4200, "output_tokens": 1300, "model_calls": 6,
        "model": "deepseek-v4-pro", "cost_source": "self-report",
        "evidence_source": "log",
        "events": ["run.start", "wechat.open", "type.message",
                   "press.enter", "verify.bubble", "run.end"],
    }, ensure_ascii=False)

    for i, prod in enumerate(products):
        # 末态由人工勾选: vio 真发成功, 其余留待复核 (这里都给真结果, 演示穿通)。
        received = (prod == "vio")
        files = {
            "artifact": (f"{prod}.png", io.BytesIO(b"\x89PNG fake artifact"), "image/png"),
            "log_bundle": (f"{prod}-log.json", io.BytesIO(log_bundle.encode()),
                           "application/json"),
        }
        data = {
            "product": prod,
            "manual_assertions": json.dumps({
                "msg_received": received, "text_exact": received,
                "no_collateral": True}),
            "claimed_success": "true",
            "competitor_version": "computer-use" if prod == "vio" else "0.4.3",
        }
        r = client.post(f"/api/assignments/{aid}/submissions",
                        data=data, files=files, headers=_hdr(intern_tok))
        _ok(f"submit {prod} 200", r.status_code == 200,
            f"{r.status_code} {r.text[:160]}")
    r = client.get(f"/api/assignments/{aid}/submissions", headers=_hdr(intern_tok))
    prog = r.json()
    _ok("整组提交齐 (complete)", prog.get("complete") is True, str(prog))

    print("\n=== 7. intern 收口整组 -> submitted ===")
    r = client.post(f"/api/assignments/{aid}/submit", headers=_hdr(intern_tok))
    _ok("收口 submitted 200", r.status_code == 200, str(r.status_code))
    _ok("状态=submitted", r.json().get("status") == "submitted", str(r.json()))

    print("\n=== 8. 方法闸: intern 提炼 -> reviewer 把关 -> 导出 ===")
    # owner 把 intern 之外再造一个 reviewer (职责: 谁执行谁不批, 换个人把关)。
    store.upsert_user(con, {"id": "rv1", "name": "审核员", "role": "reviewer"})
    rv_tok = AUTH.login(con, user_id="rv1")

    prod0 = products[1] if len(products) > 1 else products[0]
    # intern 创建方法初稿 (draft)
    r = client.post("/api/methods", json={
        "task_id": task_id, "product": prod0,
        "draft": "竞品多步规划更稳; Violoop 建议引入显式计划树 + 末态自检"},
        headers=_hdr(intern_tok))
    _ok("intern 创建 draft 200", r.status_code == 200, str(r.status_code))
    mid = r.json()["id"]

    # 负例: draft 未把关就导出 -> 复核闸拦 409
    r = client.post(f"/api/methods/{mid}/export", headers=_hdr(rv_tok))
    _ok("未把关导出被拒 409", r.status_code == 409, str(r.status_code))
    # 负例: intern 不能把关自己的提炼 (gate_method reviewer 起)
    r = client.post(f"/api/methods/{mid}/approve", headers=_hdr(intern_tok))
    _ok("intern 把关被拒 403", r.status_code == 403, str(r.status_code))

    # reviewer 把关 draft->approved
    r = client.post(f"/api/methods/{mid}/approve", headers=_hdr(rv_tok))
    _ok("reviewer approve 200", r.status_code == 200, str(r.status_code))
    _ok("status=approved", r.json().get("status") == "approved", str(r.json()))

    # reviewer 导出 -> 研发可读 markdown
    r = client.post(f"/api/methods/{mid}/export", headers=_hdr(rv_tok))
    _ok("export 200", r.status_code == 200, str(r.status_code))
    out = r.json()
    doc = out["document"]
    _ok("导出=exported", out["method"]["status"] == "exported", str(out["method"]))
    _ok("研发文档含落地建议", "显式计划树" in doc, doc[:120])
    _ok("研发文档含差距证据块", "差距证据" in doc, "")
    print("\n----- 导出的研发可读方法文档 (节选) -----")
    print("\n".join(doc.splitlines()[:16]))

    con.close()
    print("\n[OK] Web 前台完整闭环端到端穿通: "
          "注册→领取→提交(缺证据被拒)→收口→方法闸导出, RBAC 负例全过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
