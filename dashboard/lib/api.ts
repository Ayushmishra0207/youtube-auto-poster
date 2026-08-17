import type { InstagramPost } from "./types";

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

// Fired whenever a request comes back 401 — e.g. the API server restarted
// and its in-memory sessions were wiped. `page.tsx` listens for this and
// bounces back to the login screen instead of leaving an uncaught
// AuthError to crash the app.
const AUTH_EXPIRED_EVENT = "auth-expired";

function handleAuthExpired(): void {
  clearToken();
  if (typeof window !== "undefined") window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
}

export function onAuthExpired(handler: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener(AUTH_EXPIRED_EVENT, handler);
  return () => window.removeEventListener(AUTH_EXPIRED_EVENT, handler);
}

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
  if (res.status === 401) { handleAuthExpired(); throw new AuthError("Not authenticated"); }
  if (!res.ok) {
    // Surface the backend's actual error text (FastAPI's {detail: "..."} body
    // shape, or any other JSON/plain-text error) instead of just the bare
    // status code — callers that display e.message (e.g. VideoGeneratePanel)
    // then show the real validation/failure reason.
    let detail = "";
    try {
      const body = await res.clone().json();
      detail = (body && typeof body === "object" && "detail" in body) ? String(body.detail) : JSON.stringify(body);
    } catch {
      try { detail = await res.clone().text(); } catch { /* no body available */ }
    }
    throw new Error(detail ? `API ${label} → ${res.status}: ${detail}` : `API ${label} → ${res.status}`);
  }
  return res.json();
}

// Builds a "?k=v&k2=v2" query string, skipping undefined/empty values —
// used to thread optional params like account_id through GET calls.
function qs(params: Record<string, string | number | undefined>): string {
  const parts = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== "")
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`);
  return parts.length ? `?${parts.join("&")}` : "";
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
  status:          (accountId?: string)        => get(`/api/status${qs({ account_id: accountId })}`),
  videos:          (date?: string, accountId?: string) => get(`/api/videos${qs({ date, account_id: accountId })}`),
  topics:          ()                          => get("/api/topics"),
  setTopics:       (topics: string[])          => post("/api/topics", { topics }),
  clearTopics:     ()                          => del("/api/topics"),
  // Legacy root-level topic_config.json routes. The pipeline reads
  // accounts/<id>/topic_config.json, so the UI uses
  // get/saveAccountTopicConfig below — these are kept only as the raw
  // pre-multi-account endpoints and are not wired to any panel.
  topicConfig:     ()                          => get("/api/topic-config"),
  saveTopicConfig: (slots: TopicConfigSlot[])  => put("/api/topic-config", { slots }),
  analytics:       (accountId?: string)        => get(`/api/analytics${qs({ account_id: accountId })}`),
  run:             ()                          => post("/api/run"),
  logs:            (lines = 150, accountId?: string) => get<{ logs: string[] }>(`/api/logs${qs({ lines, account_id: accountId })}`),
  settings:        ()                          => get("/api/settings"),
  saveSettings:    (data: Record<string, string>) => post("/api/settings", data),
  script:          (date: string, index: number, accountId?: string) => get(`/api/videos/${date}/${index}/script${qs({ account_id: accountId })}`),
  shorts:          (date?: string, accountId?: string) => get(`/api/shorts${qs({ date, account_id: accountId })}`),
  generateShort:   (feed: "india" | "world" | "business", topic: string = "", contentType: string = "news", accountId: string = "default") =>
    post("/api/shorts/generate", { feed, topic, content_type: contentType, account_id: accountId }),
  shortScript:     (date: string, index: number, accountId?: string) => get(`/api/shorts/${date}/${index}/script${qs({ account_id: accountId })}`),
  instagramPosts:     ()               => get<{ posts: InstagramPost[] }>("/api/instagram/posts"),
  retryInstagramPost: (id: string)     => post(`/api/instagram/posts/${id}/retry`),
  runInstagramNow:    ()               => post<{ ok: boolean; posted: number; failed: number }>("/api/instagram/run"),
  listAccounts:            ()                              => get<any>("/api/accounts"),
  toggleAccount:           (id: string, enabled: boolean)   => post(`/api/accounts/${id}/toggle`, { enabled }),
  getAccountTopicConfig:   (id: string)                     => get<any>(`/api/accounts/${id}/topic-config`),
  saveAccountTopicConfig:  (id: string, cfg: unknown)       => post(`/api/accounts/${id}/topic-config`, cfg),
  getAccountShortsConfig:  (id: string)                     => get<any>(`/api/accounts/${id}/shorts-config`),
  saveAccountShortsConfig: (id: string, cfg: unknown)       => post(`/api/accounts/${id}/shorts-config`, cfg),
  generateVideo: (accountId: string, category: string, customTopic: string, locale: string) =>
    post<GenerateVideoResult>("/api/videos/generate", { account_id: accountId, category, custom_topic: customTopic, locale }),
};

// Shape of POST /api/videos/generate's response (api/main.py's generate_video).
//
// Fire-and-forget, exactly like /api/shorts/generate: the endpoint validates
// the account/category/locale, spawns generate_video_now.py, and returns
// immediately — generation + upload takes minutes, far longer than this
// client's 20s fetch timeout. There is no youtube_id to return yet; the
// finished video shows up through the existing /api/videos poll.
//
// ok:false + message means "couldn't start" (something already running).
// Genuine input errors come back as a non-2xx HTTPException, which unwrap()
// turns into a thrown Error carrying the backend's detail text.
export interface GenerateVideoResult {
  ok: boolean;
  pid?: number;
  message?: string;
}

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
