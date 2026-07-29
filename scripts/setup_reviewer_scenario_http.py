"""后三阶段场景搭建 —— 打真实运行的 8600 后端(写的就是 UI 读的同一个 Postgres)。

之前的坑: TestClient 默认连 SQLite, 而 8600 跑的是 pgserver(Postgres) —— 两个库,
所以 UI 里查无此人。这里改用 HTTP 直打 8600, 数据落到 UI 真正读的 PG。
"""
import io, json, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import requests

BASE = "http://127.0.0.1:8600/api"
S = requests.Session()
S.trust_env = False   # 绕开系统全局代理 7897
TID = "T1-wechat-send-001"
INTERN = "u_poPLRC2lBrxd"


def login(uid):
    r = S.post(f"{BASE}/login", json={"user_id": uid}, timeout=10)
    r.raise_for_status()
    return r.json()["session_token"]


def h(tok):
    return {"Authorization": f"Bearer {tok}"}


out = []
def log(*a):
    line = " ".join(str(x) for x in a)
    out.append(line)
    print(line, flush=True)


# 1. owner 登录, 建 reviewer 账号 —— 走真实端点。owner 无法凭空建用户, 故先让
#    reviewer 用一个邀请自注册? 简化: owner 直接 promote 一个已存在 intern 不行(只有一个)。
#    改为: 用 invite 生成邀请 -> register 自注册成 intern -> owner promote 成 reviewer。
owner = login("owner1")
inv = S.post(f"{BASE}/invites", headers=h(owner), json={"note": "reviewer for walkthrough"}, timeout=10)
log("invite:", inv.status_code, inv.text[:150])
invite_token = inv.json().get("token") or inv.json().get("invite_token")

reg = S.post(f"{BASE}/register", json={"invite_token": invite_token, "name": "复核员-走查Reviewer"}, timeout=10)
log("register:", reg.status_code, reg.text[:200])
rev_user = reg.json()["user"]["id"]

pr = S.post(f"{BASE}/users/{rev_user}/role", headers=h(owner), json={"role": "reviewer"}, timeout=10)
log("promote reviewer:", pr.status_code, pr.text[:150], "-> id=", rev_user)

# 2. 实习生领 T1 (若已被领/交, 先放弃重来)。
itok = login(INTERN)
# 查我的任务里 T1 状态
mine = S.get(f"{BASE}/assignments", headers=h(itok), timeout=10).json()
t1 = next((a for a in mine if a["task_id"] == TID), None)
if t1 and t1["status"] in ("claimed", "submitted"):
    S.post(f"{BASE}/assignments/{t1['id']}/abandon", headers=h(itok), timeout=10)
    log("abandoned old T1:", t1["id"], t1["status"])
rc = S.post(f"{BASE}/catalog/{TID}/claim", headers=h(itok), timeout=10)
log("claim:", rc.status_code, rc.text[:200])
if rc.status_code < 400 and "id" in rc.json():
    aid = rc.json()["id"]
else:
    # 已被本人领取(409): 从我的任务取回该 assignment id 继续。
    mine2 = S.get(f"{BASE}/assignments", headers=h(itok), timeout=10).json()
    t1b = next(a for a in mine2 if a["task_id"] == TID)
    aid = t1b["id"]
    log("reuse claimed T1:", aid, t1b["status"])


def submit(product, manual, art, log_json, claimed):
    files = {"artifact": (f"{product}.txt", io.BytesIO(art.encode()), "text/plain"),
             "log_bundle": (f"{product}.json", io.BytesIO(log_json.encode()), "application/json")}
    data = {"product": product, "manual_assertions": json.dumps(manual),
            "claimed_success": str(claimed).lower(), "transcript_excerpt": f"{product} run"}
    rr = S.post(f"{BASE}/assignments/{aid}/submissions", headers=h(itok), files=files, data=data, timeout=30)
    log(f"submit {product}:", rr.status_code, rr.text[:120])


vio_log = json.dumps({"product": "vio", "input_tokens": 3800, "output_tokens": 900,
    "model_calls": 4, "model": "deepseek-v4-pro", "cost_source": "self-report",
    "events": ["run.start", "wechat.open", "type.message", "press.enter", "verify.bubble.visible", "run.end"]})
claude_log = json.dumps({"product": "claude", "input_tokens": 15200, "output_tokens": 3100,
    "model_calls": 14, "model": "claude-3.7-sonnet", "cost_source": "self-report",
    "events": ["run.start", "screenshot.desktop", "search.contact", "type.message", "press.enter", "run.end"]})

submit("vio", {"msg_received": True, "text_exact": True, "no_collateral": True},
       "vio: sent exact msg to 文件传输助手, bubble 15:02, no collateral.", vio_log, True)
submit("claude", {"msg_received": False, "text_exact": False, "no_collateral": True},
       "claude: claimed done, but NO message actually reached 文件传输助手.", claude_log, True)

# 3. 收口 -> 盲评 + 重评 findings (180s 超时给盲评)
rs = S.post(f"{BASE}/assignments/{aid}/submit", headers=h(itok), timeout=180)
log("收口:", rs.status_code, rs.text[:200])

# 4. owner 重建抽查队列
rb = S.post(f"{BASE}/spotcheck/rebuild", headers=h(owner), timeout=30)
log("rebuild spotcheck:", rb.status_code, rb.text[:200])

# 5. 读回验证
sc = S.get(f"{BASE}/scores", headers=h(owner), timeout=10)
log("scores(T1):", [(x["product"], x.get("sample_score"), x.get("h1_honesty"))
                    for x in sc.json() if x.get("task_id") == TID] if sc.status_code < 400 else sc.text[:150])
sq = S.get(f"{BASE}/spotcheck", headers=h(owner), timeout=10)
log("spotcheck pending:", [(q["id"], q["product"], q.get("stratum"))
                           for q in sq.json() if q.get("status") == "pending"] if sq.status_code < 400 else sq.text[:150])

pathlib.Path("board/reviewer_scenario_out.txt").write_text("\n".join(out))
log("REVIEWER_ID=" + rev_user)
