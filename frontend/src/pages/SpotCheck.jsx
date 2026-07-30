import React, { useEffect, useState } from "react";
import {
  Typography, Card, Tag, Spin, Alert, Empty, Button, Space, Input, message,
  Collapse, Descriptions, List, InputNumber, Divider, Statistic, Row, Col,
} from "antd";
import {
  ReloadOutlined, CheckCircleOutlined, WarningOutlined, StopOutlined,
  QuestionCircleOutlined, EditOutlined, FileTextOutlined, DownloadOutlined,
} from "@ant-design/icons";
import {
  getSpotcheck, rebuildSpotcheck, spotcheckDetail, artifactUrl,
  reviewVerdict, markSuspect, excludeRun, clearReview, overrideScore,
} from "../api";
import { InfoTip } from "../glossary.jsx";
import { useAuth } from "../auth.jsx";

const STRATUM = {
  "high-risk": { label: "🔴 高风险(必查 100%)", color: "red" },
  "contradiction": { label: "🟠 结论矛盾(必查 100%)", color: "orange" },
  "big-gap": { label: "🟣 大差距(必查 100%)", color: "purple" },
  "normal": { label: "🟢 普通(随机抽 10%)", color: "green" },
};

const REVIEW_STATUS = {
  suspect: { label: "存疑", color: "gold" },
  excluded: { label: "已排除出榜", color: "red" },
  overridden: { label: "已改分", color: "blue" },
};

function stratumTag(s) {
  const t = STRATUM[s] || { label: s, color: "default" };
  return <Tag color={t.color}>{t.label}</Tag>;
}

function fmtUsd(v) {
  return v == null ? "未采集" : `$${Number(v).toFixed(4)}`;
}

// 展开区: 一次运行的完整完成情况(客观断言逐条 + 五维 + 成本 + 产物文件)。
function CompletionDetail({ id }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    spotcheckDetail(id).then(setD).catch((e) => setErr(e.userMessage || String(e)));
  }, [id]);
  if (err) return <Alert type="error" showIcon message="加载完成情况失败" description={err} />;
  if (!d) return <Spin style={{ display: "block", margin: "20px auto" }} />;

  const obj = d.objective || {};
  const score = d.score || {};
  const run = d.run || {};
  const subjective = score.subjective || null;
  const defects = score.defects || [];
  const disagreement = score.disagreement || [];

  return (
    <div>
      <Divider orientation="left" style={{ marginTop: 0 }}>
        客观完成度 <InfoTip title="不靠 AI,看末态事实硬判:硬性断言过了几条、有没有关键项(primary)没做到。这是核实机器判分对不对的头号依据。" />
      </Divider>
      <Row gutter={16}>
        <Col><Statistic title="硬性断言通过" value={obj.passed ?? "?"} suffix={`/ ${obj.total ?? "?"}`} /></Col>
        <Col><Statistic title="失败条数" value={obj.failed ?? "?"}
          valueStyle={{ color: (obj.failed > 0) ? "#cf1322" : "#3f8600" }} /></Col>
        <Col><Statistic title="关键项失败" value={obj.failed_primary ? "有" : "无"}
          valueStyle={{ color: obj.failed_primary ? "#cf1322" : "#3f8600" }} /></Col>
        <Col><Statistic title="证据来源" value={obj.evidence_source || "unavailable"} /></Col>
      </Row>

      <Divider orientation="left">主观五维(双 AI 盲评) <InfoTip title="S1质量/S2效率/S3可靠性/S4自主性/S5体验,两家族 AI 背靠背盲打取中位。标红维度=两家分歧≥2。" /></Divider>
      {subjective ? (
        <Space wrap>
          {Object.entries(subjective).map(([dim, v]) => (
            <Tag key={dim} color={disagreement.includes(dim) ? "red" : "blue"}>
              {dim}: {v}{disagreement.includes(dim) ? " ⚠分歧" : ""}
            </Tag>
          ))}
          <span style={{ color: "#8c8c8c" }}>能力分 {score.sample_score ?? "—"} · 诚实度 H1 {score.h1_honesty ?? "—"}</span>
        </Space>
      ) : <span style={{ color: "#bfbfbf" }}>无主观打分(可能未评分/够不到)</span>}

      {defects.length > 0 && (
        <>
          <Divider orientation="left">评委挑出的毛病</Divider>
          <List size="small" dataSource={defects}
            renderItem={(x) => <List.Item>{typeof x === "string" ? x : JSON.stringify(x)}</List.Item>} />
        </>
      )}

      <Divider orientation="left">资源效率 <InfoTip title="token 用量 + 调用轮数 + 折算成本,和是否真完成一起看。成本按日志包真实来源折算,拿不到时如实标未采集。" /></Divider>
      <Space wrap>
        <Tag>成本 {fmtUsd(run.cost_usd)}</Tag>
        <Tag>调用 {run.cost_model_calls ?? "?"} 轮</Tag>
        <Tag>输入 {run.cost_input_tokens ?? "?"} tok</Tag>
        <Tag>输出 {run.cost_output_tokens ?? "?"} tok</Tag>
        <Tag>来源 {run.cost_source || "unavailable"}</Tag>
      </Space>

      <Divider orientation="left">AI 实际交付的产物 <InfoTip title="AI 这次跑完真正交付了哪些文件(截图/导出文件/对话记录)。点击可预览下载,亲眼核对。" /></Divider>
      {d.artifacts && d.artifacts.length > 0 ? (
        <List size="small" dataSource={d.artifacts}
          renderItem={(f) => (
            <List.Item actions={[
              <a key="dl" href={artifactUrl(id, f.rel)} target="_blank" rel="noreferrer">
                <DownloadOutlined /> 打开
              </a>,
            ]}>
              <Space><FileTextOutlined /> {f.rel}
                <span style={{ color: "#bfbfbf" }}>{(f.size / 1024).toFixed(1)} KB</span></Space>
            </List.Item>
          )} />
      ) : <span style={{ color: "#bfbfbf" }}>没有可下载的产物目录(该提交未上传原始产物)</span>}

      {d.expected && (
        <>
          <Divider orientation="left">本该做到什么(判定标准原文)</Divider>
          <pre style={{ whiteSpace: "pre-wrap", background: "#fafafa", padding: 12,
            borderRadius: 6, maxHeight: 200, overflow: "auto", fontSize: 12 }}>{d.expected}</pre>
        </>
      )}

      {score.human_review_status && (
        <Alert style={{ marginTop: 12 }} type="info" showIcon
          message={`当前处置: ${(REVIEW_STATUS[score.human_review_status] || {}).label || score.human_review_status}`}
          description={<>
            {score.override_sample_score != null && <div>改分后能力分: {score.override_sample_score}</div>}
            {score.review_note && <div>备注: {score.review_note}</div>}
            {score.reviewed_by && <div>处置人: {score.reviewed_by}</div>}
          </>} />
      )}
    </div>
  );
}

