import { describe, it, expect, beforeEach, vi } from "vitest";
import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

// mock api 模块:登录/注册/请求走桩,不打网络。
vi.mock("../api", () => {
  const store = { token: null };
  return {
    default: {
      get: vi.fn(async (url) => {
        if (url === "/me") {
          if (!store.token) { const e = new Error("401"); e.response = { status: 401 }; throw e; }
          return { data: { id: "owner1", name: "PM", role: "owner" } };
        }
        return { data: {} };
      }),
      post: vi.fn(async (url, body) => {
        if (url === "/login") {
          if (body.user_id === "owner1") { store.token = "sess-1"; return { data: { session_token: "sess-1" } }; }
          const e = new Error("401"); e.response = { status: 401 }; e.userMessage = "用户不存在"; throw e;
        }
        if (url === "/logout") { store.token = null; return { data: { ok: true } }; }
        return { data: {} };
      }),
    },
    setAuthToken: vi.fn((t) => { store.token = t; }),
    __store: store,
  };
});

import { AuthProvider, useAuth } from "../auth.jsx";

// 一个把 auth 状态暴露到 DOM 的探针组件。
function Probe() {
  const { user, ready, login, logout } = useAuth();
  return (
    <div>
      <span data-testid="ready">{String(ready)}</span>
      <span data-testid="user">{user ? `${user.name}:${user.role}` : "anon"}</span>
      <button onClick={() => login("owner1")}>login-ok</button>
      <button onClick={() => login("nobody").catch(() => {})}>login-bad</button>
      <button onClick={() => logout()}>logout</button>
    </div>
  );
}

describe("AuthProvider 登录流程", () => {
  beforeEach(() => { localStorage.clear(); });

  it("初始未登录:ready=true 且 user=anon", async () => {
    render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId("ready").textContent).toBe("true"));
    expect(screen.getByTestId("user").textContent).toBe("anon");
  });

  it("owner1 登录后 user 变为 PM:owner 并写入 localStorage", async () => {
    render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId("ready").textContent).toBe("true"));
    fireEvent.click(screen.getByText("login-ok"));
    await waitFor(() => expect(screen.getByTestId("user").textContent).toBe("PM:owner"));
    expect(localStorage.getItem("ce_session_token")).toBe("sess-1");
  });

  it("登出后回到 anon 并清 localStorage", async () => {
    render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId("ready").textContent).toBe("true"));
    fireEvent.click(screen.getByText("login-ok"));
    await waitFor(() => expect(screen.getByTestId("user").textContent).toBe("PM:owner"));
    fireEvent.click(screen.getByText("logout"));
    await waitFor(() => expect(screen.getByTestId("user").textContent).toBe("anon"));
    expect(localStorage.getItem("ce_session_token")).toBeNull();
  });
});
