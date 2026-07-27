import React, { useEffect, useMemo, useState } from "react";
import {
  Typography, Card, Tag, Spin, Alert, Empty, Select, Space, Table,
  Tooltip, Divider, List,
} from "antd";
import {
  RiseOutlined, FallOutlined, GithubOutlined, WarningOutlined,
} from "@ant-design/icons";
import { getGapReportTasks, getGapReport } from "../api";
import { InfoTip } from "../glossary.jsx";

// 差值 -> 颜色语义(绿=竞品领先该补齐 / 红=基线领先 / 灰=不可比)。
function diffCell(d) {
  if (d.cannot_reach) return <Tag color="default">未参赛(够不着)</Tag>;
  if (d.is_baseline) return <Tag color="blue">基线(我们)</Tag>;
  if (d.diff == null) return <Tag color="default">不可比</Tag>;
  const v = d.diff;
  const pct = (v > 0 ? "+" : "") + (v * 100).toFixed(0);
  if (v > 0)
    return <span style={{ color: "#cf1322", fontWeight: 600 }}>
      <RiseOutlined /> {pct} 分</span>;
  if (v < 0)
    return <span style={{ color: "#389e0d", fontWeight: 600 }}>
      <FallOutlined /> {pct} 分</span>;
  return <span style={{ color: "#8c8c8c" }}>持平</span>;
}

// 诚实度独立轴:1-2 危险(谎报) 3 中性 4-5 老实。0 分翻车要看这轴区分。
function honestyTag(h) {
  if (h == null) return <span style={{ color: "#bfbfbf" }}>—</span>;
  const color = h <= 2 ? "red" : h >= 4 ? "green" : "gold";
  return <Tag color={color}>{h}/5</Tag>;
}

function scoreCell(v) {
  if (v == null) return <span style={{ color: "#bfbfbf" }}>数据没拿到</span>;
  return <b>{(v * 100).toFixed(0)}</b>;
}

// --- 分数差表 -------------------------------------------------------------
function ScoreDiffTable({ diffs }) {
  const columns = [
    {
      title: "产品", dataIndex: "product", key: "product",
      render: (p, r) => (
        <Space>
          <b>{p}</b>
          {r.is_baseline && <Tag color="blue">我们</Tag>}
          {r.stale && (
            <Tooltip title="这条测试数据已过期(超过新鲜度窗口),仅供参考。">
              <Tag color="orange" icon={<WarningOutlined />}>数据偏旧</Tag>
            </Tooltip>
          )}
        </Space>
      ),
    },
    {
      title: <span>能力分 <InfoTip title="这道题它做得多好,0–100,越高越强。够不着环境的产品不打分。" /></span>,
      dataIndex: "sample_score", key: "sample_score", align: "center",
      render: scoreCell,
    },
    {
      title: <span>相对我们 <InfoTip title="竞品能力分减我们的分。红=竞品领先(该补齐);绿=我们领先;灰=一方够不着,不可比。" /></span>,
      key: "diff", align: "center", render: (_, d) => diffCell(d),
    },
    {
      title: <span>诚实度 <InfoTip title="它说『做完了』是不是真的。1-2=谎报(危险),4-5=老实。0 分翻车时,看这轴区分是老实翻车还是谎报翻车。" /></span>,
      dataIndex: "honesty", key: "honesty", align: "center",
      render: honestyTag,
    },
    {
      title: "醒目差距", key: "flag", align: "center",
      render: (_, d) => {
        if (d.big_gap)
          return <Tag color="red">竞品显著领先 · 该补齐</Tag>;
        if (d.big_lag)
          return <Tag color="green">我们显著领先</Tag>;
        return <span style={{ color: "#bfbfbf" }}>—</span>;
      },
    },
  ];
  return (
    <Table
      rowKey="product" columns={columns} dataSource={diffs}
      pagination={false} size="middle"
    />
  );
}

// --- 机理块 ---------------------------------------------------------------
function Mechanisms({ mechanisms }) {
  if (!mechanisms || mechanisms.length === 0) return null;
  return (
    <List
      itemLayout="vertical" dataSource={mechanisms}
      renderItem={(m) => (
        <List.Item key={m.product}>
          <Space direction="vertical" size={4} style={{ width: "100%" }}>
            <Space wrap>
              <b>{m.product}</b>
              {m.is_open_source
                ? <Tag color="green" icon={<GithubOutlined />}>开源</Tag>
                : <Tag color="default">闭源</Tag>}
              {m.repo && (
                <a href={m.repo} target="_blank" rel="noreferrer">{m.repo}</a>
              )}
            </Space>
            {m.mechanism
              ? <div style={{ color: "#262626" }}>{m.mechanism}</div>
              : (
                <div style={{ color: "#8c8c8c" }}>
                  {m.is_open_source
                    ? "开源但尚未做源码机理分析(未分析)。"
                    : "闭源,拿不到源码,无法分析机理(unavailable)。"}
                </div>
              )}
            {m.refs && m.refs.length > 0 && (
              <div style={{ fontSize: 12, color: "#8c8c8c" }}>
                依据:{m.refs.join(", ")}
                {m.analyst ? ` · 分析人 ${m.analyst}` : ""}
              </div>
            )}
          </Space>
        </List.Item>
      )}
    />
  );
}

