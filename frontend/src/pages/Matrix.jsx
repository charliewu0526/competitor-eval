import React, { useEffect, useState } from "react";
import { Typography, Card, Spin, Alert, Empty, Tag } from "antd";
import { getLeaderboard } from "../api";
import { InfoTip } from "../glossary.jsx";

function cellColor(score) {
  if (score == null) return { bg: "#fafafa", fg: "#bfbfbf" };
  const pct = score * 100;
  if (pct >= 60) return { bg: "#d9f7be", fg: "#237804" };
  if (pct >= 30) return { bg: "#fff1b8", fg: "#ad6800" };
  return { bg: "#ffccc7", fg: "#a8071a" };
}

export default function Matrix() {
  const [lb, setLb] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    getLeaderboard("vio").then(setLb).catch((e) => setErr(e.userMessage || String(e)));
  }, []);

  if (err) return <Alert type="error" message="后端没连上" description={err} showIcon />;
  if (!lb) return <Spin size="large" style={{ display: "block", margin: "80px auto" }} />;

  const tasks = lb.tasks || [];
  const matrix = lb.matrix || {};
  const products = Object.keys(matrix);

  return (
    <div>
      <Typography.Title level={3} className="page-title">按题矩阵</Typography.Title>
      <p className="page-sub">
        每个产品在每道题上的<b>能力分</b> <InfoTip name="capability" />。
        颜色越绿越好,越红越差,灰色「—」表示没跑这道题。
      </p>

      {tasks.length === 0 || products.length === 0 ? (
        <Card><Empty description="还没有可对比的成绩。先跑 pipeline 把分数落库。" /></Card>
      ) : (
        <Card style={{ overflowX: "auto" }}>
          <table style={{ borderCollapse: "separate", borderSpacing: 4, width: "100%" }}>
            <thead>
              <tr>
                <th style={{ textAlign: "left", padding: "8px 12px", minWidth: 120 }}>产品 \ 任务</th>
                {tasks.map((t) => (
                  <th key={t} style={{ padding: "8px 12px", fontWeight: 500, fontSize: 13, color: "#595959" }}>
                    {t}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {products.map((p) => (
                <tr key={p}>
                  <td style={{ padding: "8px 12px", fontWeight: 600 }}>
                    {p}{p === lb.baseline && <Tag color="blue" style={{ marginLeft: 6 }}>Vio</Tag>}
                  </td>
                  {tasks.map((t) => {
                    const cell = matrix[p] && matrix[p][t];
                    const score = cell ? cell.sample_score : null;
                    const c = cellColor(score);
                    return (
                      <td key={t} className="dim-cell" style={{
                        background: c.bg, color: c.fg, textAlign: "center",
                        padding: "12px 8px", borderRadius: 6, fontWeight: 600, minWidth: 80,
                      }}>
                        {score == null ? "—" : Math.round(score * 100)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          <p style={{ color: "#8c8c8c", fontSize: 12, marginTop: 12, marginBottom: 0 }}>
            分数 0–100。绿 ≥60 · 黄 30–59 · 红 &lt;30 · 灰「—」=未测此题。
          </p>
        </Card>
      )}
    </div>
  );
}
