import React from "react";
import { Typography, Card, Steps, Collapse, Tag, Alert, Divider } from "antd";
import { useAuth } from "../auth.jsx";

const { Title, Paragraph, Text } = Typography;

// 三角色使用说明 + 常见 FAQ。所有角色可见, 内容按当前角色分段。
// 目标: 实习生/审核员/PM 有任何不懂先看这里, 照着能独立跑通。

const INTERN_STEPS = [
  { title: "领一道题", description: "去『我的任务』页, 看到『待领取』的题点『领取』。一道题=一次要在 Violoop + 同域几个竞品上都跑一遍(整组对打),由你一个人完成。领不到题?说明还没有 PM 铸造出可领的题,找 PM。" },
  { title: "看清怎么做", description: "『任务清单』里点开这道题, 看『中立标准 Prompt』——这就是你要原样丢给每个 AI 产品的指令。不要自己改写、不要用某个产品的专属语法, 大家用同一条才公平。" },
  { title: "在每个产品上各跑一次", description: "把同一条 Prompt 分别发给这道题要测的每个产品(如 Violoop、Claude、Manus…), 让它们各自完成任务。跑的时候记得留好证据: 结果文件/截图/对话记录, 以及执行日志(token 花销、调用次数、时间线)。" },
  { title: "逐个产品提交", description: "回『我的任务』, 每个产品点『提交』, 上传两样东西: ①原始产物(结果文件/截图) ②执行日志包(必传)。缺证据交不了。如果某产品这次没跑成/够不着环境, 如实标注, 别造假。" },
  { title: "收口交付", description: "一道题里所有产品都提交完, 点『收口交付』。系统会自动送去 AI 评审打分(在后台跑, 30-90 秒), 稍后在『排行榜』能看到分数。收口后这道题就交完了。" },
];

const REVIEWER_STEPS = [
  { title: "看 AI 给的评价", description: "『评分详情』看一道题一个产品的五维能力分(质量/效率/可靠性/自主性/体验)+ AI 评委挑出的毛病 + 评委之间是否吵架(分歧)。『成本面板』看它花了多少 token/钱, 和『是否真完成』一起看。" },
  { title: "重点复核 AI 的疑点", description: "『发现看板』: 机器把异常(疑似谎报、带病通过、大差距)预标成『疑似发现』, 你在这里下判断——写产品判断 + 最终分类。机器只提名, 拍板在人。" },
  { title: "抽查", description: "『抽查队列』: 高风险/矛盾的 100% 必查, 普通随机 10%。看一条判『一致(机器判对了)』或『异常→触发重新校准』。注意: 你不能复核自己执行过的题(职责分离)。" },
];

const OWNER_STEPS = [
  { title: "签发邀请、管人", description: "『用户管理』签发邀请令牌(私发给实习生, 一次性显示记得复制), 把信任的实习生提升为审核员。" },
  { title: "铸造任务", description: "『我的任务』页把『任务清单』里的题铸造成可领取任务, 实习生才领得到。" },
  { title: "把差距变成给研发的方法", description: "『差距报告』看 AI 分析的竞品差异化 → 去『方法沉淀』写方法初稿 → 你把关通过 → 导出给研发。" },
  { title: "校准(危险开关, 仅你)", description: "『黄金集授权』管评委校准。复核里发现评委漂移时才动, 这个开关不外放。" },
];

