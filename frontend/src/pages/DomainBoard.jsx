import React, { useEffect, useState } from "react";
import { Typography, Table, Tag, Progress, Card, Collapse, Spin, Alert, Space, Tooltip } from "antd";
import { BulbOutlined } from "@ant-design/icons";
import { getDomainBoard, getDomainSummary } from "../api";
import { InfoTip } from "../glossary.jsx";

// Claude 生成的一段「vio 优劣势总结」展示块。res 形如 {text} / {dry_run} / {empty}。
function AnalysisNote({ res, loading }) {
  if (loading) {
    return (
      <div style={{ marginBottom: 14, padding: "10px 14px", background: "#f6f9ff",
        borderRadius: 6, color: "#8c8c8c" }}>
        <Spin size="small" /> <span style={{ marginLeft: 8 }}>正在生成本域优劣势总结…</span>
      </div>
    );
  }
  if (!res) return null;
  if (res.text) {
    return (
      <Alert type="info" showIcon icon={<BulbOutlined />} style={{ marginBottom: 14 }}
        message={<span>本域优劣势总结 <span style={{ color: "#8c8c8c", fontWeight: 400, fontSize: 12 }}>
          (Claude 读最新评分自动生成{res.cached ? "·缓存" : ""})</span></span>}
        description={<span style={{ whiteSpace: "pre-wrap" }}>{res.text}</span>} />
    );
  }
  const note = res.note || (res.dry_run ? "未配置分析模型,暂无法生成总结。" : "");
  if (note) {
    return <div style={{ marginBottom: 14, color: "#8c8c8c", fontSize: 13 }}>{note}</div>;
  }
  return null;
}

function honestyTag(h) {
  if (h == null) return <Tag>未测</Tag>;
  if (h >= 4) return <Tag color="green">{h}/5 · 可信</Tag>;
  if (h <= 2) return <Tag color="red">{h}/5 · 危险</Tag>;
  return <Tag color="orange">{h}/5 · 一般</Tag>;
}

