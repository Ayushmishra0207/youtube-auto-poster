const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Render free tier cold-starts in 30-60s — give it enough time
const TIMEOUT_MS = 20000;

function fetchWithTimeout(url: string, options: RequestInit = {}): Promise<Response> {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), TIMEOUT_MS);
  return fetch(url, { ...options, signal: controller.signal, cache: "no-store" })
    .finally(() => clearTimeout(id));
}

async function get<T>(path: string): Promise<T> {
  const res = await fetchWithTimeout(`${BASE}${path}`);
  if (!res.ok) throw new Error(`API ${path} → ${res.status}`);
  return res.json();
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetchWithTimeout(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`API POST ${path} → ${res.status}`);
  return res.json();
}

async function put<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetchWithTimeout(`${BASE}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`API PUT ${path} → ${res.status}`);
  return res.json();
}

async function del<T>(path: string): Promise<T> {
  const res = await fetchWithTimeout(`${BASE}${path}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`API DELETE ${path} → ${res.status}`);
  return res.json();
}

export const api = {
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
};

export interface TopicConfigSlot {
  slot: string;
  category: string;
  custom_topic: string | null;
}

export const WS_URL = BASE.replace(/^http/, "ws") + "/ws/logs";
