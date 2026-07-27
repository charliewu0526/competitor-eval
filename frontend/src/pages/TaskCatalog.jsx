import React, { useEffect, useMemo, useState } from "react";
import {
  Card, Collapse, Segmented, Tag, Typography, Spin, Empty, Space, Alert,
} from "antd";
import { getCatalog } from "../api.js";

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

function TaskPanel({ task }) {
  return (
    <div>
      <Paragraph type="secondary" style={{ marginBottom: 8 }}>
        <Text strong>能力域:</Text> {task.capability_domain} ·{" "}
        <Text strong>性质:</Text> {task.task_nature} ·{" "}
        <Text strong>层级:</Text> {task.tier} ·{" "}
        <Text strong>应用:</Text> {task.app}
        {task.expects_file ? " · 产出文件" : ""}
      </Paragraph>

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
  const [groups, setGroups] = useState(null);
  const [err, setErr] = useState(null);
  const [domain, setDomain] = useState("全部");

  useEffect(() => {
    getCatalog().then(setGroups).catch((e) => setErr(String(e)));
  }, []);

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
        按<Text strong>能力域</Text>分组的任务清单 —— 同域才同台。浏览未领取的题、
        看该发的中立标准 Prompt 与同域参赛竞品。领取任务在后续切片开放。
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
              children: <TaskPanel task={t} />,
            }))}
          />
        </Card>
      ))}
    </div>
  );
}
