import React, { createContext, useContext, useEffect, useState } from "react";
import { Tooltip, Space } from "antd";
import { QuestionCircleOutlined } from "@ant-design/icons";
import { getGlossary } from "./api";

const GlossaryCtx = createContext({});

// Fallback so UI is readable even if /api/glossary is slow/unavailable.
const FALLBACK = {
  capability: { label: "能力分", hint: "这道题它做得多好,0–100 分,越高越强。" },
  honesty: { label: "诚实度", hint: "它说『做完了』是不是真做完了。1=谎报,5=老实。独立于能力分。" },
  gate: { label: "能否参赛", hint: "这道题的环境它够不够得着。够不着就不参与公平对比,不会被冤枉打 0 分。" },
  objective_ratio: { label: "硬性完成度", hint: "靠末态事实查到的完成比例,不看它自己怎么说。" },
  disagreement: { label: "评委分歧大", hint: "三个 AI 评委打分差太多,这条需要人复核。" },
  defects: { label: "评委挑出的毛病", hint: "评审面板指出的实质缺陷。" },
  cost: { label: "成本", hint: "花了多少 token / 调用几次 / 折算多少钱,要和『是否真完成』一起看。" },
  kappa: { label: "AI评委可信度", hint: "AI 评委和人工标准答案的一致率,够高才被授权自动打分。" },
};

export function GlossaryProvider({ children }) {
  const [g, setG] = useState(FALLBACK);
  useEffect(() => {
    getGlossary()
      .then((data) => setG({ ...FALLBACK, ...data }))
      .catch(() => {});
  }, []);
  return <GlossaryCtx.Provider value={g}>{children}</GlossaryCtx.Provider>;
}

export function useGlossary() {
  return useContext(GlossaryCtx);
}

// <Term name="capability"/> -> 中文 label + ⓘ tooltip(hint)
export function Term({ name, label }) {
  const g = useGlossary();
  const entry = g[name] || {};
  const text = label || entry.label || name;
  return (
    <Space size={4}>
      <span>{text}</span>
      {entry.hint ? (
        <Tooltip title={entry.hint}>
          <QuestionCircleOutlined style={{ color: "#bfbfbf", cursor: "help" }} />
        </Tooltip>
      ) : null}
    </Space>
  );
}

// Just the hint icon (for inline use next to a custom label).
export function InfoTip({ name, title }) {
  const g = useGlossary();
  const t = title || (g[name] || {}).hint;
  if (!t) return null;
  return (
    <Tooltip title={t}>
      <QuestionCircleOutlined style={{ color: "#bfbfbf", cursor: "help", marginLeft: 4 }} />
    </Tooltip>
  );
}
