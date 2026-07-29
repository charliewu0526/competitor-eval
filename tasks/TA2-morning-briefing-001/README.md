# TA2-morning-briefing-001 — 定时晨报 Routine（assistant-integration / scheduled）

对标 Town 真实已上线功能。

- **能力域**：assistant-integration（云端/API 集成，非本地 GUI 操控）
- **任务性质**：scheduled
- **tier**：core-common
- **脏数据**：none
- **requires_local_desktop**：false → 云端产品（Town）判 `api-or-integration` 跨层轨；vio 判 `native-operable`

## 立身之本
只认末态事实（产物文件 + 人核内容），不信产品自述完成。

## 起始素材
助理集成域(云端/API), 模拟 Town 的定时 Routine。起始素材:input/calendar.json(今日事件, 含一处时间重叠)、input/inbox/(隔夜邮件)、input/todos.txt(待办)。素材由系统统一提供, 请勿自建或更换。晨报只产出到 output/briefing.md, 全程只读不改原始数据。
