"""Publish PRD-0003's 14 vertical-slice issues in dependency order, backfilling
real blocker issue numbers. Idempotent-ish: prints created numbers; re-running
creates duplicates, so run once. Uses gh CLI on PATH.
"""
import subprocess, json, pathlib, sys

REPO_DIR = "/Users/charlie/.violoop/workspace/competitor-eval"
PARENT = 36
LABEL = "ready-for-agent"

# id -> (title, blocked_by[ids], what, acceptance[])
ISSUES = [
    ("I1", "[MR-1] 预制:存储迁并发库 + 新实体 schema", [],
     "预制切片(make the change easy):把 store 层从本地 SQLite 迁到支持多人并发的数据库(选型:Postgres 或托管库,在本切片定并落地),并扩展 F1 schema 新增实体 User / Assignment / Submission / Method,以及 RunRecord+score 的 competitor_version / tested_at / stale 字段(ADR-0017)。评分核心逻辑不改,现有 20 个测试全部保持绿色作为回归护栏。这是纯地基,不含任何多人业务逻辑。",
     ["选定并接入支持并发的数据库,store 层读写通过它",
      "User/Assignment/Submission/Method 四实体建表,字段对齐 CONTEXT 术语",
      "RunRecord/score 增 competitor_version、tested_at、stale 字段",
      "现有 tests/ 全部 20 个测试不改动即通过(回归护栏)",
      "评分核心 pipeline/ 代码零改动"]),

    ("I2", "[MR-2] 曳光弹:Submission→RunRecord→引擎→榜单 打穿", ["I1"],
     "唯一新核心接缝的最小实现(tracer bullet)。新增 intake 翻译模块 translate(submission, task_meta, registry) -> RunRecord,用一份写死的 Submission(含日志包 fixture)喂进去,穿过现有评分核心(GATE→客观断言→盲评→H1),最终榜单出现一条带 competitor_version/tested_at 的分数。故意不含注册/领取/上传/脱敏——只证明整条链端到端打通。与现有 5 适配器同构:真实现 + 内存假实现。",
     ["intake 模块存在,translate 把假 Submission 译成合法 RunRecord",
      "写死输入端到端跑通:Submission→RunRecord→独立打分→落库→榜单",
      "榜单能查到该分且带 competitor_version 与 tested_at",
      "intake 有真实现 + 内存假实现,契约测试(仿 test_*_adapter_*)覆盖",
      "GATE 由 gate_for(competitor,task) 推导,不信 submission 自报"]),

    ("I3", "[MR-3] 私发链接自注册登录,默认 intern", ["I1"],
     "内部人员通过私发注册链接自注册并登录,注册成功默认拿到 intern 角色。注册不对公网开放(仅持链接者可注册,ADR-0014)。这是账号系统最薄的一刀,只到「能登录、有身份」。",
     ["持有效链接可自注册,无链接不能注册",
      "注册成功默认角色为 intern",
      "登录后会话可识别当前用户与角色",
      "端到端:注册→登录→拿到 intern 身份可验证"]),

    ("I4", "[MR-4] 角色提升 + 权限边界", ["I3"],
     "三级 RBAC 的权限边界(ADR-0014):PM(owner)可把某 intern 提升为 reviewer;owner 独占黄金集校准/评委授权/脱敏规则等权限;reviewer 可复核但碰不到校准开关;intern 不能复核。本切片只做角色与权限判定,不含具体复核/校准业务(那在 I13)。",
     ["owner 能把 intern 提升为 reviewer",
      "校准/评委授权类操作仅 owner 可调用,reviewer/intern 被拒",
      "复核类入口 intern 被拒、reviewer/owner 放行",
      "权限边界有针对性测试(每种角色 × 每类操作)"]),

    ("I5", "[MR-5] 任务清单预置 + 按能力域分组浏览", ["I1"],
     "PM 预置一个按能力域(capability domain)分组的任务清单;intern 能浏览清单、按域筛选、看到每道题的详细说明与中立标准 Prompt(ADR-0016,禁用产品专属语法)。本切片只到「看得到题、看得到该发的 Prompt」,不含领取动作(在 I6)。",
     ["PM 能预置任务并归入能力域分组",
      "intern 浏览清单,可按能力域筛选",
      "每道题展示详细说明 + 中立标准 Prompt",
      "同域才同台:清单结构支撑「同域竞品放一起比」"]),

    ("I6", "[MR-6] 并发领取 + Assignment 状态机", ["I5", "I4"],
     "intern 领取「一道对比任务的全部」(Assignment = 该题 Violoop + 同域全部竞品,一人一次性,ADR-0015)。领取加并发锁:两人抢同一道只有一个成功。状态机 open→claimed→submitted,以及放弃/超时回到 open。",
     ["领取的最小单元是整道对比任务(含该域全部参赛产品)",
      "并发领取:两请求抢同一 Assignment,仅一个成功,另一个见已锁定",
      "状态机 open/claimed/submitted/abandoned 正确流转",
      "放弃或超时未交的 Assignment 回到 open 可被再领"]),

    ("I7", "[MR-7] 提交表单 + 原始产物上传 + 缺证据拒收", ["I2", "I6"],
     "intern 为 Assignment 里每个产品各提交一份 Submission:上传原始产物(截图/导出文件/AI 对话记录)。缺证据(无原始产物或后续 I9 的无日志包)拒绝提交,落实「无证据不入池」。本切片建立提交管道 + 文件存储 + 与 I2 的 intake 接线。",
     ["一道 Assignment 可为每个产品分别提交 Submission",
      "原始产物文件上传并持久化(对象存储/服务端目录)",
      "缺原始产物时提交被拒",
      "提交的 Submission 能流向 I2 的 intake 接缝"]),

    ("I8", "[MR-8] 人工勾选断言 + claimed_success + 机器断言自动判", ["I7"],
     "断言翻译分工(CONTEXT):只能人看的断言(如微信消息真发出)由 intern 勾选;机器可验的(文件存在、某格值、日志有无某事件)自动判定;intern 声明该产品是否自称完成(claimed_success)供 H1 诚实度轴;GATE 由能力×任务推导。这些经 intake 正确落入 RunRecord。",
     ["提交表单含人工勾选断言 + claimed_success 声明",
      "机器可验断言由脚本/规则自动判定,不落人手",
      "claimed_success 进入 RunRecord,H1 诚实度轴能算出(谎报→H1=1)",
      "GATE 推导:够不到的产品判 cannot-reach 而非 0 分"]),

    ("I9", "[MR-9] 日志包解析→cost + 脱敏/原始双视图", ["I7"],
     "强制上传执行日志包(时间线+token+调用次数);解析填入 cost_source(复用 A3 成本契约);派生脱敏版(洗品牌/模型指纹,喂盲评面板)与原始版(完整,给成本统计+人工抽查)(ADR-0013)。MVP 脱敏可人工,但双视图数据结构必须就位。",
     ["无日志包时提交被拒(强制)",
      "日志解析出 token/调用/时间线并填 cost_source(非 0 伪装)",
      "同一日志派生 redacted 与 raw 两视图,数据结构就位",
      "脱敏版不含品牌/模型指纹(洗漏=破盲,重点回归测)"]),

    ("I10", "[MR-10] 送面板前打乱标签 + 独立打分接线", ["I2", "I8", "I9"],
     "盲评(ADR-0012):交付物送评审面板前打乱产品标签(复用 registry blind_label),每份交付物各自独立跑评分(非成对对比)。把 I8/I9 产出的完整 RunRecord 正式接入盲评面板,面板看脱敏版日志。",
     ["送面板前产品标签被打乱为 Product A/B/C",
      "每份交付物独立打分,不做成对对比",
      "面板输入用脱敏版日志,不泄露产品身份",
      "端到端:真实 Submission→独立盲评分数落库"]),

    ("I11", "[MR-11] 差距报告派生视图", ["I10"],
     "差距报告 = 派生视图(ADR-0012),不是新审核逻辑:从现有 scores/findings 组装「分数差 + 大差距自动生成的 Finding + 开源竞品源码机理分析」。一道对比任务产出一份可读差距报告。",
     ["一道 Assignment 产出一份差距报告",
      "报告含:Violoop vs 各竞品分数差",
      "大差距自动生成 Finding(现象,机器只标不下结论)",
      "开源竞品附源码机理分析(带 repo 链接)"]),

    ("I12", "[MR-12] 能力域分维度榜单 + 版本/日期/stale", ["I11"],
     "榜单按能力域分维度展示(Violoop 全域参赛,竞品各归其位);每条分数显示竞品版本 + 测试日期;超过 N 天(建议 90)标陈旧 stale(ADR-0017,MVP 判定可人工/半自动)。桌面题考代码 agent 显示 cannot-reach 而非 0 分。",
     ["榜单按能力域分成多个维度榜",
      "每条分数显示 competitor_version + tested_at",
      "超期分数标 stale,不冒充现状",
      "cannot-reach 的产品在榜上标「未参赛」而非 0 分垫底"]),

    ("I13", "[MR-13] 人工复核队列 + 职责分离 + 重校准", ["I12"],
     "只对大差距/评委分歧/疑似谎报强制入人工复核队列,其余分层抽查(复用 sampling.build_queue,「大差距」并入分层规则)。职责分离:执行某 Assignment 的 intern 不被指派复核同一条。reviewer/PM 下「有道理/有问题」结论;「有问题」可触发黄金集重校准(仅 owner)。",
     ["大差距/分歧/谎报强制入复核队列,其余抽查",
      "执行者不被指派复核自己执行的 Assignment(职责分离)",
      "reviewer/PM 能对复核项下有道理/有问题结论",
      "「有问题」可触发重校准,且仅 owner 能触发"]),

    ("I14", "[MR-14] 方法初稿提炼 + 复核闸 + 导出研发", ["I11"],
     "沉淀方法给研发:intern 在差距证据包(分数差+Finding+机理)上提炼「方法」初稿(Method,状态 draft);初稿必须经 reviewer/PM 把关(approved)才能导出(exported)给研发(方法复核闸)。防新人瞎提炼污染可信度。",
     ["intern 能在差距证据包上创建 Method 初稿(draft)",
      "draft 未经把关不能导出",
      "reviewer/PM 可把关 draft→approved",
      "approved 的 Method 可导出为研发可读格式(竞品为何强+Violoop落地建议)"]),
]


