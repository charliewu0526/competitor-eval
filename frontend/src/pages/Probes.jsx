import React, { useEffect, useState } from "react";
import {
  Typography, Card, Tag, Spin, Alert, Empty, Table, Space, Select, Button,
  Col, Row, message, Descriptions,
} from "antd";
import { ExperimentOutlined, SaveOutlined } from "@ant-design/icons";
import { getProbes, getEnums, postJudgment } from "../api";
import { InfoTip } from "../glossary.jsx";

function ProbeCard({ p, enums, onSaved }) {
  const [pj, setPj] = useState(p.product_judgment || undefined);
  const [fc, setFc] = useState(p.final_category || undefined);
  const [saving, setSaving] = useState(false);
  const dirty = (pj || null) !== (p.product_judgment || null)
    || (fc || null) !== (p.final_category || null);

  const save = async () => {
    setSaving(true);
    try {
      await postJudgment(p.id, { product_judgment: pj || null, final_category: fc || null });
      message.success("已写回数据库");
      onSaved && onSaved();
    } catch (e) { message.error(e.userMessage || "保存失败:" + String(e)); }
    finally { setSaving(false); }
  };

  const evidence = Array.isArray(p.evidence) ? p.evidence : [];
  const metrics = evidence.filter((e) => e.source === "probe-metric");
  const codeAnalysis = evidence.find((e) => e.source === "code-analysis");

  return (
    <Card
      style={{ marginBottom: 16 }}
      title={<Space><ExperimentOutlined /><b>{p.subject}</b>
        <span style={{ color: "#8c8c8c", fontWeight: 400 }}>@ {p.task_id}</span>
        {codeAnalysis && <Tag color="geekblue">🔬 附源码机理</Tag>}
      </Space>}
      extra={pj ? <Tag color="green">已定:{pj}</Tag> : <Tag color="orange">待你拍板</Tag>}
    >
      <p style={{ marginTop: 0, color: "#262626" }}>{p.phenomenon}</p>

      {metrics.length > 0 && (
        <Table
          size="small" pagination={false} style={{ marginBottom: 12 }}
          rowKey={(r, i) => i}
          dataSource={metrics}
          columns={[
            { title: "产品", dataIndex: "product" },
            { title: "维度", dataIndex: "dimension" },
            { title: "实测值", key: "v",
              render: (_, r) => <b>{r.value}{r.unit || ""}</b> },
          ]}
        />
      )}

      {codeAnalysis && (
        <Descriptions size="small" column={1} bordered style={{ marginBottom: 12 }}
          title={<span>🔬 源码机理 <InfoTip title="开源竞品:搞清它怎么做到的,让『借鉴/补齐』判断带机理证据,而不是只说『人家行』。" /></span>}>
          <Descriptions.Item label="怎么做到的">
            {codeAnalysis.mechanism || codeAnalysis.detail || JSON.stringify(codeAnalysis)}
          </Descriptions.Item>
          {codeAnalysis.repo && (
            <Descriptions.Item label="代码仓库">
              <a href={codeAnalysis.repo} target="_blank" rel="noreferrer">{codeAnalysis.repo}</a>
            </Descriptions.Item>
          )}
          {Array.isArray(codeAnalysis.refs) && codeAnalysis.refs.length > 0 && (
            <Descriptions.Item label="证据出处">
              <Space direction="vertical" size={2}>
                {codeAnalysis.refs.map((rr, i) => {
                  const isUrl = typeof rr === "string" && /^https?:\/\//.test(rr);
                  return isUrl
                    ? <a key={i} href={rr} target="_blank" rel="noreferrer">{rr}</a>
                    : <code key={i} style={{ fontSize: 12 }}>{rr}</code>;
                })}
              </Space>
            </Descriptions.Item>
          )}
          {codeAnalysis.analyst && (
            <Descriptions.Item label="分析人">{codeAnalysis.analyst}</Descriptions.Item>
          )}
        </Descriptions>
      )}

      <Row gutter={12} align="bottom">
        <Col span={9}>
          <div style={{ fontSize: 12, color: "#8c8c8c", marginBottom: 4 }}>产品判断(你来定)</div>
          <Select style={{ width: "100%" }} allowClear placeholder="必须补齐 / 值得借鉴 / …"
            value={pj} onChange={setPj}
            options={(enums.product_judgment || []).map((v) => ({ value: v, label: v }))} />
        </Col>
        <Col span={9}>
          <div style={{ fontSize: 12, color: "#8c8c8c", marginBottom: 4 }}>最终分类(你来定)</div>
          <Select style={{ width: "100%" }} allowClear placeholder="bug / feature-gap / …"
            value={fc} onChange={setFc}
            options={(enums.final_category || []).map((v) => ({ value: v, label: v }))} />
        </Col>
        <Col span={6}>
          <Button type="primary" icon={<SaveOutlined />} loading={saving}
            disabled={!dirty} onClick={save} block>保存</Button>
        </Col>
      </Row>
    </Card>
  );
}

export default function Probes() {
  const [rows, setRows] = useState(null);
  const [enums, setEnums] = useState({});
  const [err, setErr] = useState(null);

  const load = () => getProbes().then(setRows).catch((e) => setErr(e.userMessage || String(e)));
  useEffect(() => { load(); getEnums().then(setEnums).catch(() => {}); }, []);

  if (err) return <Alert type="error" message="后端没连上" description={err} showIcon />;
  if (!rows) return <Spin size="large" style={{ display: "block", margin: "80px auto" }} />;

  return (
    <div>
      <Typography.Title level={3} className="page-title">能力专项 · 卖点对打</Typography.Title>
      <p className="page-sub">
        针对竞品某个卖点(如省 token)设计探针,拿它 vs Vio 直接对打;开源的还会附上源码机理证据。
      </p>
      {rows.length === 0 ? (
        <Card><Empty description="还没有能力专项。跑 pipeline 的 probe(如 PB-token-001)后这里会出现对打结果。" /></Card>
      ) : (
        rows.map((p) => <ProbeCard key={p.id} p={p} enums={enums} onSaved={load} />)
      )}
    </div>
  );
}
