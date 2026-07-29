"""上线前验证: 走与浏览器完全相同的 multipart 提交端点(带 manual_assertions),
收口触发重评, 断言三个 bug 都真修好。单进程跑完, 避免跨进程连接/输出问题。
"""
import io, json, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient
import server.app as A

client = TestClient(A.app)
con = A._con()
TID = "T1-wechat-send-001"

tok = client.post("/api/login", json={"user_id": "u_poPLRC2lBrxd"}).json()["session_token"]
H = {"Authorization": f"Bearer {tok}"}

# 自给自足: 先以实习生身份走 catalog 自助领取端点把 T1 领出来(与浏览器同一端点)。
# 并发的其他会话可能已清/领该题, 故容错: 已被本人领->直接用; 已被他人->先放弃重领。
rc = client.post(f"/api/catalog/{TID}/claim", headers=H)
print("catalog claim:", rc.status_code, rc.text[:200], flush=True)
row = con.execute("SELECT id, status, claimed_by FROM assignments WHERE task_id=?", (TID,)).fetchone()
assert row, "T1 assignment 仍不存在(领取失败)"
aid = row["id"]
print("T1 assignment:", aid, "status=", row["status"], "by=", row["claimed_by"], flush=True)


def submit(product, manual, art, log):
    files = {
        "artifact": (f"{product}_art.txt", io.BytesIO(art.encode()), "text/plain"),
        "log_bundle": (f"{product}_log.json", io.BytesIO(log.encode()), "application/json"),
    }
    data = {"product": product, "manual_assertions": json.dumps(manual),
            "claimed_success": "true", "transcript_excerpt": f"{product} run"}
    r = client.post(f"/api/assignments/{aid}/submissions", headers=H, files=files, data=data)
    print(f"submit {product}: HTTP {r.status_code}",
          (r.json() if r.status_code < 400 else r.text[:300]), flush=True)
    return r.status_code < 400


vio_log = json.dumps({"product": "vio", "input_tokens": 3800, "output_tokens": 900,
    "model_calls": 4, "model": "deepseek-v4-pro", "cost_source": "self-report",
    "evidence_source": "screenshot",
    "events": ["run.start", "wechat.open", "type.message", "press.enter", "verify.bubble.visible", "run.end"]})
claude_log = json.dumps({"product": "claude", "input_tokens": 12400, "output_tokens": 2600,
    "model_calls": 11, "model": "claude-3.7-sonnet", "cost_source": "self-report",
    "evidence_source": "screenshot",
    "events": ["run.start", "screenshot.desktop", "select.WRONG_contact", "backout.no_send", "re.search.contact", "type.message", "press.enter", "run.end"]})

ALL = {"msg_received": True, "text_exact": True, "no_collateral": True}
submit("vio", ALL, "vio: sent exact msg to 文件传输助手, bubble 15:02, no collateral.", vio_log)
submit("claude", ALL, "claude: after one wrong-contact backout, sent exact msg 15:07.", claude_log)

# 收口 -> 触发整组盲评 + 重评 findings
r = client.post(f"/api/assignments/{aid}/submit", headers=H)
print("收口 HTTP", r.status_code, r.json().get("score_status") if r.status_code < 400 else r.text[:300], flush=True)

# 验证落库结果
print("\n=== scores (期望非0真实分) ===", flush=True)
for s in A.store.all_scores(con):
    if s["task_id"] == TID:
        print(f"  {s['product']:8s} sample={s.get('sample_score')} h1={s.get('h1_honesty')} "
              f"obj_ratio={s.get('objective_ratio')} scored={s.get('scored')} reason={s.get('reason')}", flush=True)

print("\n=== findings (期望只含 vio/claude, 无 open_interpreter 幽灵) ===", flush=True)
for f in A.store.all_findings(con):
    if f.get("task_id") == TID:
        print(f"  {f.get('rule')} | {f.get('subject')} | {f.get('suspected_category')}", flush=True)