def sh(args):
    return subprocess.run(args, cwd=REPO_DIR, capture_output=True, text=True)


def main():
    created = {}  # id -> issue number
    order = [i[0] for i in ISSUES]
    by_id = {i[0]: i for i in ISSUES}
    for iid in order:
        _id, title, blocked, what, acc = by_id[iid]
        blockers = "\n".join(f"- #{created[b]} ({b})" for b in blocked) or "None - can start immediately"
        acc_md = "\n".join(f"- [ ] {a}" for a in acc)
        body = (f"## Parent\n\n- #{PARENT} (PRD-0003 多人竞品评测工场)\n\n"
                f"## What to build\n\n{what}\n\n"
                f"## Acceptance criteria\n\n{acc_md}\n\n"
                f"## Blocked by\n\n{blockers}\n")
        bf = pathlib.Path(REPO_DIR) / f"outputs/agenda/_issue_{iid}.md"
        bf.write_text(body)
        r = sh(["gh", "issue", "create", "--title", title,
                "--label", LABEL, "--body-file", str(bf)])
        url = (r.stdout or "").strip().splitlines()[-1] if r.stdout.strip() else ""
        num = url.rsplit("/", 1)[-1] if url else "?"
        created[iid] = num
        print(f"{iid} -> #{num}  {title}  (blocked by {blocked})")
        if r.returncode != 0:
            print("  ERROR:", r.stderr[:400]); sys.exit(1)
    print("\nDONE. mapping:", json.dumps(created, ensure_ascii=False))


if __name__ == "__main__":
    main()
