import React, { useEffect, useState } from "react";
import {
  Typography, Card, Tag, Spin, Alert, Empty, Button, Space, Input, message,
} from "antd";
import {
  ReloadOutlined, CheckCircleOutlined, WarningOutlined,
} from "@ant-design/icons";
import { getSpotcheck, rebuildSpotcheck, postVerdict } from "../api";
import { InfoTip } from "../glossary.jsx";

const STRATUM = {
  "high-risk": { label: "🔴 高风险(必查 100%)", color: "red" },
  "contradiction": { label: "🟠 结论矛盾(必查 100%)", color: "orange" },
  "normal": { label: "🟢 普通(随机抽 10%)", color: "green" },
};

function stratumTag(s) {
  const t = STRATUM[s] || { label: s, color: "default" };
  return <Tag color={t.color}>{t.label}</Tag>;
}

function ItemCard({ it, onDone }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const verdict = async (status) => {
    setBusy(true);
    try {
      await postVerdict(it.id, { status, checked_by: "PM", verdict_note: note || null });
      message.success(status === "ok" ? "已记「一致」" : "已记「异常」,将触发重新校准");
      onDone && onDone();
    } catch (e) { message.error("提交失败:" + e); }
    finally { setBusy(false); }
  };

  return (
    <Card style={{ marginBottom: 12 }}
      title={<Space wrap>{stratumTag(it.stratum)}<b>{it.product}</b>
        <span style={{ color: "#8c8c8c", fontWeight: 400 }}>@ {it.task_id} · 第 {it.run_idx} 次</span>
      </Space>}>
      <p style={{ marginTop: 0 }}>
        <b>为什么进队列:</b> <span style={{ color: "#595959" }}>{it.reason}</span>
      </p>
      <Space.Compact style={{ width: "100%", marginBottom: 12 }}>
        <Input placeholder="抽查备注(可选)" value={note}
          onChange={(e) => setNote(e.target.value)} />
      </Space.Compact>
      <Space>
        <Button icon={<CheckCircleOutlined />} loading={busy}
          onClick={() => verdict("ok")}>一致(机器判对了)</Button>
        <Button danger icon={<WarningOutlined />} loading={busy}
          onClick={() => verdict("anomaly")}>异常 → 触发重新校准</Button>
      </Space>
    </Card>
  );
}

export default function SpotCheck() {
  const [rows, setRows] = useState(null);
  const [err, setErr] = useState(null);
  const [rebuilding, setRebuilding] = useState(false);

  const load = () => getSpotcheck("pending").then(setRows).catch((e) => setErr(String(e)));
  useEffect(() => { load(); }, []);

  const rebuild = async () => {
    setRebuilding(true);
    try {
      const r = await rebuildSpotcheck();
      message.success(`已重建队列,共 ${r.enqueued ?? "?"} 项`);
      load();
    } catch (e) { message.error("重建失败:" + e); }
    finally { setRebuilding(false); }
  };

  if (err) return <Alert type="error" message="后端没连上" description={err} showIcon />;

  return (
    <div>
      <Typography.Title level={3} className="page-title">抽查队列</Typography.Title>
      <p className="page-sub">
        主流程不等人签字就入库,人只做<b>事后分层抽查</b> <InfoTip title="普通任务随机抽 10%,矛盾项和高风险结论 100% 必查——精力花在刀刃上。" />:
        普通随机 10%、矛盾/高风险 100%。发现异常会触发 AI 评委重新校准。
      </p>

      <Button type="primary" icon={<ReloadOutlined />} loading={rebuilding}
        onClick={rebuild} style={{ marginBottom: 16 }}>
        重建抽查队列(扫库分层采样)
      </Button>

      {!rows ? <Spin size="large" style={{ display: "block", margin: "40px auto" }} />
        : rows.length === 0 ? (
          <Card><Empty description="队列为空。pipeline 落库后点上面「重建抽查队列」生成分层抽查项。" /></Card>
        ) : (
          <>
            <p style={{ color: "#8c8c8c" }}>待抽查 {rows.length} 项(高风险/矛盾排在前):</p>
            {rows.map((it) => <ItemCard key={it.id} it={it} onDone={load} />)}
          </>
        )}
    </div>
  );
}
