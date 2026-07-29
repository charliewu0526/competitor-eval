import React, { useEffect, useState, useCallback } from "react";
import {
  Typography, Card, Tag, Spin, Alert, Empty, Button, Space, Input, message,
  Upload, List,
} from "antd";
import { SendOutlined, ReloadOutlined, UploadOutlined } from "@ant-design/icons";
import { submitReport, getMyReports } from "../api";

const { TextArea } = Input;

// 提交者只见「人话进展」标签(后端 submitter_view 已裁掉 diff/诊断,前端也只认标签)。
const LABEL_COLOR = {
  "已收到": "default",
  "处理中": "blue",
  "需人工处理": "orange",
  "已修复": "green",
  "已关闭": "default",
};
function statusTag(row) {
  const label = row.status_label || "处理中";
  return <Tag color={LABEL_COLOR[label] || "blue"}>{label}</Tag>;
}

function fmtTs(ts) {
  if (!ts) return "—";
  try { return new Date(ts * 1000).toLocaleString(); } catch { return "—"; }
}

export default function Feedback() {
  const [text, setText] = useState("");
  const [fileList, setFileList] = useState([]);
  const [busy, setBusy] = useState(false);
  const [mine, setMine] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);

  const load = useCallback(async () => {
    setLoading(true); setErr(null);
    try { setMine(await getMyReports()); }
    catch (e) { setErr(e.userMessage || String(e)); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const go = async () => {
    if (!text.trim()) { message.warning("先写一句问题描述吧"); return; }
    setBusy(true);
    try {
      const files = fileList.map((f) => f.originFileObj).filter(Boolean);
      await submitReport(text.trim(), files);
      message.success("反馈已提交,系统会自动带上后端日志。修复上线后你会在这里看到「已修复」。");
      setText(""); setFileList([]);
      load();
    } catch (e) { message.error(e.userMessage || String(e)); }
    finally { setBusy(false); }
  };

  return (
    <div style={{ maxWidth: 820 }}>
      <Typography.Title level={3}>意见反馈</Typography.Title>
      <Typography.Paragraph type="secondary">
        用这个系统遇到 bug 或不顺手的地方,直接在这里报 —— 不用私聊 PM。写清楚你点了哪里、
        期望什么、实际发生了什么,截图更好。系统会自动附上后端日志,你不用手动收集。
      </Typography.Paragraph>

      <Card size="small" style={{ marginBottom: 24 }}>
        <Space direction="vertical" style={{ width: "100%" }} size={12}>
          <TextArea
            rows={4} value={text} onChange={(e) => setText(e.target.value)}
            placeholder="例:在「我的任务」页点提交按钮没反应,页面也没提示。期望能提交成功或告诉我哪里不对。"
          />
          <Upload
            listType="picture"
            fileList={fileList}
            beforeUpload={() => false}  /* 不自动上传,交给提交时一起走 multipart */
            onChange={({ fileList: fl }) => setFileList(fl)}
            accept="image/*"
            multiple
          >
            <Button icon={<UploadOutlined />}>添加截图(可多张,可选)</Button>
          </Upload>
          <div>
            <Button type="primary" icon={<SendOutlined />} loading={busy} onClick={go}>
              提交反馈
            </Button>
          </div>
        </Space>
      </Card>

      <Space style={{ marginBottom: 12 }}>
        <Typography.Title level={4} style={{ margin: 0 }}>我的反馈</Typography.Title>
        <Button size="small" icon={<ReloadOutlined />} onClick={load}>刷新</Button>
      </Space>

      {err && <Alert type="error" message={err} style={{ marginBottom: 12 }} />}
      {loading ? <Spin /> : (
        mine.length === 0 ? <Empty description="还没提过反馈" /> : (
          <List
            bordered
            dataSource={mine}
            renderItem={(r) => (
              <List.Item>
                <List.Item.Meta
                  title={<Space>{statusTag(r)}<span>{r.text || "(无文字)"}</span></Space>}
                  description={`提交于 ${fmtTs(r.created_ts)} · 最近更新 ${fmtTs(r.updated_ts)}`}
                />
              </List.Item>
            )}
          />
        )
      )}
    </div>
  );
}