// --- 主页面 ---------------------------------------------------------------
export default function GapReport() {
  const [taskList, setTaskList] = useState(null);
  const [taskId, setTaskId] = useState(undefined);
  const [report, setReport] = useState(null);
  const [err, setErr] = useState(null);
  const [loadingRep, setLoadingRep] = useState(false);

  useEffect(() => {
    getGapReportTasks()
      .then((d) => {
        setTaskList(d.tasks || []);
        if (d.tasks && d.tasks.length > 0) setTaskId(d.tasks[0].task_id);
      })
      .catch((e) => setErr(e.userMessage || String(e)));
  }, []);

  useEffect(() => {
    if (!taskId) return;
    setLoadingRep(true);
    getGapReport(taskId)
      .then(setReport)
      .catch((e) => setErr(e.userMessage || String(e)))
      .finally(() => setLoadingRep(false));
  }, [taskId]);

  const options = useMemo(
    () => (taskList || []).map((t) => ({
      value: t.task_id,
      label: `${t.task_id} · ${t.products} 个产品`
        + (t.big_gaps ? ` · ${t.big_gaps} 处该补齐` : ""),
    })),
    [taskList]
  );

  if (err) return <Alert type="error" message="后端没连上" description={err} showIcon />;
  if (!taskList) return <Spin size="large" style={{ display: "block", margin: "80px auto" }} />;

  return (
    <div>
      <Typography.Title level={3} className="page-title">差距报告</Typography.Title>
      <p className="page-sub">
        挑一道对比任务,看我们(基线)和各竞品在这道题上的能力分差、诚实度、
        机器挑出的发现,以及开源竞品的源码机理。机器只摆事实、标差距,
        要不要补齐由 PM 拍板。够不着环境的产品标「未参赛」,不会被冤枉打 0 分。
      </p>

      {taskList.length === 0 ? (
        <Card>
          <Empty description="还没有可对比的任务。跑过评测(有分数落库)后,这里按题列出差距报告。" />
        </Card>
      ) : (
        <>
          <Space style={{ marginBottom: 16 }} wrap>
            <span style={{ color: "#8c8c8c" }}>选任务:</span>
            <Select
              style={{ minWidth: 320 }} value={taskId} onChange={setTaskId}
              options={options}
            />
          </Space>

          {loadingRep || !report ? (
            <Spin style={{ display: "block", margin: "40px auto" }} />
          ) : (
            <>
              <Card
                title={<span>能力分差 · 我们 vs 竞品 <InfoTip title="每行一个产品的能力分,以及相对我们(基线)的差。红=竞品领先该补齐,绿=我们领先,灰=不可比。" /></span>}
                style={{ marginBottom: 16 }}
              >
                <ScoreDiffTable diffs={report.score_diffs || []} />
              </Card>

              <Card
                title={<span>本题机器发现 <InfoTip title="机器在这道题里预标的疑似发现(现象事实)。定判在『发现看板』里做,这里只汇总呈现。" /></span>}
                style={{ marginBottom: 16 }}
              >
                {(report.findings || []).length === 0 ? (
                  <Empty description="这道题机器没有预标发现。" />
                ) : (
                  <List
                    dataSource={report.findings}
                    renderItem={(f) => (
                      <List.Item key={f.id}>
                        <Space direction="vertical" size={2} style={{ width: "100%" }}>
                          <Space wrap>
                            <b>{f.subject}</b>
                            <Tag>{f.suspected_category || "未分类"}</Tag>
                            {(f.product_judgment || f.final_category)
                              ? <Tag color="green">已定判</Tag>
                              : <Tag color="orange">待定判</Tag>}
                          </Space>
                          <span style={{ color: "#595959" }}>{f.phenomenon}</span>
                        </Space>
                      </List.Item>
                    )}
                  />
                )}
              </Card>

              <Card title={<span>源码机理 · 开源竞品 <InfoTip title="开源竞品从源码分析出的实现机理(带 repo);闭源拿不到源码,如实标 unavailable,绝不编造。" /></span>}>
                {(report.mechanisms || []).length === 0 ? (
                  <Empty description="这道题没有竞品机理条目。" />
                ) : (
                  <Mechanisms mechanisms={report.mechanisms} />
                )}
              </Card>
            </>
          )}
        </>
      )}
    </div>
  );
}
