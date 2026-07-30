import React, { useEffect, useMemo, useState } from "react";
import {
  Typography, Card, Select, Spin, Alert, Empty, Tag, Row, Col, Descriptions,
  List, Space, Statistic, Divider, Segmented,
} from "antd";
import { Radar } from "@ant-design/plots";
import { getScores, getScore, getCompetitorRadar, getDomainBoard } from "../api";
import { InfoTip } from "../glossary.jsx";

const DIM_LABEL = {
  S1: "质量", S2: "效率", S3: "可靠性", S4: "自主性", S5: "体验",
};
const DIM_ORDER = ["S1", "S2", "S3", "S4", "S5"];

function gateLabel(g) {
  if (g === "native-operable") return <Tag color="green">能参赛(环境够得着)</Tag>;
  if (g === "cannot-reach") return <Tag>不参赛(环境够不着)</Tag>;
  return <Tag>{g}</Tag>;
}

// ============ 按竞品雷达图(默认视图) ============
function CompetitorRadar() {
  const [radar, setRadar] = useState(null);
  const [err, setErr] = useState(null);
  const [domain, setDomain] = useState(null);   // null=全部域
  const [domains, setDomains] = useState([]);
  const [focus, setFocus] = useState("__all__"); // __all__=多竞品叠加, 或单个产品

  useEffect(() => {
    getDomainBoard("vio").then((d) => {
      const ds = (d.boards || []).map((b) => ({ value: b.domain, label: b.label || b.domain }));
      setDomains(ds);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    setRadar(null);
    getCompetitorRadar("vio", domain).then(setRadar).catch((e) => setErr(e.userMessage || String(e)));
  }, [domain]);

  const { chartData, products } = useMemo(() => {
    if (!radar || !radar.products) return { chartData: [], products: [] };
    const prods = radar.products;
    const rows = [];
    for (const p of prods) {
      if (focus !== "__all__" && p.product !== focus) continue;
      for (const dim of DIM_ORDER) {
        const v = p.dims[dim];
        if (v == null) continue;
        rows.push({
          product: p.is_baseline ? `${p.product} (我们)` : p.product,
          dim: `${dim} ${DIM_LABEL[dim]}`,
          score: v,
        });
      }
    }
    return { chartData: rows, products: prods };
  }, [radar, focus]);

  if (err) return <Alert type="error" message="后端没连上" description={err} showIcon />;
  if (!radar) return <Spin size="large" style={{ display: "block", margin: "60px auto" }} />;

  const focusOptions = [
    { value: "__all__", label: "全部竞品叠加" },
    ...products.map((p) => ({ value: p.product, label: p.is_baseline ? `${p.product}(我们)` : p.product })),
  ];

  return (
    <div>
      <Space style={{ marginBottom: 16 }} wrap>
        <span style={{ color: "#8c8c8c" }}>能力域:</span>
        <Select
          style={{ width: 200 }} allowClear placeholder="全部域(跨题平均)"
          options={domains} value={domain} onChange={(v) => setDomain(v || null)}
        />
        <span style={{ color: "#8c8c8c", marginLeft: 12 }}>看:</span>
        <Segmented
          options={focusOptions.map((o) => o.label)}
          value={(focusOptions.find((o) => o.value === focus) || focusOptions[0]).label}
          onChange={(label) => setFocus((focusOptions.find((o) => o.label === label) || {}).value || "__all__")}
        />
      </Space>

      {chartData.length === 0 ? (
        <Card><Empty description="这个范围还没有五维评分。跑几道题、落库后自动出雷达图。" /></Card>
      ) : (
        <Card title={<span>能力五维 · 按竞品对比 <InfoTip title="每个竞品在五个维度(质量/效率/可靠性/自主性/体验)上的跨题平均分(0-5)。多个竞品叠在一张图上,一眼看出我们 Vio 每一维相对强弱。" /></span>}>
          <Radar
            data={chartData}
            xField="dim" yField="score" seriesField="product" colorField="product"
            meta={{ score: { min: 0, max: 5 } }}
            area={{ visible: false }} point={{ size: 3 }}
            legend={{ position: "top" }}
            height={420}
          />
          <p style={{ color: "#8c8c8c", fontSize: 12, marginTop: 12, marginBottom: 0 }}>
            分数 0–5,越往外越强。「我们」= Vio 基准。选能力域可只看该域;下拉「看」可单独查某个竞品。
          </p>
        </Card>
      )}
    </div>
  );
}

// ============ 单题拆解(原视图, 选 产品@任务) ============
function SingleTaskDetail() {
  const [list, setList] = useState(null);
  const [sel, setSel] = useState(null);     // "task||product"
  const [detail, setDetail] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    getScores().then((rows) => {
      setList(rows);
      if (rows.length) setSel(`${rows[0].task_id}||${rows[0].product}`);
    }).catch((e) => setErr(e.userMessage || String(e)));
  }, []);

  useEffect(() => {
    if (!sel) return;
    const [task, product] = sel.split("||");
    setDetail(null);
    getScore(task, product).then(setDetail).catch((e) => setErr(e.userMessage || String(e)));
  }, [sel]);

  const radarData = useMemo(() => {
    if (!detail || !detail.subjective) return [];
    return Object.entries(detail.subjective).map(([dim, v]) => ({
      dim: `${dim} ${DIM_LABEL[dim] || ""}`.trim(),
      score: v && typeof v === "object" ? (v.median ?? v.score ?? 0) : (v ?? 0),
    }));
  }, [detail]);

  if (err) return <Alert type="error" message="后端没连上" description={err} showIcon />;
  if (!list) return <Spin size="large" style={{ display: "block", margin: "60px auto" }} />;

  const options = list.map((r) => ({
    value: `${r.task_id}||${r.product}`,
    label: `${r.product} @ ${r.task_id}`,
  }));
  const disag = (detail && detail.disagreement) || [];
  const defects = (detail && detail.defects) || [];

  return (
    <div>
      <Select
        style={{ width: 360, marginBottom: 16 }}
        options={options} value={sel} onChange={setSel}
        placeholder="选一个 产品@任务"
        showSearch optionFilterProp="label"
      />
      {!detail ? (
        list.length === 0
          ? <Card><Empty description="还没有评分。先跑 pipeline 落库。" /></Card>
          : <Spin />
      ) : (
        <Row gutter={16}>
          <Col span={10}>
            <Card title="能力五维">
              {radarData.length ? (
                <Radar
                  data={radarData} xField="dim" yField="score"
                  meta={{ score: { min: 0, max: 5 } }}
                  area={{ visible: true }} point={{ size: 3 }}
                  height={300}
                />
              ) : <Empty description="这道题没有主观五维(可能客观层就失败了,直接 0 分)。" />}
            </Card>
          </Col>
          <Col span={14}>
            <Card title="这道题的硬指标" style={{ marginBottom: 16 }}>
              <Row gutter={16}>
                <Col span={8}>
                  <Statistic title={<span>能力分 <InfoTip name="capability" /></span>}
                    value={detail.sample_score == null ? "—" : Math.round(detail.sample_score * 100)}
                    suffix={detail.sample_score == null ? "" : "/100"} />
                </Col>
                <Col span={8}>
                  <Statistic title={<span>硬性完成度 <InfoTip name="objective_ratio" /></span>}
                    value={detail.objective_ratio == null ? "—" : Math.round(detail.objective_ratio * 100)}
                    suffix={detail.objective_ratio == null ? "" : "%"} />
                </Col>
                <Col span={8}>
                  <Statistic title={<span>诚实度 <InfoTip name="honesty" /></span>}
                    value={detail.h1_honesty == null ? "未测" : `${detail.h1_honesty}/5`} />
                </Col>
              </Row>
              <Divider style={{ margin: "12px 0" }} />
              <Descriptions size="small" column={1}>
                <Descriptions.Item label="能否参赛">{gateLabel(detail.gate)}</Descriptions.Item>
                {detail.run && (
                  <Descriptions.Item label="过程摘录">
                    <span style={{ color: "#595959" }}>{detail.run.transcript_excerpt || "—"}</span>
                  </Descriptions.Item>
                )}
              </Descriptions>
            </Card>

            <Card title={<span>评委挑出的毛病 <InfoTip name="defects" /></span>} style={{ marginBottom: 16 }}>
              {defects.length === 0 ? (
                <span style={{ color: "#8c8c8c" }}>评委没挑出实质毛病。</span>
              ) : (
                <List size="small" dataSource={defects}
                  renderItem={(d) => (
                    <List.Item>
                      <Space align="start">
                        <Tag color="volcano">{d.by || "评委"}</Tag>
                        <span>{d.desc || d.text || JSON.stringify(d)}</span>
                      </Space>
                    </List.Item>
                  )} />
              )}
            </Card>

            <Card title={<span>评委分歧 <InfoTip name="disagreement" /></span>}>
              {disag.length === 0 ? (
                <span style={{ color: "#52c41a" }}>三个评委基本一致,无需复核。</span>
              ) : (
                <Space wrap>
                  {disag.map((d) => (
                    <Tag color="red" key={String(d)}>
                      {typeof d === "string" ? `${d} ${DIM_LABEL[d] || ""}` : JSON.stringify(d)} · 分歧大需复核
                    </Tag>
                  ))}
                </Space>
              )}
            </Card>
          </Col>
        </Row>
      )}
    </div>
  );
}

export default function ScoreDetail() {
  const [view, setView] = useState("竞品雷达对比");

  return (
    <div>
      <Typography.Title level={3} className="page-title">评分详情</Typography.Title>
      <p className="page-sub">
        默认<b>按竞品看五维雷达</b> —— 多个竞品叠在一张图上,一眼看出我们 Vio 哪一维强、哪一维弱。
        也可切到<b>单题拆解</b>看某一道题的评委打分与挑出的毛病。
      </p>

      <Segmented
        style={{ marginBottom: 16 }}
        options={["竞品雷达对比", "单题拆解"]}
        value={view} onChange={setView}
      />

      {view === "竞品雷达对比" ? <CompetitorRadar /> : <SingleTaskDetail />}
    </div>
  );
}
