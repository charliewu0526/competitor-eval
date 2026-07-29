import React from "react";
import { Typography, Tabs } from "antd";
import {
  TrophyOutlined, AppstoreOutlined, TableOutlined,
  RadarChartOutlined, DollarOutlined,
} from "@ant-design/icons";
import { useSearchParams } from "react-router-dom";

import Leaderboard from "./Leaderboard.jsx";
import DomainBoard from "./DomainBoard.jsx";
import Matrix from "./Matrix.jsx";
import ScoreDetail from "./ScoreDetail.jsx";
import Cost from "./Cost.jsx";

// 评测明细:把原先 5 个各自独立的「分数切片」看板(排行榜/分维度/按题矩阵/
// 评分详情/成本)收拢到一个页,内部用 Tab 切换。它们本就是同一份 scores 表的
// 不同看法,合成一页后普通人不用面对 5 个专业入口。每个子页组件原样复用,
// 逻辑不重写;子页自带 page-title,切到哪个 Tab 只显示那一个,不冲突。
const ITEMS = [
  { key: "leaderboard", label: <span><TrophyOutlined /> 排行榜</span>, children: <Leaderboard /> },
  { key: "domain", label: <span><AppstoreOutlined /> 分维度榜单</span>, children: <DomainBoard /> },
  { key: "matrix", label: <span><TableOutlined /> 按题矩阵</span>, children: <Matrix /> },
  { key: "score", label: <span><RadarChartOutlined /> 评分详情</span>, children: <ScoreDetail /> },
  { key: "cost", label: <span><DollarOutlined /> 成本面板</span>, children: <Cost /> },
];

export default function EvalDetail() {
  // Tab 选择同步到 URL(?tab=xxx),这样刷新/分享能回到同一个 Tab。
  const [sp, setSp] = useSearchParams();
  const active = sp.get("tab") || "leaderboard";
  return (
    <div>
      <Typography.Title level={3} className="page-title">评测明细</Typography.Title>
      <p className="page-sub">
        同一份评测分数的几种看法:总排名、按能力域分榜、按题矩阵、单题拆解、成本。
        先在这里看清"谁强谁弱",再去<b>差距归因</b>看"为什么、该补什么"。
      </p>
      <Tabs
        activeKey={active}
        onChange={(k) => setSp({ tab: k }, { replace: true })}
        items={ITEMS}
        destroyInactiveTabPane
      />
    </div>
  );
}
