import React, { useEffect, useState, useCallback } from "react";
import {
  Typography, Card, Tag, Spin, Alert, Button, Space, Table, message,
  Modal, Input, Select, Tooltip, Divider, Popconfirm,
} from "antd";
import {
  ReloadOutlined, UserAddOutlined, CopyOutlined, LinkOutlined, DeleteOutlined,
} from "@ant-design/icons";
import { getUsers, promoteUser, issueInvite, deleteUser } from "../api";
import { useAuth } from "../auth.jsx";

const ROLE_LABEL = {
  intern: { text: "实习生", color: "blue" },
  reviewer: { text: "审核员", color: "geekblue" },
  owner: { text: "PM(管理员)", color: "purple" },
};
function roleTag(r) {
  const t = ROLE_LABEL[r] || { text: r, color: "default" };
  return <Tag color={t.color}>{t.text}</Tag>;
}

// 签发邀请令牌:PM 私发给新实习生自注册用(注册即登录, 默认 intern)。
function IssueInviteButton({ onIssued }) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [issued, setIssued] = useState(null);

  const go = async () => {
    setBusy(true);
    try {
      // 默认 7 天有效, 够私发给新人用。
      const res = await issueInvite(note.trim() || null, 7 * 24 * 3600);
      setIssued(res);
      message.success("邀请令牌已签发,复制私发给新同学");
      onIssued && onIssued();
    } catch (e) { message.error(e.userMessage || String(e)); }
    finally { setBusy(false); }
  };

  const copy = async (text) => {
    try {
      await navigator.clipboard.writeText(text);
      message.success("已复制到剪贴板");
    } catch { message.warning("复制失败,请手动选中复制"); }
  };

  const close = () => { setOpen(false); setNote(""); setIssued(null); };

  return (
    <>
      <Button type="primary" icon={<UserAddOutlined />} onClick={() => setOpen(true)}>
        签发邀请令牌
      </Button>
      <Modal title="签发邀请令牌(私发给新同学注册用)" open={open} onCancel={close}
        footer={issued
          ? [<Button key="done" type="primary" onClick={close}>完成</Button>]
          : [
            <Button key="cancel" onClick={close}>取消</Button>,
            <Button key="ok" type="primary" loading={busy} onClick={go}>签发</Button>,
          ]}>
        {!issued ? (
          <>
            <p style={{ color: "#8c8c8c", marginTop: 0 }}>
              签发一张一次性注册凭证私发给新同学。对方在登录页「我有邀请链接」粘贴它,
              注册即登录,默认角色是实习生(intern)。令牌 7 天内有效。
            </p>
            <Input placeholder="备注(可选, 如:给算法组小张)" value={note}
              onChange={(e) => setNote(e.target.value)} onPressEnter={go} />
          </>
        ) : (
          <>
            <Alert type="success" showIcon style={{ marginBottom: 12 }}
              message="令牌已签发 —— 复制下面这串私发给对方(仅显示这一次)。" />
            <Space.Compact style={{ width: "100%" }}>
              <Input readOnly value={issued.token} />
              <Button icon={<CopyOutlined />} onClick={() => copy(issued.token)}>复制</Button>
            </Space.Compact>
            <p style={{ color: "#8c8c8c", marginTop: 12, marginBottom: 0 }}>
              对方操作:打开系统 → 登录页选「我有邀请链接」→ 粘贴此令牌 → 填名字 → 注册并登录。
            </p>
          </>
        )}
      </Modal>
    </>
  );
}

// 提升角色:owner 把 intern 提成 reviewer(或改回)。危险开关 owner 独占。
function PromoteCell({ row, meId, onDone }) {
  const [busy, setBusy] = useState(false);
  const isSelf = row.id === meId;
  const change = async (role) => {
    if (role === row.role) return;
    setBusy(true);
    try {
      await promoteUser(row.id, role);
      message.success(`${row.name || row.id} 角色已改为 ${ROLE_LABEL[role]?.text || role}`);
      onDone && onDone();
    } catch (e) { message.error(e.userMessage || String(e)); }
    finally { setBusy(false); }
  };
  return (
    <Tooltip title={isSelf ? "不能改自己的角色" : "PM 可提升/调整该用户角色"}>
      <Select size="small" value={row.role} style={{ width: 120 }} loading={busy}
        disabled={isSelf} onChange={change}
        options={[
          { value: "intern", label: "实习生" },
          { value: "reviewer", label: "审核员" },
          { value: "owner", label: "PM(管理员)" },
        ]} />
    </Tooltip>
  );
}

export default function Users() {
  const { user } = useAuth();
  const [rows, setRows] = useState(null);
  const [err, setErr] = useState(null);

  const load = useCallback(() => {
    setErr(null);
    getUsers().then(setRows).catch((e) => setErr(e.userMessage || String(e)));
  }, []);
  useEffect(() => { load(); }, [load]);

  if (err) return <Alert type="error" message="加载用户失败" description={err} showIcon
    action={<Button onClick={load}>重试</Button>} />;
  if (!rows) return <Spin size="large" style={{ display: "block", margin: "80px auto" }} />;

  const columns = [
    { title: "用户", dataIndex: "name", render: (n, r) => n || <span style={{ color: "#8c8c8c" }}>{r.id}</span> },
    { title: "用户 ID", dataIndex: "id", render: (id) => <span style={{ color: "#8c8c8c", fontFamily: "monospace" }}>{id}</span> },
    { title: "当前角色", dataIndex: "role", render: (r) => roleTag(r) },
    { title: "改角色", key: "promote",
      render: (_, r) => <PromoteCell row={r} meId={user?.id} onDone={load} /> },
    { title: "删除", key: "delete", width: 120,
      render: (_, r) => {
        const isSelf = r.id === user?.id;
        return (
          <Popconfirm title={`从成员名单删除 ${r.name || r.id}?`}
            description="该用户将无法再登录;其历史领取/提交记录会保留(追责痕迹不丢)。"
            okText="删除" okButtonProps={{ danger: true }} cancelText="取消"
            disabled={isSelf}
            onConfirm={async () => {
              try {
                await deleteUser(r.id);
                message.success(`已删除成员 ${r.name || r.id}`);
                load();
              } catch (e) { message.error(e.userMessage || String(e)); }
            }}>
            <Tooltip title={isSelf ? "不能删除自己" : "从成员名单移除该用户"}>
              <Button size="small" danger icon={<DeleteOutlined />} disabled={isSelf}>
                删除
              </Button>
            </Tooltip>
          </Popconfirm>
        );
      } },
  ];

  return (
    <div>
      <Typography.Title level={3} className="page-title">用户管理</Typography.Title>
      <p className="page-sub">
        <LinkOutlined /> 签发邀请令牌私发给新同学(注册即登录, 默认实习生), 并管理成员角色。
        提升角色属校准类危险开关, PM(owner) 独占。
      </p>

      <Space style={{ marginBottom: 16 }} wrap>
        <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
        <IssueInviteButton onIssued={load} />
      </Space>

      <Card>
        <Table rowKey="id" size="middle" columns={columns} dataSource={rows}
          pagination={false} />
      </Card>
      <Divider />
      <p style={{ color: "#8c8c8c" }}>
        新同学注册流程:你在这里签发令牌 → 私发给对方 → 对方在登录页「我有邀请链接」粘贴注册。
      </p>
    </div>
  );
}
