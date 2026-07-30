import { describe, it, expect, beforeEach, vi } from "vitest";
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";

// 角色收敛回归: intern 不该看到 reviewer/PM 专属的复核/定判按钮(否则点了静默 403,
// 是真实体验 bug — 首次真点前端时发现)。这里用 mock 分别以 intern / reviewer 渲染
// SpotCheck / Findings / Probes, 断言按钮的显隐。
const state = { user: { id: "u1", name: "小王", role: "intern" } };

vi.mock("../api", () => ({
  default: { get: vi.fn(async () => ({ data: {} })), post: vi.fn(async () => ({ data: {} })) },
  setAuthToken: vi.fn(),
  // SpotCheck: 一条待抽查项
  getSpotcheck: vi.fn(async () => [
    { id: 1, stratum: "high-risk", product: "open_interpreter",
      task_id: "T1", run_idx: 1, reason: "诚实存疑 H1=1" },
  ]),
  rebuildSpotcheck: vi.fn(async () => ({ enqueued: 1 })),
  spotcheckDetail: vi.fn(async () => ({
    objective: { passed: 2, total: 4, failed: 2, failed_primary: false, evidence_source: "artifact" },
    score: { sample_score: 0.8, h1_honesty: 3, subjective: { S1: 4 }, defects: [], disagreement: [] },
    run: { cost_usd: 0.1, cost_model_calls: 5 },
    artifacts: [], expected: "",
  })),
  artifactUrl: (id, rel) => `/api/spotcheck/${id}/artifact/${rel}`,
  reviewVerdict: vi.fn(async () => ({})),
  markSuspect: vi.fn(async () => ({})),
  excludeRun: vi.fn(async () => ({})),
  clearReview: vi.fn(async () => ({})),
  overrideScore: vi.fn(async () => ({})),
  // Findings: 一条未定判
  getFindings: vi.fn(async () => [
    { id: 1, suspected_category: "honesty-alert", subject: "open_interpreter",
      task_id: "T1", phenomenon: "自称完成但末态失败", evidence: [] },
  ]),
  // Probes: 一条未定判
  getProbes: vi.fn(async () => [
    { id: 2, subject: "open_interpreter", task_id: "PB-token-001",
      phenomenon: "省 token", evidence: [] },
  ]),
  getEnums: vi.fn(async () => ({
    product_judgment: ["必须补齐", "值得借鉴"],
    final_category: ["bug", "feature-gap"],
  })),
}));

vi.mock("../auth.jsx", () => ({
  useAuth: () => ({ user: state.user, ready: true, login: vi.fn(), logout: vi.fn() }),
  AuthProvider: ({ children }) => children,
}));

vi.mock("../glossary.jsx", () => ({
  InfoTip: () => null,
  GlossaryProvider: ({ children }) => children,
}));

import SpotCheck from "../pages/SpotCheck.jsx";
import Findings from "../pages/Findings.jsx";
import Probes from "../pages/Probes.jsx";

describe("角色收敛: 复核/定判按钮按角色显隐", () => {
  beforeEach(() => { state.user = { id: "u1", name: "小王", role: "intern" }; });

  it("SpotCheck: intern 看只读提示, 无复核按钮", async () => {
    render(<SpotCheck />);
    await waitFor(() => expect(screen.getByText(/抽查裁定由审核员\/PM 处理/)).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /有道理/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /重建抽查队列/ })).not.toBeInTheDocument();
  });

  it("SpotCheck: reviewer 能看到复核按钮", async () => {
    state.user = { id: "rv1", name: "审核员", role: "reviewer" };
    render(<SpotCheck />);
    await waitFor(() => expect(screen.getByRole("button", { name: /有道理/ })).toBeInTheDocument());
  });

  it("Findings: intern 看只读提示, 无保存按钮", async () => {
    render(<Findings />);
    await waitFor(() => expect(screen.getByText(/定判由审核员\/PM 处理/)).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /保存/ })).not.toBeInTheDocument();
  });

  it("Findings: reviewer 能看到保存按钮", async () => {
    state.user = { id: "rv1", name: "审核员", role: "reviewer" };
    render(<Findings />);
    await waitFor(() => expect(screen.getByRole("button", { name: /保存/ })).toBeInTheDocument());
  });

  it("Probes: intern 看只读提示, 无保存按钮", async () => {
    render(<Probes />);
    await waitFor(() => expect(screen.getByText(/定判由审核员\/PM 处理/)).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /保存/ })).not.toBeInTheDocument();
  });

  it("Probes: reviewer 能看到保存按钮", async () => {
    state.user = { id: "rv1", name: "审核员", role: "reviewer" };
    render(<Probes />);
    await waitFor(() => expect(screen.getByRole("button", { name: /保存/ })).toBeInTheDocument());
  });
});
