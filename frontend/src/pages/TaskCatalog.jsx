import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Card, Collapse, Segmented, Tag, Typography, Spin, Empty, Space, Alert,
  Button, message,
} from "antd";
import { ThunderboltOutlined, DownloadOutlined } from "@ant-design/icons";
import { getCatalog, claimFromCatalog, downloadTaskInput } from "../api.js";
import { useAuth } from "../auth.jsx";

const { Paragraph, Text } = Typography;

// GATE -> 给 intern 看的中文含义 (人话原则). 与后端 gate.py GATE_VALUES 对齐.
const GATE_META = {
  "native-operable": { color: "green", label: "参赛 (原生可操作)" },
  "api-or-integration": { color: "gold", label: "参赛 (跨层: API/集成)" },
  "cannot-reach": { color: "default", label: "不参赛 (够不着, 非差)" },
};

function CompetitorTags({ competitors }) {
  return (
    <Space size={[4, 4]} wrap>
      {competitors.map((c) => {
        const m = GATE_META[c.gate] || { color: "default", label: c.gate };
        return (
          <Tag key={c.id} color={m.color}>
            {c.display_name} · {m.label}
          </Tag>
        );
      })}
    </Space>
  );
}

function TaskPanel({ task, canClaim, onClaim, claiming }) {
  // 方案B: 领取粒度细化到「题×产品」—— 每个参赛产品一个独立领取按钮,
  // 不同人可用各自账号分别领同题的不同产品。参赛集 = participating (GATE 派生)。
  const participating = task.participating || [];
  const nameOf = (pid) => {
    const c = (task.competitors || []).find((x) => x.id === pid);
    return c ? c.display_name : pid;
  };
  return (
    <div>
      {canClaim && participating.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <Text type="secondary" style={{ display: "block", marginBottom: 6 }}>
            领取粒度 = <Text strong>这道题的某一个产品</Text>。你手上有哪个账号就领哪个,
            不同产品可由不同人分别领取。领后去『我的任务』交这个产品的产物。
          </Text>
          <Space size={[8, 8]} wrap>
            {participating.map((pid) => (
              <Button key={pid} type="primary" icon={<ThunderboltOutlined />}
                loading={claiming === `${task.task_id}::${pid}`}
                onClick={() => onClaim(task.task_id, pid)}>
                领取 {nameOf(pid)}
              </Button>
            ))}
          </Space>
        </div>
      )}
      <Paragraph type="secondary" style={{ marginBottom: 8 }}>
        <Text strong>能力域:</Text> {task.capability_domain} ·{" "}
        <Text strong>性质:</Text> {task.task_nature} ·{" "}
        <Text strong>层级:</Text> {task.tier} ·{" "}
        <Text strong>应用:</Text> {task.app}
        {task.expects_file ? " · 产出文件" : ""}
      </Paragraph>

      {(task.setup || task.input_files?.length > 0) && (
        <Card size="small" title="起始状态 / 前置准备 (由 PM 统一提供, 请勿自建素材)"
          style={{ marginBottom: 12, background: "#fffbe6", borderColor: "#ffe58f" }}>
          {task.setup && (
            <Paragraph style={{ whiteSpace: "pre-wrap", marginBottom: task.input_files?.length ? 10 : 0 }}>
              {task.setup}
            </Paragraph>
          )}
          {task.input_files?.length > 0 && (
            <div>
              <Text strong>系统已提供的起始素材(点击下载):</Text>
              <div style={{ marginTop: 6 }}>
                <Space wrap>
                  {task.input_files.map((f) => (
                    <Button key={f} size="small" icon={<DownloadOutlined />}
                      onClick={async () => {
                        try { await downloadTaskInput(task.task_id, f); }
                        catch (e) { message.error(e.userMessage || "下载失败"); }
                      }}>
                      {f}
                    </Button>
                  ))}
                </Space>
              </div>
              <Text type="secondary" style={{ fontSize: 12, display: "block", marginTop: 6 }}>
                这些就是这道题要处理的素材,直接下载到本机再让 AI 产品操作。请勿自建或更换文件。
              </Text>
            </div>
          )}
        </Card>
      )}

      <Card size="small" title="中立标准 Prompt (每个产品发同一条, ADR-0016)"
        style={{ marginBottom: 12, background: "#fafafa" }}>
        <Paragraph copyable style={{ whiteSpace: "pre-wrap", marginBottom: 0 }}>
          {task.prompt}
        </Paragraph>
      </Card>

      <Card size="small" title="同域参赛竞品 (GATE 派生, 够不着不硬拉进来打 0)"
        style={{ marginBottom: 12 }}>
        <CompetitorTags competitors={task.competitors} />
      </Card>

      {task.core_assertions?.length > 0 && (
        <Card size="small" title="核心判定点 (末态事实, 非自报)"
          style={{ marginBottom: 12 }}>
          <ul style={{ marginBottom: 0, paddingLeft: 18 }}>
            {task.core_assertions.map((a, i) => <li key={i}>{a}</li>)}
          </ul>
        </Card>
      )}

      {task.readme && (
        <Collapse ghost items={[{
          key: "readme",
          label: "详细说明 (README)",
          children: (
            <Paragraph style={{ whiteSpace: "pre-wrap" }}>{task.readme}</Paragraph>
          ),
        }]} />
      )}
    </div>
  );
}

