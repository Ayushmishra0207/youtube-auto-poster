"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { PipelineStatus } from "@/lib/types";
import { Activity, Video, Clock, CheckCircle, AlertCircle } from "lucide-react";

function StatCard({
  icon, label, value, sub, accent = false,
}: {
  icon: React.ReactNode; label: string; value: string; sub?: string; accent?: boolean;
}) {
  return (
    <div
      className="glass rounded-2xl p-5 flex flex-col gap-3"
      style={{ boxShadow: accent ? "0 0 24px rgba(79,195,247,0.08)" : "var(--shadow-card)" }}
    >
      <div
        className="w-9 h-9 rounded-xl flex items-center justify-center"
        style={{ background: "rgba(79,195,247,0.12)", color: "#4FC3F7" }}
      >
        {icon}
      </div>
      <div>
        <p className="text-2xl font-bold text-white">{value}</p>
        <p className="text-sm mt-0.5" style={{ color: "var(--muted)" }}>{label}</p>
        {sub && <p className="text-xs mt-1" style={{ color: "#4FC3F7" }}>{sub}</p>}
      </div>
    </div>
  );
}

function LogLine({ line }: { line: string }) {
  let cls = "log-info";
  if (line.includes("ERROR") || line.includes("[fail]")) cls = "log-error";
  else if (line.includes("WARNING") || line.includes("[warn]")) cls = "log-warning";
  else if (line.includes("complete") || line.includes("[ok]") || line.includes("ready")) cls = "log-success";

  const parts = line.match(/^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+(\w+)\s+(.*)$/);
  if (parts) {
    return (
      <div className={`flex gap-3 text-xs font-mono py-1 ${cls}`}>
        <span className="shrink-0 opacity-50">{parts[1]}</span>
        <span className="shrink-0 w-16 opacity-70">{parts[2]}</span>
        <span className="truncate">{parts[3]}</span>
      </div>
    );
  }
  return <div className={`text-xs font-mono py-0.5 truncate ${cls}`}>{line}</div>;
}

