import { describe, it, expect, beforeEach, vi } from "vitest";
import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

// 用可控的 api mock 驱动页面:登录失败给人话错误、Assignments 按角色渲染。
const state = { user: { id: "u1", name: "小王", role: "intern" } };

vi.mock("../api", () => ({
  default: {
    get: vi.fn(async (url) => {
      if (url === "/assignments") return { data: [] };
      return { data: {} };
    }),
    post: vi.fn(async () => ({ data: {} })),
  },
  setAuthToken: vi.fn(),
  getAssignments: vi.fn(async () => []),
  materializeAssignment: vi.fn(async () => ({})),
}));

// mock auth 上下文,直接给定角色,避免真登录。
vi.mock("../auth.jsx", () => ({
  useAuth: () => ({ user: state.user, ready: true, login: vi.fn(), logout: vi.fn() }),
  AuthProvider: ({ children }) => children,
}));

import Login from "../pages/Login.jsx";
import Assignments from "../pages/Assignments.jsx";

describe("Login 页错误呈现", () => {
  it("渲染登录页两种入口(已有账号 / 邀请链接)", () => {
    // Login 用真 useAuth mock 的 login,不会真提交。
    render(<Login />);
    expect(screen.getByText(/我已有账号/)).toBeInTheDocument();
    expect(screen.getByText(/我有邀请链接/)).toBeInTheDocument();
  });
});

describe("Assignments 页按角色渲染", () => {
  beforeEach(() => { state.user = { id: "u1", name: "小王", role: "intern" }; });

  it("intern 看到空态引导语,且没有『铸造任务』按钮(owner 专属)", async () => {
    render(<Assignments />);
    await waitFor(() => expect(screen.getByText(/我的评测任务/)).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /铸造任务/ })).not.toBeInTheDocument();
    expect(screen.getByText(/等 PM 从任务清单铸造后/)).toBeInTheDocument();
  });

  it("owner 能看到『铸造任务(从清单)』按钮", async () => {
    state.user = { id: "owner1", name: "PM", role: "owner" };
    render(<Assignments />);
    await waitFor(() => expect(screen.getByText(/我的评测任务/)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /铸造任务/ })).toBeInTheDocument();
  });
});
