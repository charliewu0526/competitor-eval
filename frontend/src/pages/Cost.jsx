import React, { useEffect, useState } from "react";
import { Typography, Card, Table, Tag, Spin, Alert, Empty, Space } from "antd";
import { WarningOutlined } from "@ant-design/icons";
import { getCost } from "../api";
import { InfoTip } from "../glossary.jsx";

// 成本来源诚实标注:self-report=模型自报(可能虚高/虚低)、proxy=代理网关计量、
// unavailable=拿不到。颜色即语义:自报=橙(存疑)、代理=绿(可信)、拿不到=灰。
const COST_SOURCE = {
  "self-report": { label: "模型自报", color: "orange",
    hint: "数值来自模型自己报的用量,可能不准(自报≠实测),仅供参考。" },
  "proxy": { label: "代理计量", color: "green",
    hint: "由代理网关实测计量,较可信。" },
  "unavailable": { label: "拿不到", color: "default",
    hint: "这条 run 没有可用的成本来源,数值不可信,别当成『很省』。" },
};

// A row is the trap "省 token = 没干活" when it spent tokens but scored ~0.
function isSlackerTrap(r) {
  const spent = (r.cost_input_tokens || 0) + (r.cost_output_tokens || 0) > 0
    || (r.cost_model_calls || 0) > 0;
  const failed = r.sample_score != null && r.sample_score <= 0.01;
  return spent && failed;
}

export default function Cost() {
  const [rows, setRows] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    getCost().then(setRows).catch((e) => setErr(e.userMessage || String(e)));
  }, []);

  if (err) return <Alert type="error" message="后端没连上" description={err} showIcon />;
  if (!rows) return <Spin size="large" style={{ display: "block", margin: "80px auto" }} />;

  const columns = [
    { title: "任务", dataIndex: "task_id", width: 150 },
    { title: "产品", dataIndex: "product", width: 140,
      render: (v) => <b>{v}</b> },
    {
      title: <span>输入 token <InfoTip title="喂给模型的 token 量。" /></span>,
      dataIndex: "cost_input_tokens", width: 110, align: "right",
      render: (v) => (v || 0).toLocaleString(),
    },
    {
      title: <span>输出 token</span>,
      dataIndex: "cost_output_tokens", width: 110, align: "right",
      render: (v) => (v || 0).toLocaleString(),
    },
    {
      title: <span>调用次数 <InfoTip title="来回调了几次模型,反映架构效率(轮数越多越费)。" /></span>,
      dataIndex: "cost_model_calls", width: 100, align: "right",
    },
    {
      title: <span>折算成本 <InfoTip title="按单价表折算的美元。灰色『未采集』表示价格拿不到,不是 0 元。" /></span>,
      dataIndex: "cost_usd", width: 120, align: "right",
      render: (v, r) => (r.cost_priced
        ? <b>${Number(v).toFixed(4)}</b>
        : <Tag>未采集</Tag>),
    },
    {
      title: <span>成本来源 <InfoTip title="这些数字从哪来:代理计量最可信,模型自报存疑,拿不到就别当成『很省』。" /></span>,
      dataIndex: "cost_source", width: 130,
      render: (v) => {
        const s = COST_SOURCE[v] || { label: v || "未知", color: "default", hint: null };
        const tag = <Tag color={s.color}>{s.label}</Tag>;
        return s.hint ? <Tooltip title={s.hint}>{tag}</Tooltip> : tag;
      },
    },
    {
      title: <span>能力分 <InfoTip name="capability" /></span>,
      dataIndex: "sample_score", width: 120, align: "right",
      render: (v) => (v == null
        ? <Tag>未评分</Tag>
        : <b style={{ color: v <= 0.01 ? "#cf1322" : v >= 0.6 ? "#389e0d" : "#ad6800" }}>
            {Math.round(v * 100)}/100
          </b>),
    },
    {
      title: <span>硬性完成度 <InfoTip name="objective_ratio" /></span>,
      dataIndex: "objective_ratio", width: 120, align: "right",
      render: (v) => (v == null ? "—" : `${Math.round(v * 100)}%`),
    },
    {
      title: "提示", key: "flag", width: 160,
      render: (_, r) => (isSlackerTrap(r)
        ? <Tag icon={<WarningOutlined />} color="red">花了钱却没干成</Tag>
        : null),
    },
  ];

  return (
    <div>
      <Typography.Title level={3} className="page-title">成本面板</Typography.Title>
      <p className="page-sub">
        <b>成本必须和「是否真完成」一起看</b> <InfoTip name="cost" />——
        否则「摆烂没干完」会伪装成「省 token」。红色行 = 花了 token/调用却没做成的陷阱。
      </p>

      {rows.length === 0 ? (
        <Card><Empty description="还没有成本记录。pipeline 跑过带成本的 run 后这里就有数据。" /></Card>
      ) : (
        <Card>
          <Table
            rowKey={(r) => `${r.task_id}||${r.product}||${r.run_idx}`}
            columns={columns} dataSource={rows} pagination={false} size="middle"
            rowClassName={(r) => (isSlackerTrap(r) ? "row-trap" : "")}
          />
          <p style={{ color: "#8c8c8c", fontSize: 12, marginTop: 12, marginBottom: 0 }}>
            「未采集」表示成本源拿不到该数值,不等于 0——避免「拿不到」被误读成「很省」。
          </p>
        </Card>
      )}
    </div>
  );
}
