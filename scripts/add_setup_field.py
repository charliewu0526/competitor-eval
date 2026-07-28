# -*- coding: utf-8 -*-
"""给全 26 道题的 meta.json 注入 task_spec.setup 字段(起始状态/前置准备)。

owner 统一写、实习生只读。每条 setup = 中性上手提示 + "起始状态由系统统一提供、
禁止自建/更换素材"的公正性约束。消除实习生"我没文件、要不要自己建"的困惑。
幂等: 覆盖写 setup 字段, 不动其他字段。
"""
import json
import pathlib

TASKS = pathlib.Path(__file__).resolve().parent.parent / "tasks"

_NO_SELF = "起始素材由系统在 input/ 统一提供,请勿自建或更换文件——所有产品必须在同一份素材上跑,结果才可比。"

SETUP = {
    "T1-wechat-send-001":
        "在本机已登录的微信客户端里操作。无需 input 文件。请勿新建群/改联系人备注,只按题目发指定消息。",
    "T2-excel-sum-001":
        f"对系统提供的 input/sales.xlsx 操作。{_NO_SELF}",
    "T3-web-extract-001":
        f"目标网址见 input/target-url.txt。{_NO_SELF} 用其中给定的 URL,勿自换网页。",
    "T4-wechat-forward-001":
        "在本机已登录的微信客户端里操作。无需 input 文件。转发对象/内容严格按题目,勿发给题外的人。",
    "T5-wechat-followup-001":
        "在本机已登录的微信客户端里操作。无需 input 文件。按题目对指定对象跟进,勿改动其他会话。",
    "T6-wechat-schedule-001":
        "在本机已登录的微信客户端里操作(定时任务)。无需 input 文件。按题目设定时间/内容,勿改系统时钟造假。",
    "T7-wechat-dirty-roster-001":
        f"脏名单见 input/roster.txt(含错别字/重复/尾随空格/垃圾行)。{_NO_SELF} "
        "需你判断哪些是能匹配到微信的真实联系人,勿凭空补人。",
    "T8-word-contract-001":
        f"待处理文档为系统提供的 input/contract-draft.docx。{_NO_SELF} 在此文档上套样式/加页码/导出,勿另起新文档。",
    "T9-excel-merge-pivot-001":
        f"12 个月度表在 input/sales-by-region/(2025-01..12.xlsx)。{_NO_SELF} 合并这 12 个文件,勿增删月份。",
    "T10-excel-schedule-report-001":
        f"账本为系统提供的 input/ledger.xlsx,含两个 sheet:transactions(逐笔流水)与 summary(月度汇总,初值为上月旧值待重算)。"
        f"{_NO_SELF} 任务是重算 summary 并导出 PDF,勿改流水数据。",
    "T11-excel-dirty-clean-001":
        f"脏数据为系统提供的 input/expenses.csv(日期格式不一/金额带货币符号文本/空行/中途重复表头)。{_NO_SELF} 清洗后在 B1 给出金额总和。",
    "T12-capcut-trim-001":
        "待剪素材为系统提供的 input/clip.mp4(占位视频,足够走通导入/裁剪/导出流程)。"
        "请勿自换素材;在剪映里导入它,裁剪 00:05–00:20,按 1080p 导出。",
    "T13-capcut-color-render-001":
        "待处理素材为 input/raw-footage/ 下 5 个片段(占位视频)。请勿自换素材;在剪映里统一调色+加转场后渲染导出。",
    "T14-accounting-dirty-entry-001":
        f"待录入凭证为 input/receipts/ 下的收据图(金额/日期需人读,含手写/多币种)。{_NO_SELF} 按图里信息录入,勿编造数字。",
    "T15-file-rename-001":
        f"待重命名的照片在 input/photos/(固定 5 张:IMG_0001/0002/0003.jpg、DSC_1010.jpg、photo (1).jpg)。"
        f"{_NO_SELF} 就对这个文件夹这 5 张操作——文件夹位置和图片数量都固定,勿自建目录或增删图片。",
    "T16-cross-app-archive-001":
        "按题目从指定来源取附件→建文件夹→打包。若题目未随附素材,以题面描述的来源为准,勿自造不同的文件集。",
    "T17-cleanup-schedule-001":
        "系统清理类定时任务,按题目设定。无固定 input 文件;勿对题外的真实系统文件动手,只在题目指定范围内操作。",
    "T18-dedupe-dirty-001":
        f"待去重目录为 input/messy-dir/(含嵌套子目录、同内容不同名的重复文件、空目录、.DS_Store 垃圾)。"
        f"{_NO_SELF} 就对这个目录去重,勿自建不同结构。",
    "T19-web-form-001":
        f"表单页见 input/target-url.txt(指向 input/registration.html),填表数据见 input/profile.json。{_NO_SELF} 用给定资料填这个表单,勿改数据。",
    "T20-web-price-schedule-001":
        f"商品页见 input/target-url.txt(指向 input/product.html)。{_NO_SELF} 定时抓这个页面的价格,勿换成别的商品。",
    "T21-web-dirty-extract-001":
        f"脏列表页见 input/target-url.txt(指向 input/listing.html,价格在 span/div 混排、缺评分、混入广告行)。{_NO_SELF} 从这个页面抽取,勿自换网页。",
    "W1-sales-reconcile-dunning-001":
        f"跨 app 职业工作流。素材:input/receivables.csv(应收)、input/bank-statement.csv(银行流水)、input/contacts.txt(微信联系人)。"
        f"{_NO_SELF} 微信在本机已登录客户端里发;按给定数据判断未到账者,勿改数据、勿群发。",
    "W2-hr-screening-schedule-001":
        f"跨 app 职业工作流。素材:input/candidates.csv(候选人)、input/jd.txt(硬性要求)、input/contacts.txt(微信)。"
        f"{_NO_SELF} 按 JD 判断入围,微信约面只发入围者,勿改候选数据。",
    "W3-finance-expense-audit-001":
        f"跨 app 职业工作流。素材:input/expenses.csv(报销申请)、input/budget.txt(规则)、input/contacts.txt(微信)。"
        f"{_NO_SELF} 按规则审核,微信通知被打回者,勿改申请数据。",
    "W4-market-research-brief-001":
        f"跨 app 职业工作流。素材:input/pages/(三个竞品本地页 rival-a/b/c.html)、input/template.txt(简报要求)、input/boss-contact.txt(汇报对象)。"
        f"{_NO_SELF} rival-c 价格缺失须如实标\"未公开\",严禁编造。",
    "W5-admin-meeting-logistics-001":
        f"跨 app 职业工作流。素材:input/attendees.csv(参会人+时段)、input/rooms.csv(会议室)、input/contacts.txt(微信)。"
        f"{_NO_SELF} 求解满足必到者的时段+会议室,微信只通知实际参会者。",
}


def main():
    changed, missing = [], []
    for d in sorted(TASKS.glob("[TW]*-*")):
        mp = d / "meta.json"
        m = json.loads(mp.read_text(encoding="utf-8"))
        tid = m["task_spec"]["task_id"]
        if tid not in SETUP:
            missing.append(tid)
            continue
        m["task_spec"]["setup"] = SETUP[tid]
        mp.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
        changed.append(tid)
    print(f"已写 setup: {len(changed)} 道")
    if missing:
        print("未覆盖(需补文案):", missing)


if __name__ == "__main__":
    main()
