import axios from "axios";
import { getToken, logout } from "./lib/auth";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

const client = axios.create({ baseURL: API });

// ── Request interceptor: attach JWT token ──────────────────────────
client.interceptors.request.use((config) => {
  const token = getToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// ── Response interceptor: redirect to login on 401 ─────────────────
client.interceptors.response.use(
  (res) => res,
  (error) => {
    if (error.response?.status === 401) {
      logout();
      // Only redirect if we're not already on the login page
      if (window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);

export const api = {
  // Auth
  login: (data) => client.post("/auth/login", data).then((r) => r.data),

  // Stats & overview
  stats: () => client.get("/stats").then((r) => r.data),

  // Accounts
  listAccounts: () => client.get("/accounts").then((r) => r.data),
  accountGroups: () => client.get("/account-groups").then((r) => r.data),
  addAccount: (data) => client.post("/accounts", data).then((r) => r.data),
  uploadAccount: (formData) =>
    client.post("/accounts/upload", formData, { headers: { "Content-Type": "multipart/form-data" } }).then((r) => r.data),
  deleteAccount: (id) => client.delete(`/accounts/${id}`).then((r) => r.data),
  getGroups: (id) => client.get(`/accounts/${id}/groups`).then((r) => r.data),

  // Session tester
  sessionTest: (data) => client.post("/session-test", data).then((r) => r.data),

  // Media upload
  upload: (formData) =>
    client.post("/upload", formData, { headers: { "Content-Type": "multipart/form-data" } }).then((r) => r.data),

  // Campaigns
  listCampaigns: () => client.get("/campaigns").then((r) => r.data),
  createCampaign: (data) => client.post("/campaigns", data).then((r) => r.data),
  updateCampaign: (id, data) => client.put(`/campaigns/${id}`, data).then((r) => r.data),
  startCampaign: (id) => client.post(`/campaigns/${id}/start`).then((r) => r.data),
  stopCampaign: (id) => client.post(`/campaigns/${id}/stop`).then((r) => r.data),
  deleteCampaign: (id) => client.delete(`/campaigns/${id}`).then((r) => r.data),
  deleteCampaignAccounts: (id) => client.delete(`/campaigns/${id}/accounts`).then((r) => r.data),
  campaignTargets: (id) => client.get(`/campaigns/${id}/targets-health`).then((r) => r.data),
  campaignBans: (id) => client.get(`/campaigns/${id}/bans`).then((r) => r.data),
  removeGroups: (id, group_ids) => client.post(`/campaigns/${id}/remove-groups`, { group_ids }).then((r) => r.data),

  // Logs
  logs: () => client.get("/logs").then((r) => r.data),
  clearLogs: () => client.delete("/logs").then((r) => r.data),

  // Proxies
  listProxies: () => client.get("/proxies").then((r) => r.data),
  loadProxies: (data) => client.post("/proxies", data).then((r) => r.data),
  clearProxies: () => client.delete("/proxies").then((r) => r.data),
  deleteProxy: (id) => client.delete(`/proxies/${id}`).then((r) => r.data),
  testProxy: (data) => client.post("/proxies/test", data).then((r) => r.data),
  testStoredProxy: (id) => client.post(`/proxies/${id}/test`).then((r) => r.data),
  assignProxies: (data) => client.post("/proxies/assign", data).then((r) => r.data),
  unassignProxies: (data) => client.post("/proxies/unassign", data).then((r) => r.data),
  proxyCoverage: () => client.get("/proxies/coverage").then((r) => r.data),
};
