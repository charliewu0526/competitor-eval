import React, { useEffect, useMemo, useState } from "react";
import {
  Typography, Card, Tag, Spin, Alert, Empty, Select, Button, Space,
  Collapse, List, message, Row, Col,
} from "antd";
import { BugOutlined, SaveOutlined, RobotOutlined } from "@ant-design/icons";
import { getFindings, getEnums, postJudgment, precheckFinding } from "../api";
import { InfoTip } from "../glossary.jsx";
import { useAuth } from "../auth.jsx";

// suspected_category -> 中文主标签 + 颜色语义(颜色即语义)
const SUSPECTED = {
  "suspected-bug": { label: "疑似 Bug", color: "volcano" },
  "feature-gap": { label: "功能缺口", color: "blue" },
  "experience-borrow": { label: "体验可借鉴", color: "purple" },
  "honesty-alert": { label: "诚实度警示", color: "gold" },
  "quality-alert": { label: "质量警示", color: "magenta" },
  "capability-gap": { label: "能力空白 · 候选新功能", color: "geekblue" },
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

// 机器现象里常带黑话前缀,如 "[capability-probe:token 成本(总 token)] xxx".
// PM 看不懂 capability-probe / S1 之类,这里剥掉机器前缀,只留人能读的正文。
function humanizePhenomenon(text) {
  if (!text) return "";
  let t = String(text);
  // 去掉开头的 [xxx] 机器标记(如 [capability-probe:...])
  t = t.replace(/^\s*\[[^\]]*\]\s*/, "");
  // 常见黑话 -> 人话
  t = t
    .replace(/S1（质量）|S1\(质量\)|\bS1\b/g, "质量维度")
    .replace(/客观判通过/g, "硬性完成度算通过")
    .replace(/基线\s*/g, "我们(基线)")
    .replace(/—/g, " — ");
  return t.trim();
}

// panel-defect 的 ref 形如 "deepseek: Sent message to ...".
// 拆出评委名(deepseek/gemini/claude/glm...)和缺陷描述,单独醒目渲染。
function parseDefect(e) {
  const ref = (e && e.ref) || "";
  const m = /^\s*([A-Za-z0-9_\- ]{2,20}?)\s*[:：]\s*(.+)$/s.exec(ref);
  const judge = m ? m[1].trim() : "评委";
  const raw = m ? m[2].trim() : ref;
  // 中文主显:优先库里的权威译文 ref_zh(人工翻译,不失真);没有则退回原文。
  const zh = e && e.ref_zh ? String(e.ref_zh).trim() : null;
  return { judge, desc: zh || raw, raw, hasZh: !!zh };
}

