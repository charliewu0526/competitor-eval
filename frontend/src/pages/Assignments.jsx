import React, { useEffect, useState, useCallback } from "react";
import {
  Typography, Card, Tag, Spin, Alert, Empty, Button, Space, Input, message,
  Modal, Form, Upload, Checkbox, Divider, List, Tooltip,
} from "antd";
import {
  InboxOutlined, UploadOutlined, SendOutlined, RollbackOutlined,
  PlusOutlined, ReloadOutlined, CheckCircleTwoTone,
} from "@ant-design/icons";
import {
  getAssignments, materializeAssignment, claimAssignment, abandonAssignment,
  submitAssignment, getSubmissionProgress, postSubmission,
} from "../api";
import { useAuth } from "../auth.jsx";
import { InfoTip } from "../glossary.jsx";

const STATUS = {
  open: { label: "待领取", color: "green" },
  claimed: { label: "已领取(进行中)", color: "blue" },
  submitted: { label: "已交付", color: "default" },
};

function statusTag(s) {
  const t = STATUS[s] || { label: s, color: "default" };
  return <Tag color={t.color}>{t.label}</Tag>;
}

// owner 把任务清单里的一道题铸成可领取 Assignment。
function MaterializeButton({ onDone }) {
  const [open, setOpen] = useState(false);
  const [taskId, setTaskId] = useState("");
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try {
      await materializeAssignment(taskId.trim());
      message.success("已铸造为可领取任务");
      setOpen(false); setTaskId(""); onDone && onDone();
    } catch (e) { message.error(e.userMessage || String(e)); }
    finally { setBusy(false); }
  };
  return (
    <>
      <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
        铸造任务(从清单)
      </Button>
      <Modal title="把任务清单里的题铸成可领取任务" open={open} onCancel={() => setOpen(false)}
        onOk={go} okButtonProps={{ loading: busy, disabled: !taskId.trim() }} okText="铸造">
        <p style={{ color: "#8c8c8c" }}>
          输入任务清单里的 task_id(如 T1-wechat-send-001)。系统会带上该能力域的
          同域参赛竞品集,铸成一道整组对打任务。同题重复铸造会复用原单。
        </p>
        <Input placeholder="task_id" value={taskId}
          onChange={(e) => setTaskId(e.target.value)} onPressEnter={go} />
      </Modal>
    </>
  );
}

// 一份产品交付的上传表单(multipart:原始产物 + 执行日志包必填)。
function SubmitProductModal({ assignmentId, product, open, onClose, onDone }) {
  const [form] = Form.useForm();
  const [busy, setBusy] = useState(false);
  const [artifact, setArtifact] = useState([]);
  const [logBundle, setLogBundle] = useState([]);

  const go = async () => {
    const vals = await form.validateFields().catch(() => null);
    if (!vals) return;
    const fd = new FormData();
    fd.append("product", product);
    if (artifact[0]?.originFileObj) fd.append("artifact", artifact[0].originFileObj);
    if (logBundle[0]?.originFileObj) fd.append("log_bundle", logBundle[0].originFileObj);
    fd.append("transcript_excerpt", vals.transcript || "");
    if (vals.claimed_success != null) fd.append("claimed_success", String(vals.claimed_success));
    setBusy(true);
    try {
      await postSubmission(assignmentId, fd);
      message.success(`已提交 ${product} 的产物`);
      form.resetFields(); setArtifact([]); setLogBundle([]);
      onDone && onDone(); onClose();
    } catch (e) { message.error(e.userMessage || String(e)); }
    finally { setBusy(false); }
  };

  return (
    <Modal title={`提交产物 · ${product}`} open={open} onCancel={onClose}
      onOk={go} okButtonProps={{ loading: busy }} okText="提交" width={560}>
      <p style={{ color: "#8c8c8c", marginTop: 0 }}>
        无证据不入池:<b>原始产物</b>(截图/导出文件/AI 对话记录)与<b>执行日志包</b>
        (时间线/token/调用次数)都必须上传,否则后端会拒收。
      </p>
      <Form form={form} layout="vertical">
        <Form.Item label="原始产物(必传)" required
          extra="能证明它到底做了什么的可核查实体。">
          <Upload beforeUpload={() => false} maxCount={1} fileList={artifact}
            onChange={({ fileList }) => setArtifact(fileList)}>
            <Button icon={<UploadOutlined />}>选择产物文件</Button>
          </Upload>
        </Form.Item>
        <Form.Item label="执行日志包(必传)" required
          extra="成本与过程的真实来源,不靠事后自报。">
          <Upload beforeUpload={() => false} maxCount={1} fileList={logBundle}
            onChange={({ fileList }) => setLogBundle(fileList)}>
            <Button icon={<UploadOutlined />}>选择日志包</Button>
          </Upload>
        </Form.Item>
        <Form.Item name="transcript" label="过程摘录(可选)">
          <Input.TextArea rows={2} placeholder="关键步骤/异常的简述" />
        </Form.Item>
        <Form.Item name="claimed_success" valuePropName="checked"
          extra="它自己声称做完了吗?仅喂给诚实度(H1),不当作末态判据。">
          <Checkbox>该产品自称完成(claimed_success)</Checkbox>
        </Form.Item>
      </Form>
    </Modal>
  );
}

