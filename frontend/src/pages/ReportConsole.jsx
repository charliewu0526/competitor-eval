import React, { useEffect, useState, useCallback } from "react";
import {
  Typography, Table, Tag, Spin, Alert, Button, Space, Badge, Tooltip,
  Descriptions, Modal, Input, message as antdMessage,
} from "antd";
import {
  ReloadOutlined, PictureOutlined, FileTextOutlined,
  CheckOutlined, CloseOutlined,
} from "@ant-design/icons";
import { getReportConsole, approveReport, rejectReport } from "../api";

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
  const [acting, setActing] = useState(null);   // 正在批准/拒绝的 report id

  const load = useCallback(async () => {
    setLoading(true); setErr(null);
    try { setRows(await getReportConsole()); }
    catch (e) { setErr(e.userMessage || String(e)); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  // 批准:走冒烟金丝雀。有 in-flight 评测(deferred)时提示 owner 是否强制上线。
  const doApprove = useCallback(async (id, force = false) => {
    setActing(id);
    try {
      const res = await approveReport(id, force);
      if (res.outcome === "deferred") {
        Modal.confirm({
          title: "有正在进行的评测",
          content: `${res.reason || "检测到 in-flight 领题/评测"}。硬重启会打断正在跑的评测,建议等安静窗口。仍要强制上线吗?`,
          okText: "强制上线", okType: "danger", cancelText: "稍后再说",
          onOk: () => doApprove(id, true),
        });
      } else if (res.outcome === "resolved") {
        antdMessage.success("冒烟通过,已切主进程上线并通知提交者");
        load();
      } else if (res.outcome === "rolled-back") {
        antdMessage.warning(`冒烟失败已自动回滚:${res.reason || ""}。已转人工。`);
        load();
      } else {
        antdMessage.info(`结果:${res.outcome}`);
        load();
      }
    } catch (e) {
      antdMessage.error(e.userMessage || String(e));
    } finally { setActing(null); }
  }, [load]);

  // 拒绝:弹框收留言 + 是否让 AI 重试一次。
  const doReject = useCallback((id) => {
    let msg = "";
    let retry = false;
    Modal.confirm({
      title: "拒绝这个补丁",
      content: (
        <div>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
            留一句为何拒绝(会作为诊断,勾选后可让 AI 按留言重试一次)。
          </Typography.Paragraph>
          <Input.TextArea rows={3} placeholder="例:颜色还是不对,改用 flex 布局"
            onChange={(e) => { msg = e.target.value; }} />
          <label style={{ display: "block", marginTop: 8 }}>
            <input type="checkbox" onChange={(e) => { retry = e.target.checked; }} />
            {" "}拒绝后让 AI 重试一次
          </label>
        </div>
      ),
      okText: "拒绝", okType: "danger", cancelText: "取消",
      onOk: async () => {
        setActing(id);
        try {
          await rejectReport(id, msg, retry);
          antdMessage.success(retry ? "已拒绝并重新排队让 AI 重试" : "已拒绝,转人工");
          load();
        } catch (e) {
          antdMessage.error(e.userMessage || String(e));
        } finally { setActing(null); }
      },
    });
  }, [load]);

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
    {
      title: "上线闸门", key: "gate", width: 170,
      render: (_, r) => (
        r.status === "patch-ready" ? (
          <Space>
            <Button size="small" type="primary" icon={<CheckOutlined />}
              loading={acting === r.id} onClick={() => doApprove(r.id)}>
              批准上线
            </Button>
            <Button size="small" danger icon={<CloseOutlined />}
              disabled={acting === r.id} onClick={() => doReject(r.id)}>
              拒绝
            </Button>
          </Space>
        ) : <Typography.Text type="secondary">—</Typography.Text>
      ),
    },
  ];

  // 行展开:owner 可见 AI 起草的 diff / 跑过的测试 / 诊断(story 15)。
  const expandable = {
    expandedRowRender: (r) => (
      <Descriptions size="small" column={1} bordered
        style={{ maxWidth: 900 }}>
        <Descriptions.Item label="诊断">
          {r.diagnosis || <Typography.Text type="secondary">(无)</Typography.Text>}
        </Descriptions.Item>
        <Descriptions.Item label="候选补丁 diff">
          {r.diff_ref
            ? <Typography.Text code copyable>{r.diff_ref}</Typography.Text>
            : <Typography.Text type="secondary">(尚无补丁)</Typography.Text>}
        </Descriptions.Item>
        <Descriptions.Item label="AI 跑过的测试">
          {r.test_result || <Typography.Text type="secondary">(无)</Typography.Text>}
        </Descriptions.Item>
        <Descriptions.Item label="隔离分支">
          {r.branch_name || "—"}
        </Descriptions.Item>
        <Descriptions.Item label="上线锚点 / 时间">
          {(r.good_commit || "—") + "  ·  " + fmtTs(r.resolved_ts)}
        </Descriptions.Item>
      </Descriptions>
    ),
  };

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
      <Typography.Paragraph type="secondary" style={{ maxWidth: 760 }}>
        所有用户反馈集中在这里(与发现看板两条流不混)。展开行可看 AI 起草的补丁 diff、
        跑过的测试与诊断;<b>「待你审补丁」</b>可一键批准上线(先过冒烟金丝雀:临时端口起新进程
        跑健康检查+冒烟,全过才切主进程,失败自动回滚;有正在进行的评测会提示是否强制)或拒绝
        (可留言让 AI 重试)。<b>「需人工 / AI 失败」的反馈会红色高亮,优先处理。</b>
      </Typography.Paragraph>

      {err && <Alert type="error" message={err} style={{ marginBottom: 12 }} />}
      {loading ? <Spin /> : (
        <Table
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={rows}
          expandable={expandable}
          pagination={{ pageSize: 20, hideOnSinglePage: true }}
          rowClassName={(r) => (PRIORITY.has(r.status) ? "report-priority-row" : "")}
        />
      )}
    </div>
  );
}