export default function OverviewPanel() {
  const [status, setStatus] = useState<PipelineStatus | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [dots, setDots] = useState(".");

  const refresh = async (isFirst = false) => {
    try {
      const [s, l] = await Promise.all([api.status(), api.logs(20)]);
      setStatus(s as PipelineStatus);
      setLogs((l as { logs: string[] }).logs);
      setError(false);
    } catch {
      setError(true);
    } finally {
      if (isFirst) setLoading(false);
    }
  };

  useEffect(() => {
    refresh(true);
    const id = setInterval(() => refresh(false), 5000);
    return () => clearInterval(id);
  }, []);

  // Animate dots while loading
  useEffect(() => {
    if (!loading) return;
    const id = setInterval(() => setDots(d => d.length >= 3 ? "." : d + "."), 500);
    return () => clearInterval(id);
  }, [loading]);

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-4">
        <div
          className="w-10 h-10 rounded-full border-2 border-t-transparent animate-spin"
          style={{ borderColor: "#4FC3F7", borderTopColor: "transparent" }}
        />
        <div className="text-center space-y-1">
          <p className="text-sm font-medium text-white">Connecting to API{dots}</p>
          <p className="text-xs" style={{ color: "var(--muted)" }}>
            Server may be waking up — this can take up to 30s
          </p>
        </div>
      </div>
    );
  }

  if (error && !status) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-4">
        <div className="text-center space-y-2">
          <p className="text-sm font-medium" style={{ color: "#f87171" }}>Cannot reach API server</p>
          <p className="text-xs" style={{ color: "var(--muted)" }}>
            Check that the Render backend is running
          </p>
        </div>
        <button
          onClick={() => { setLoading(true); refresh(true); }}
          className="px-4 py-2 rounded-lg text-sm font-medium transition-all"
          style={{ background: "rgba(79,195,247,0.1)", border: "1px solid rgba(79,195,247,0.3)", color: "#4FC3F7" }}
        >
          Retry
        </button>
      </div>
    );
  }

  if (!status) return null;

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Overview</h1>
          <p className="text-sm mt-1" style={{ color: "var(--muted)" }}>
            {status.today_date} · Hindi YouTube pipeline
          </p>
        </div>
        <div
          className="flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium"
          style={{
            background: status.is_running ? "rgba(34,197,94,0.12)" : "rgba(100,116,139,0.12)",
            border: `1px solid ${status.is_running ? "rgba(34,197,94,0.3)" : "rgba(100,116,139,0.3)"}`,
            color: status.is_running ? "#4ade80" : "#94a3b8",
          }}
        >
          <span
            className={`w-1.5 h-1.5 rounded-full ${status.is_running ? "bg-green-400 animate-pulse" : "bg-slate-500"}`}
          />
          {status.is_running ? "Pipeline Running" : "Idle"}
        </div>
      </div>

      {error && (
        <div
          className="flex items-center gap-2 px-4 py-3 rounded-xl text-sm"
          style={{ background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.3)", color: "#f87171" }}
        >
          <AlertCircle size={15} />
          Cannot reach API server — is <code className="mx-1 font-mono text-xs">uvicorn api.main:app</code> running on port 8000?
        </div>
      )}

      {/* Stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          icon={<Video size={18} />}
          label="Videos today"
          value={`${status.today_video_count} / ${status.total_slots}`}
          sub={`${status.total_slots - status.today_video_count} remaining`}
          accent
        />
        <StatCard
          icon={<Clock size={18} />}
          label="Next scheduled run"
          value={status.next_scheduled_run}
          sub="Daily auto-trigger"
        />
        <StatCard
          icon={<Activity size={18} />}
          label="Upload window"
          value="18:30–19:30"
          sub="IST, 7 slots × 10 min"
        />
        <StatCard
          icon={<CheckCircle size={18} />}
          label="Status"
          value={status.is_running ? "Running" : "Ready"}
          sub={status.is_running ? "Processing…" : "Waiting for trigger"}
        />
      </div>

      {/* Progress bar */}
      <div className="glass rounded-2xl p-5">
        <div className="flex items-center justify-between mb-3">
          <p className="text-sm font-medium text-white">Today's progress</p>
          <p className="text-sm font-mono" style={{ color: "#4FC3F7" }}>
            {status.today_video_count}/{status.total_slots}
          </p>
        </div>
        <div className="h-2 rounded-full" style={{ background: "rgba(255,255,255,0.06)" }}>
          <div
            className="h-2 rounded-full transition-all duration-700"
            style={{
              width: `${(status.today_video_count / status.total_slots) * 100}%`,
              background: "linear-gradient(90deg, #4FC3F7 0%, #7c3aed 100%)",
              boxShadow: "0 0 8px rgba(79,195,247,0.4)",
            }}
          />
        </div>
        <div className="flex justify-between mt-2">
          {Array.from({ length: status.total_slots }, (_, i) => (
            <div
              key={i}
              className="w-2 h-2 rounded-full"
              style={{
                background: i < status.today_video_count
                  ? "#4FC3F7"
                  : "rgba(255,255,255,0.1)",
                boxShadow: i < status.today_video_count ? "0 0 4px rgba(79,195,247,0.6)" : "none",
              }}
            />
          ))}
        </div>
      </div>

      {/* Recent logs */}
      <div className="glass rounded-2xl p-5">
        <p className="text-sm font-medium text-white mb-4">Recent activity</p>
        <div className="space-y-0.5 max-h-64 overflow-y-auto">
          {logs.length === 0 ? (
            <p className="text-xs" style={{ color: "var(--muted)" }}>No logs yet</p>
          ) : (
            [...logs].reverse().map((l, i) => <LogLine key={i} line={l} />)
          )}
        </div>
      </div>
    </div>
  );
}