// 一道 Assignment 卡片:状态 + 参赛产品集 + 领取/放弃/逐产品提交/收口。
function AssignmentCard({ a, me, busy, onClaim, onAbandon, onSubmitFinal, onChanged }) {
  const mine = a.claimed_by === me?.id;
  const [progress, setProgress] = useState(null);
  const [submitFor, setSubmitFor] = useState(null);

  const loadProgress = useCallback(() => {
    if (a.status !== "claimed" || !mine) { setProgress(null); return; }
    getSubmissionProgress(a.id).then(setProgress).catch(() => setProgress(null));
  }, [a.id, a.status, mine]);
  useEffect(() => { loadProgress(); }, [loadProgress]);

  const submitted = new Set(progress?.submitted || []);
  const canFinal = progress?.complete;

  return (
    <Card style={{ marginBottom: 12 }}
      title={<Space wrap>{statusTag(a.status)}<b>{a.task_id}</b>
        {a.claimed_by && <span style={{ color: "#8c8c8c", fontWeight: 400 }}>
          领取人 {a.claimed_by}{mine ? "(你)" : ""}</span>}
      </Space>}
      extra={
        <Space>
          {a.status === "open" && (
            <Button type="primary" loading={busy} onClick={onClaim}>领取</Button>
          )}
          {a.status === "claimed" && mine && (
            <>
              <Tooltip title={canFinal ? "整组产物已交齐,可以收口" : "组内还有产品没交,交齐才能收口"}>
                <Button type="primary" icon={<SendOutlined />} loading={busy}
                  disabled={!canFinal} onClick={onSubmitFinal}>收口交付</Button>
              </Tooltip>
              <Button icon={<RollbackOutlined />} loading={busy} onClick={onAbandon}>放弃</Button>
            </>
          )}
        </Space>
      }>
      <div style={{ color: "#595959" }}>
        参赛产品集(整组对打):
        <Space wrap style={{ marginLeft: 8 }}>
          {(a.products || []).map((p) => (
            <Tag key={p} color={submitted.has(p) ? "green" : "default"}
              icon={submitted.has(p) ? <CheckCircleTwoTone twoToneColor="#52c41a" /> : null}>
              {p}{submitted.has(p) ? " 已交" : ""}
            </Tag>
          ))}
        </Space>
      </div>

      {a.status === "claimed" && mine && (
        <>
          <Divider style={{ margin: "12px 0" }} />
          <Space wrap>
            <span style={{ color: "#8c8c8c" }}>逐个产品提交产物:</span>
            {(a.products || []).map((p) => (
              <Button key={p} size="small" disabled={submitted.has(p)}
                icon={<InboxOutlined />} onClick={() => setSubmitFor(p)}>
                {submitted.has(p) ? `${p} ✓` : `提交 ${p}`}
              </Button>
            ))}
          </Space>
          {submitFor && (
            <SubmitProductModal
              assignmentId={a.id} product={submitFor} open={!!submitFor}
              onClose={() => setSubmitFor(null)}
              onDone={() => { loadProgress(); onChanged && onChanged(); }}
            />
          )}
        </>
      )}
    </Card>
  );
}

export default function Assignments() {
  const { user } = useAuth();
  const isOwner = user?.role === "owner";
  const [rows, setRows] = useState(null);
  const [err, setErr] = useState(null);
  const [busyId, setBusyId] = useState(null);

  const load = useCallback(() => {
    setErr(null);
    getAssignments().then(setRows).catch((e) => setErr(e.userMessage || String(e)));
  }, []);
  useEffect(() => { load(); }, [load]);

  const doClaim = async (id) => {
    setBusyId(id);
    try { await claimAssignment(id); message.success("已领取,去提交你的产物吧"); load(); }
    catch (e) { message.error(e.userMessage || String(e)); }
    finally { setBusyId(null); }
  };
  const doAbandon = async (id) => {
    setBusyId(id);
    try { await abandonAssignment(id); message.success("已放弃,任务回到待领取"); load(); }
    catch (e) { message.error(e.userMessage || String(e)); }
    finally { setBusyId(null); }
  };
  const doSubmitFinal = async (id) => {
    setBusyId(id);
    try { await submitAssignment(id); message.success("整组已收口交付"); load(); }
    catch (e) { message.error(e.userMessage || String(e)); }
    finally { setBusyId(null); }
  };

  if (err) return <Alert type="error" message="加载任务失败" description={err} showIcon
    action={<Button onClick={load}>重试</Button>} />;
  if (!rows) return <Spin size="large" style={{ display: "block", margin: "80px auto" }} />;

  return (
    <div>
      <Typography.Title level={3} className="page-title">我的评测任务</Typography.Title>
      <p className="page-sub">
        领一道题 = 领它的<b>整组同域竞品对打</b> <InfoTip title="一道任务把该能力域的参赛竞品打包,你要给组里每个产品各交一份产物,才算齐。" />:
        给组里每个产品各交一份产物(截图/导出/对话记录 + 执行日志包),交齐后收口。
        {isOwner && " 作为 PM,你还能把任务清单里的题铸成可领取任务。"}
      </p>

      <Space style={{ marginBottom: 16 }} wrap>
        <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
        {isOwner && <MaterializeButton onDone={load} />}
      </Space>

      {rows.length === 0 ? (
        <Card>
          <Empty description={isOwner
            ? "还没有可领取任务。点上面「铸造任务」把清单里的题变成可领取。"
            : "还没有可领取任务。等 PM 从任务清单铸造后,这里就能领了。"} />
        </Card>
      ) : (
        rows.map((a) => (
          <AssignmentCard
            key={a.id} a={a} me={user} busy={busyId === a.id}
            onClaim={() => doClaim(a.id)} onAbandon={() => doAbandon(a.id)}
            onSubmitFinal={() => doSubmitFinal(a.id)} onChanged={load}
          />
        ))
      )}
    </div>
  );
}
