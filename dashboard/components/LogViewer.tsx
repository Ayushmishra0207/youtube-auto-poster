"use client";

import { useEffect, useRef, useState } from "react";
import { wsLogsUrl } from "@/lib/api";
import { Wifi, WifiOff, Trash2 } from "lucide-react";

function colorLine(line: string) {
  if (line.includes("ERROR") || line.includes("[fail]") || line.includes("Traceback")) return "log-error";
  if (line.includes("WARNING") || line.includes("[warn]") || line.includes("[retry]")) return "log-warning";
  if (line.includes("complete") || line.includes("[ok]") || line.includes("ready") || line.includes("saved") || line.includes("Uploaded")) return "log-success";
  return "log-info";
}

export default function LogViewer() {
  const [lines, setLines] = useState<string[]>([]);
  const [connected, setConnected] = useState(false);
  const [filter, setFilter] = useState("");
  const [autoScroll, setAutoScroll] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const connect = () => {
      const ws = new WebSocket(wsLogsUrl());
      wsRef.current = ws;

      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        setTimeout(connect, 3000); // auto-reconnect
      };
      ws.onerror = () => ws.close();
      ws.onmessage = (e) => {
        const text = e.data as string;
        setLines((prev) => [...prev.slice(-2000), text]); // keep last 2000 lines
      };
    };
    connect();
    return () => { wsRef.current?.close(); };
  }, []);

  useEffect(() => {
    if (autoScroll) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines, autoScroll]);

  const filtered = filter
    ? lines.filter((l) => l.toLowerCase().includes(filter.toLowerCase()))
    : lines;

  return (
    <div className="space-y-4 h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Logs</h1>
          <p className="text-sm mt-1 flex items-center gap-2" style={{ color: "var(--muted)" }}>
            {connected ? (
              <><Wifi size={13} className="text-green-400" /> Live stream active</>
            ) : (
              <><WifiOff size={13} className="text-red-400" /> Reconnecting…</>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setAutoScroll((v) => !v)}
            className="px-3 py-1.5 rounded-lg text-xs transition-all glass glass-hover"
            style={{ color: autoScroll ? "#4FC3F7" : "var(--muted)" }}
          >
            {autoScroll ? "Auto-scroll on" : "Auto-scroll off"}
          </button>
          <button
            onClick={() => setLines([])}
            className="w-8 h-8 rounded-lg flex items-center justify-center glass glass-hover transition-all"
            style={{ color: "var(--muted)" }}
          >
            <Trash2 size={13} />
          </button>
        </div>
      </div>

      {/* Filter */}
      <input
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        placeholder="Filter logs…"
        className="w-full bg-transparent px-4 py-2.5 rounded-xl text-sm outline-none"
        style={{
          background: "rgba(255,255,255,0.04)",
          border: "1px solid var(--border)",
          color: "#e2e8f0",
        }}
      />

      {/* Log output */}
      <div
        className="flex-1 rounded-2xl p-4 font-mono text-xs overflow-y-auto"
        style={{
          background: "rgba(2,6,23,0.8)",
          border: "1px solid var(--border)",
          minHeight: "500px",
          maxHeight: "calc(100vh - 300px)",
        }}
      >
        {filtered.length === 0 ? (
          <p style={{ color: "var(--muted)" }}>
            {connected ? "Waiting for log output…" : "Connecting to log stream…"}
          </p>
        ) : (
          filtered.map((line, i) => {
            const parts = line.match(/^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+(\S+)\s+(.*)$/);
            if (parts) {
              return (
                <div key={i} className={`flex gap-3 py-0.5 hover:bg-white/5 rounded px-1 ${colorLine(line)}`}>
                  <span className="shrink-0 opacity-40 tabular-nums">{parts[1]}</span>
                  <span className="shrink-0 w-14 opacity-60">{parts[2]}</span>
                  <span className="break-all">{parts[3]}</span>
                </div>
              );
            }
            return (
              <div key={i} className={`py-0.5 px-1 break-all ${colorLine(line)}`}>
                {line}
              </div>
            );
          })
        )}
        <div ref={bottomRef} />
      </div>

      <p className="text-xs" style={{ color: "var(--muted)" }}>
        {filtered.length} lines · {lines.length} total
      </p>
    </div>
  );
}
