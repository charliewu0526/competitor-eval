import React, { useEffect, useMemo, useState } from "react";
import {
  Typography, Card, Tag, Spin, Alert, Empty, Select, Button, Space,
  Collapse, List, message, Row, Col,
} from "antd";
import { BugOutlined, SaveOutlined } from "@ant-design/icons";
import { getFindings, getEnums, postJudgment } from "../api";
import { InfoTip } from "../glossary.jsx";

// suspected_category -> 中文主标签 + 颜色语义(颜色即语义)
const SUSPECTED = {
  "suspected-bug": { label: "疑似 Bug", color: "volcano" },
  "feature-gap": { label: "功能缺口", color: "blue" },
  "experience-borrow": { label: "体验可借鉴", color: "purple" },
  "honesty-alert": { label: "诚实度警示", color: "gold" },
  "quality-alert": { label: "质量警示", color: "magenta" },
};

// 证据来源 -> 人话
const EVI_SOURCE = {
  "panel-defect": { label: "评委挑出的毛病", color: "volcano" },
  "probe-metric": { label: "卖点实测", color: "blue" },
  "code-analysis": { label: "源码机理", color: "geekblue" },
};

function suspectedTag(cat) {
  const s = SUSPECTED[cat] || { label: cat || "未分类", color: "default" };
  return <Tag color={s.color}>{s.label}</Tag>;
}

function eviLine(e, i) {
  const src = EVI_SOURCE[e.source] || { label: e.source || "证据", color: "default" };
  const detail = e.ref
    ? e.ref
    : [e.product, e.dimension, e.value != null ? `${e.value}${e.unit || ""}` : null]
        .filter(Boolean).join(" · ") || JSON.stringify(e);
  return (
    <List.Item key={i}>
      <Space align="start">
        <Tag color={src.color} style={{ marginTop: 2 }}>{src.label}</Tag>
        <span style={{ color: "#595959" }}>{detail}</span>
      </Space>
    </List.Item>
  );
}
function FindingCard({ f, enums, onSaved }) {
  const [pj, setPj] = useState(f.product_judgment || undefined);
  const [fc, setFc] = useState(f.final_category || undefined);
  const [saving, setSaving] = useState(false);
  const dirty = (pj || null) !== (f.product_judgment || null)
    || (fc || null) !== (f.final_category || null);

  const save = async () => {
    setSaving(true);
    try {
      await postJudgment(f.id, { product_judgment: pj || null, final_category: fc || null });
      message.success("判断已写回数据库");
      onSaved && onSaved();
    } catch (e) {
      message.error("保存失败:" + String(e));
    } finally {
      setSaving(false);
    }
  };

  const evidence = Array.isArray(f.evidence) ? f.evidence : [];
  const decided = f.product_judgment || f.final_category;

  return (
    <Card
      style={{ marginBottom: 16 }}
      title={
        <Space wrap>
          {suspectedTag(f.suspected_category)}
          <b>{f.subject}</b>
          <span style={{ color: "#8c8c8c", fontWeight: 400 }}>@ {f.task_id}</span>
          {f.routed_to
            ? <Tag icon={<BugOutlined />} color="red">已转 bug → {f.routed_to}</Tag>
            : null}
        </Space>
      }
      extra={decided
        ? <Tag color="green">已定判</Tag>
        : <Tag color="orange">待你拍板</Tag>}
    >
      <p style={{ marginTop: 0 }}>
        <b style={{ color: "#8c8c8c" }}>机器观察到的现象</b>(只陈述事实,不下结论):<br />
        <span style={{ color: "#262626" }}>{f.phenomenon}</span>
      </p>

      <Collapse
        ghost size="small"
        items={[{
          key: "e",
          label: <span>证据明细({evidence.length} 条) <InfoTip title="机器给出的原始佐证:评委挑出的毛病、卖点实测数值、或源码机理分析。" /></span>,
          children: evidence.length
            ? <List size="small" dataSource={evidence} renderItem={eviLine} />
            : <span style={{ color: "#8c8c8c" }}>没有附证据。</span>,
        }]}
      />

      <Row gutter={12} align="bottom" style={{ marginTop: 12 }}>
        <Col span={9}>
          <div style={{ fontSize: 12, color: "#8c8c8c", marginBottom: 4 }}>
            产品判断 <InfoTip title="PM 的产品决策:这条发现对 Violoop 意味着什么(必须补齐 / 值得借鉴 / 观察中 / 不适合)。" />
          </div>
          <Select
            style={{ width: "100%" }} allowClear placeholder="选产品判断"
            value={pj} onChange={setPj}
            options={(enums.product_judgment || []).map((v) => ({ value: v, label: v }))}
          />
        </Col>
        <Col span={9}>
          <div style={{ fontSize: 12, color: "#8c8c8c", marginBottom: 4 }}>
            最终分类 <InfoTip title="人工复核后的归类:bug / 功能缺口 / 体验借鉴 / 诚实度警示 / 不需处理。机器只给『疑似』,这里定案。" />
          </div>
          <Select
            style={{ width: "100%" }} allowClear placeholder="选最终分类"
            value={fc} onChange={setFc}
            options={(enums.final_category || []).map((v) => ({ value: v, label: v }))}
          />
        </Col>
        <Col span={6}>
          <Button type="primary" icon={<SaveOutlined />} loading={saving}
            disabled={!dirty} onClick={save} block>
            保存
          </Button>
        </Col>
      </Row>
    </Card>
  );
}

export default function Findings() {
  const [rows, setRows] = useState(null);
  const [enums, setEnums] = useState({});
  const [err, setErr] = useState(null);
  const [filter, setFilter] = useState("all"); // all | undecided | decided

  const load = () => getFindings().then(setRows).catch((e) => setErr(String(e)));
  useEffect(() => {
    load();
    getEnums().then(setEnums).catch(() => {});
  }, []);

  const shown = useMemo(() => {
    if (!rows) return [];
    if (filter === "undecided") return rows.filter((f) => !f.product_judgment && !f.final_category);
    if (filter === "decided") return rows.filter((f) => f.product_judgment || f.final_category);
    return rows;
  }, [rows, filter]);

  if (err) return <Alert type="error" message="后端没连上" description={err} showIcon />;
  if (!rows) return <Spin size="large" style={{ display: "block", margin: "80px auto" }} />;

  const nUndecided = rows.filter((f) => !f.product_judgment && !f.final_category).length;

  return (
    <div>
      <Typography.Title level={3} className="page-title">发现看板</Typography.Title>
      <p className="page-sub">
        机器把评测里的异常预标成「疑似」发现,PM 在这里定判——写下产品判断 + 最终分类,
        决定它要不要变成一个待办。机器只提名,拍板在人。
      </p>

      <Space style={{ marginBottom: 16 }} wrap>
        <Select
          value={filter} onChange={setFilter} style={{ width: 200 }}
          options={[
            { value: "all", label: `全部(${rows.length})` },
            { value: "undecided", label: `待定判(${nUndecided})` },
            { value: "decided", label: `已定判(${rows.length - nUndecided})` },
          ]}
        />
      </Space>

      {shown.length === 0 ? (
        <Card>
          <Empty description={
            rows.length === 0
              ? "还没有发现。跑过评测(带缺陷/卖点差异的 run)后,机器会在这里预标疑似发现。"
              : "这个筛选下没有发现。切到『全部』看看。"
          } />
        </Card>
      ) : (
        shown.map((f) => (
          <FindingCard key={f.id} f={f} enums={enums} onSaved={load} />
        ))
      )}
    </div>
  );
}
