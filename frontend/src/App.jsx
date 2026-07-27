import React from "react";
import { Routes, Route, useNavigate, useLocation } from "react-router-dom";
import { Layout, Menu, Typography } from "antd";
import {
  DashboardOutlined, TrophyOutlined, TableOutlined, RadarChartOutlined,
  DollarOutlined, BulbOutlined, ExperimentOutlined, SafetyCertificateOutlined,
  AuditOutlined, UnorderedListOutlined,
} from "@ant-design/icons";
import { GlossaryProvider } from "./glossary.jsx";

import Dashboard from "./pages/Dashboard.jsx";
import TaskCatalog from "./pages/TaskCatalog.jsx";
import Leaderboard from "./pages/Leaderboard.jsx";
import Matrix from "./pages/Matrix.jsx";
import ScoreDetail from "./pages/ScoreDetail.jsx";
import Cost from "./pages/Cost.jsx";
import Findings from "./pages/Findings.jsx";
import Probes from "./pages/Probes.jsx";
import SpotCheck from "./pages/SpotCheck.jsx";
import Authorizations from "./pages/Authorizations.jsx";

const { Header, Sider, Content } = Layout;

const NAV = [
  { key: "/", icon: <DashboardOutlined />, label: "总览" },
  { key: "/catalog", icon: <UnorderedListOutlined />, label: "任务清单" },
  { key: "/leaderboard", icon: <TrophyOutlined />, label: "排行榜" },
  { key: "/matrix", icon: <TableOutlined />, label: "按题矩阵" },
  { key: "/score", icon: <RadarChartOutlined />, label: "评分详情" },
  { key: "/cost", icon: <DollarOutlined />, label: "成本面板" },
  { key: "/findings", icon: <BulbOutlined />, label: "发现看板" },
  { key: "/probes", icon: <ExperimentOutlined />, label: "能力专项" },
  { key: "/spotcheck", icon: <SafetyCertificateOutlined />, label: "抽查队列" },
  { key: "/authorizations", icon: <AuditOutlined />, label: "黄金集授权" },
];

export default function App() {
  const nav = useNavigate();
  const loc = useLocation();
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
            display: "flex", alignItems: "center", boxShadow: "0 1px 4px rgba(0,0,0,0.06)" }}>
            <Typography.Title level={4} style={{ margin: 0 }}>
              竞品任务评测与产品机会看板
            </Typography.Title>
          </Header>
          <Content style={{ margin: 24 }}>
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/catalog" element={<TaskCatalog />} />
              <Route path="/leaderboard" element={<Leaderboard />} />
              <Route path="/matrix" element={<Matrix />} />
              <Route path="/score" element={<ScoreDetail />} />
              <Route path="/cost" element={<Cost />} />
              <Route path="/findings" element={<Findings />} />
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
