# TA4-crm-deal-capture-001 — 跨工具 CRM 机会捕捉（assistant-integration / workflow-heavy）

对标 Town 真实已上线功能。

- **能力域**：assistant-integration（云端/API 集成，非本地 GUI 操控）
- **任务性质**：workflow-heavy
- **tier**：stress
- **脏数据**：light
- **requires_local_desktop**：false → 云端产品（Town）判 `api-or-integration` 跨层轨；vio 判 `native-operable`

## 立身之本
只认末态事实（产物文件 + 人核内容），不信产品自述完成。

## 起始素材
助理集成域(云端/API), 对标 Town 的销售/CRM 运营卖点(从入站邮件发现机会→记录到HubSpot/Salesforce→起草跟进)。起始素材:input/inbox/(入站邮件, 混机会与推销)、input/crm-schema.txt(CRM字段定义)。素材由系统统一提供, 请勿自建或更换。联系人写入 output/crm-contacts.json, 草稿到 output/drafts/, 严禁自动发送。
