import React, { useEffect, useState } from "react";
import {
  Typography, Card, Tag, Spin, Alert, Empty, Row, Col, Statistic, Descriptions,
} from "antd";
import { getAuthorizations } from "../api";
import { InfoTip } from "../glossary.jsx";

const STATUS = {
  authorized: { label: "已授权", color: "green" },
  revoked: { label: "已撤销", color: "red" },
  uncalibrated: { label: "未校准", color: "default" },
};

const ROLE = {
  reviewer: "评审员(打分)",
  verifier: "核验员(判完成)",
};

function statusTag(s) {
  const t = STATUS[s] || { label: s, color: "default" };
  return <Tag color={t.color}>{t.label}</Tag>;
}

export default function Authorizations() {
  const [rows, setRows] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    getAuthorizations().then(setRows).catch((e) => setErr(e.userMessage || String(e)));
  }, []);

  if (err) return <Alert type="error" message="后端没连上" description={err} showIcon />;
  if (!rows) return <Spin size="large" style={{ display: "block", margin: "80px auto" }} />;

  return (
    <div>
      <Typography.Title level={3} className="page-title">黄金集授权</Typography.Title>
      <p className="page-sub">
        AI 评委得先在<b>人工标定的黄金集</b>上考出足够的一致率 <InfoTip name="kappa" />,
        才被授权自动打分/核验。换模型、改评分标准、抽查发现异常都会让授权作废、需重新校准。
      </p>

      {rows.length === 0 ? (
        <Card>
          <Empty
            description={
              <span>
                AI 评委还没参加考核(黄金集校准)。<br />
                先用 20–30 道人工标定的黄金集跑校准,算出一致率后才授权它自动打分。
              </span>
            }
          />
        </Card>
      ) : (
        <Row gutter={16}>
          {rows.map((a) => (
            <Col span={12} key={a.subject} style={{ marginBottom: 16 }}>
              <Card
                title={<span>{a.subject} <span style={{ color: "#8c8c8c", fontWeight: 400 }}>
                  · {ROLE[a.role] || a.role}</span></span>}
                extra={statusTag(a.status)}
              >
                <Row gutter={16}>
                  <Col span={12}>
                    <Statistic
                      title={<span>一致率 kappa <InfoTip name="kappa" /></span>}
                      value={a.kappa == null ? "—" : a.kappa}
                      precision={a.kappa == null ? undefined : 2}
                    />
                  </Col>
                  <Col span={12}>
                    <Statistic title="原始一致率"
                      value={a.agreement == null ? "—" : `${Math.round(a.agreement * 100)}%`} />
                  </Col>
                </Row>
                <Descriptions size="small" column={1} style={{ marginTop: 12 }}>
                  <Descriptions.Item label="样本数">{a.n_samples ?? 0}</Descriptions.Item>
                  {a.revoked_reason && (
                    <Descriptions.Item label="撤销原因">
                      <span style={{ color: "#cf1322" }}>{a.revoked_reason}</span>
                    </Descriptions.Item>
                  )}
                </Descriptions>
              </Card>
            </Col>
          ))}
        </Row>
      )}
    </div>
  );
}
