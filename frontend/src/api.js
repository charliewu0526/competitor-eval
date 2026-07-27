import axios from "axios";

const api = axios.create({ baseURL: "/api", timeout: 15000 });

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

export const postJudgment = (id, body) =>
  api.post(`/findings/${id}/judgment`, body).then((r) => r.data);
export const rebuildSpotcheck = () =>
  api.post("/spotcheck/rebuild").then((r) => r.data);
export const postVerdict = (id, body) =>
  api.post(`/spotcheck/${id}/verdict`, body).then((r) => r.data);

export default api;
