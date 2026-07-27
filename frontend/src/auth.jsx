import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import api, { setAuthToken } from "./api";

// 会话持久化 key。存 session_token + 当前用户(id/name/role)。
const TOK_KEY = "ce_session_token";
const USER_KEY = "ce_user";

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  const [token, setTok] = useState(() => localStorage.getItem(TOK_KEY) || null);
  const [user, setUser] = useState(() => {
    try { return JSON.parse(localStorage.getItem(USER_KEY) || "null"); }
    catch { return null; }
  });
  const [ready, setReady] = useState(false);

  // 令 axios 始终带上当前 token。
  useEffect(() => { setAuthToken(token); }, [token]);

  const persist = useCallback((tok, u) => {
    if (tok) localStorage.setItem(TOK_KEY, tok); else localStorage.removeItem(TOK_KEY);
    if (u) localStorage.setItem(USER_KEY, JSON.stringify(u)); else localStorage.removeItem(USER_KEY);
    setTok(tok || null);
    setUser(u || null);
    setAuthToken(tok || null);
  }, []);

  // 启动时若已有 token,校验一次 /me;失效则清会话。
  useEffect(() => {
    let alive = true;
    (async () => {
      if (token) {
        try {
          const me = await api.get("/me").then((r) => r.data);
          if (alive) { setUser(me); localStorage.setItem(USER_KEY, JSON.stringify(me)); }
        } catch {
          if (alive) persist(null, null);
        }
      }
      if (alive) setReady(true);
    })();
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 用 user_id 登录(已注册用户换发会话)。
  const login = useCallback(async (userId) => {
    const { session_token } = await api.post("/login", { user_id: userId }).then((r) => r.data);
    setAuthToken(session_token);
    const me = await api.get("/me").then((r) => r.data);
    persist(session_token, me);
    return me;
  }, [persist]);

  // 用邀请 token 自注册(默认 intern),注册即登录。
  const register = useCallback(async (inviteToken, name) => {
    const res = await api.post("/register", { invite_token: inviteToken, name: name || null })
      .then((r) => r.data);
    persist(res.session_token, res.user);
    return res.user;
  }, [persist]);

  const logout = useCallback(async () => {
    try { await api.post("/logout"); } catch { /* 忽略:本地清即可 */ }
    persist(null, null);
  }, [persist]);

  // 供响应拦截器在 401 时强制登出(见 api.js 注册的回调)。
  useEffect(() => {
    api.__onUnauthorized = () => persist(null, null);
    return () => { api.__onUnauthorized = null; };
  }, [persist]);

  return (
    <AuthCtx.Provider value={{ token, user, ready, login, register, logout }}>
      {children}
    </AuthCtx.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error("useAuth 必须在 AuthProvider 内使用");
  return ctx;
}
