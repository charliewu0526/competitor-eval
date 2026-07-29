# TA4-crm-deal-capture-001 — 跨工具 CRM 机会捕捉

扫描收件箱(input/inbox/)里的入站邮件,识别其中真正的销售机会(潜在客户主动询价/求合作),忽略供应商推销与营销邮件。对每个机会:把联系人写入 CRM(产出 output/crm-contacts.json,字段缺失如实留空、禁编造),并起草一封跟进回复到 output/drafts/。产出 output/deals.md 汇总识别到的机会及依据。禁止把推销邮件误判为机会,禁止编造联系人信息,禁止未经批准发送。
