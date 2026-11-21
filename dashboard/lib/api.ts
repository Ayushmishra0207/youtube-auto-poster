import type { ClipJob, ClipOptions, ClipRequest, InstagramPost } from "./types";

// Cleaned before use: an invisible BOM/zero-width char pasted into the Vercel env var
// turned every request into "<vercel-site>/%EF%BB%BFhttps:/…" (404), and a trailing
// slash would produce "//api/..." (404).
export const BASE = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000")
  .replace(/[\s﻿​-‍⁠]+/g, "")
  .replace(/\/+$/, "");

// Render free tier cold-starts in 30-60s — the old 20 s limit aborted the first
// request after every sleep (login said "Invalid password", panels errored).
const TIMEOUT_MS = 65000;

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

// Fired when the backend rejects our token (expired, or the server's session DB
// was wiped by a Render redeploy) — page.tsx listens and shows the login screen.
export const AUTH_EXPIRED_EVENT = "yt-autoposter:auth-expired";

function handleUnauthorized(): never {
  clearToken();
  if (typeof window !== "undefined") window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
  throw new AuthError("Not authenticated");
}

async function unwrap<T>(res: Response, label: string): Promise<T> {
  if (res.status === 401) handleUnauthorized();
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
  if (res.status === 401) throw new AuthError("Invalid username or password");
  if (!res.ok) throw new Error(`Server error (${res.status}) — try again in a minute`);
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
  generateShort:   (feed: "india" | "world" | "business", topic: string = "", contentType: string = "news") =>
    post("/api/shorts/generate", { feed, topic, content_type: contentType }),
  shortScript:     (date: string, index: number)  => get(`/api/shorts/${date}/${index}/script`),
  instagramPosts:     ()               => get<{ posts: InstagramPost[] }>("/api/instagram/posts"),
  retryInstagramPost: (id: string)     => post(`/api/instagram/posts/${id}/retry`),
  // Publishing a Reel polls Instagram for well over 20 s — must not use the timed post()
  runInstagramNow:    ()               => longRequest<{ ok: boolean; posted: number; failed: number }>("/api/instagram/run", { method: "POST" }),
  regenerateVideo: (date: string, index: number) =>
    post<{ ok: boolean; message?: string }>(`/api/videos/${date}/${index}/regenerate`, {}),
  regenerateShort: (date: string, index: number, feed: "india" | "world" | "business", topic = "", contentType = "news") =>
    post<{ ok: boolean; message?: string }>(`/api/shorts/${date}/${index}/regenerate`, { feed, topic, content_type: contentType }),
  clipOptions:     ()                          => get<ClipOptions>("/api/clips/options"),
  clipJobs:        ()                          => get<{ jobs: ClipJob[]; running: number }>("/api/clips"),
  createClipJob:   (req: ClipRequest)          => post<{ ok: boolean; job_id?: string; message: string }>("/api/clips", req),
  cancelClipJob:   (jobId: string)             => post<{ ok: boolean; message?: string }>(`/api/clips/${jobId}/cancel`),
  deleteClipJob:   (jobId: string)             => del<{ ok: boolean }>(`/api/clips/${jobId}`),
};

/**
 * For long-running calls (YouTube uploads, Instagram publishing): no client-side
 * timeout, 401 → login screen, and a readable error even when Render's proxy
 * answers with an HTML 502/504 page instead of JSON.
 */
export async function longRequest<T = any>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    cache: "no-store",
    headers: authHeaders(init.headers as Record<string, string> | undefined),
  });
  if (res.status === 401) handleUnauthorized();
  const text = await res.text();
  let data: any = {};
  try { data = text ? JSON.parse(text) : {}; } catch { /* non-JSON error page */ }
  if (!res.ok) {
    const detail = typeof data.detail === "string" ? data.detail : "";
    throw new Error(detail || `Request failed (${res.status}${res.status >= 502 ? " — server busy or restarting, try again" : ""})`);
  }
  return data as T;
}

/** Upload a video file from the PC for "Split into parts" — XHR so big files show progress. */
export function uploadClipSource(
  file: File,
  onProgress: (fraction: number) => void,
): Promise<{ ok: boolean; source_file: string; filename: string; duration: number }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${BASE}/api/clips/upload-source`);
    const token = getToken();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total); };
    xhr.onload = () => {
      if (xhr.status === 401) { try { handleUnauthorized(); } catch (err) { reject(err); } return; }
      let data: any = {};
      try { data = JSON.parse(xhr.responseText || "{}"); } catch { /* non-JSON error page */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else reject(new Error(data.detail || `Upload failed (${xhr.status})`));
    };
    xhr.onerror = () => reject(new Error("Upload failed — check the connection and that the server is running"));
    const fd = new FormData();
    fd.append("file", file);
    xhr.send(fd);
  });
}

export function uploadClip(jobId: string, index: number) {
  return longRequest<{ ok: boolean; url: string; video_id: string }>(`/api/clips/${jobId}/${index}/upload`, { method: "POST" });
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
