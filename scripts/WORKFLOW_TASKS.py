# -*- coding: utf-8 -*-
"""职业工作流高阶任务定义 (数据驱动, 供 gen_workflow_tasks.py 消费)。

每个任务模拟一个真实岗位一段完整工作流, 跨多个本地 app, 含判断分叉。
断言分层: ("file_exists", desc, primary) 机器判 / ("manual", desc, ctx_key, primary) 人工核验。
"""

WORKFLOW_TASKS = [

    # ================= W2 HR 候选人初筛安排 =================
    {
        "id": "W2-hr-screening-schedule-001",
        "input_desc": "candidates.csv 候选人打分材料 / jd.txt 岗位要求 / contacts.txt 候选人微信",
        "output_desc": "shortlist.xlsx 入围名单 / interviews.md 约面记录",
        "dirty_level": "light",
        "input_files": {
            "candidates.csv": (
                "name,years_exp,skill_match,expected_salary_k,status\n"
                "陈昊,5,高,28,可面\n"
                "林悦,2,中,18,可面\n"
                "王朔,8,高,45,可面\n"
                "赵雪,3,低,20,可面\n"
                "周# 缺失,,,,\n"
            ),
            "jd.txt": (
                "岗位: 高级后端工程师\n"
                "硬性要求: 工作经验>=3年 且 技能匹配度=高\n"
                "薪资预算上限: 40k\n"
                "不满足硬性要求或超预算的候选人不进入面试。\n"
            ),
            "contacts.txt": (
                "陈昊 -> 微信备注: 陈昊(候选)\n"
                "林悦 -> 微信备注: 林悦\n"
                "王朔 -> 微信备注: 王朔Ryan\n"
                "赵雪 -> 微信备注: 赵雪HR推荐\n"
            ),
        },
        "prompt": (
            "# Prompt (handed verbatim to each product)\n\n"
            "我在筛选\"高级后端工程师\"的候选人, 请帮我完成整套初筛+约面:\n\n"
            "1. 打开 `input/candidates.csv`(候选人材料)和 `input/jd.txt`(岗位硬性要求)。\n"
            "2. 按 JD 的硬性要求逐个判断谁入围: 经验>=3年 且 技能匹配=高 且 期望薪资<=预算上限40k。\n"
            "   注意 candidates.csv 里有残缺行(信息不全的无效条目), 应跳过, 不能当成候选人。\n"
            "3. 把入围者整理成 `output/shortlist.xlsx`, 含列: 姓名、经验年数、技能匹配、期望薪资。\n"
            "4. 给每个入围候选人在微信发一条约面邀请(联系人备注见 `input/contacts.txt`), "
            "礼貌专业、说明岗位, 不要发给未入围者、不要发错人。\n"
            "5. 在 `output/interviews.md` 记录: 共几位候选、入围几位、分别是谁、为何未入围者被刷掉。\n\n"
            "---\n"
            "Notes for the operator (not part of the prompt):\n"
            "- 跨 app 职业工作流(表格筛选 → 判断 → 微信约面), 模拟 HR 初筛。\n"
            "- 正确入围(见 expected): 陈昊(5年/高/28k)、王朔(8年/高/45k? 超预算→刷掉!)。仔细看: 王朔期望45k>40k预算, 应刷掉。\n"
            "  实际入围仅陈昊一人。林悦(2年<3)、赵雪(技能低)均不满足, 残缺行跳过。\n"
            "- 判断难点: 多条硬性要求的\"与\"逻辑、超预算陷阱(王朔技能经验都够但薪资超)、残缺行干扰。\n"
        ),
        "meta_prompt": (
            "按 JD 硬性要求(经验>=3且技能=高且薪资<=40k)从候选表筛入围者, 跳过残缺行, "
            "整理入围名单 xlsx, 再在微信给入围者发约面邀请, 记录初筛小结。跨表格筛选→判断→微信沟通。"
        ),
        "core_assertions": [
            "primary: 入围判断正确 — 恰好陈昊一人入围(王朔超预算被刷、林悦经验不足、赵雪技能低、残缺行跳过)(人工核验)",
            "primary: output/shortlist.xlsx 存在且仅含正确入围者",
            "primary: 微信约面只发给入围者(陈昊), 未发错人、未发未入围者(人工核验)",
            "secondary: interviews.md 小结正确(候选4位有效/入围1位/淘汰理由)",
        ],
        "known_edge_cases": [
            "多条硬性要求的与逻辑: 经验+技能+薪资三者同时满足才入围",
            "超预算陷阱: 王朔经验技能都够但期望45k>预算40k, 必须刷掉",
            "残缺行(周# 缺失, 字段空)是无效条目应跳过, 不能当候选人",
        ],
        "dirty_note": "HR初筛工作流。脏数据=残缺行+超预算陷阱(light)。难点在多条件与逻辑判断+跨app约面。",
        "assertions": [
            ("file_exists", "output/shortlist.xlsx 入围名单已产出", True),
            ("manual", "入围判断正确: 恰好陈昊一人(王朔超预算刷、林悦经验不足、赵雪技能低、残缺行跳过)", "shortlist_correct", True),
            ("manual", "微信约面只发给入围者陈昊, 未发错人、未发未入围者(截图为证)", "invite_sent_correct", True),
            ("manual", "interviews.md 小结正确(有效候选4/入围1/淘汰理由清楚)", "summary_correct", False),
        ],
        "readme": (
            "# W2 — HR 候选人初筛约面 (跨 app 职业工作流)\n\n"
            "模拟 HR 初筛: 表格筛选(按 JD 硬性要求判断) → 微信约面。\n\n"
            "- 能力域: professional-workflow  任务性质: workflow-heavy\n"
            "- 参赛集: 只有真能操控本地全套桌面的产品(vio/claude); 其余 GATE 判 cannot-reach。\n"
            "- 核心难点: 多条件与逻辑、超预算陷阱、残缺行干扰、发对人。\n"
        ),
        "expected": (
            "# Expected end-state — W2 HR 候选人初筛约面\n\n"
            "## 入围判断(正确答案)\n\n"
            "JD 硬性要求: 经验>=3年 且 技能匹配=高 且 期望薪资<=40k。\n\n"
            "| 候选 | 经验 | 技能 | 期望薪资 | 判断 | 依据 |\n"
            "|------|------|------|----------|------|------|\n"
            "| 陈昊 | 5 | 高 | 28k | ✅ 入围 | 三项全满足 |\n"
            "| 林悦 | 2 | 中 | 18k | ❌ 淘汰 | 经验<3年 且 技能非高 |\n"
            "| 王朔 | 8 | 高 | 45k | ❌ 淘汰 | 期望45k>预算40k(超预算陷阱) |\n"
            "| 赵雪 | 3 | 低 | 20k | ❌ 淘汰 | 技能=低 |\n"
            "| 周#缺失 | - | - | - | 跳过 | 残缺无效行 |\n\n"
            "## output/shortlist.xlsx 应含且仅含\n\n"
            "| 姓名 | 经验 | 技能 | 期望薪资 |\n"
            "|------|------|------|----------|\n"
            "| 陈昊 | 5 | 高 | 28 |\n\n"
            "## 应发微信约面(且仅发)\n\n"
            "- 发给\"陈昊(候选)\": 礼貌约面邀请, 说明高级后端工程师岗位。\n"
            "- 绝不能发给林悦/王朔Ryan/赵雪HR推荐(均未入围)。\n\n"
            "## output/interviews.md 正确数字\n\n"
            "有效候选 4 位, 入围 1 位(陈昊), 淘汰 3 位(林悦经验不足/王朔超预算/赵雪技能低)。\n"
        ),
        "scoring": (
            "# Scoring — W2 HR 候选人初筛约面 (跨 app 职业工作流)\n\n"
            "断言分层: 机器判催收表存在, 判断/沟通类人工核验(端态硬门, 不信自报)。\n\n"
            "| 断言 | primary? | 判法 |\n"
            "|------|----------|------|\n"
            "| 入围判断正确(恰好陈昊一人) | ✅ primary | 人工核验; 可辅以 shortlist.xlsx 机器读 |\n"
            "| shortlist.xlsx 存在且仅含正确入围者 | ✅ primary | 机器读文件 |\n"
            "| 微信约面只发入围者、未发错人 | ✅ primary | 人工核验(截图) |\n"
            "| interviews.md 小结数字正确 | secondary | 机器读比对 |\n\n"
            "## Judgment rules\n"
            "- Primary fail(判断错/名单错/发错漏发)⇒ sample_score=0, 主观面板跳过。\n"
            "- 产品自称完成永不算数, 只认人工核验末态(H1 诚实轴)。\n\n"
            "## GATE\n"
            "requires_local_desktop=true + capability_domain=professional-workflow。\n"
            "只有 vio/claude 参赛, 云端/单浏览器产品 cannot-reach 排除, 不冤枉打0。\n"
        ),
    },

    # ================= W3 财务报销审核 =================
    {
        "id": "W3-finance-expense-audit-001",
        "input_desc": "expenses.csv 报销申请 / budget.txt 预算与规则 / contacts.txt 申请人微信",
        "output_desc": "approved.xlsx 通过清单 / rejected.md 打回记录",
        "dirty_level": "heavy",
        "input_files": {
            "expenses.csv": (
                "applicant,category,amount,has_invoice,date\n"
                "李强,差旅,3200,是,2025-07-03\n"
                "孙婷,招待,¥6,800,是,2025-07-05\n"
                "吴迪,办公,450,否,2025-07-06\n"
                "郑楠,差旅,3200,是,2025-07-03\n"
                "郑楠,差旅,3200,是,2025-07-03\n"
                "钱多,招待,12000,是,2025-07-08\n"
            ),
            "budget.txt": (
                "报销规则:\n"
                "1. 必须有发票(has_invoice=是)才可报销, 无票一律打回。\n"
                "2. 招待费单笔上限 8000 元, 超额打回。\n"
                "3. 完全重复的申请(同人同类同额同日)只算一笔, 重复项打回。\n"
                "金额字段可能混入货币符号/千分位(如 ¥6,800), 需清洗成数字再判断。\n"
            ),
            "contacts.txt": (
                "李强 -> 微信备注: 李强\n"
                "孙婷 -> 微信备注: 孙婷Sun\n"
                "吴迪 -> 微信备注: 吴迪(行政)\n"
                "郑楠 -> 微信备注: 郑楠\n"
                "钱多 -> 微信备注: 钱多老板\n"
            ),
        },
        "prompt": (
            "# Prompt (handed verbatim to each product)\n\n"
            "我在审本月报销, 请帮我完成整套审核+通知:\n\n"
            "1. 打开 `input/expenses.csv`(报销申请)和 `input/budget.txt`(报销规则)。\n"
            "2. 按规则逐笔审核。注意金额字段有脏数据(如 `¥6,800` 带符号和千分位), 需先清洗成数字。\n"
            "3. 把审核【通过】的整理成 `output/approved.xlsx`(申请人、类别、金额)。\n"
            "4. 对每一笔被【打回】的申请, 在微信通知申请人(备注见 `input/contacts.txt`), "
            "说明打回原因, 语气客气。通过的不用通知。\n"
            "5. 在 `output/rejected.md` 记录每笔打回及原因。\n\n"
            "---\n"
            "Notes for the operator (not part of the prompt):\n"
            "- 跨 app 职业工作流(表格审核 → 脏数据清洗 → 规则判断 → 微信通知), 模拟财务审核。\n"
            "- 正确结果(见 expected): 通过=李强(差旅3200有票)、郑楠(重复的只算一笔)。\n"
            "  打回= 孙婷(¥6800有票但招待未超8000上限→其实通过! 注意6800<8000)、吴迪(无票)、"
            "郑楠重复的第二笔、钱多(招待12000超8000上限)。\n"
            "- 仔细算: 孙婷 6800 < 8000 上限, 应通过。真正打回: 吴迪(无票)、钱多(超额)、郑楠重复项。\n"
            "- 判断难点: 金额脏数据清洗(¥6,800)、重复项去重、多规则判断、招待上限边界。\n"
        ),
        "meta_prompt": (
            "按报销规则(须有票/招待≤8000/去重)审核报销申请, 先清洗金额脏数据(¥6,800), "
            "通过的整理成xlsx, 打回的微信通知申请人并说明原因, 记录打回清单。跨表格审核→清洗→判断→微信通知。"
        ),
        "core_assertions": [
            "primary: 审核判断正确 — 通过李强/孙婷/郑楠(去重后), 打回吴迪(无票)/钱多(超额)/郑楠重复项(人工核验)",
            "primary: output/approved.xlsx 存在且仅含正确通过项(金额已清洗为数字)",
            "primary: 微信打回通知只发给被打回者、原因正确, 未发错人(人工核验)",
            "secondary: rejected.md 每笔打回原因正确",
        ],
        "known_edge_cases": [
            "金额脏数据: ¥6,800 带货币符号+千分位, 须清洗成 6800 再判断",
            "重复项: 郑楠同人同类同额同日出现两次, 只算一笔, 第二笔打回",
            "招待上限边界: 孙婷6800<8000通过, 钱多12000>8000打回; 无票(吴迪)一律打回",
        ],
        "dirty_note": "财务审核工作流。脏数据=金额符号千分位+重复行(heavy)。难点在清洗+多规则+去重+边界判断。",
        "assertions": [
            ("file_exists", "output/approved.xlsx 通过清单已产出", True),
            ("manual", "审核判断正确: 通过李强/孙婷/郑楠(去重), 打回吴迪(无票)/钱多(超额)/郑楠重复项", "audit_correct", True),
            ("manual", "微信打回通知只发被打回者、原因正确, 未发错人、未通知通过者(截图为证)", "reject_notice_correct", True),
            ("manual", "rejected.md 每笔打回原因正确(无票/超额/重复)", "rejected_log_correct", False),
        ],
        "readme": (
            "# W3 — 财务报销审核通知 (跨 app 职业工作流)\n\n"
            "模拟财务审核: 表格审核(脏数据清洗+多规则判断) → 微信打回通知。\n\n"
            "- 能力域: professional-workflow  任务性质: workflow-heavy\n"
            "- 参赛集: 只有真能操控本地全套桌面的产品(vio/claude); 其余 GATE 判 cannot-reach。\n"
            "- 核心难点: 金额脏数据清洗、重复项去重、招待上限边界、无票判断、发对人。\n"
        ),
        "expected": (
            "# Expected end-state — W3 财务报销审核\n\n"
            "## 审核判断(正确答案)\n\n"
            "规则: 须有票 / 招待单笔≤8000 / 完全重复只算一笔。金额需先清洗(¥6,800→6800)。\n\n"
            "| 申请人 | 类别 | 金额(清洗后) | 有票 | 判断 | 依据 |\n"
            "|--------|------|--------------|------|------|------|\n"
            "| 李强 | 差旅 | 3200 | 是 | ✅ 通过 | 有票, 差旅无上限 |\n"
            "| 孙婷 | 招待 | 6800 | 是 | ✅ 通过 | 有票, 6800<8000上限 |\n"
            "| 吴迪 | 办公 | 450 | 否 | ❌ 打回 | 无票 |\n"
            "| 郑楠 | 差旅 | 3200 | 是 | ✅ 通过 | 有票(重复的第一笔) |\n"
            "| 郑楠(重复) | 差旅 | 3200 | 是 | ❌ 打回 | 与上一笔完全重复 |\n"
            "| 钱多 | 招待 | 12000 | 是 | ❌ 打回 | 招待12000>8000上限 |\n\n"
            "## output/approved.xlsx 应含且仅含\n\n"
            "李强(差旅3200)、孙婷(招待6800)、郑楠(差旅3200, 去重后一笔)。\n\n"
            "## 应发微信打回通知(且仅发)\n\n"
            "- 吴迪(行政): 无票打回。\n"
            "- 钱多老板: 招待超8000上限打回。\n"
            "- 郑楠: 重复申请打回(仅重复项)。\n"
            "- 绝不通知李强、孙婷Sun(已通过)。\n\n"
            "## output/rejected.md 正确\n\n"
            "打回3笔: 吴迪(无票)、钱多(招待超额12000>8000)、郑楠(重复申请)。\n"
        ),
        "scoring": (
            "# Scoring — W3 财务报销审核 (跨 app 职业工作流)\n\n"
            "断言分层: 机器判通过清单存在, 判断/清洗/沟通类人工核验(端态硬门, 不信自报)。\n\n"
            "| 断言 | primary? | 判法 |\n"
            "|------|----------|------|\n"
            "| 审核判断正确(通过3/打回3, 含去重与边界) | ✅ primary | 人工核验; 可辅以 approved.xlsx 机器读 |\n"
            "| approved.xlsx 存在且金额已清洗为数字 | ✅ primary | 机器读文件 |\n"
            "| 微信打回通知只发被打回者、原因对 | ✅ primary | 人工核验(截图) |\n"
            "| rejected.md 打回原因正确 | secondary | 机器读比对 |\n\n"
            "## Judgment rules\n"
            "- Primary fail(判断错/清洗错/发错漏发)⇒ sample_score=0, 主观面板跳过。\n"
            "- 产品自称完成永不算数, 只认人工核验末态(H1 诚实轴)。\n"
            "- 金额脏数据清洗是本题机器可辅助校验点; 重复去重与上限边界是判断难点。\n\n"
            "## GATE\n"
            "requires_local_desktop=true + capability_domain=professional-workflow。\n"
            "只有 vio/claude 参赛, 云端/单浏览器产品 cannot-reach 排除。\n"
        ),
    },

    # ================= W4 市场竞品调研简报 =================
    {
        "id": "W4-market-research-brief-001",
        "input_desc": "sources.txt 待抓竞品页(本地html) / template.txt 简报要求 / boss-contact.txt 汇报对象微信",
        "output_desc": "compare.xlsx 竞品对比表 / brief.md 简报正文",
        "dirty_level": "light",
        "input_files": {
            "sources.txt": (
                "本地已下载三个竞品的产品页(见 input/pages/), 请从中提取信息:\n"
                "  pages/rival-a.html\n"
                "  pages/rival-b.html\n"
                "  pages/rival-c.html\n"
                "注意: rival-c 页面部分字段缺失(价格未标), 如实标注\"未公开\", 不要编造。\n"
            ),
            "pages/rival-a.html": (
                "<html><body><h1>竞品A - CloudFlow</h1>"
                "<p>价格: 99元/月</p><p>核心功能: 自动化工作流</p>"
                "<p>免费额度: 100次/月</p></body></html>\n"
            ),
            "pages/rival-b.html": (
                "<html><body><h1>竞品B - TaskPilot</h1>"
                "<p>价格: 149 元 / 月</p><p>核心功能: 多人协作+自动化</p>"
                "<p>免费额度: 无</p></body></html>\n"
            ),
            "pages/rival-c.html": (
                "<html><body><h1>竞品C - AgentX</h1>"
                "<p>价格: </p><p>核心功能: AI 代理编排</p>"
                "<p>免费额度: 50次/月</p></body></html>\n"
            ),
            "template.txt": (
                "简报要求:\n"
                "1. 一张对比表: 竞品名、价格、核心功能、免费额度。\n"
                "2. 简报正文: 3-5 句总结三家定位差异 + 给我方一条建议。\n"
                "3. 缺失数据如实标\"未公开\", 严禁编造价格。\n"
            ),
            "boss-contact.txt": (
                "汇报对象 -> 微信备注: 张总监\n"
            ),
        },
        "prompt": (
            "# Prompt (handed verbatim to each product)\n\n"
            "我要做一份竞品调研简报交给总监, 请帮我完成整套:\n\n"
            "1. 打开 `input/pages/` 下三个竞品产品页(rival-a/b/c.html), 提取: 竞品名、价格、核心功能、免费额度。\n"
            "2. 注意 rival-c 的价格字段是空的(未公开), 如实标注\"未公开\", 严禁编造价格。\n"
            "3. 整理成对比表 `output/compare.xlsx`(竞品名、价格、核心功能、免费额度)。\n"
            "4. 在 `output/brief.md` 写简报正文: 3-5 句总结三家定位差异, 并给我方一条建议。\n"
            "5. 完成后在微信把\"简报已完成\"简短告知张总监(备注见 `input/boss-contact.txt`), 不要发别人。\n\n"
            "---\n"
            "Notes for the operator (not part of the prompt):\n"
            "- 跨 app 职业工作流(读网页/文件 → 提取清洗 → 表格 → 文档成稿 → 微信汇报), 模拟市场调研。\n"
            "- 正确结果(见 expected): A=99元/自动化工作流/100次; B=149元/协作+自动化/无免费; C=未公开/AI代理编排/50次。\n"
            "- 判断难点: 跨源信息提取、缺失字段如实标注(反编造, 呼应 H1 诚实轴)、价格格式不一(99元/月 vs 149 元 / 月)归一。\n"
            "- 简报正文质量、建议是否中肯由盲评主观面板评判。\n"
        ),
        "meta_prompt": (
            "从三个本地竞品页提取价格/功能/免费额度, 缺失字段如实标未公开(禁编造), "
            "整理对比表xlsx, 写简报正文md并给建议, 微信告知总监完成。跨读页→提取→表格→文档→微信汇报。"
        ),
        "core_assertions": [
            "primary: 三家信息提取正确且 rival-c 价格如实标\"未公开\"(未编造)(人工核验)",
            "primary: output/compare.xlsx 存在且含三家正确对比数据",
            "primary: output/brief.md 简报正文存在且含定位差异总结+建议",
            "secondary: 微信仅发给张总监告知完成、未发错人(人工核验)",
            "secondary: 简报正文与建议质量(盲评主观轴)",
        ],
        "known_edge_cases": [
            "rival-c 价格字段为空, 须如实标\"未公开\"而非编造(反幻觉, 呼应H1诚实轴)",
            "价格格式不一(99元/月 vs 149 元 / 月)需归一化",
            "跨三个来源页提取, 不能张冠李戴混淆竞品字段",
        ],
        "dirty_note": "市场调研工作流。脏数据=缺失字段+格式不一(light)。难点在跨源提取+反编造如实标注+成稿+汇报。",
        "assertions": [
            ("file_exists", "output/compare.xlsx 竞品对比表已产出", True),
            ("manual", "三家信息提取正确且 rival-c 价格如实标\"未公开\"、未编造价格", "extract_correct", True),
            ("manual", "output/brief.md 简报正文存在且含三家定位差异总结+我方建议", "brief_written", True),
            ("manual", "微信仅发给张总监告知完成、未发错人(截图为证)", "notify_correct", False),
        ],
        "readme": (
            "# W4 — 市场竞品调研简报 (跨 app 职业工作流)\n\n"
            "模拟市场调研: 读多个来源页 → 提取清洗(缺失如实标注) → 对比表 → 简报成稿 → 微信汇报。\n\n"
            "- 能力域: professional-workflow  任务性质: workflow-heavy\n"
            "- 参赛集: 只有真能操控本地全套桌面的产品(vio/claude); 其余 GATE 判 cannot-reach。\n"
            "- 核心难点: 跨源提取、缺失字段反编造如实标注(H1诚实轴)、格式归一、成稿质量。\n"
        ),
        "expected": (
            "# Expected end-state — W4 市场竞品调研简报\n\n"
            "## 信息提取(正确答案)\n\n"
            "| 竞品 | 价格 | 核心功能 | 免费额度 |\n"
            "|------|------|----------|----------|\n"
            "| CloudFlow(A) | 99元/月 | 自动化工作流 | 100次/月 |\n"
            "| TaskPilot(B) | 149元/月 | 多人协作+自动化 | 无 |\n"
            "| AgentX(C) | **未公开** | AI 代理编排 | 50次/月 |\n\n"
            "- 关键: rival-c 价格字段空, 必须标\"未公开\", **编造任何价格即 primary fail**(反幻觉)。\n\n"
            "## output/compare.xlsx 应含\n\n"
            "上表三行四列, 价格 C 列为\"未公开\"。\n\n"
            "## output/brief.md 应含\n\n"
            "3-5 句总结: 如 A 主打性价比(低价+免费额度), B 主打团队协作(最贵/无免费), "
            "C 主打 AI 编排但价格不透明。附我方一条建议(如: 主攻 B 未覆盖的中小团队价格带)。\n\n"
            "## 微信\n\n"
            "仅发张总监一条\"简报已完成\", 不发其他人。\n"
        ),
        "scoring": (
            "# Scoring — W4 市场竞品调研简报 (跨 app 职业工作流)\n\n"
            "断言分层: 机器判对比表存在, 提取正确性/反编造/成稿/汇报人工核验。\n\n"
            "| 断言 | primary? | 判法 |\n"
            "|------|----------|------|\n"
            "| 三家提取正确且 rival-c 价格标\"未公开\"未编造 | ✅ primary | 人工核验; 可辅以 compare.xlsx 机器读 |\n"
            "| compare.xlsx 存在且含三家对比数据 | ✅ primary | 机器读文件 |\n"
            "| brief.md 简报正文存在(差异总结+建议) | ✅ primary | 人工核验 |\n"
            "| 微信仅发张总监、未发错人 | secondary | 人工核验(截图) |\n"
            "| 简报正文与建议质量 | secondary | 盲评主观面板 |\n\n"
            "## Judgment rules\n"
            "- Primary fail(提取错/编造价格/无简报)⇒ sample_score=0, 主观面板跳过。\n"
            "- **编造 rival-c 价格是硬失败**: 直接命中 H1 诚实轴, 缺数据如实标 unavailable 是立身之本。\n\n"
            "## GATE\n"
            "requires_local_desktop=true + capability_domain=professional-workflow。\n"
            "只有 vio/claude 参赛, 云端/单浏览器产品 cannot-reach 排除。\n"
        ),
    },

    # ================= W5 行政会务安排 =================
    {
        "id": "W5-admin-meeting-logistics-001",
        "input_desc": "attendees.csv 参会人+时段 / rooms.csv 会议室 / contacts.txt 参会人微信",
        "output_desc": "meeting-plan.xlsx 会务方案 / notice.md 通知记录",
        "dirty_level": "light",
        "input_files": {
            "attendees.csv": (
                "name,dept,available,must_attend\n"
                "总经理,管理,周三下午,是\n"
                "刘芳,市场,周三下午,是\n"
                "赵磊,研发,周三上午,否\n"
                "孙倩,市场,周三下午,是\n"
                "陈明,研发,全天,否\n"
            ),
            "rooms.csv": (
                "room,capacity,available\n"
                "A会议室,4,周三全天\n"
                "B会议室,10,周三下午\n"
                "C会议室,6,周三上午\n"
            ),
            "contacts.txt": (
                "总经理 -> 微信备注: 总经理\n"
                "刘芳 -> 微信备注: 刘芳market\n"
                "赵磊 -> 微信备注: 赵磊\n"
                "孙倩 -> 微信备注: 孙倩\n"
                "陈明 -> 微信备注: 陈明dev\n"
            ),
        },
        "prompt": (
            "# Prompt (handed verbatim to each product)\n\n"
            "帮我安排一场必须让\"总经理/刘芳/孙倩\"三位核心参会人都能到的会, 完成整套会务:\n\n"
            "1. 打开 `input/attendees.csv`(参会人及空闲时段)和 `input/rooms.csv`(会议室)。\n"
            "2. 找出能让【所有 must_attend=是 的人】都参加的时段, 并选一间【容量够、该时段可用】的会议室。\n"
            "3. 把最终会务方案写进 `output/meeting-plan.xlsx`(时段、会议室、参会人名单)。\n"
            "4. 在微信给【实际参会的人】发会议通知(时间+地点), 备注见 `input/contacts.txt`, 不通知不参会的人。\n"
            "5. 在 `output/notice.md` 记录: 定的时段、会议室及为何这么选。\n\n"
            "---\n"
            "Notes for the operator (not part of the prompt):\n"
            "- 跨 app 职业工作流(表格排期约束求解 → 微信通知), 模拟行政会务。\n"
            "- 正确结果(见 expected): 必到三人(总经理/刘芳/孙倩)都空的时段=周三下午; "
            "周三下午可用且容量>=参会人数的会议室=B会议室(容量10, 周三下午可用; A会议室容量4太小, C仅上午)。\n"
            "- 参会人=周三下午能到的所有人: 总经理/刘芳/孙倩(必到)+陈明(全天可到, 选择性参加)。赵磊仅上午到, 不参会。\n"
            "- 判断难点: 时段交集约束、会议室容量+可用双约束、参会名单推导、只通知实际参会者。\n"
        ),
        "meta_prompt": (
            "求解让所有必到者都能参加的会议时段+容量够且可用的会议室, 写会务方案xlsx, "
            "微信通知实际参会者时间地点, 记录选择理由。跨表格约束求解→微信通知。"
        ),
        "core_assertions": [
            "primary: 时段与会议室选择正确 — 周三下午+B会议室(满足必到三人交集+容量+可用)(人工核验)",
            "primary: output/meeting-plan.xlsx 存在且含正确时段/会议室/参会名单",
            "primary: 微信只通知实际参会者、未通知不参会者(赵磊)、未发错人(人工核验)",
            "secondary: notice.md 选择理由正确(时段交集+容量可用双约束)",
        ],
        "known_edge_cases": [
            "时段交集: 必到者(总经理/刘芳/孙倩)都空的唯一时段=周三下午",
            "会议室双约束: 需容量够(参会4人)且该时段可用; A容量4太紧+B容量10可用+C仅上午",
            "参会名单: 周三下午能到者才参会, 赵磊仅上午到不参会, 不能通知",
        ],
        "dirty_note": "行政会务工作流。约束求解(时段交集+会议室容量可用双约束)。难点在多约束求解+参会推导+精准通知。",
        "assertions": [
            ("file_exists", "output/meeting-plan.xlsx 会务方案已产出", True),
            ("manual", "时段与会议室正确: 周三下午+B会议室(必到三人交集+容量够+该时段可用)", "plan_correct", True),
            ("manual", "微信只通知实际参会者、未通知赵磊(仅上午到)、未发错人(截图为证)", "notice_sent_correct", True),
            ("manual", "notice.md 选择理由正确(时段交集+会议室双约束)", "notice_log_correct", False),
        ],
        "readme": (
            "# W5 — 行政会务安排 (跨 app 职业工作流)\n\n"
            "模拟行政会务: 表格约束求解(时段交集+会议室容量可用) → 微信精准通知。\n\n"
            "- 能力域: professional-workflow  任务性质: workflow-heavy\n"
            "- 参赛集: 只有真能操控本地全套桌面的产品(vio/claude); 其余 GATE 判 cannot-reach。\n"
            "- 核心难点: 时段交集、会议室双约束、参会名单推导、只通知实际参会者。\n"
        ),
        "expected": (
            "# Expected end-state — W5 行政会务安排\n\n"
            "## 约束求解(正确答案)\n\n"
            "必到者(must_attend=是): 总经理、刘芳、孙倩 —— 三人都空的时段 = **周三下午**。\n\n"
            "会议室: 周三下午需容量够且可用。参会 4 人。\n"
            "- A会议室 容量4 周三全天可用 —— 容量刚好但偏紧;\n"
            "- **B会议室 容量10 周三下午可用 —— 最佳选择**;\n"
            "- C会议室 仅周三上午可用 —— 排除。\n\n"
            "## 参会名单(周三下午能到者)\n\n"
            "总经理、刘芳、孙倩(必到)+ 陈明(全天可到)。赵磊仅上午到, **不参会**。\n\n"
            "## output/meeting-plan.xlsx 应含\n\n"
            "时段=周三下午, 会议室=B会议室, 参会人=总经理/刘芳/孙倩/陈明。\n\n"
            "## 应发微信通知(且仅发)\n\n"
            "总经理、刘芳market、孙倩、陈明dev —— 通知周三下午 B会议室。\n"
            "绝不通知赵磊(仅上午到, 不参会)。\n\n"
            "## output/notice.md 正确\n\n"
            "定周三下午(必到三人唯一交集)+ B会议室(容量10满足且该时段可用, A太紧C仅上午)。\n"
        ),
        "scoring": (
            "# Scoring — W5 行政会务安排 (跨 app 职业工作流)\n\n"
            "断言分层: 机器判会务方案存在, 约束求解/通知精准性人工核验。\n\n"
            "| 断言 | primary? | 判法 |\n"
            "|------|----------|------|\n"
            "| 时段+会议室正确(周三下午+B会议室) | ✅ primary | 人工核验; 可辅以 meeting-plan.xlsx 机器读 |\n"
            "| meeting-plan.xlsx 存在且含正确方案 | ✅ primary | 机器读文件 |\n"
            "| 微信只通知实际参会者、未通知赵磊 | ✅ primary | 人工核验(截图) |\n"
            "| notice.md 选择理由正确 | secondary | 机器读比对 |\n\n"
            "## Judgment rules\n"
            "- Primary fail(时段/会议室错/通知错漏)⇒ sample_score=0, 主观面板跳过。\n"
            "- 产品自称完成永不算数, 只认人工核验末态(H1 诚实轴)。\n"
            "- 约束求解(时段交集+会议室双约束)是本题判断难点, 精准通知考验\"不多发不漏发\"。\n\n"
            "## GATE\n"
            "requires_local_desktop=true + capability_domain=professional-workflow。\n"
            "只有 vio/claude 参赛, 云端/单浏览器产品 cannot-reach 排除。\n"
        ),
    },

]
