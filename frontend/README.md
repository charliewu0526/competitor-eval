# 竞品评测系统 · 正式前端

产品级前端(取代 Streamlit 表格原型)。前后端分离,数据全部来自现有 SQLite
(`board/competitor_eval.db`),评测引擎 `pipeline/` 一行不动。

## 技术栈
- **后端**:FastAPI (`server/app.py`),只包装 `pipeline` 的 store/leaderboard/probe/sampling,暴露 JSON API。
- **前端**:React 18 + Vite 5 + Ant Design 5 + @ant-design/plots(用 bun 运行)。

## 一键启动
```bash
./run_frontend.sh          # 起后端(8600)+ 前端(5273),自动开浏览器
./run_frontend.sh stop     # 关掉两端
```
打开 http://127.0.0.1:5273

## 手动启动
```bash
# 后端
python3 -m uvicorn server.app:app --host 127.0.0.1 --port 8600
# 前端
cd frontend && bun install && bun run dev
```

## 9 个页面
| 页面 | 路由 | 说明 |
|---|---|---|
| 总览 | `/` | 统计卡 + 排行速览 |
| 排行榜 | `/leaderboard` | 能力分排名;诚实度独立列;不参赛(cannot-reach)单独分区 |
| 按题矩阵 | `/matrix` | 产品×任务能力分热力网格 |
| 评分详情 | `/score` | S1-S5 五维雷达 + 评委毛病 + 分歧标红 |
| 成本面板 | `/cost` | token/调用/$ 与完成度并排;「花了钱没干成」红标 |
| 发现看板 | `/findings` | 机器只标疑似,PM 下拉定判写回 DB |
| 能力专项 | `/probes` | 卖点对打 + 🔬源码机理 |
| 抽查队列 | `/spotcheck` | 分层抽查(10%/100%/100%)+ 异常触发重校 |
| 黄金集授权 | `/authorizations` | AI 评委 kappa 一致率 + 授权状态 |

## 设计原则:人话优先
所有技术指标用中文业务名做主标签,原始字段名退到 tooltip(ⓘ)。术语映射由后端
`/api/glossary` 统一提供,前端 `src/glossary.jsx` 消费。颜色即语义:绿=好/可信,
红=危险/翻车,灰=数据没拿到(非 0)。