export default function TaskCatalog() {
  const nav = useNavigate();
  const { user } = useAuth();
  const canClaim = !!user;   // 任意已登录用户(intern 起)都能自助领取
  const [groups, setGroups] = useState(null);
  const [err, setErr] = useState(null);
  const [domain, setDomain] = useState("全部");
  const [claiming, setClaiming] = useState(null);

  useEffect(() => {
    getCatalog().then(setGroups).catch((e) => setErr(e.userMessage || String(e)));
  }, []);

  // 方案B: 必须把 product 一起传给后端, 否则 product=undefined 会回退整题领取,
  // 造出锁死整道题的整题单(实习生反馈"没领同一产品也领不了"的真凶)。
  // claiming 用 `${taskId}::${product}` 与 TaskPanel 的 loading 判定对齐。
  const onClaim = async (taskId, product) => {
    setClaiming(`${taskId}::${product}`);
    try {
      await claimFromCatalog(taskId, product);
      message.success(`已领取 ${product},去『我的任务』提交这个产品的产物`);
      nav("/assignments");
    } catch (e) {
      message.warning(e.userMessage || String(e));
    } finally {
      setClaiming(null);
    }
  };

  const options = useMemo(() => {
    if (!groups) return ["全部"];
    return ["全部", ...groups.map((g) => g.label)];
  }, [groups]);

  if (err) return <Alert type="error" message="加载任务清单失败" description={err} />;
  if (!groups) return <Spin style={{ display: "block", marginTop: 80 }} />;
  if (groups.length === 0) return <Empty description="还没有预置任务" />;

  const shown = domain === "全部"
    ? groups : groups.filter((g) => g.label === domain);

  return (
    <div>
      <Typography.Paragraph type="secondary">
        按<Text strong>能力域</Text>分组的任务清单 —— 同域才同台。展开任一道题即可看
        中立标准 Prompt、同域参赛竞品,并直接<Text strong>领取这道题</Text>。
        领取后系统把它锁给你,去『我的任务』给组内每个产品各交一份产物。
      </Typography.Paragraph>

      <Segmented
        options={options}
        value={domain}
        onChange={setDomain}
        style={{ marginBottom: 16 }}
      />

      {shown.map((g) => (
        <Card
          key={g.domain}
          title={<span>{g.label} <Text type="secondary" style={{ fontWeight: 400 }}>· {g.tasks.length} 道题</Text></span>}
          style={{ marginBottom: 16 }}
        >
          <Paragraph type="secondary">{g.hint}</Paragraph>
          <Collapse
            items={g.tasks.map((t) => ({
              key: t.task_id,
              label: (
                <span>
                  <Text strong>{t.task_id}</Text>{" "}
                  <Text type="secondary">— {t.prompt.slice(0, 48)}…</Text>
                </span>
              ),
              children: <TaskPanel task={t} canClaim={canClaim}
                onClaim={onClaim} claiming={claiming === t.task_id} />,
            }))}
          />
        </Card>
      ))}
    </div>
  );
}
