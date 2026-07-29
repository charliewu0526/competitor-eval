import React from "react";
import { Routes, Route, useNavigate, useLocation } from "react-router-dom";
import { Layout, Menu, Typography, Spin, Space, Tag, Dropdown, Avatar, Button, Result } from "antd";
import {
  DashboardOutlined, TrophyOutlined, TableOutlined, RadarChartOutlined,
  DollarOutlined, BulbOutlined, ExperimentOutlined, SafetyCertificateOutlined,
  AuditOutlined, UnorderedListOutlined, AppstoreOutlined, DiffOutlined,
  UserOutlined, LogoutOutlined, SolutionOutlined, DeploymentUnitOutlined,
  TeamOutlined, QuestionCircleOutlined, MessageOutlined, InboxOutlined,
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
import Users from "./pages/Users.jsx";
import Help from "./pages/Help.jsx";
import Feedback from "./pages/Feedback.jsx";
import ReportConsole from "./pages/ReportConsole.jsx";

const { Header, Sider, Content } = Layout;

// 角色分级(与后端 pipeline/rbac.py 的 rank 对齐):数值越大权限越高。
const ROLE_RANK = { intern: 0, reviewer: 1, owner: 2 };
export function roleRank(role) { return ROLE_RANK[role] ?? -1; }

// 导航单一真相源:每项带 minRole —— 菜单过滤 + 路由守卫共用这一份,
// 保证「藏了菜单」和「敲 URL 也进不去」永远一致(否则藏菜单等于没藏)。
// 分档(charlie 拍板):
//   intern 实习生(6): 总览/任务清单/我的任务/方法沉淀/差距报告/排行榜 —— 只留他的活 + 看结果。
//   reviewer 审核员(+7): 分维度/按题矩阵/评分详情/成本/发现看板/能力专项/抽查队列 —— 复核分析。
//   owner PM(+1): 黄金集授权 —— 校准类危险开关独占。
const NAV = [
  { key: "/", icon: <DashboardOutlined />, label: "总览", minRole: "intern" },
  { key: "/catalog", icon: <UnorderedListOutlined />, label: "任务清单", minRole: "intern" },
  { key: "/assignments", icon: <SolutionOutlined />, label: "我的任务", minRole: "intern" },
  { key: "/methods", icon: <DeploymentUnitOutlined />, label: "方法沉淀", minRole: "intern" },
  { key: "/gap-report", icon: <DiffOutlined />, label: "差距报告", minRole: "intern" },
  { key: "/leaderboard", icon: <TrophyOutlined />, label: "排行榜", minRole: "intern" },
  { key: "/help", icon: <QuestionCircleOutlined />, label: "使用说明", minRole: "intern" },
  { key: "/feedback", icon: <MessageOutlined />, label: "意见反馈", minRole: "intern" },
  { key: "/domain-board", icon: <AppstoreOutlined />, label: "分维度榜单", minRole: "reviewer" },
  { key: "/matrix", icon: <TableOutlined />, label: "按题矩阵", minRole: "reviewer" },
  { key: "/score", icon: <RadarChartOutlined />, label: "评分详情", minRole: "reviewer" },
  { key: "/cost", icon: <DollarOutlined />, label: "成本面板", minRole: "reviewer" },
  { key: "/findings", icon: <BulbOutlined />, label: "发现看板", minRole: "reviewer" },
  { key: "/probes", icon: <ExperimentOutlined />, label: "能力专项", minRole: "reviewer" },
  { key: "/spotcheck", icon: <SafetyCertificateOutlined />, label: "抽查队列", minRole: "reviewer" },
  { key: "/authorizations", icon: <AuditOutlined />, label: "黄金集授权", minRole: "owner" },
  { key: "/users", icon: <TeamOutlined />, label: "用户管理", minRole: "owner" },
  { key: "/report-console", icon: <InboxOutlined />, label: "反馈台", minRole: "owner" },
];

// 路由 path -> 该页要求的 minRole(路由守卫用)。与 NAV 同源。
const ROUTE_MIN_ROLE = Object.fromEntries(NAV.map((n) => [n.key, n.minRole]));

const ROLE_LABEL = {
  intern: { text: "实习生", color: "blue" },
  reviewer: { text: "审核员", color: "geekblue" },
  owner: { text: "PM(管理员)", color: "purple" },
};

// 路由守卫:实习生直接敲 /authorizations 这类 URL 也进不去(否则藏了菜单等于没藏)。
// 与 NAV 同源(ROUTE_MIN_ROLE),无权则显示人话拦截页并给回总览的入口。
function Guard({ path, children }) {
  const { user } = useAuth();
  const need = ROUTE_MIN_ROLE[path] || "intern";
  if (roleRank(user?.role) < roleRank(need)) {
    const needLabel = ROLE_LABEL[need]?.text || need;
    return (
      <Result
        status="403"
        title="这个页面不对你开放"
        subTitle={`该页面面向「${needLabel}」及以上角色。你当前是「${ROLE_LABEL[user?.role]?.text || user?.role}」,做好自己的活就行,不必看这里。`}
        extra={<Button type="primary" href="/">回到总览</Button>}
      />
    );
  }
  return children;
}

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
  const myRank = roleRank(user.role);
  // 按角色过滤菜单:只显示 minRole <= 我的角色的页(实习生彻底看不到治理/分析页)。
  const visibleNav = NAV.filter((n) => myRank >= roleRank(n.minRole))
    .map(({ key, icon, label }) => ({ key, icon, label }));

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
            items={visibleNav}
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
            <Space size={16}>
            <Button type="text" icon={<QuestionCircleOutlined />}
              onClick={() => nav("/help")}>使用说明</Button>
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
            </Space>
          </Header>
          <Content style={{ margin: 24 }}>
            <Routes>
              <Route path="/" element={<Guard path="/"><Dashboard /></Guard>} />
              <Route path="/catalog" element={<Guard path="/catalog"><TaskCatalog /></Guard>} />
              <Route path="/assignments" element={<Guard path="/assignments"><Assignments /></Guard>} />
              <Route path="/methods" element={<Guard path="/methods"><Methods /></Guard>} />
              <Route path="/leaderboard" element={<Guard path="/leaderboard"><Leaderboard /></Guard>} />
              <Route path="/domain-board" element={<Guard path="/domain-board"><DomainBoard /></Guard>} />
              <Route path="/matrix" element={<Guard path="/matrix"><Matrix /></Guard>} />
              <Route path="/score" element={<Guard path="/score"><ScoreDetail /></Guard>} />
              <Route path="/cost" element={<Guard path="/cost"><Cost /></Guard>} />
              <Route path="/findings" element={<Guard path="/findings"><Findings /></Guard>} />
              <Route path="/gap-report" element={<Guard path="/gap-report"><GapReport /></Guard>} />
              <Route path="/probes" element={<Guard path="/probes"><Probes /></Guard>} />
              <Route path="/spotcheck" element={<Guard path="/spotcheck"><SpotCheck /></Guard>} />
              <Route path="/authorizations" element={<Guard path="/authorizations"><Authorizations /></Guard>} />
              <Route path="/users" element={<Guard path="/users"><Users /></Guard>} />
              <Route path="/help" element={<Guard path="/help"><Help /></Guard>} />
              <Route path="/feedback" element={<Guard path="/feedback"><Feedback /></Guard>} />
              <Route path="/report-console" element={<Guard path="/report-console"><ReportConsole /></Guard>} />
              {/* 无匹配路由的人话兜底页 —— 否则敲错 URL(如 /tasks 应为 /catalog)整片白屏。 */}
              <Route path="*" element={
                <Result
                  status="404"
                  title="这个页面不存在"
                  subTitle="你访问的地址没有对应页面,可能是链接过期或敲错了。回总览重新开始吧。"
                  extra={<Button type="primary" href="/">回到总览</Button>}
                />
              } />
            </Routes>
          </Content>
        </Layout>
      </Layout>
    </GlossaryProvider>
  );
}
