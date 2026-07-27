import axios from "axios";

const api = axios.create({ baseURL: "/api", timeout: 15000 });

// --- 鉴权:注入 Bearer token + 统一错误消息 ---------------------------
let _authToken = null;
export function setAuthToken(tok) { _authToken = tok || null; }

api.interceptors.request.use((config) => {
  if (_authToken) {
    config.headers = config.headers || {};
    config.headers.Authorization = `Bearer ${_authToken}`;
  }
  return config;
});

// 把后端错误翻成人话:优先用后端 detail(可能是字符串或校验数组),
// 401 顺带触发全局登出回调(AuthProvider 注册)。err.userMessage 供 UI 直接显示。
function humanError(err) {
  const resp = err && err.response;
  if (!resp) return "后端没连上,请确认服务在运行(board/backend.log)。";
  const status = resp.status;
  const detail = resp.data && resp.data.detail;
  let msg = null;
  if (typeof detail === "string") msg = detail;
  else if (Array.isArray(detail) && detail.length) {
    msg = detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
  }
  if (status === 401) return msg || "请先登录,或会话已失效,请重新登录。";
  if (status === 403) return msg || "你的角色没有权限执行这个操作,请联系 PM。";
  if (status === 404) return msg || "找不到对应的数据。";
  if (status === 409) return msg || "操作与当前状态冲突(可能已被他人处理)。";
  if (status === 422) return msg || "提交的内容不完整或格式不对。";
  return msg || `请求失败(HTTP ${status})。`;
}

api.interceptors.response.use(
  (r) => r,
  (err) => {
    err.userMessage = humanError(err);
    if (err.response && err.response.status === 401 && typeof api.__onUnauthorized === "function") {
      api.__onUnauthorized();
    }
    return Promise.reject(err);
  }
);

export const getOverview = () => api.get("/overview").then((r) => r.data);
export const getGlossary = () => api.get("/glossary").then((r) => r.data);
export const getLeaderboard = (baseline = "vio") =>
  api.get("/leaderboard", { params: { baseline } }).then((r) => r.data);
export const getDomainBoard = (baseline = "vio", windowDays) =>
  api.get("/domain-board", {
    params: { baseline, ...(windowDays != null ? { window_days: windowDays } : {}) },
  }).then((r) => r.data);
export const getScores = () => api.get("/scores").then((r) => r.data);
export const getScore = (task, product) =>
  api.get(`/score/${encodeURIComponent(task)}/${encodeURIComponent(product)}`).then((r) => r.data);
export const getCost = () => api.get("/cost").then((r) => r.data);
export const getFindings = () => api.get("/findings").then((r) => r.data);
export const getProbes = () => api.get("/probes").then((r) => r.data);
export const getSpotcheck = (status) =>
  api.get("/spotcheck", { params: status ? { status } : {} }).then((r) => r.data);
export const getAuthorizations = () => api.get("/authorizations").then((r) => r.data);
export const getEnums = () => api.get("/enums").then((r) => r.data);
export const getCatalog = () => api.get("/catalog").then((r) => r.data);
export const getCatalogTask = (taskId) =>
  api.get(`/catalog/${encodeURIComponent(taskId)}`).then((r) => r.data);
export const getGapReportTasks = (baseline = "vio") =>
  api.get("/gap-report", { params: { baseline } }).then((r) => r.data);
export const getGapReport = (taskId, baseline = "vio") =>
  api.get(`/gap-report/${encodeURIComponent(taskId)}`, { params: { baseline } })
    .then((r) => r.data);

export const postJudgment = (id, body) =>
  api.post(`/findings/${id}/judgment`, body).then((r) => r.data);
export const rebuildSpotcheck = () =>
  api.post("/spotcheck/rebuild").then((r) => r.data);
export const postVerdict = (id, body) =>
  api.post(`/spotcheck/${id}/verdict`, body).then((r) => r.data);

export default api;
