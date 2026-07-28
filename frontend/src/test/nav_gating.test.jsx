import { describe, it, expect, beforeEach, vi } from "vitest";
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// 分级导航回归(charlie 拍板的三档):
//   intern 实习生(6): 总览/任务清单/我的任务/方法沉淀/差距报告/排行榜
//   reviewer 审核员(+7): 分维度/按题矩阵/评分详情/成本/发现看板/能力专项/抽查队列
//   owner PM(+1): 黄金集授权
// 验两层收敛: (1) 侧边栏只显示 <= 自己角色的页; (2) 路由守卫:直接进无权 path 被拦。
const state = { user: { id: "u1", name: "小王", role: "intern" } };

vi.mock("../api", () => ({
  default: { get: vi.fn(async () => ({ data: {} })), post: vi.fn(async () => ({ data: {} })) },
  setAuthToken: vi.fn(),
}));

vi.mock("../auth.jsx", () => ({
  useAuth: () => ({ user: state.user, ready: true, login: vi.fn(), register: vi.fn(), logout: vi.fn() }),
  AuthProvider: ({ children }) => children,
}));

// 各页组件桩:只渲染一个可识别标记,避免真页面拉数据。
// 注意 vi.mock 被提升到文件顶部,工厂里不能引用循环变量,只能逐个显式声明。
vi.mock("../glossary.jsx", () => ({
  InfoTip: () => null, GlossaryProvider: ({ children }) => children,
}));
vi.mock("../pages/Dashboard.jsx", () => ({ default: () => <div data-testid="page-Dashboard">Dashboard</div> }));
vi.mock("../pages/TaskCatalog.jsx", () => ({ default: () => <div data-testid="page-TaskCatalog">TaskCatalog</div> }));
vi.mock("../pages/Assignments.jsx", () => ({ default: () => <div data-testid="page-Assignments">Assignments</div> }));
vi.mock("../pages/Methods.jsx", () => ({ default: () => <div data-testid="page-Methods">Methods</div> }));
vi.mock("../pages/Leaderboard.jsx", () => ({ default: () => <div data-testid="page-Leaderboard">Leaderboard</div> }));
vi.mock("../pages/DomainBoard.jsx", () => ({ default: () => <div data-testid="page-DomainBoard">DomainBoard</div> }));
vi.mock("../pages/Matrix.jsx", () => ({ default: () => <div data-testid="page-Matrix">Matrix</div> }));
vi.mock("../pages/ScoreDetail.jsx", () => ({ default: () => <div data-testid="page-ScoreDetail">ScoreDetail</div> }));
vi.mock("../pages/Cost.jsx", () => ({ default: () => <div data-testid="page-Cost">Cost</div> }));
vi.mock("../pages/Findings.jsx", () => ({ default: () => <div data-testid="page-Findings">Findings</div> }));
vi.mock("../pages/GapReport.jsx", () => ({ default: () => <div data-testid="page-GapReport">GapReport</div> }));
vi.mock("../pages/Probes.jsx", () => ({ default: () => <div data-testid="page-Probes">Probes</div> }));
vi.mock("../pages/SpotCheck.jsx", () => ({ default: () => <div data-testid="page-SpotCheck">SpotCheck</div> }));
vi.mock("../pages/Authorizations.jsx", () => ({ default: () => <div data-testid="page-Authorizations">Authorizations</div> }));
vi.mock("../pages/Users.jsx", () => ({ default: () => <div data-testid="page-Users">Users</div> }));

import App from "../App.jsx";

const INTERN_ONLY = ["总览", "任务清单", "我的任务", "方法沉淀", "差距报告", "排行榜"];
const REVIEWER_EXTRA = ["分维度榜单", "按题矩阵", "评分详情", "成本面板", "发现看板", "能力专项", "抽查队列"];
const OWNER_EXTRA = ["黄金集授权", "用户管理"];

function renderAt(path) {
  return render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>);
}

describe("分级导航:侧边栏按角色过滤", () => {
  beforeEach(() => { state.user = { id: "u1", name: "小王", role: "intern" }; });

  it("intern 只看到 6 个菜单项,治理/分析页全不可见", async () => {
    renderAt("/");
    await waitFor(() => expect(screen.getAllByText("总览").length).toBeGreaterThan(0));
    for (const label of INTERN_ONLY) expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    for (const label of [...REVIEWER_EXTRA, ...OWNER_EXTRA]) {
      expect(screen.queryByText(label)).toBeNull();
    }
  });

  it("reviewer 看到 intern + 审核分析页,但看不到黄金集授权", async () => {
    state.user = { id: "rv1", name: "审核员", role: "reviewer" };
    renderAt("/");
    await waitFor(() => expect(screen.getAllByText("抽查队列").length).toBeGreaterThan(0));
    for (const label of [...INTERN_ONLY, ...REVIEWER_EXTRA]) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
    for (const label of OWNER_EXTRA) expect(screen.queryByText(label)).toBeNull();
  });

  it("owner 看到全部 15 个菜单项", async () => {
    state.user = { id: "owner1", name: "PM", role: "owner" };
    renderAt("/");
    await waitFor(() => expect(screen.getAllByText("用户管理").length).toBeGreaterThan(0));
    for (const label of [...INTERN_ONLY, ...REVIEWER_EXTRA, ...OWNER_EXTRA]) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
  });
});

describe("分级导航:路由守卫拦截直接进入", () => {
  beforeEach(() => { state.user = { id: "u1", name: "小王", role: "intern" }; });

  it("intern 直接进 /authorizations 被拦(显示 403 拦截页,不渲染真页面)", async () => {
    renderAt("/authorizations");
    await waitFor(() => expect(screen.getByText(/这个页面不对你开放/)).toBeInTheDocument());
    expect(screen.queryByTestId("page-Authorizations")).toBeNull();
  });

  it("intern 直接进 /cost(审核员页)被拦", async () => {
    renderAt("/cost");
    await waitFor(() => expect(screen.getByText(/这个页面不对你开放/)).toBeInTheDocument());
    expect(screen.queryByTestId("page-Cost")).toBeNull();
  });

  it("intern 进自己有权的 /gap-report 正常渲染", async () => {
    renderAt("/gap-report");
    await waitFor(() => expect(screen.getByTestId("page-GapReport")).toBeInTheDocument());
  });

  it("reviewer 进 /cost 正常,进 /authorizations 被拦", async () => {
    state.user = { id: "rv1", name: "审核员", role: "reviewer" };
    const { unmount } = renderAt("/cost");
    await waitFor(() => expect(screen.getByTestId("page-Cost")).toBeInTheDocument());
    unmount();
    renderAt("/authorizations");
    await waitFor(() => expect(screen.getByText(/这个页面不对你开放/)).toBeInTheDocument());
  });
});
