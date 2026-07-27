import React, { useState } from "react";
import { Card, Form, Input, Button, Tabs, Typography, Alert, message } from "antd";
import { LoginOutlined, UserAddOutlined } from "@ant-design/icons";
import { useAuth } from "../auth.jsx";

// 登录页:两种入口 —— 已有身份用 user_id 登录 / 持邀请链接自注册(默认 intern)。
// 第一版链接即凭证、无密码(ADR-0019 最薄):这里不收密码,符合后端契约。
export default function Login() {
  const { login, register } = useAuth();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const doLogin = async ({ user_id }) => {
    setBusy(true); setErr(null);
    try {
      const me = await login((user_id || "").trim());
      message.success(`欢迎回来,${me.name || me.id}(${me.role})`);
    } catch (e) { setErr(e.userMessage || String(e)); }
    finally { setBusy(false); }
  };

  const doRegister = async ({ invite_token, name }) => {
    setBusy(true); setErr(null);
    try {
      const u = await register((invite_token || "").trim(), (name || "").trim());
      message.success(`注册成功,你现在是 ${u.role}:${u.name || u.id}`);
    } catch (e) { setErr(e.userMessage || String(e)); }
    finally { setBusy(false); }
  };

  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center",
      justifyContent: "center", background: "#f0f2f5" }}>
      <Card style={{ width: 420, boxShadow: "0 4px 24px rgba(0,0,0,0.08)" }}>
        <Typography.Title level={3} style={{ textAlign: "center", marginBottom: 4 }}>
          竞品评测系统
        </Typography.Title>
        <p style={{ textAlign: "center", color: "#8c8c8c", marginTop: 0 }}>
          登录后才能领题、定判、提交。只看榜单也需要一个身份。
        </p>
        {err && <Alert type="error" showIcon message={err} style={{ marginBottom: 16 }} />}
        <Tabs
          defaultActiveKey="login"
          items={[
            {
              key: "login",
              label: <span><LoginOutlined /> 我已有账号</span>,
              children: (
                <Form layout="vertical" onFinish={doLogin} requiredMark={false}>
                  <Form.Item
                    label="用户 ID" name="user_id"
                    rules={[{ required: true, message: "请输入你的用户 ID(如 owner1)" }]}
                    extra="第一版无密码,链接即凭证。PM 首次可用 owner1 登录(需先跑 scripts/seed_owner.py)。"
                  >
                    <Input placeholder="owner1 或 u_xxxxx" autoFocus />
                  </Form.Item>
                  <Button type="primary" htmlType="submit" loading={busy} block>
                    登录
                  </Button>
                </Form>
              ),
            },
            {
              key: "register",
              label: <span><UserAddOutlined /> 我有邀请链接</span>,
              children: (
                <Form layout="vertical" onFinish={doRegister} requiredMark={false}>
                  <Form.Item
                    label="邀请令牌" name="invite_token"
                    rules={[{ required: true, message: "请粘贴 PM 私发给你的邀请令牌" }]}
                    extra="PM 在『用户管理』签发邀请令牌私发给你,注册后默认是实习生(intern)。"
                  >
                    <Input placeholder="粘贴邀请令牌" />
                  </Form.Item>
                  <Form.Item label="你的名字(可选)" name="name">
                    <Input placeholder="用于榜单/复核署名" />
                  </Form.Item>
                  <Button type="primary" htmlType="submit" loading={busy} block>
                    注册并登录
                  </Button>
                </Form>
              ),
            },
          ]}
        />
      </Card>
    </div>
  );
}
