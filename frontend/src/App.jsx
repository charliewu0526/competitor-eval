import React from "react";
import { Routes, Route, useNavigate, useLocation } from "react-router-dom";
import { Layout, Menu, Typography, Spin, Space, Tag, Dropdown, Avatar, Button } from "antd";
import {
  DashboardOutlined, TrophyOutlined, TableOutlined, RadarChartOutlined,
  DollarOutlined, BulbOutlined, ExperimentOutlined, SafetyCertificateOutlined,
  AuditOutlined, UnorderedListOutlined, AppstoreOutlined, DiffOutlined,
  UserOutlined, LogoutOutlined, SolutionOutlined, DeploymentUnitOutlined,
} from "@ant-design/icons";
import { GlossaryProvider } from "./glossary.jsx";
import { useAuth } from "./auth.jsx";
import Login from "./pages/Login.jsx";

import Dashboard from "./pages/Dashboard.jsx";
import TaskCatalog from "./pages/TaskCatalog.jsx";
import Leaderboard from "./pages/Leaderboard.jsx";
import DomainBoard from "./pages/DomainBoard.jsx";
import Matrix from "./pages/Matrix.jsx";
import ScoreDetail from "./pages/ScoreDetail.jsx";
import Cost from "./pages/Cost.jsx";
import Findings from "./pages/Findings.jsx";
import GapReport from "./pages/GapReport.jsx";
import Probes from "./pages/Probes.jsx";
import SpotCheck from "./pages/SpotCheck.jsx";
import Authorizations from "./pages/Authorizations.jsx";
import Assignments from "./pages/Assignments.jsx";
import Methods from "./pages/Methods.jsx";

const { Header, Sider, Content } = Layout;

const NAV = [
  { key: "/", icon: <DashboardOutlined />, label: "总览" },
  { key: "/catalog", icon: <UnorderedListOutlined />, label: "任务清单" },
  { key: "/assignments", icon: <SolutionOutlined />, label: "我的任务" },
  { key: "/methods", icon: <DeploymentUnitOutlined />, label: "方法沉淀" },
  { key: "/leaderboard", icon: <TrophyOutlined />, label: "排行榜" },
  { key: "/domain-board", icon: <AppstoreOutlined />, label: "分维度榜单" },
  { key: "/matrix", icon: <TableOutlined />, label: "按题矩阵" },
  { key: "/score", icon: <RadarChartOutlined />, label: "评分详情" },
  { key: "/cost", icon: <DollarOutlined />, label: "成本面板" },
  { key: "/findings", icon: <BulbOutlined />, label: "发现看板" },
  { key: "/gap-report", icon: <DiffOutlined />, label: "差距报告" },
  { key: "/probes", icon: <ExperimentOutlined />, label: "能力专项" },
  { key: "/spotcheck", icon: <SafetyCertificateOutlined />, label: "抽查队列" },
  { key: "/authorizations", icon: <AuditOutlined />, label: "黄金集授权" },
];

const ROLE_LABEL = {
  intern: { text: "实习生", color: "blue" },
  reviewer: { text: "审核员", color: "geekblue" },
  owner: { text: "PM(管理员)", color: "purple" },
};

export default function App() {
  const nav = useNavigate();
  const loc = useLocation();
  const { user, ready, logout } = useAuth();

  // 启动校验会话中:先转圈,避免闪一下登录页。
  if (!ready) {
    return <div style={{ minHeight: "100vh", display: "flex", alignItems: "center",
      justifyContent: "center" }}><Spin size="large" /></div>;
  }
  // 未登录:整屏登录页,不渲染看板(所有数据端点都需要身份)。
  if (!user) return <Login />;

  const role = ROLE_LABEL[user.role] || { text: user.role, color: "default" };

  return (
    <GlossaryProvider>
      <Layout style={{ minHeight: "100vh" }}>
        <Sider theme="dark" width={210}>
          <div style={{ height: 56, display: "flex", alignItems: "center",
            justifyContent: "center", color: "#fff", fontWeight: 600,
            fontSize: 15, letterSpacing: 1 }}>
            竞品评测系统
          </div>
          <Menu
            theme="dark" mode="inline"
            selectedKeys={[loc.pathname]}
            items={NAV}
            onClick={({ key }) => nav(key)}
          />
        </Sider>
        <Layout>
          <Header style={{ background: "#fff", padding: "0 24px",
            display: "flex", alignItems: "center", justifyContent: "space-between",
            boxShadow: "0 1px 4px rgba(0,0,0,0.06)" }}>
            <Typography.Title level={4} style={{ margin: 0 }}>
              竞品任务评测与产品机会看板
            </Typography.Title>
            <Dropdown
              menu={{ items: [{ key: "logout", icon: <LogoutOutlined />, label: "登出" }],
                onClick: ({ key }) => { if (key === "logout") logout(); } }}
            >
              <Space style={{ cursor: "pointer" }}>
                <Avatar size="small" icon={<UserOutlined />} />
                <span>{user.name || user.id}</span>
                <Tag color={role.color} style={{ marginRight: 0 }}>{role.text}</Tag>
              </Space>
            </Dropdown>
          </Header>
          <Content style={{ margin: 24 }}>
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/catalog" element={<TaskCatalog />} />
              <Route path="/assignments" element={<Assignments />} />
              <Route path="/methods" element={<Methods />} />
              <Route path="/leaderboard" element={<Leaderboard />} />
              <Route path="/domain-board" element={<DomainBoard />} />
              <Route path="/matrix" element={<Matrix />} />
              <Route path="/score" element={<ScoreDetail />} />
              <Route path="/cost" element={<Cost />} />
              <Route path="/findings" element={<Findings />} />
              <Route path="/gap-report" element={<GapReport />} />
              <Route path="/probes" element={<Probes />} />
              <Route path="/spotcheck" element={<SpotCheck />} />
              <Route path="/authorizations" element={<Authorizations />} />
            </Routes>
          </Content>
        </Layout>
      </Layout>
    </GlossaryProvider>
  );
}
