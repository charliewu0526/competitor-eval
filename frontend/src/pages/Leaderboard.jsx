import React, { useEffect, useState } from "react";
import { Typography, Table, Tag, Progress, Card, Collapse, Spin, Alert, Space } from "antd";
import { getLeaderboard } from "../api";
import { InfoTip } from "../glossary.jsx";

function honestyTag(h) {
  if (h == null) return <Tag>未测</Tag>;
  if (h >= 4) return <Tag color="green">{h}/5 · 可信</Tag>;
  if (h <= 2) return <Tag color="red">{h}/5 · 危险</Tag>;
  return <Tag color="orange">{h}/5 · 一般</Tag>;
}

export default function Leaderboard() {
  const [lb, setLb] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    getLeaderboard("vio").then(setLb).catch((e) => setErr(String(e)));
  }, []);

  if (err) return <Alert type="error" message="后端没连上" description={err} showIcon />;
  if (!lb) return <Spin size="large" style={{ display: "block", margin: "80px auto" }} />;

  const ranking = lb.ranking || [];
  const columns = [
    { title: "名次", dataIndex: "rank", width: 70, render: (v) => <b>#{v}</b> },
    {
      title: "产品", dataIndex: "product",
      render: (v, r) => (
        <Space>{v}{r.is_baseline && <Tag color="blue">我们 Vio（基准）</Tag>}</Space>
      ),
    },
    {
      title: <span>能力分 <InfoTip name="capability" /></span>,
      dataIndex: "avg_capability", width: 240,
      sorter: (a, b) => a.avg_capability - b.avg_capability,
      defaultSortOrder: "descend",
      render: (v) => {
        const pct = Math.round((v || 0) * 100);
        return (
          <Space>
            <Progress percent={pct} steps={0} style={{ width: 120 }} showInfo={false}
              strokeColor={pct >= 60 ? "#52c41a" : pct >= 30 ? "#faad14" : "#ff4d4f"} />
            <b>{pct}</b><span style={{ color: "#8c8c8c" }}>/100</span>
          </Space>
        );
      },
    },
    {
      title: <span>对比基准 <InfoTip title="和我们 Vio 比,高出多少 / 落后多少能力分(百分点)。" /></span>,
      dataIndex: "vs_baseline", width: 130,
      render: (v) => {
        if (v == null) return "—";
        const pts = Math.round(v * 100);
        if (pts === 0) return <span style={{ color: "#8c8c8c" }}>基准</span>;
        return <span style={{ color: pts > 0 ? "#cf1322" : "#389e0d", fontWeight: 600 }}>
          {pts > 0 ? `领先 +${pts}` : `落后 ${pts}`}
        </span>;
      },
    },
    {
      title: <span>诚实度 <InfoTip name="honesty" /></span>,
      dataIndex: "honesty_avg", width: 130,
      render: honestyTag,
    },
    { title: "题数", dataIndex: "n_tasks", width: 70 },
  ];

  const excluded = lb.excluded || [];
  return (
    <div>
      <Typography.Title level={3} className="page-title">排行榜</Typography.Title>
      <p className="page-sub">
        按<b>能力分</b>排名;<b>诚实度</b>单独成列,不并进能力——「能力强但爱谎报」和「老实但弱」一眼分得开。
      </p>

      <Card>
        <Table
          rowKey="product" columns={columns} dataSource={ranking}
          pagination={false}
          rowClassName={(r) => (r.is_baseline ? "row-baseline" : "")}
        />
      </Card>

      {excluded.length > 0 && (
        <Collapse style={{ marginTop: 16 }} items={[{
          key: "ex",
          label: <span>未参与公平对比 · {excluded.length} 项 <InfoTip name="gate" /></span>,
          children: (
            <>
              <p style={{ color: "#8c8c8c", marginTop: 0 }}>
                这些产品在对应任务上<b>环境够不着</b>(cannot-reach),不打分、不排名,避免被冤枉打 0 分。
              </p>
              <Table
                rowKey={(r) => r.product + r.task_id} pagination={false} size="small"
                dataSource={excluded}
                columns={[
                  { title: "产品", dataIndex: "product" },
                  { title: "任务", dataIndex: "task_id" },
                  { title: "原因", dataIndex: "reason", render: () => <Tag>环境够不着</Tag> },
                ]}
              />
            </>
          ),
        }]} />
      )}
    </div>
  );
}
