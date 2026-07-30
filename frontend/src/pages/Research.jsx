import React, { useState, useEffect } from "react";
import {
  Typography, Card, Input, Button, Space, Table, Tag, message, Alert, Divider,
} from "antd";
import { SearchOutlined, CheckOutlined, ReloadOutlined, WarningOutlined } from "@ant-design/icons";
import { runCapabilityResearch, reviewCapability, getCandidateTasks } from "../api";

const { Title, Paragraph, Text } = Typography;

// D: 竞品自动调研入口 —— 加竞品 + 贴官网/新闻/社媒链接 → 抓取 → LLM 抽能力 → candidate
// 待复核。抽出的能力一律 candidate(AI 复核闸),复核 approve 才升 shipped 进差集。
const STATUS_META = {
  candidate: { color: "gold", text: "待复核" },
  shipped: { color: "green", text: "已确认(进差集)" },
  limited: { color: "orange", text: "有限制" },
  marketing: { color: "default", text: "纯宣传" },
};

export default function Research() {
  const [product, setProduct] = useState("");
  const [urlsText, setUrlsText] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [candTasks, setCandTasks] = useState([]);
  const [candBusy, setCandBusy] = useState(false);

  const loadCandidates = async () => {
    setCandBusy(true);
    try {
      const r = await getCandidateTasks();
      setCandTasks(r.tasks || []);
    } catch (e) { message.error(e.userMessage || String(e)); }
    finally { setCandBusy(false); }
  };
  useEffect(() => { loadCandidates(); }, []);

  const doResearch = async () => {
    const urls = urlsText.split("\n").map((s) => s.trim()).filter(Boolean);
    if (!product.trim()) { message.warning("先填竞品 id(如 acme)"); return; }
    if (!urls.length) { message.warning("至少贴一个官网/新闻/社媒链接"); return; }
    setBusy(true);
    try {
      const r = await runCapabilityResearch(product.trim(), urls, true);
      setResult(r);
      if (r.count > 0) message.success(`抽出 ${r.count} 条候选能力(待复核)`);
      else message.info(r.note || "未抽到能力条目(如实标)");
    } catch (e) {
      message.error(e.userMessage || String(e));
    } finally { setBusy(false); }
  };

  const doReview = async (capability, approve) => {
    try {
      const r = await reviewCapability(product.trim(), capability, approve);
      if (approve && r.generated_task) {
        message.success(`已确认升 shipped,并自动生成候选题 ${r.generated_task.task_id}(未核验,不进主榜)`);
      } else if (approve && r.gen_note) {
        message.warning(`已升 shipped,但候选题生成失败:${r.gen_note}`);
      } else {
        message.success(approve ? "已确认,升为 shipped 进差集" : "维持 candidate");
      }
      // 本地反映状态变化
      setResult((prev) => prev && {
        ...prev,
        extracted: prev.extracted.map((e) =>
          e.capability === capability ? { ...e, status: approve ? "shipped" : "candidate" } : e),
      });
    } catch (e) { message.error(e.userMessage || String(e)); }
  };

  const cols = [
    { title: "能力条目", dataIndex: "capability", key: "capability",
      render: (t) => <Text>{t}</Text> },
    { title: "状态", dataIndex: "status", key: "status", width: 130,
      render: (s) => {
        const m = STATUS_META[s] || { color: "default", text: s };
        return <Tag color={m.color}>{m.text}</Tag>;
      } },
    { title: "证据", dataIndex: "evidence", key: "evidence", ellipsis: true },
    { title: "来源", dataIndex: "source_url", key: "source_url", width: 160,
      render: (u) => u ? <a href={u} target="_blank" rel="noreferrer">{u.slice(0, 40)}</a> : "—" },
    { title: "复核", key: "review", width: 150,
      render: (_, r) => r.status === "candidate" ? (
        <Space>
          <Button size="small" type="primary" icon={<CheckOutlined />}
            onClick={() => doReview(r.capability, true)}>确认</Button>
        </Space>
      ) : <Text type="secondary">—</Text> },
  ];

  return (
    <div>
      <Title level={3}>竞品自动调研</Title>
      <Paragraph type="secondary">
        贴竞品官网 / 新闻 / 社媒公开链接,系统抓取原文 → AI 抽出它声称的能力条目 →
        一律落「待复核」(candidate)。你复核确认后升为 shipped,才进能力差集当候选新功能。
        抓不到 / 抽不到会如实标,不伪造。
      </Paragraph>
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: "100%" }} size={10}>
          <Input addonBefore="竞品 id" placeholder="如 acme / town"
            value={product} onChange={(e) => setProduct(e.target.value)} />
          <Input.TextArea rows={4}
            placeholder={"每行一个链接(官网/新闻/社媒公开页)\nhttps://acme.ai\nhttps://acme.ai/features"}
            value={urlsText} onChange={(e) => setUrlsText(e.target.value)} />
          <Button type="primary" icon={<SearchOutlined />} loading={busy}
            onClick={doResearch}>启动调研</Button>
        </Space>
      </Card>

      {result && (
        <Card size="small"
          title={<Space>调研结果 · {result.product}
            <Tag>{result.count} 条候选</Tag>
            {result.persisted && <Tag color="green">已入库</Tag>}</Space>}>
          {result.note && <Alert type="info" showIcon message={result.note}
            style={{ marginBottom: 12 }} />}
          {result.fetched && result.fetched.length > 0 && (
            <>
              <Text strong>抓取来源:</Text>
              <ul>
                {result.fetched.map((f, i) => (
                  <li key={i}>
                    <Tag color={f.ok ? "green" : "red"}>{f.ok ? "成功" : "失败"}</Tag>
                    {f.url} {f.note && <Text type="secondary">— {f.note}</Text>}
                  </li>
                ))}
              </ul>
              <Divider style={{ margin: "8px 0" }} />
            </>
          )}
          <Table rowKey="capability" size="small" columns={cols}
            dataSource={result.extracted || []} pagination={false} />
        </Card>
      )}

      <Divider />
      <Card size="small"
        title={<Space><WarningOutlined style={{ color: "#faad14" }} />
          自动生成候选题(auto-from-census)
          <Tag color="gold">{candTasks.length} 道</Tag></Space>}
        extra={<Button size="small" icon={<ReloadOutlined />} loading={candBusy}
          onClick={loadCandidates}>刷新</Button>}>
        <Alert type="warning" showIcon style={{ marginBottom: 12 }}
          message="AI 暂定基准 · 未经人核验 · 不进公平主榜单"
          description={"这些题由能力普查差集在你确认竞品能力升 shipped 时自动生成," +
            "prompt/expected 是 AI 依据竞品能力条目暂拟、尚未人工核验。拿它给所有产品" +
            "打分会失真,所以它们隔离于公平主榜单,单列此区。请真跑核验、写死正确答案后" +
            "把 provenance 改为 human 才能转正进主榜。"} />
        <Table rowKey="task_id" size="small" pagination={false}
          dataSource={candTasks}
          columns={[
            { title: "候选题 id", dataIndex: "task_id", key: "task_id",
              render: (t) => <Text code>{t}</Text> },
            { title: "来源竞品", dataIndex: "rival", key: "rival", width: 100,
              render: (r) => r ? <Tag>{r}</Tag> : "—" },
            { title: "能力(AI 暂定)", dataIndex: "capability", key: "capability", ellipsis: true },
            { title: "能力域", dataIndex: "capability_domain", key: "capability_domain", width: 150 },
            { title: "状态", key: "prov", width: 160,
              render: () => <Tag color="gold" icon={<WarningOutlined />}>未核验·不进主榜</Tag> },
            { title: "证据", dataIndex: "evidence", key: "evidence", ellipsis: true,
              render: (e) => e || "—" },
          ]} />
      </Card>
    </div>
  );
}