function metricLine(e, i) {
  const src = EVI_SOURCE[e.source] || { label: e.source || "证据", color: "default" };
  const detail = e.mechanism
    ? `${e.product ? e.product + ":" : ""}${e.mechanism}${e.refs ? "(" + e.refs.join(", ") + ")" : ""}`
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
function FindingCard({ f, enums, onSaved, canReview }) {
  const [pj, setPj] = useState(f.product_judgment || undefined);
  const [fc, setFc] = useState(f.final_category || undefined);
  const [saving, setSaving] = useState(false);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiSug, setAiSug] = useState(null);   // {suggested_final_category, suggested_product_judgment, reason, dry_run}
  const dirty = (pj || null) !== (f.product_judgment || null)
    || (fc || null) !== (f.final_category || null);

  // E: AI 预复核 —— 让 AI 先给 final_category/product_judgment 建议 + 理由,人一键采纳或改。
  const runPrecheck = async () => {
    setAiBusy(true);
    try {
      const r = await precheckFinding(f.id);
      setAiSug(r.suggestion || null);
      if (r.suggestion && r.suggestion.dry_run) {
        message.info(r.suggestion.reason || "AI 预复核不可用(如实标)");
      }
    } catch (e) {
      message.error(e.userMessage || String(e));
    } finally { setAiBusy(false); }
  };
  const adoptAi = () => {
    if (!aiSug) return;
    if (aiSug.suggested_final_category) setFc(aiSug.suggested_final_category);
    if (aiSug.suggested_product_judgment) setPj(aiSug.suggested_product_judgment);
    message.success("已采纳 AI 建议(仍需你保存拍板)");
  };

  const save = async () => {
    setSaving(true);
    try {
      await postJudgment(f.id, { product_judgment: pj || null, final_category: fc || null });
      message.success("判断已写回数据库");
      onSaved && onSaved();
    } catch (e) {
      message.error(e.userMessage || "保存失败:" + String(e));
    } finally {
      setSaving(false);
    }
  };

  const evidence = Array.isArray(f.evidence) ? f.evidence : [];
  const defects = evidence.filter((e) => e.source === "panel-defect");
  const metrics = evidence.filter((e) => e.source !== "panel-defect");
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
        <span style={{ color: "#262626" }}>{humanizePhenomenon(f.phenomenon)}</span>
      </p>

      {defects.length > 0 && (
        <div style={{
          background: "#fff2f0", border: "1px solid #ffccc7",
          borderRadius: 6, padding: "10px 12px", marginBottom: 12,
        }}>
          <div style={{ fontWeight: 600, color: "#cf1322", marginBottom: 6 }}>
            评委挑出的毛病 <InfoTip title="AI 评审面板指出的实质缺陷。哪个评委挑的都记下来,是判『带病通过』的关键依据。" />
          </div>
          <List
            size="small" split={false} dataSource={defects}
            renderItem={(e, i) => {
              const d = parseDefect(e);
              return (
                <List.Item key={i} style={{ padding: "2px 0" }}>
                  <Space align="start" direction="vertical" size={2}>
                    <Space align="start">
                      <Tag color="volcano" style={{ marginTop: 2 }}>{d.judge}</Tag>
                      <span style={{ color: "#434343" }}>{d.desc}</span>
                    </Space>
                    {d.hasZh && d.raw && (
                      <Collapse
                        ghost size="small"
                        style={{ marginLeft: 4 }}
                        items={[{
                          key: "raw",
                          label: <span style={{ fontSize: 12, color: "#8c8c8c" }}>评委原话(英文)</span>,
                          children: <span style={{ color: "#8c8c8c", fontSize: 12 }}>{d.raw}</span>,
                        }]}
                      />
                    )}
                  </Space>
                </List.Item>
              );
            }}
          />
        </div>
      )}

      {metrics.length > 0 && (
        <Collapse
          ghost size="small" defaultActiveKey={["e"]}
          items={[{
            key: "e",
            label: <span>佐证数据({metrics.length} 条) <InfoTip title="机器给出的原始佐证:卖点实测数值、或源码机理分析。" /></span>,
            children: <List size="small" dataSource={metrics} renderItem={metricLine} />,
          }]}
        />
      )}

      {evidence.length === 0 && (
        <p style={{ color: "#8c8c8c", marginTop: 0 }}>没有附证据。</p>
      )}

      {canReview && (
        <div style={{ marginTop: 12 }}>
          {!aiSug ? (
            <Button size="small" icon={<RobotOutlined />} loading={aiBusy}
              onClick={runPrecheck}>AI 预复核建议</Button>
          ) : aiSug.dry_run ? (
            <Alert type="warning" showIcon banner
              message={aiSug.reason || "AI 预复核不可用(如实标)"} />
          ) : (
            <div style={{ background: "#f6ffed", border: "1px solid #b7eb8f",
              borderRadius: 6, padding: "8px 12px" }}>
              <Space wrap size={8}>
                <Tag icon={<RobotOutlined />} color="green">AI 预复核建议</Tag>
                {aiSug.suggested_final_category &&
                  <Tag color="geekblue">最终分类:{aiSug.suggested_final_category}</Tag>}
                {aiSug.suggested_product_judgment &&
                  <Tag color="blue">产品判断:{aiSug.suggested_product_judgment}</Tag>}
                <Button size="small" type="link" onClick={adoptAi}>采纳到下方</Button>
              </Space>
              {aiSug.reason && <div style={{ color: "#595959", marginTop: 4, fontSize: 13 }}>
                理由:{aiSug.reason}</div>}
              <div style={{ color: "#8c8c8c", marginTop: 2, fontSize: 12 }}>
                AI 只给建议,最终由你保存拍板。
              </div>
            </div>
          )}
        </div>
      )}

      {canReview ? (
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
      ) : (
        <div style={{ marginTop: 12 }}>
          {decided ? (
            <Space wrap>
              {f.product_judgment && <Tag color="blue">产品判断:{f.product_judgment}</Tag>}
              {f.final_category && <Tag color="geekblue">最终分类:{f.final_category}</Tag>}
            </Space>
          ) : (
            <Tag color="default">定判由审核员/PM 处理(你是实习生,只读)</Tag>
          )}
        </div>
      )}
    </Card>
  );
}

export default function Findings() {
  const { user } = useAuth();
  const canReview = user?.role === "reviewer" || user?.role === "owner";
  const [rows, setRows] = useState(null);
  const [enums, setEnums] = useState({});
  const [err, setErr] = useState(null);
  const [filter, setFilter] = useState("all"); // all | undecided | decided

  const load = () => getFindings().then(setRows).catch((e) => setErr(e.userMessage || String(e)));
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
          <FindingCard key={f.id} f={f} enums={enums} onSaved={load} canReview={canReview} />
        ))
      )}
    </div>
  );
}
