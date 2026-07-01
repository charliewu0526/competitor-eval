# 竞品评测正式前端 — 构建规格 (React + Vite + Ant Design)

> 📋 正式 PRD 已归档为 `docs/prd/0002-frontend.md`（流程真相源）。本文件就地保留供前端开发者就近查阅，两者同源。

## 目标
把 SQLite 里的竞品评测数据渲染成**产品级前端**(不是表格 dump)。后端 API 已就绪在
`http://127.0.0.1:8600`(vite dev 用 proxy 转发 `/api`)。引擎不动,前端只消费 JSON。

## 最高设计原则:人话优先(HARD RULE)
非技术用户(老板/设计/研发)必须看懂。每个技术指标:
- **中文业务名做主标签**,英文/原始字段名退到副文本或 tooltip。
- 每个指标旁放 AntD `<Tooltip>` + `<QuestionCircleOutlined>`,给一句大白话 + 为什么看它。
- 文案统一从 `/api/glossary` 拉(返回 {key:{label,hint}}),不要在各页硬写黑话。
- 颜色即语义:绿=好/可信,红=危险/翻车,灰=数据没拿到(不是0分,显示 "未采集")。
- 空状态写引导语(如「还没跑过评测,先运行 pipeline 落库」),不要 "no data" / "no rows"。

术语映射(也由 /api/glossary 提供):
- sample_score → 能力分(0–100,越高越强)※后端是 0–1,前端 ×100 显示
- h1_honesty → 诚实度(说做完了是不是真做完了,1谎报~5老实)
- gate / cannot-reach → 能否参赛(环境够不够得着;够不着不参与公平对比)
- objective_ratio → 硬性完成度(末态事实查到几条)
- disagreement → 评委分歧大(三个AI评委打分差太多,需人复核)
- defects → 评委挑出的毛病
- cost (token/calls/usd) → 成本(花了多少token/调用几次/折多少钱)
- kappa → AI评委可信度(和人工标准答案一致率)

## 技术栈
- Vite + React 18 (JS,不用 TS 省事)
- antd 5 + @ant-design/icons
- @ant-design/plots(雷达图/柱图)或 recharts,二选一
- axios、react-router-dom 6
- vite.config.js: server.proxy `/api` → `http://127.0.0.1:8600`

## 布局
- `<Layout>`:左 `<Sider>` 导航(9项)+ 顶 `<Header>` 标题「竞品评测系统」+ `<Content>` 路由出口。
- 浅色或深色专业主题(ConfigProvider),配色克制。
- 9 个路由 + 菜单项见下。

## API 形状(后端已实现,GET)
- `/api/overview` → {products,tasks,scores,findings,findings_undecided,spotcheck_pending}
- `/api/glossary` → {key:{label,hint}}
- `/api/leaderboard?baseline=vio` → {baseline,ranking[],matrix{prod:{task:{sample_score,h1_honesty,scored,reason}}},tasks[],excluded[]}
  - ranking item: {product,is_baseline,avg_capability(0-1),honesty_avg(1-5|null),n_tasks,vs_baseline,rank}
  - excluded item: {product,task_id,reason:"cannot-reach"}
- `/api/scores` → score 行数组
- `/api/score/{task}/{product}` → {...,subjective{S1..S5},disagreement[],defects[{by,desc}],run{cost_*,objective_*,transcript_excerpt}}
- `/api/cost` → [{task_id,product,cost_input_tokens,cost_output_tokens,cost_model_calls,cost_usd,cost_source,sample_score,objective_ratio,objective_failed_primary,gate,cost_priced}]
- `/api/findings` → [{id,task_id,rule,suspected_category,subject,phenomenon,evidence,product_judgment,final_category,routed_to}]
- `/api/probes` → 同 findings 形状(rule=capability-probe),evidence 里有 source=probe-metric / code-analysis
- `/api/spotcheck?status=pending` → [{id,task_id,product,run_idx,stratum,reason,status,checked_by,verdict_note}]
- `/api/authorizations` → [{subject,role,status,kappa,agreement,n_samples,...}]
- `/api/enums` → {product_judgment[],final_category[],suspected[]}

## 写端点(POST)
- `/api/findings/{id}/judgment` body {product_judgment,final_category}
- `/api/spotcheck/rebuild`
- `/api/spotcheck/{id}/verdict` body {status:"ok"|"anomaly",checked_by,verdict_note}

## 页面清单
1. **总览 Dashboard** `/` — 顶部统计卡(产品数/任务数/发现数/待定发现/待抽查),排行榜 mini。
2. **排行榜** `/leaderboard` — Table 按能力分排序,能力分进度条;诚实度**独立 Tag 列**(低=红「危险的强」,高=绿「可信的弱」);vs baseline 正负色;cannot-reach 单独折叠区(标明「环境够不着,不参与公平对比」)。
3. **按题矩阵** `/matrix` — 产品×任务网格,格子=能力分,分值映射颜色深浅;"-"=没这道题。
4. **评分详情** `/score` — 选任务+产品下拉;S1-S5 雷达图;每维下方列 justification(若有);分歧维度标红 badge;缺陷清单(by deepseek/gemini)。
5. **成本面板** `/cost` — Table:token/calls/$ 与 能力分/硬性完成度 **并排**;cost_priced=false 显示「未采集」灰标;有成本但能力分=0 的行**红色高亮**(省token=没干活陷阱),配 tooltip 解释。
6. **发现看板** `/findings` — 卡片流;suspected_category 彩色 Tag;机器现象+证据折叠;PM 用两个 Select(产品判断/最终分类,选项来自 /api/enums)+保存按钮 POST 写回;routed_to 显示 🐞→bug。
7. **能力专项** `/probes` — 卖点对打(probe-metric 表)+ 机理证据卡(code-analysis,开源带🔬);同样可 PM 定판。
8. **抽查队列** `/spotcheck` — 重建按钮(POST rebuild);分层色(high-risk红/contradiction橙/normal绿);每项一致/异常裁决按钮(POST verdict)。
9. **黄金集授权** `/authorizations` — kappa/agreement/status 卡片;空时显示「AI评委还没参加考核(黄金集校准),先校准再授权自动打分」空状态。

## 验收
`npm run dev` 起 dev server,9 个页面都能从 /api 拉真实数据渲染,人话标签+tooltip 到位,
发现页 PM 改判断保存后刷新值保留。