const FAQ = [
  { q: "我怕写错 / 操作错怎么办?", a: "别怕。所有提交前都能改, 收口前也能重来。真错了找 PM 把这道题放回清单重领即可。系统的原则是『只看最终结果』, 过程试错不扣分。" },
  { q: "『我的任务』里领不到题 / 没有可领的题?", a: "可领的题需要 PM 先『铸造』出来。任务清单里能看到题、但不能直接领——领取入口在『我的任务』页。看不到可领的题就找 PM 铸造。" },
  { q: "提交时说『缺证据』交不了?", a: "每个产品提交必须传两样: ①原始产物(结果文件/截图/对话记录) ②执行日志包。两样缺一不可, 这是『无证据不入池』的规矩。日志包要含 token 花销、调用次数、时间线。" },
  { q: "某个竞品我没装 / 跑不起来 / 拿不到 token 怎么办?", a: "如实标注『未采集 / 拿不到(unavailable)』, 千万别填 0 或编数。缺失本身是有用的信息, 造假才会污染榜单。够不着环境的产品系统会判『未参赛』, 不会冤枉打 0 分。" },
  { q: "收口后为什么排行榜还没出分?", a: "收口会在后台跑 AI 评审面板(真打多个大模型, 约 30-90 秒)。稍等一会刷新『排行榜』/『评分详情』就能看到。不用重复点收口。" },
  { q: "『盲评』是什么意思?", a: "送 AI 评委打分前, 系统会把产品名字打乱成 Product A/B/C, 评委不知道哪个是自家 Violoop, 所以不会手软或偏袒。这是保证榜单可信的关键。" },
  { q: "成本面板显示『未采集』是不是 0 花费?", a: "不是。『未采集』表示这个产品的成本数据拿不到(比如闭源云端黑箱), 不等于它没花钱。别把『拿不到』读成『很省』。" },
  { q: "能力分和诚实度什么关系?", a: "两个独立的轴。能力分=做得多好; 诚实度=它说『做完了』是不是真的(1-2 谎报危险, 4-5 老实)。一个产品可能能力强但爱谎报, 榜单把这两件事分开列, 一眼能看清。" },
  { q: "我能复核自己跑过的题吗?", a: "不能。执行和复核职责分离——你不能批自己的作业, 系统不会把你执行过的题派给你复核。" },
];

function StepsCard({ title, steps, color }) {
  return (
    <Card style={{ marginBottom: 16 }}
      title={<span><Tag color={color}>你的角色</Tag> {title}</span>}>
      <Steps direction="vertical" size="small" current={-1}
        items={steps.map((s) => ({ status: "process", title: s.title, description: s.description }))} />
    </Card>
  );
}

export default function Help() {
  const { user } = useAuth();
  const role = user?.role || "intern";
  return (
    <div>
      <Title level={3} className="page-title">使用说明 & 常见问题</Title>
      <Paragraph type="secondary">
        遇到任何不懂的, 先看这里。下面先按你的角色列出该做什么, 再是大家都可能问到的 FAQ。
      </Paragraph>

      <Alert type="info" showIcon style={{ marginBottom: 16 }}
        message="一句话理解这个系统"
        description="我们让实习生用同一条标准指令, 把同一道题分别丢给 Violoop 和各竞品跑一遍, 收集证据; AI 盲评打分 + 人工复核疑点, 最后把『竞品强在哪、我们怎么补』沉淀成方法交给研发。你只管把活干扎实、证据留全, 剩下的系统来。" />

      {role === "intern" && <StepsCard title="实习生: 领题 → 跑测 → 提交 五步" steps={INTERN_STEPS} color="blue" />}
      {role === "reviewer" && (
        <>
          <StepsCard title="审核员: 你也能做实习生的领题跑测" steps={INTERN_STEPS} color="blue" />
          <StepsCard title="审核员: 复核与抽查" steps={REVIEWER_STEPS} color="geekblue" />
        </>
      )}
      {role === "owner" && (
        <>
          <StepsCard title="PM: 管人 / 铸题 / 打包给研发" steps={OWNER_STEPS} color="purple" />
          <StepsCard title="PM: 复核与抽查(同审核员)" steps={REVIEWER_STEPS} color="geekblue" />
          <StepsCard title="PM: 底层的领题跑测(同实习生)" steps={INTERN_STEPS} color="blue" />
        </>
      )}

      <Divider />
      <Title level={4}>常见问题 FAQ</Title>
      <Collapse items={FAQ.map((f, i) => ({
        key: String(i),
        label: <Text strong>{f.q}</Text>,
        children: <Paragraph style={{ marginBottom: 0 }}>{f.a}</Paragraph>,
      }))} />

      <Alert type="success" showIcon style={{ marginTop: 16 }}
        message="还是不懂?"
        description="直接找 PM(管理员)。这套系统鼓励多问, 问清楚再跑, 比跑错重来省事。" />
    </div>
  );
}
