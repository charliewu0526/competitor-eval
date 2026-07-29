import React, { useEffect, useState, useCallback } from "react";
import {
  Typography, Table, Tag, Spin, Alert, Button, Space, Badge, Tooltip,
} from "antd";
import {
  ReloadOutlined, PictureOutlined, FileTextOutlined,
} from "@ant-design/icons";
import { getReportConsole } from "../api";

// 反馈台按内部状态显示(owner 看得到全链路,不像提交者只见人话标签)。
// needs-human / ai-failed 高亮为「优先处理」(story 20)。
const STATUS = {
  submitted:     { label: "已提交", color: "default" },
  queued:        { label: "排队中", color: "blue" },
  "ai-working":  { label: "AI 处理中", color: "processing" },
  "patch-ready": { label: "待你审补丁", color: "gold" },
  "needs-human": { label: "需人工", color: "red" },
  "ai-failed":   { label: "AI 失败", color: "red" },
  resolved:      { label: "已修复上线", color: "green" },
  closed:        { label: "已关闭", color: "default" },
};
const PRIORITY = new Set(["needs-human", "ai-failed"]);

function statusTag(s) {
  const t = STATUS[s] || { label: s, color: "default" };
  return <Tag color={t.color}>{t.label}</Tag>;
}
function fmtTs(ts) {
  if (!ts) return "—";
  try { return new Date(ts * 1000).toLocaleString(); } catch { return "—"; }
}

export default function ReportConsole() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);

  const load = useCallback(async () => {
    setLoading(true); setErr(null);
    try { setRows(await getReportConsole()); }
    catch (e) { setErr(e.userMessage || String(e)); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const priorityCount = rows.filter((r) => PRIORITY.has(r.status)).length;

  const columns = [
    {
      title: "状态", dataIndex: "status", width: 120,
      render: (s) => statusTag(s),
      filters: Object.entries(STATUS).map(([k, v]) => ({ text: v.label, value: k })),
      onFilter: (v, r) => r.status === v,
    },
    {
      title: "反馈内容", dataIndex: "text",
      render: (t) => t || <Typography.Text type="secondary">(无文字)</Typography.Text>,
    },
    {
      title: "附件", key: "attach", width: 120,
      render: (_, r) => (
        <Space>
          <Tooltip title={`${r.screenshot_count || 0} 张截图`}>
            <Space size={2}><PictureOutlined />{r.screenshot_count || 0}</Space>
          </Tooltip>
          <Tooltip title={r.has_log ? "已附后端日志" : "无日志"}>
            <FileTextOutlined style={{ color: r.has_log ? "#1677ff" : "#ccc" }} />
          </Tooltip>
        </Space>
      ),
    },
    { title: "提交者", dataIndex: "submitter", width: 140 },
    {
      title: "提交时间", dataIndex: "created_ts", width: 180,
      render: fmtTs,
      sorter: (a, b) => (a.created_ts || 0) - (b.created_ts || 0),
      defaultSortOrder: "descend",
    },
  ];

  return (
    <div>
      <Space align="center" style={{ marginBottom: 8 }}>
        <Typography.Title level={3} style={{ margin: 0 }}>反馈台</Typography.Title>
        {priorityCount > 0 && (
          <Badge count={priorityCount} offset={[4, -2]}>
            <Tag color="red">需优先处理</Tag>
          </Badge>
        )}
        <Button size="small" icon={<ReloadOutlined />} onClick={load}>刷新</Button>
      </Space>
      <Typography.Paragraph type="secondary" style={{ maxWidth: 720 }}>
        所有用户反馈集中在这里(与发现看板两条流不混)。当前为只读骨架:能看到每条反馈、
        状态、截图与日志。AI 起草的补丁 diff 面板、一键批准/上线由后续切片接入。
        <b>「需人工 / AI 失败」的反馈会红色高亮,优先处理。</b>
      </Typography.Paragraph>

      {err && <Alert type="error" message={err} style={{ marginBottom: 12 }} />}
      {loading ? <Spin /> : (
        <Table
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={rows}
          pagination={{ pageSize: 20, hideOnSinglePage: true }}
          rowClassName={(r) => (PRIORITY.has(r.status) ? "report-priority-row" : "")}
        />
      )}
    </div>
  );
}
