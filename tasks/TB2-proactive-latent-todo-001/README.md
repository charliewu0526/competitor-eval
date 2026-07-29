# TB2 — 主动性（assistant-integration / rival-signature）

**竞品卖点验证题**。验证 Town 宣传的「在你意识到需要之前就把活干了 / 主动发现并处理 / chief of staff 而非 chatbot」是否属实。

- **能力域**：assistant-integration
- **任务性质**：long-horizon
- **tier**：rival-signature（竞品主打卖点轨）
- **脏数据**：light（隐含待办藏正文 + 营销噪声诱导误报）
- **参赛**：town + vio 对打
- **requires_local_desktop**：false → town 判 `api-or-integration`，vio 判 `native-operable`

## 立身之本
只认末态事实：主动行动结果看 `output/proactive.md`，是否发现隐含待办/日历冲突/是否误报由受训 intern 人核。发给产品的完整指令须留证（证明未指派具体任务）。不信产品自述"我很主动"。

## 三种结局都有用
- 真主动发现并处置隐含待办+冲突 → 话术为真 → **violoop 照着补齐**
- 「你得具体告诉我做什么」/ 只罗列收件箱不产出处置 → 坐实是话术
- 只发现一部分 → 划出真实边界

## 起始素材
- `input/inbox/`：含一封隐含截止日待办的邮件 + 普通/营销邮件
- `input/calendar.json`：含一处时间冲突
- `input/todos.txt`：已有待办（勿重复）
- `expected/end-state.md`：应被主动发现的待办/冲突 + 不该误报的噪声清单
