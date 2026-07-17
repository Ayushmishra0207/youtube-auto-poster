"use client";

import { type Tab } from "@/app/page";
import {
  LayoutDashboard, ListTodo, Film, ScrollText,
  CalendarClock, Settings, Zap, BarChart2, PlaySquare,
  Upload, Target, X, Sparkles,
} from "lucide-react";
import { useState, useEffect } from "react";
import { api } from "@/lib/api";

const DEADLINE = new Date("2026-05-19T00:00:00+05:30"); // IST
const TOTAL_DAYS = 30;

function useCountdown() {
  const calc = () => {
    const now = new Date();
    const diff = Math.max(0, DEADLINE.getTime() - now.getTime());
    return {
      days:    Math.floor(diff / 86400000),
      hours:   Math.floor((diff % 86400000) / 3600000),
      minutes: Math.floor((diff % 3600000)  / 60000),
      seconds: Math.floor((diff % 60000)    / 1000),
      pct:     Math.min(100, ((TOTAL_DAYS * 86400000 - diff) / (TOTAL_DAYS * 86400000)) * 100),
    };
  };
  const [t, setT] = useState(calc);
  useEffect(() => {
    const id = setInterval(() => setT(calc()), 1000);
    return () => clearInterval(id);
  }, []);
  return t;
}

const NAV: { id: Tab; label: string; icon: React.ReactNode }[] = [
  { id: "overview",   label: "Overview",   icon: <LayoutDashboard size={18} /> },
  { id: "analytics",  label: "Analytics",  icon: <BarChart2 size={18} /> },
  { id: "topics",     label: "Topics",     icon: <ListTodo size={18} /> },
  { id: "videos",     label: "Videos",     icon: <Film size={18} /> },
  { id: "shorts",     label: "Shorts",     icon: <Sparkles size={18} /> },
  { id: "upload",     label: "Upload",     icon: <Upload size={18} /> },
  { id: "logs",       label: "Logs",       icon: <ScrollText size={18} /> },
  { id: "schedule",   label: "Schedule",   icon: <CalendarClock size={18} /> },
  { id: "settings",   label: "Settings",   icon: <Settings size={18} /> },
];

function MonetizationFooter() {
  const { days, hours, minutes, seconds, pct } = useCountdown();
  const urgent = days < 7;
  const warn   = days < 15;
  const accent = urgent ? "#f87171" : warn ? "#fbbf24" : "#4FC3F7";

  return (
    <div
      className="mx-3 mb-3 rounded-xl p-3 space-y-2"
      style={{
        background: `rgba(${urgent ? "239,68,68" : warn ? "251,191,36" : "79,195,247"},0.06)`,
        border: `1px solid rgba(${urgent ? "239,68,68" : warn ? "251,191,36" : "79,195,247"},0.2)`,
      }}
    >
      <div className="flex items-center gap-1.5">
        <Target size={12} style={{ color: accent }} />
        <p className="text-xs font-semibold" style={{ color: accent }}>Monetization Deadline</p>
      </div>

      {/* Big countdown */}
      <div className="flex items-end gap-1">
        <span className="text-2xl font-bold tabular-nums" style={{ color: accent }}>{days}</span>
        <span className="text-xs mb-0.5" style={{ color: accent }}>d</span>
        <span className="text-lg font-bold tabular-nums ml-1" style={{ color: accent, opacity: 0.8 }}>{String(hours).padStart(2,"0")}</span>
        <span className="text-xs mb-0.5" style={{ color: accent, opacity: 0.8 }}>h</span>
        <span className="text-lg font-bold tabular-nums" style={{ color: accent, opacity: 0.6 }}>{String(minutes).padStart(2,"0")}</span>
        <span className="text-xs mb-0.5" style={{ color: accent, opacity: 0.6 }}>m</span>
        <span className="text-base font-bold tabular-nums" style={{ color: accent, opacity: 0.4 }}>{String(seconds).padStart(2,"0")}</span>
        <span className="text-xs mb-0.5" style={{ color: accent, opacity: 0.4 }}>s</span>
      </div>

      {/* Progress bar — time elapsed */}
      <div>
        <div className="h-1.5 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.07)" }}>
          <div
            className="h-full rounded-full transition-all duration-1000"
            style={{ width: `${pct}%`, background: accent, boxShadow: `0 0 6px ${accent}66` }}
          />
        </div>
        <div className="flex justify-between mt-1">
          <p className="text-[10px]" style={{ color: "var(--muted)" }}>Apr 19</p>
          <p className="text-[10px]" style={{ color: "var(--muted)" }}>May 19, 2026</p>
        </div>
      </div>

      {/* Targets */}
      <div className="pt-0.5 space-y-0.5">
        <p className="text-[10px]" style={{ color: "var(--muted)" }}>Need: 1,000 subs · 4,000 watch hrs</p>
        <p className="text-[10px]" style={{ color: "var(--muted)" }}>Pipeline at 14:30 IST · Upload 18:30–19:30</p>
      </div>
    </div>
  );
}

export default function Sidebar({
  active, onSelect, onClose,
}: {
  active: Tab;
  onSelect: (t: Tab) => void;
  onClose?: () => void;
}) {
  const [running, setRunning] = useState(false);
  const [triggering, setTriggering] = useState(false);
  const [runMsg, setRunMsg] = useState<{ text: string; ok: boolean } | null>(null);

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
    setRunMsg(null);
    try {
      const res: any = await api.run();
      if (res?.ok === false) {
        setRunMsg({ text: res.message ?? "Cannot start pipeline", ok: false });
      } else {
        setRunning(true);
        setRunMsg({ text: "Pipeline started!", ok: true });
        setTimeout(() => setRunMsg(null), 4000);
      }
    } catch (e: any) {
      setRunMsg({ text: "Failed to reach API", ok: false });
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
            className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
            style={{ background: "linear-gradient(135deg, #4FC3F7 0%, #7c3aed 100%)" }}
          >
            <PlaySquare size={16} className="text-white" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-white leading-tight">Auto-Poster</p>
            <p className="text-xs" style={{ color: "var(--muted)" }}>@bitnomad1</p>
          </div>
          {onClose && (
            <button
              onClick={onClose}
              className="md:hidden w-7 h-7 rounded-lg flex items-center justify-center shrink-0 transition-colors hover:bg-white/10"
              style={{ color: "#64748b" }}
            >
              <X size={16} />
            </button>
          )}
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
        {runMsg && (
          <p className="mt-2 text-[11px] leading-snug text-center px-1" style={{ color: runMsg.ok ? "#4ade80" : "#f87171" }}>
            {runMsg.text}
          </p>
        )}
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

      {/* Monetization countdown footer */}
      <MonetizationFooter />
    </aside>
  );
}
