"use client";

import { useState, useEffect } from "react";
import { PlaySquare, Zap, Target, Menu } from "lucide-react";
import { api } from "@/lib/api";

const DEADLINE = new Date("2026-05-19T00:00:00+05:30");

export default function MobileHeader({ onMenuClick }: { onMenuClick?: () => void }) {
  const [running,    setRunning]    = useState(false);
  const [triggering, setTriggering] = useState(false);
  const [daysLeft,   setDaysLeft]   = useState(30);

  useEffect(() => {
    const calc = () => setDaysLeft(Math.max(0, Math.floor((DEADLINE.getTime() - Date.now()) / 86400000)));
    calc();
    const id = setInterval(calc, 60_000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const poll = async () => {
      try { const s: any = await api.status(); setRunning(s.is_running); } catch {}
    };
    poll();
    const id = setInterval(poll, 5000);
    return () => clearInterval(id);
  }, []);

  const handleRun = async () => {
    if (running || triggering) return;
    setTriggering(true);
    try { await api.run(); setRunning(true); } finally { setTriggering(false); }
  };

  const urgent = daysLeft < 7;
  const warn   = daysLeft < 15;
  const accent = urgent ? "#f87171" : warn ? "#fbbf24" : "#4FC3F7";

  return (
    <header
      className="md:hidden flex items-center justify-between px-4 py-3 border-b sticky top-0 z-30"
      style={{ background: "rgba(8,12,24,0.98)", borderColor: "var(--border)", backdropFilter: "blur(16px)" }}
    >
      {/* Hamburger + Logo */}
      <div className="flex items-center gap-2">
        <button
          onClick={onMenuClick}
          className="w-8 h-8 rounded-lg flex items-center justify-center transition-colors hover:bg-white/10"
          style={{ color: "#94a3b8" }}
        >
          <Menu size={18} />
        </button>
        <div
          className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0"
          style={{ background: "linear-gradient(135deg, #4FC3F7 0%, #7c3aed 100%)" }}
        >
          <PlaySquare size={13} className="text-white" />
        </div>
        <span className="text-sm font-bold text-white">Auto-Poster</span>
      </div>

      {/* Countdown chip */}
      <div
        className="flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold"
        style={{ background: `rgba(${urgent?"239,68,68":warn?"251,191,36":"79,195,247"},0.12)`, color: accent }}
      >
        <Target size={10} />
        {daysLeft}d left
      </div>

      {/* Run Now */}
      <button
        onClick={handleRun}
        disabled={running || triggering}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all disabled:opacity-50"
        style={{
          background: running ? "rgba(34,197,94,0.15)" : "rgba(79,195,247,0.15)",
          border: `1px solid ${running ? "rgba(34,197,94,0.4)" : "rgba(79,195,247,0.4)"}`,
          color: running ? "#4ade80" : "#4FC3F7",
        }}
      >
        <Zap size={12} className={running ? "animate-pulse" : ""} />
        {running ? "Running" : "Run"}
      </button>
    </header>
  );
}
