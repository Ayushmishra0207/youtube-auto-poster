const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Render free tier cold-starts in 30-60s — give it enough time
const TIMEOUT_MS = 20000;

const TOKEN_KEY = "yt_autoposter_token";

// Session token, persisted so a page refresh doesn't force a re-login.
// Guarded for SSR (localStorage doesn't exist during server render).
export function getToken(): string {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(TOKEN_KEY) ?? "";
}

export function setToken(token: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TOKEN_KEY);
}

export class AuthError extends Error {}

// For plain <img>/<video> tags, which can't set custom headers — the
// backend accepts the session token as a "token" query param fallback
// (see api/main.py's _session_token_from_request).
export function authedMediaUrl(path: string): string {
  const token = getToken();
  if (!token) return `${BASE}${path}`;
  const sep = path.includes("?") ? "&" : "?";
  return `${BASE}${path}${sep}token=${encodeURIComponent(token)}`;
}

// For raw fetch() calls that need to stay outside the get/post/put/del
// wrappers (e.g. file uploads, or long-running requests that must NOT
// get the 20s timeout those wrappers apply).
export function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const token = getToken();
  return {
    ...extra,
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

function fetchWithTimeout(url: string, options: RequestInit = {}): Promise<Response> {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), TIMEOUT_MS);
  return fetch(url, { ...options, signal: controller.signal, cache: "no-store" })
    .finally(() => clearTimeout(id));
}

async function unwrap<T>(res: Response, label: string): Promise<T> {
  if (res.status === 401) throw new AuthError("Not authenticated");
  if (!res.ok) throw new Error(`API ${label} → ${res.status}`);
  return res.json();
}

async function get<T>(path: string): Promise<T> {
  const res = await fetchWithTimeout(`${BASE}${path}`, { headers: authHeaders() });
  return unwrap<T>(res, path);
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetchWithTimeout(`${BASE}${path}`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  return unwrap<T>(res, `POST ${path}`);
}

async function put<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetchWithTimeout(`${BASE}${path}`, {
    method: "PUT",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  return unwrap<T>(res, `PUT ${path}`);
}

async function del<T>(path: string): Promise<T> {
  const res = await fetchWithTimeout(`${BASE}${path}`, { method: "DELETE", headers: authHeaders() });
  return unwrap<T>(res, `DELETE ${path}`);
}

// Login doesn't carry a token yet — call the endpoint directly rather than
// through get/post's authHeaders (which would send an empty/stale Authorization).
async function login(username: string, password: string): Promise<{ token: string; username: string }> {
  const res = await fetchWithTimeout(`${BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) throw new Error("Invalid username or password");
  return res.json();
}

export const api = {
  login,
  logout:          ()                          => post("/api/auth/logout"),
  me:              ()                          => get<{ user: { id: number; username: string } }>("/api/auth/me"),
  status:          ()                          => get("/api/status"),
  videos:          (date?: string)             => get(`/api/videos${date ? `?date=${date}` : ""}`),
  topics:          ()                          => get("/api/topics"),
  setTopics:       (topics: string[])          => post("/api/topics", { topics }),
  clearTopics:     ()                          => del("/api/topics"),
  topicConfig:     ()                          => get("/api/topic-config"),
  saveTopicConfig: (slots: TopicConfigSlot[])  => put("/api/topic-config", { slots }),
  analytics:       ()                          => get("/api/analytics"),
  run:             ()                          => post("/api/run"),
  logs:            (lines = 150)               => get<{ logs: string[] }>(`/api/logs?lines=${lines}`),
  settings:        ()                          => get("/api/settings"),
  saveSettings:    (data: Record<string, string>) => post("/api/settings", data),
  script:          (date: string, index: number)  => get(`/api/videos/${date}/${index}/script`),
  shorts:          (date?: string)             => get(`/api/shorts${date ? `?date=${date}` : ""}`),
  generateShort:   (feed: "india" | "world" | "business") => post("/api/shorts/generate", { feed }),
  shortScript:     (date: string, index: number)  => get(`/api/shorts/${date}/${index}/script`),
};

export interface TopicConfigSlot {
  slot: string;
  category: string;
  custom_topic: string | null;
}

// WebSockets can't set custom headers, so the token travels as a query param
// (the backend's /ws/logs handler already reads it from there as a fallback).
export function wsLogsUrl(): string {
  const base = BASE.replace(/^http/, "ws") + "/ws/logs";
  const token = getToken();
  return token ? `${base}?token=${encodeURIComponent(token)}` : base;
}