function ItemCard({ it, onDone, canReview, isOwner }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [overrideVal, setOverrideVal] = useState(null);
  const [overrideH1, setOverrideH1] = useState(null);

  const run = async (fn, okMsg) => {
    setBusy(true);
    try { await fn(); message.success(okMsg); onDone && onDone(); }
    catch (e) { message.error(e.userMessage || "操作失败: " + String(e)); }
    finally { setBusy(false); }
  };

  const rs = it.human_review_status;

  return (
    <Card style={{ marginBottom: 12 }}
      title={<Space wrap>{stratumTag(it.stratum)}<b>{it.product}</b>
        <span style={{ color: "#8c8c8c", fontWeight: 400 }}>@ {it.task_id} · 第 {it.run_idx} 次</span>
        {rs && <Tag color={(REVIEW_STATUS[rs] || {}).color}>{(REVIEW_STATUS[rs] || {}).label || rs}</Tag>}
      </Space>}>
      <p style={{ marginTop: 0 }}>
        <b>为什么进队列:</b> <span style={{ color: "#595959" }}>{it.reason}</span>
      </p>

      <Collapse ghost items={[{
        key: "detail",
        label: <span><FileTextOutlined /> 展开看这次运行的完整完成情况(断言/五维/成本/产物)</span>,
        children: <CompletionDetail id={it.id} />,
      }]} />

      {canReview ? (
        <>
          <Space.Compact style={{ width: "100%", margin: "12px 0" }}>
            <Input placeholder="处置备注(可选,写给后来人看)" value={note}
              onChange={(e) => setNote(e.target.value)} />
          </Space.Compact>
          <Space wrap>
            <Button icon={<CheckCircleOutlined />} loading={busy}
              onClick={() => run(() => reviewVerdict(it.id, "reasonable", note), "已记「有道理」")}>
              有道理(机器判对了)
            </Button>
            <Button icon={<QuestionCircleOutlined />} loading={busy}
              onClick={() => run(() => markSuspect(it.id, note), "已标「存疑」(保留在榜,打标提示)")}>
              标记存疑
            </Button>
            <Button danger icon={<StopOutlined />} loading={busy}
              onClick={() => run(() => excludeRun(it.id, note), "已「排除出榜」(不进公平排名,记录留存)")}>
              排除出榜
            </Button>
            <Button icon={<WarningOutlined />} loading={busy}
              onClick={() => run(() => reviewVerdict(it.id, "problematic", note), "已记「有问题」(可由 PM 触发重校准)")}>
              有问题
            </Button>
            {rs && (
              <Button icon={<ReloadOutlined />} loading={busy}
                onClick={() => run(() => clearReview(it.id), "已撤销处置,恢复机器原判")}>
                撤销处置
              </Button>
            )}
          </Space>

          {isOwner && (
            <>
              <Divider style={{ margin: "12px 0" }} />
              <Space wrap align="center">
                <span><EditOutlined /> <b>PM 改分</b> <InfoTip title="人工覆写能力分/诚实度,机器原分留痕,榜单优先用改后分。最重的干预,仅 PM 可用。" /></span>
                <span>能力分[0-1]:</span>
                <InputNumber min={0} max={1} step={0.05} value={overrideVal}
                  onChange={setOverrideVal} style={{ width: 90 }} />
                <span>诚实度[1-5]:</span>
                <InputNumber min={1} max={5} step={1} value={overrideH1}
                  onChange={setOverrideH1} style={{ width: 80 }} />
                <Button type="primary" ghost loading={busy}
                  disabled={overrideVal == null && overrideH1 == null}
                  onClick={() => run(() => overrideScore(it.id,
                    { sample_score: overrideVal, h1_honesty: overrideH1, note: note || null }),
                    "已改分,榜单将用新分")}>
                  改分并回写榜单
                </Button>
              </Space>
            </>
          )}
        </>
      ) : (
        <Tag color="default" style={{ marginTop: 12 }}>抽查裁定由审核员/PM 处理(你是实习生,只读)</Tag>
      )}
    </Card>
  );
}

