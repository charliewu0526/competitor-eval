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
export const getGapReport = (taskId, baseline = "vio", attribution = false) =>
  api.get(`/gap-report/${encodeURIComponent(taskId)}`,
    // 归因调 Claude 最强模型读交付物, 单次可达 ~20s, 远超默认 15s 超时;
    // 带归因时放宽到 120s, 否则前端会误报「后端没连上」。
    { params: { baseline, attribution },
      timeout: attribution ? 120000 : 15000 })
    .then((r) => r.data);
// 自动闭环: 跑归因 -> 提炼一句话功能点 -> 自动落 draft 进方法沉淀。慢调用放宽超时。
export const synthesizeMethods = (taskId, baseline = "vio") =>
  api.post(`/gap-report/${encodeURIComponent(taskId)}/synthesize-methods`,
    null, { params: { baseline }, timeout: 180000 })
    .then((r) => r.data);

export const postJudgment = (id, body) =>
  api.post(`/findings/${id}/judgment`, body).then((r) => r.data);
export const rebuildSpotcheck = () =>
  api.post("/spotcheck/rebuild").then((r) => r.data);
export const postVerdict = (id, body) =>
  api.post(`/spotcheck/${id}/verdict`, body).then((r) => r.data);

// --- MR-6/7 实习生工作流:领题 / 提交 ---------------------------------
export const getAssignments = () => api.get("/assignments").then((r) => r.data);
export const materializeAssignment = (taskId) =>
  api.post("/assignments/materialize", { task_id: taskId }).then((r) => r.data);
// PRD story 8 自助领取。方案B: product 给出时只领这道题的这个产品(题×产品),
// 不同人可用各自账号领同题不同产品; 缺省回退整题领取(兼容)。
export const claimFromCatalog = (taskId, product) =>
  api.post(`/catalog/${encodeURIComponent(taskId)}/claim`,
    { task_id: taskId, product: product || null }).then((r) => r.data);

// 下载一道题的起始素材文件(远程实习生靠这个真拿到 input/ 里的文件)。
// 带 Bearer token 拉 blob, 触发浏览器下载。
export async function downloadTaskInput(taskId, relPath) {
  const resp = await api.get(
    `/catalog/${encodeURIComponent(taskId)}/input/${relPath.split("/").map(encodeURIComponent).join("/")}`,
    { responseType: "blob" });
  const url = URL.createObjectURL(resp.data);
  const a = document.createElement("a");
  a.href = url;
  a.download = relPath.split("/").pop();
  document.body.appendChild(a); a.click();
  a.remove(); URL.revokeObjectURL(url);
}
export const claimAssignment = (id) =>
  api.post(`/assignments/${encodeURIComponent(id)}/claim`).then((r) => r.data);
export const abandonAssignment = (id) =>
  api.post(`/assignments/${encodeURIComponent(id)}/abandon`).then((r) => r.data);
// 收口会同步触发整组盲评面板(真打多模型, 30-90s), 远超默认 15s 超时 ——
// 给这个慢端点单独放大到 180s, 否则前端会在评分完成前中断请求(走查发现的 UX bug)。
export const submitAssignment = (id) =>
  api.post(`/assignments/${encodeURIComponent(id)}/submit`, null,
    { timeout: 180000 }).then((r) => r.data);
export const getSubmissionProgress = (id) =>
  api.get(`/assignments/${encodeURIComponent(id)}/submissions`).then((r) => r.data);
// 提交一份产品交付(multipart:产物 + 日志包 + 元数据)。
export const postSubmission = (id, formData) =>
  api.post(`/assignments/${encodeURIComponent(id)}/submissions`, formData, {
    headers: { "Content-Type": "multipart/form-data" },
  }).then((r) => r.data);

// --- MR-4 用户管理:列用户 / 提升角色 / 签发邀请令牌 (owner 专属) --------
export const getUsers = () => api.get("/users").then((r) => r.data);
export const promoteUser = (userId, role) =>
  api.post(`/users/${encodeURIComponent(userId)}/role`, { role }).then((r) => r.data);
export const issueInvite = (note, ttlSeconds) =>
  api.post("/invites", {
    ...(note ? { note } : {}),
    ...(ttlSeconds != null ? { ttl_seconds: ttlSeconds } : {}),
  }).then((r) => r.data);

// --- MR-14 方法沉淀:初稿 → 把关 → 导出 -------------------------------
export const getMethods = (status) =>
  api.get("/methods", { params: status ? { status } : {} }).then((r) => r.data);
export const createMethod = (body) =>
  api.post("/methods", body).then((r) => r.data);
export const approveMethod = (id) =>
  api.post(`/methods/${id}/approve`).then((r) => r.data);
export const previewMethod = (id) =>
  api.get(`/methods/${id}/preview`).then((r) => r.data);
export const exportMethod = (id) =>
  api.post(`/methods/${id}/export`).then((r) => r.data);

// --- MR-B (#56) 用户反馈:提交(文字+截图,自动附日志)/ 我的状态 / owner 反馈台 ---
// 提交走 multipart:文字 + 0..N 张截图。系统自动附带后端日志(用户无需手动收集)。
export const submitReport = (text, files) => {
  const fd = new FormData();
  fd.append("text", text || "");
  (files || []).forEach((f) => fd.append("screenshots", f));
  return api.post("/reports", fd, {
    headers: { "Content-Type": "multipart/form-data" },
  }).then((r) => r.data);
};
// 提交者查看自己每条反馈的状态(返回不含 diff/诊断)。
export const getMyReports = () => api.get("/reports/mine").then((r) => r.data);
// owner 反馈台:全部反馈 + 状态 + 内部字段(diff/测试/诊断,owner 可见)。
export const getReportConsole = () =>
  api.get("/reports/console").then((r) => r.data);

// --- MR-D (#59) 上线闸门:批准(冒烟金丝雀)/ 拒绝 -------------------------
// 批准走真金丝雀:临时端口起新进程 → 健康+冒烟全过才切主进程,失败自动回滚。
// force=true:有 in-flight 领题/评测时仍强制上线(否则返回 outcome:"deferred")。
export const approveReport = (id, force = false) =>
  api.post(`/reports/${id}/approve`, { force }).then((r) => r.data);
// 拒绝 → needs-human 附留言;retry=true 让 AI 按留言重试一次。
export const rejectReport = (id, message, retry = false) =>
  api.post(`/reports/${id}/reject`, { message, retry }).then((r) => r.data);

export default api;
