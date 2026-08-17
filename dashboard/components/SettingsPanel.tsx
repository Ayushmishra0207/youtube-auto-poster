"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Settings } from "@/lib/types";
import { Save, Eye, EyeOff } from "lucide-react";

function Field({
  label, value, onChange, type = "text", hint,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  hint?: string;
}) {
  const [show, setShow] = useState(false);
  const isSecret = type === "password";

  return (
    <div className="space-y-1.5">
      <label className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--muted)" }}>
        {label}
      </label>
      <div className="relative">
        <input
          type={isSecret && !show ? "password" : "text"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full px-4 py-2.5 rounded-xl text-sm outline-none transition-all font-mono"
          style={{
            background: "rgba(255,255,255,0.04)",
            border: "1px solid var(--border)",
            color: "#e2e8f0",
          }}
          onFocus={(e) => {
            e.target.style.borderColor = "var(--border-strong)";
            e.target.style.boxShadow = "0 0 0 3px rgba(79,195,247,0.08)";
          }}
          onBlur={(e) => {
            e.target.style.borderColor = "var(--border)";
            e.target.style.boxShadow = "none";
          }}
        />
        {isSecret && (
          <button
            onClick={() => setShow((v) => !v)}
            className="absolute right-3 top-1/2 -translate-y-1/2"
            style={{ color: "var(--muted)" }}
          >
            {show ? <EyeOff size={14} /> : <Eye size={14} />}
          </button>
        )}
      </div>
      {hint && <p className="text-xs" style={{ color: "#475569" }}>{hint}</p>}
    </div>
  );
}

export default function SettingsPanel() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.settings().then((s: any) => {
      setSettings(s);
      setForm({
        ANTHROPIC_API_KEY: s.ANTHROPIC_API_KEY,
        PEXELS_API_KEY: s.PEXELS_API_KEY,
        KEEP_OUTPUT_DAYS: s.KEEP_OUTPUT_DAYS,
      });
    }).catch(() => {});
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      const updates: Record<string, string> = {};
      for (const [k, v] of Object.entries(form)) {
        if (v && v !== "***") updates[k] = v;
      }
      await api.saveSettings(updates);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } finally {
      setSaving(false);
    }
  };

  if (!settings) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="w-6 h-6 border-2 border-cyan-DEFAULT border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h1 className="text-2xl font-bold text-white">Settings</h1>
        <p className="text-sm mt-1" style={{ color: "var(--muted)" }}>
          Edit configuration values — changes are written to <code className="font-mono text-xs mx-1" style={{ color: "#94a3b8" }}>.env</code>
        </p>
      </div>

      <div className="glass rounded-2xl p-6 space-y-5">
        <p className="text-xs font-semibold uppercase tracking-wider" style={{ color: "#4FC3F7" }}>API Keys</p>
        <Field
          label="Anthropic API Key"
          value={form.ANTHROPIC_API_KEY ?? ""}
          onChange={(v) => setForm((f) => ({ ...f, ANTHROPIC_API_KEY: v }))}
          type="password"
          hint="Required — used for Claude script generation"
        />
        <Field
          label="Pexels API Key"
          value={form.PEXELS_API_KEY ?? ""}
          onChange={(v) => setForm((f) => ({ ...f, PEXELS_API_KEY: v }))}
          type="password"
          hint="Optional — fetches background images. Gradient fallback if absent."
        />
      </div>

      <div className="glass rounded-2xl p-6 space-y-5">
        <p className="text-xs font-semibold uppercase tracking-wider" style={{ color: "#4FC3F7" }}>Output</p>
        <Field
          label="Keep output days"
          value={form.KEEP_OUTPUT_DAYS ?? "3"}
          onChange={(v) => setForm((f) => ({ ...f, KEEP_OUTPUT_DAYS: v }))}
          hint="Number of days to keep generated videos on disk before auto-deletion"
        />
      </div>

      <div className="glass rounded-2xl p-6">
        <p className="text-xs font-semibold uppercase tracking-wider mb-4" style={{ color: "#4FC3F7" }}>Upload Slots</p>
        <div className="flex flex-wrap gap-2">
          {settings.upload_slots.map((slot, i) => (
            <div
              key={i}
              className="px-3 py-1.5 rounded-lg text-xs font-mono"
              style={{ background: "rgba(79,195,247,0.1)", color: "#4FC3F7", border: "1px solid rgba(79,195,247,0.2)" }}
            >
              {slot} IST
            </div>
          ))}
        </div>
        <p className="text-xs mt-3" style={{ color: "#475569" }}>
          Upload slots are defined in <code className="font-mono text-[11px] mx-0.5" style={{ color: "#64748b" }}>config.py → UPLOAD_SLOTS_IST</code>
        </p>
      </div>

      <button
        onClick={handleSave}
        disabled={saving}
        className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold transition-all duration-200"
        style={{
          background: saved ? "rgba(34,197,94,0.15)" : "linear-gradient(135deg, rgba(79,195,247,0.2) 0%, rgba(124,58,237,0.2) 100%)",
          border: `1px solid ${saved ? "rgba(34,197,94,0.4)" : "var(--border-strong)"}`,
          color: saved ? "#4ade80" : "#4FC3F7",
          boxShadow: saved ? "0 0 16px rgba(34,197,94,0.15)" : "0 0 16px rgba(79,195,247,0.1)",
        }}
      >
        <Save size={14} />
        {saving ? "Saving…" : saved ? "Saved!" : "Save Settings"}
      </button>
    </div>
  );
}
