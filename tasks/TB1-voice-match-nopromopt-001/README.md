# TB1 — 零配置懂你（assistant-integration / rival-signature）

**竞品卖点验证题**。验证 Town 宣传的「像 raw denim 一样贴合你 / day one 就懂你 / 免调教」是否属实。

- **能力域**：assistant-integration
- **任务性质**：simple
- **tier**：rival-signature（竞品主打卖点轨）
- **脏数据**：light（语料含两种语域诱导一刀切）
- **参赛**：town + vio 对打
- **requires_local_desktop**：false → town 判 `api-or-integration`，vio 判 `native-operable`

## 立身之本
只认末态事实：草稿看 `output/draft.txt`，是否贴合语气/沿用签名/是否追问由受训 intern 人核勾选。发给产品的完整指令须留证（证明未含风格提示）。不信产品自述"我很懂你"。

## 三种结局都有用
- 真复现用户语气指纹 → 话术为真 → **violoop 照着补齐这个能力**
- 通用 AI 腔 / 默认签名 / 反过来追问风格 → 坐实是话术
- 部分贴合 → 划出真实边界

## 起始素材
- `input/voice-corpus/`：用户以往 5-8 封邮件（真实语气指纹）
- `input/incoming.txt`：一封新到的待回邮件
- `expected/end-state.md`：用户语气指纹清单，供人核比对