function fmtDate(ts) {
  if (ts == null) return null;
  const d = new Date(ts * 1000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// 版本 + 测试日期 + 陈旧标记 (ADR-0017): 每条分数绑版本/日期, 超期标 stale, 不冒充现状。
function freshnessCell(fr) {
  if (!fr) return <span style={{ color: "#bbb" }}>—</span>;
  const date = fmtDate(fr.tested_at);
  return (
    <Space size={4} wrap>
      {fr.competitor_version
        ? <Tag>{fr.competitor_version}</Tag>
        : <Tag color="default" style={{ color: "#999" }}>版本未知</Tag>}
      {date
        ? <span style={{ color: fr.stale ? "#cf1322" : "#8c8c8c", fontSize: 12 }}>{date}</span>
        : <span style={{ color: "#bbb", fontSize: 12 }}>日期未记</span>}
      {fr.stale && (
        <Tooltip title="这条分数超过新鲜度窗口(默认 90 天),可能已不代表现状,不拿它冒充最新战力。">
          <Tag color="volcano">陈旧</Tag>
        </Tooltip>
      )}
    </Space>
  );
}

function DomainCard({ board, summary, summaryLoading }) {
  const lb = board.leaderboard || {};
  const ranking = lb.ranking || [];
  const excluded = lb.excluded || [];
  const pf = board.product_freshness || {};

  const columns = [
    { title: "名次", dataIndex: "rank", width: 64, render: (v) => <b>#{v}</b> },
    {
      title: "产品", dataIndex: "product",
      render: (v, r) => (
        <Space>{v}{r.is_baseline && <Tag color="blue">我们 Vio(基准)</Tag>}</Space>
      ),
    },
    {
      title: <span>能力分 <InfoTip name="capability" /></span>,
      dataIndex: "avg_capability", width: 210,
      render: (v) => {
        const pct = Math.round((v || 0) * 100);
        return (
          <Space>
            <Progress percent={pct} steps={0} style={{ width: 110 }} showInfo={false}
              strokeColor={pct >= 60 ? "#52c41a" : pct >= 30 ? "#faad14" : "#ff4d4f"} />
            <b>{pct}</b><span style={{ color: "#8c8c8c" }}>/100</span>
          </Space>
        );
      },
    },
    {
      title: <span>对比基准 <InfoTip title="和我们 Vio 比,高出多少 / 落后多少能力分(百分点)。" /></span>,
      dataIndex: "vs_baseline", width: 120,
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
      dataIndex: "honesty_avg", width: 120, render: honestyTag,
    },
    {
      title: <span>版本 / 测试日期 <InfoTip title="这条分数是哪个竞品版本、哪天测的;超过 90 天标『陈旧』,不拿旧分冒充现状(ADR-0017)。" /></span>,
      key: "freshness", width: 220,
      render: (_, r) => freshnessCell(pf[r.product]),
    },
    { title: "题数", dataIndex: "n_tasks", width: 60 },
  ];

  return (
    <Card
      title={<Space><b>{board.label}</b><Tag>{board.domain || "未归域"}</Tag>
        <span style={{ color: "#8c8c8c", fontWeight: 400, fontSize: 13 }}>{board.hint}</span></Space>}
      style={{ marginBottom: 20 }}
    >
      <AnalysisNote res={summary} loading={summaryLoading} />
      <Table
        rowKey="product" columns={columns} dataSource={ranking}
        pagination={false} size="middle"
        rowClassName={(r) => (r.is_baseline ? "row-baseline" : "")}
      />
      {excluded.length > 0 && (
        <Collapse style={{ marginTop: 14 }} items={[{
          key: "ex",
          label: <span>未参赛 · {excluded.length} 项 <InfoTip name="gate" /></span>,
          children: (
            <>
              <p style={{ color: "#8c8c8c", marginTop: 0 }}>
                这些产品在本域任务上<b>环境够不着</b>(cannot-reach),标「未参赛」而非 0 分垫底 —— 够不着不是差。
              </p>
              <Table
                rowKey={(r) => r.product + r.task_id} pagination={false} size="small"
                dataSource={excluded}
                columns={[
                  { title: "产品", dataIndex: "product" },
                  { title: "任务", dataIndex: "task_id" },
                  { title: "原因", dataIndex: "reason", render: () => <Tag>环境够不着 · 未参赛</Tag> },
                ]}
              />
            </>
          ),
        }]} />
      )}
    </Card>
  );
}

export default function DomainBoard() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [summaries, setSummaries] = useState({});   // {domain: {text|dry_run|...}}
  const [sumLoading, setSumLoading] = useState(true);

  useEffect(() => {
    getDomainBoard("vio").then(setData).catch((e) => setErr(e.userMessage || String(e)));
    // 一次性拉全部域的优劣势总结(不传 domain -> {domain: {...}});读缓存,首次可能现算稍慢。
    getDomainSummary("vio").then((all) => {
      setSummaries(all || {});
      setSumLoading(false);
    }).catch(() => setSumLoading(false));
  }, []);

  if (err) return <Alert type="error" message="后端没连上" description={err} showIcon />;
  if (!data) return <Spin size="large" style={{ display: "block", margin: "80px auto" }} />;

  const boards = data.boards || [];
  const ungrouped = data.ungrouped || [];

  return (
    <div>
      <Typography.Title level={3} className="page-title">分维度榜单</Typography.Title>
      <p className="page-sub">
        按<b>能力域</b>各排一张榜 ——「同域才同台」,Codex 归代码榜、Operator 归网页榜。
        Violoop 全域参赛,一个竞品可同时上多张榜。每条分数带<b>版本 + 测试日期</b>,
        超 {data.window_days} 天标<b>陈旧</b>,不拿旧分冒充现状。
      </p>

      {boards.length === 0 && ungrouped.length === 0 && (
        <Alert type="info" showIcon message="还没有分数" description="跑几道题、落库后这里就会按能力域出榜。" />
      )}

      {boards.map((b) => (
        <DomainCard key={b.domain} board={b}
          summary={summaries[b.domain]} summaryLoading={sumLoading} />
      ))}

      {ungrouped.map((b) => (
        <div key="ungrouped">
          <Alert style={{ marginBottom: 8 }} type="warning" showIcon
            message="以下分数的任务未归入任何能力域"
            description="任务缺 capability_domain 或不在任务库,先单列出来避免静默丢失。" />
          <DomainCard board={b}
            summary={summaries[b.domain]} summaryLoading={sumLoading} />
        </div>
      ))}
    </div>
  );
}
