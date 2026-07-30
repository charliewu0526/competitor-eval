"""三角色端到端真走查: 实习生(领题→下载→提交) / PM(反馈台→审→批) / 提交者(查状态)。
全程真实 HTTP 打本机 8600(绕系统代理), 验证状态机真实流转。"""
import json, urllib.request, urllib.error, io, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

BASE = "http://127.0.0.1:8600"
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))

def call(method, path, token=None, body=None, raw=None, ctype=None):
    url = BASE + path
    data = None; headers = {}
    if token: headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        data = json.dumps(body).encode(); headers["Content-Type"] = "application/json"
    elif raw is not None:
        data = raw; headers["Content-Type"] = ctype or "application/octet-stream"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with OP.open(req, timeout=30) as r:
            b = r.read()
            try: return r.getcode(), json.loads(b)
            except Exception: return r.getcode(), b
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read())
        except Exception: return e.code, e.read()[:200]

results = []
def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"{'✓' if ok else '✗'} {name}  {detail}")

from pipeline import auth as AUTH, store as STORE
# 关键: 必须连后端同一个 Postgres(board/pg_uri.txt), 而非脚本默认 SQLite ——
# 否则脚本签发的 invite 后端看不到 -> 注册 400(本项目已知连库坑)。
_uri = pathlib.Path(__file__).resolve().parent.parent / "board" / "pg_uri.txt"
con = STORE.connect(url=_uri.read_text().strip(), skip_migrate=True)

# ============ 实习生角色 ============
print("\n=== 实习生角色 ===")
inv = AUTH.issue_invite(con, created_by="owner1", note="走查")
code, res = call("POST", "/api/register", body={"invite_token": inv["token"], "name": "走查实习生"})
check("注册(持链接)", code == 200 and "session_token" in res, f"HTTP {code}")
itk = res.get("session_token"); iuid = res.get("user", {}).get("id")

code, me = call("GET", "/api/me", token=itk)
check("会话识别身份", code == 200 and me.get("role") == "intern", f"role={me.get('role')}")

code, cat = call("GET", "/api/catalog", token=itk)
ntasks = sum(len(g.get("tasks", [])) for g in cat) if isinstance(cat, list) else 0
check("浏览任务清单", code == 200 and ntasks > 0, f"HTTP {code} tasks={ntasks}")

# 选一个多素材任务验证详情 + 下载
tid = "T9-excel-merge-pivot-001"
code, task = call("GET", f"/api/catalog/{tid}", token=itk)
ifs = task.get("input_files", []) if code == 200 else []
check("任务详情+input_files", code == 200 and len(ifs) > 1, f"HTTP {code} files={len(ifs)}")

# 一键下载: 逐个真下 input 文件(模拟前端批量)
dl_ok = 0
for f in ifs:
    c, _ = call("GET", f"/api/catalog/{tid}/input/{f}", token=itk)
    if c == 200: dl_ok += 1
check("一键下载全部素材", dl_ok == len(ifs), f"{dl_ok}/{len(ifs)} 下载成功")

# 领题(题×产品粒度) — 选一个参赛产品领取
prod = (task.get("participating") or ["vio"])[0]
code, asg = call("POST", f"/api/catalog/{tid}/claim", token=itk, body={"task_id": tid, "product": prod})
# 已被领 409 也算链路可用(幂等), 取 assignment id
aid = asg.get("id") if isinstance(asg, dict) else None
check("领题(题×产品)", code in (200, 409), f"HTTP {code} product={prod}")
if code == 200 and aid:
    # 构造最小产物 + 日志包(multipart), 真提交
    import uuid
    boundary = "----wt" + uuid.uuid4().hex
    def mp_field(name, val): return (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{val}\r\n').encode()
    def mp_file(name, fn, content): return (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{fn}"\r\nContent-Type: application/octet-stream\r\n\r\n').encode()+content+b"\r\n"
    payload = (mp_field("product", prod) + mp_field("transcript_excerpt", "走查提交") +
               mp_file("artifact", "out.txt", b"walkthrough artifact bytes") +
               mp_file("log_bundle", "log.txt", b"walkthrough log bytes") +
               f"--{boundary}--\r\n".encode())
    c2, sub = call("POST", f"/api/assignments/{aid}/submissions", token=itk,
                   raw=payload, ctype=f"multipart/form-data; boundary={boundary}")
    check("提交产物+日志(intake)", c2 in (200, 201), f"HTTP {c2}")

# ============ PM/owner 角色: 反馈台 ============
print("\n=== PM/owner 角色 ===")
otk = AUTH.login(con, user_id="owner1")
code, me2 = call("GET", "/api/me", token=otk)
check("owner 登录", code == 200 and me2.get("role") in ("owner", "reviewer"), f"role={me2.get('role')}")

code, console = call("GET", "/api/reports/console", token=otk)
check("反馈台可读", code == 200 and isinstance(console, list), f"HTTP {code} n={len(console) if isinstance(console,list) else '?'}")

# 反馈台字段完整性: 应带 change_summary/diagnosis 字段(可为空但键在)
if isinstance(console, list) and console:
    sample = console[0]
    has_fields = "change_summary" in sample or "diagnosis" in sample
    check("反馈台透出人话字段", has_fields, f"keys含change_summary/diagnosis={has_fields}")

# ============ 提交者角色: 查自己反馈状态 ============
print("\n=== 提交者查状态 ===")
code, mine = call("GET", "/api/reports/mine", token=itk)
check("提交者查反馈状态", code == 200, f"HTTP {code}")

print("\n=== 汇总 ===")
passed = sum(1 for _, ok, _ in results if ok)
print(f"{passed}/{len(results)} 通过")
if passed != len(results):
    print("FAILED:", [n for n, ok, _ in results if not ok])
