import React, { useEffect, useState, useCallback } from "react";
import {
  Typography, Card, Tag, Spin, Alert, Empty, Button, Space, Input, message,
  Modal, Form, Divider,
} from "antd";
import {
  PlusOutlined, CheckOutlined, ExportOutlined, EyeOutlined, ReloadOutlined,
} from "@ant-design/icons";
import {
  getMethods, createMethod, approveMethod, previewMethod, exportMethod,
} from "../api";
import { useAuth } from "../auth.jsx";
import { InfoTip } from "../glossary.jsx";

const STATUS = {
  draft: { label: "初稿(待把关)", color: "orange" },
  approved: { label: "已把关(可导出)", color: "blue" },
  exported: { label: "已导出给研发", color: "green" },
};
function statusTag(s) {
  const t = STATUS[s] || { label: s, color: "default" };
  return <Tag color={t.color}>{t.label}</Tag>;
}

// intern 创建方法初稿(在差距证据包上)。
function CreateMethodButton({ onDone }) {
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();
  const [busy, setBusy] = useState(false);
  const go = async () => {
    const v = await form.validateFields().catch(() => null);
    if (!v) return;
    setBusy(true);
    try {
      await createMethod({ task_id: v.task_id.trim(), product: v.product.trim(), draft: v.draft });
      message.success("方法初稿已创建,等审核员/PM 把关");
      form.resetFields(); setOpen(false); onDone && onDone();
    } catch (e) { message.error(e.userMessage || String(e)); }
    finally { setBusy(false); }
  };
  return (
    <>
      <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
        写方法初稿
      </Button>
      <Modal title="在差距证据包上提炼方法初稿" open={open} onCancel={() => setOpen(false)}
        onOk={go} okButtonProps={{ loading: busy }} okText="创建初稿" width={560}>
        <p style={{ color: "#8c8c8c", marginTop: 0 }}>
          基于「差距报告」里的分数差 + 机理,写下:这个竞品为什么强、Violoop 该怎么落地。
          初稿要经审核员/PM 把关才能导出给研发,别怕写错。
        </p>
        <Form form={form} layout="vertical">
          <Form.Item name="task_id" label="任务 ID" rules={[{ required: true, message: "填 task_id" }]}>
            <Input placeholder="T1-wechat-send-001" />
          </Form.Item>
          <Form.Item name="product" label="竞品" rules={[{ required: true, message: "填竞品名" }]}>
            <Input placeholder="open_interpreter" />
          </Form.Item>
          <Form.Item name="draft" label="方法初稿" rules={[{ required: true, message: "写下你的提炼" }]}>
            <Input.TextArea rows={5} placeholder="竞品为何强 + Violoop 落地建议…" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

function MethodCard({ m, canGate, onChanged }) {
  const [busy, setBusy] = useState(false);
  const [doc, setDoc] = useState(null);

  const doApprove = async () => {
    setBusy(true);
    try { await approveMethod(m.id); message.success("已把关,可导出给研发"); onChanged && onChanged(); }
    catch (e) { message.error(e.userMessage || String(e)); }
    finally { setBusy(false); }
  };
  const doPreview = async () => {
    setBusy(true);
    try { const r = await previewMethod(m.id); setDoc(r.document); }
    catch (e) { message.error(e.userMessage || String(e)); }
    finally { setBusy(false); }
  };
  const doExport = async () => {
    setBusy(true);
    try { const r = await exportMethod(m.id); setDoc(r.document); message.success("已导出给研发"); onChanged && onChanged(); }
    catch (e) { message.error(e.userMessage || String(e)); }
    finally { setBusy(false); }
  };

  return (
    <Card style={{ marginBottom: 12 }}
      title={<Space wrap>{statusTag(m.status)}<b>{m.product}</b>
        <span style={{ color: "#8c8c8c", fontWeight: 400 }}>@ {m.task_id}</span>
        {m.author && <span style={{ color: "#8c8c8c", fontWeight: 400 }}>作者 {m.author}</span>}
        {m.gated_by && <span style={{ color: "#8c8c8c", fontWeight: 400 }}>把关人 {m.gated_by}</span>}
      </Space>}
      extra={
        <Space>
          {canGate && m.status === "draft" && (
            <Button type="primary" icon={<CheckOutlined />} loading={busy} onClick={doApprove}>把关通过</Button>
          )}
          {canGate && (
            <Button icon={<EyeOutlined />} loading={busy} onClick={doPreview}>预览导出</Button>
          )}
          {canGate && m.status === "approved" && (
            <Button icon={<ExportOutlined />} loading={busy} onClick={doExport}>导出给研发</Button>
          )}
        </Space>
      }>
      <div style={{ whiteSpace: "pre-wrap", color: "#434343" }}>{m.draft}</div>
      {doc && (
        <>
          <Divider style={{ margin: "12px 0" }}>研发可读文档</Divider>
          <div style={{ whiteSpace: "pre-wrap", background: "#fafafa",
            border: "1px solid #f0f0f0", borderRadius: 6, padding: 12,
            fontFamily: "monospace", fontSize: 13 }}>{doc}</div>
        </>
      )}
    </Card>
  );
}

export default function Methods() {
  const { user } = useAuth();
  const canGate = user?.role === "reviewer" || user?.role === "owner";
  const [rows, setRows] = useState(null);
  const [err, setErr] = useState(null);

  const load = useCallback(() => {
    setErr(null);
    getMethods().then(setRows).catch((e) => setErr(e.userMessage || String(e)));
  }, []);
  useEffect(() => { load(); }, [load]);

  if (err) return <Alert type="error" message="加载方法失败" description={err} showIcon
    action={<Button onClick={load}>重试</Button>} />;
  if (!rows) return <Spin size="large" style={{ display: "block", margin: "80px auto" }} />;

  return (
    <div>
      <Typography.Title level={3} className="page-title">方法沉淀</Typography.Title>
      <p className="page-sub">
        把差距变成研发能用的方法 <InfoTip title="实习生在差距证据包上提炼初稿 → 审核员/PM 把关 → 导出给研发。未把关不能导出,防瞎提炼污染可信度。" />:
        实习生写初稿 → 审核员/PM 把关 → 导出研发可读文档。
        {canGate ? "你可以把关和导出。" : "你可以写初稿,把关由审核员/PM 做。"}
      </p>

      <Space style={{ marginBottom: 16 }} wrap>
        <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
        <CreateMethodButton onDone={load} />
      </Space>

      {rows.length === 0 ? (
        <Card><Empty description="还没有方法初稿。去『差距报告』看看差距,再回来写第一稿。" /></Card>
      ) : (
        rows.map((m) => <MethodCard key={m.id} m={m} canGate={canGate} onChanged={load} />)
      )}
    </div>
  );
}
