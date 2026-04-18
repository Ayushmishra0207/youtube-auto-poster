"use client";

import { type Tab } from "@/app/page";
import {
  LayoutDashboard, ListTodo, Film, ScrollText,
  CalendarClock, Settings, Zap, BarChart2, PlaySquare,
} from "lucide-react";
import { useState, useEffect } from "react";
import { api } from "@/lib/api";

const NAV: { id: Tab; label: string; icon: React.ReactNode }[] = [
  { id: "overview",   label: "Overview",   icon: <LayoutDashboard size={18} /> },
  { id: "analytics",  label: "Analytics",  icon: <BarChart2 size={18} /> },
  { id: "topics",     label: "Topics",     icon: <ListTodo size={18} /> },
  { id: "videos",     label: "Videos",     icon: <Film size={18} /> },
  { id: "logs",       label: "Logs",       icon: <ScrollText size={18} /> },
  { id: "schedule",   label: "Schedule",   icon: <CalendarClock size={18} /> },
  { id: "settings",   label: "Settings",   icon: <Settings size={18} /> },
];

export default function Sidebar({
  active, onSelect,
}: {
  active: Tab;
  onSelect: (t: Tab) => void;
}) {
  const [running, setRunning] = useState(false);
  const [triggering, setTriggering] = useState(false);

  useEffect(() => {
    const poll = async () => {
      try {
        const s: any = await api.status();
        setRunning(s.is_running);
      } catch {}
    };
    poll();
    const id = setInterval(poll, 5000);
    return () => clearInterval(id);
  }, []);

  const handleRun = async () => {
    if (running || triggering) return;
    setTriggering(true);
    try {
      await api.run();
      setRunning(true);
    } finally {
      setTriggering(false);
    }
  };

  return (
    <aside
      className="w-60 shrink-0 h-screen flex flex-col border-r"
      style={{ background: "rgba(10,14,26,0.95)", borderColor: "var(--border)", backdropFilter: "blur(16px)" }}
    >
      {/* Logo */}
      <div className="px-5 py-5 border-b" style={{ borderColor: "var(--border)" }}>
        <div className="flex items-center gap-2.5">
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center"
            style={{ background: "linear-gradient(135deg, #4FC3F7 0%, #7c3aed 100%)" }}
          >
            <PlaySquare size={16} className="text-white" />
          </div>
          <div>
            <p className="text-sm font-semibold text-white leading-tight">Auto-Poster</p>
            <p className="text-xs" style={{ color: "var(--muted)" }}>@bitnomad1</p>
          </div>
        </div>
      </div>

      {/* Run Now button */}
      <div className="px-4 pt-4 pb-2">
        <button
          onClick={handleRun}
          disabled={running || triggering}
          className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-semibold transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
          style={{
            background: running
              ? "rgba(34,197,94,0.15)"
              : "linear-gradient(135deg, rgba(79,195,247,0.2) 0%, rgba(124,58,237,0.2) 100%)",
            border: `1px solid ${running ? "rgba(34,197,94,0.4)" : "var(--border-strong)"}`,
            color: running ? "#4ade80" : "#4FC3F7",
            boxShadow: running ? "0 0 12px rgba(34,197,94,0.15)" : "0 0 12px rgba(79,195,247,0.1)",
          }}
        >
          <Zap size={14} className={running ? "animate-pulse" : ""} />
          {running ? "Pipeline Running…" : triggering ? "Starting…" : "Run Now"}
        </button>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-2 space-y-0.5">
        {NAV.map((item) => {
          const isActive = active === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onSelect(item.id)}
              className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all duration-150 text-left"
              style={{
                background: isActive ? "rgba(79,195,247,0.1)" : "transparent",
                color: isActive ? "#4FC3F7" : "#94a3b8",
                borderLeft: isActive ? "2px solid #4FC3F7" : "2px solid transparent",
              }}
            >
              <span style={{ opacity: isActive ? 1 : 0.7 }}>{item.icon}</span>
              {item.label}
            </button>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="px-5 py-4 border-t" style={{ borderColor: "var(--border)" }}>
        <p className="text-xs" style={{ color: "var(--muted)" }}>
          Pipeline fires at{" "}
          <span className="font-mono" style={{ color: "#4FC3F7" }}>02:30 IST</span>
        </p>
        <p className="text-xs mt-0.5" style={{ color: "var(--muted)" }}>
          Uploads{" "}
          <span className="font-mono text-[11px]" style={{ color: "#94a3b8" }}>06:30–07:30</span>
        </p>
      </div>
    </aside>
  );
}