export default function SpotCheck() {
  const { user } = useAuth();
  const canReview = user?.role === "reviewer" || user?.role === "owner";
  const isOwner = user?.role === "owner";
  const [rows, setRows] = useState(null);
  const [err, setErr] = useState(null);
  const [rebuilding, setRebuilding] = useState(false);

  const load = () => getSpotcheck("pending").then(setRows).catch((e) => setErr(e.userMessage || String(e)));
  useEffect(() => { load(); }, []);

  const rebuild = async () => {
    setRebuilding(true);
    try {
      const r = await rebuildSpotcheck();
      message.success(`已重建队列,共 ${r.enqueued ?? "?"} 项`);
      load();
    } catch (e) { message.error(e.userMessage || "重建失败:" + String(e)); }
    finally { setRebuilding(false); }
  };

  if (err) return <Alert type="error" message="后端没连上" description={err} showIcon />;

  return (
    <div>
      <Typography.Title level={3} className="page-title">抽查队列</Typography.Title>
      <p className="page-sub">
        主流程不等人签字就入库,人只做<b>事后分层抽查</b> <InfoTip title="普通任务随机抽 10%,矛盾/高风险/大差距 100% 必查——精力花在刀刃上。" />:
        普通随机 10%、矛盾/高风险/大差距 100%。展开每项看完整完成情况(断言/五维/成本/产物),再下裁决:
        有道理 / 存疑 / 排除出榜 / 有问题;PM 还可人工改分回写榜单。
      </p>

      {isOwner && (
        <Button type="primary" icon={<ReloadOutlined />} loading={rebuilding}
          onClick={rebuild} style={{ marginBottom: 16 }}>
          重建抽查队列(扫库分层采样)
        </Button>
      )}

      {!rows ? <Spin size="large" style={{ display: "block", margin: "40px auto" }} />
        : rows.length === 0 ? (
          <Card><Empty description="队列为空。pipeline 落库后点上面「重建抽查队列」生成分层抽查项。" /></Card>
        ) : (
          <>
            <p style={{ color: "#8c8c8c" }}>待抽查 {rows.length} 项(高风险/矛盾/大差距排在前):</p>
            {rows.map((it) => <ItemCard key={it.id} it={it} onDone={load}
              canReview={canReview} isOwner={isOwner} />)}
          </>
        )}
    </div>
  );
}
