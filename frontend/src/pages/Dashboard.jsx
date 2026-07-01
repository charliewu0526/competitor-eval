import React, { useEffect, useState } from "react";
import { Typography, Row, Col, Card, Statistic, Spin, Alert, Tag } from "antd";
import {
  AppstoreOutlined, FileTextOutlined, BulbOutlined, SafetyCertificateOutlined,
} from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import { getOverview, getLeaderboard } from "../api";
import { InfoTip } from "../glossary.jsx";

export default function Dashboard() {
  const [ov, setOv] = useState(null);
  const [lb, setLb] = useState(null);
  const [err, setErr] = useState(null);
  const nav = useNavigate();

  useEffect(() => {
    Promise.all([getOverview(), getLeaderboard("vio")])
      .then(([o, l]) => { setOv(o); setLb(l); })
      .catch((e) => setErr(String(e)));
  }, []);

  if (err) return <Alert type="error" message="后端没连上" description={err} showIcon />;
  if (!ov || !lb) return <Spin size="large" style={{ display: "block", margin: "80px auto" }} />;

  const ranking = lb.ranking || [];
  return (
    <div>
      <Typography.Title level={3} className="page-title">总览</Typography.Title>
      <p className="page-sub">一眼看清:测了几个对手、几道题、攒了多少待你拍板的发现。</p>

      <Row gutter={16}>
        <Col span={6}>
          <Card hoverable onClick={() => nav("/leaderboard")}>
            <Statistic title={<span><AppstoreOutlined /> 参评产品</span>} value={ov.products} suffix="个" />
          </Card>
        </Col>
        <Col span={6}>
          <Card hoverable onClick={() => nav("/matrix")}>
            <Statistic title={<span><FileTextOutlined /> 评测任务</span>} value={ov.tasks} suffix="道" />
          </Card>
        </Col>
        <Col span={6}>
          <Card hoverable onClick={() => nav("/findings")}>
            <Statistic
              title={<span><BulbOutlined /> 待你拍板的发现</span>}
              value={ov.findings_undecided} suffix={`/ ${ov.findings}`}
              valueStyle={{ color: ov.findings_undecided ? "#fa8c16" : "#52c41a" }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card hoverable onClick={() => nav("/spotcheck")}>
            <Statistic
              title={<span><SafetyCertificateOutlined /> 待抽查</span>}
              value={ov.spotcheck_pending} suffix="项"
              valueStyle={{ color: ov.spotcheck_pending ? "#fa8c16" : "#52c41a" }}
            />
          </Card>
        </Col>
      </Row>

      <Card
        title={<span>排行榜速览 <InfoTip name="capability" /></span>}
        style={{ marginTop: 16 }}
        extra={<a onClick={() => nav("/leaderboard")}>查看完整排行榜 →</a>}
      >
        {ranking.length === 0 ? (
          <p style={{ color: "#8c8c8c" }}>还没跑过评测。先运行 pipeline 把分数落库,这里就会出现排名。</p>
        ) : (
          ranking.map((r) => (
            <Row key={r.product} align="middle" style={{ padding: "8px 0", borderBottom: "1px solid #f0f0f0" }}>
              <Col span={2}><b>#{r.rank}</b></Col>
              <Col span={8}>
                {r.product}{" "}
                {r.is_baseline && <Tag color="blue">我们 Vio</Tag>}
              </Col>
              <Col span={8}>
                <span style={{ fontSize: 18, fontWeight: 600 }}>
                  {Math.round((r.avg_capability || 0) * 100)}
                </span>
                <span style={{ color: "#8c8c8c" }}> / 100 分</span>
              </Col>
              <Col span={6}>
                {r.honesty_avg == null
                  ? <Tag>诚实度未测</Tag>
                  : <Tag color={r.honesty_avg >= 4 ? "green" : r.honesty_avg <= 2 ? "red" : "orange"}>
                      诚实度 {r.honesty_avg}/5
                    </Tag>}
              </Col>
            </Row>
          ))
        )}
      </Card>
    </div>
  );
}
