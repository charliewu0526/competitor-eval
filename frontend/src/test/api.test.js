import { describe, it, expect, beforeEach, vi } from "vitest";
import api, { setAuthToken } from "../api";

// 直接驱动 axios 实例的拦截器,不打真网络:mock adapter 回显请求/伪造响应。

describe("api 请求拦截器:注入 Bearer token", () => {
  beforeEach(() => setAuthToken(null));

  it("有 token 时注入 Authorization 头", async () => {
    setAuthToken("tok-abc");
    api.defaults.adapter = async (config) => ({
      data: { seenAuth: config.headers.Authorization },
      status: 200, statusText: "OK", headers: {}, config,
    });
    const r = await api.get("/whatever");
    expect(r.data.seenAuth).toBe("Bearer tok-abc");
  });

  it("无 token 时不带 Authorization 头", async () => {
    api.defaults.adapter = async (config) => ({
      data: { seenAuth: config.headers.Authorization || null },
      status: 200, statusText: "OK", headers: {}, config,
    });
    const r = await api.get("/whatever");
    expect(r.data.seenAuth).toBeNull();
  });
});

describe("api 响应拦截器:人话错误 + 401 登出回调", () => {
  beforeEach(() => setAuthToken(null));

  function failWith(status, data) {
    api.defaults.adapter = async (config) => {
      const err = new Error("http");
      err.config = config;
      err.response = { status, data, headers: {}, config, statusText: "" };
      throw err;
    };
  }

  it("403 字符串 detail 原样透传为 userMessage", async () => {
    failWith(403, { detail: "角色 匿名 无权执行 'review'" });
    await expect(api.get("/x")).rejects.toMatchObject({
      userMessage: "角色 匿名 无权执行 'review'",
    });
  });

  it("403 无 detail 时给出人话兜底", async () => {
    failWith(403, {});
    await expect(api.get("/x")).rejects.toMatchObject({
      userMessage: "你的角色没有权限执行这个操作,请联系 PM。",
    });
  });

  it("422 校验数组被拼成可读消息", async () => {
    failWith(422, { detail: [{ msg: "Field required" }, { msg: "bad" }] });
    await expect(api.get("/x")).rejects.toMatchObject({
      userMessage: "Field required; bad",
    });
  });

  it("无响应(网络断)给出后端没连上提示", async () => {
    api.defaults.adapter = async () => { throw new Error("Network Error"); };
    await expect(api.get("/x")).rejects.toMatchObject({
      userMessage: "后端没连上,请确认服务在运行(board/backend.log)。",
    });
  });

  it("401 触发全局登出回调", async () => {
    const onUnauth = vi.fn();
    api.__onUnauthorized = onUnauth;
    failWith(401, { detail: "未登录" });
    await expect(api.get("/x")).rejects.toBeTruthy();
    expect(onUnauth).toHaveBeenCalledTimes(1);
    api.__onUnauthorized = null;
  });
});
