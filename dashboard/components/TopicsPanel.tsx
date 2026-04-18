"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, type TopicConfigSlot } from "@/lib/api";
import { Check, X, Pencil, ChevronDown, RefreshCw, Save } from "lucide-react";

const SLOTS = ["06:30","06:40","06:50","07:00","07:10","07:20","07:30"];

interface Category {
  label: string;
  color: string;
  description: string;
}

const CATEGORY_EMOJI: Record<string, string> = {
  news_india:        "📰",
  news_world:        "🌍",
  historical_story:  "📖",
  cartoon_animation: "🎬",
  science_tech:      "🔬",
  sports:            "🏆",
  entertainment:     "🎭",
  health:            "💊",
  finance:           "📈",
  spiritual:         "🕉️",
};

function CategoryDropdown({ value, categories, onSelect }: {
  value: string;
  categories: Record<string, Category>;
  onSelect: (cat: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState({ top: 0, left: 0, width: 224 });
  const btnRef = useRef<HTMLButtonElement>(null);
  const current = categories[value];

  const handleOpen = () => {
    if (btnRef.current) {
      const r = btnRef.current.getBoundingClientRect();
      setPos({ top: r.bottom + 4, left: r.left, width: Math.max(r.width, 224) });
    }
    setOpen((o) => !o);
  };

  return (
    <div>
      <button
        ref={btnRef}
        onClick={handleOpen}
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-all w-48"
        style={{
          background: current ? `${current.color}18` : "rgba(255,255,255,0.06)",
          border: `1px solid ${current ? `${current.color}40` : "rgba(255,255,255,0.1)"}`,
          color: current?.color ?? "#94a3b8",
        }}
      >
        <span className="text-base">{CATEGORY_EMOJI[value] ?? "📋"}</span>
        <span className="flex-1 text-left truncate">{current?.label ?? "Select…"}</span>
        <ChevronDown size={12} className={`shrink-0 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && createPortal(
        <>
          {/* full-screen backdrop — outside any stacking context */}
          <div
            style={{ position: "fixed", inset: 0, zIndex: 9998 }}
            onClick={() => setOpen(false)}
          />
          {/* menu — directly in document.body, immune to backdrop-filter stacking */}
          <div
            style={{
              position: "fixed",
              top: pos.top,
              left: pos.left,
              width: pos.width,
              maxHeight: "60vh",
              overflowY: "auto",
              zIndex: 9999,
              background: "#080c18",
              border: "1px solid rgba(79,195,247,0.25)",
              borderRadius: "12px",
              boxShadow: "0 20px 60px rgba(0,0,0,0.9)",
            }}
          >
            {Object.entries(categories).map(([key, cat]) => (
              <button
                key={key}
                onClick={() => { onSelect(key); setOpen(false); }}
                style={{
                  width: "100%",
                  display: "flex",
                  alignItems: "center",
                  gap: "10px",
                  padding: "10px 12px",
                  fontSize: "14px",
                  textAlign: "left",
                  background: key === value ? "rgba(255,255,255,0.05)" : "transparent",
                  border: "none",
                  cursor: "pointer",
                  color: "#e2e8f0",
                  transition: "background 0.15s",
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.06)")}
                onMouseLeave={(e) => (e.currentTarget.style.background = key === value ? "rgba(255,255,255,0.05)" : "transparent")}
              >
                <span style={{ fontSize: "18px", flexShrink: 0 }}>{CATEGORY_EMOJI[key] ?? "📋"}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <p style={{ fontWeight: 500, color: key === value ? cat.color : "#e2e8f0", margin: 0 }}>
                    {cat.label}
                  </p>
                  <p style={{ fontSize: "11px", color: "#475569", margin: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {cat.description}
                  </p>
                </div>
                {key === value && (
                  <Check size={12} style={{ flexShrink: 0, color: cat.color }} />
                )}
              </button>
            ))}
          </div>
        </>,
        document.body
      )}
    </div>
  );
}

export default function TopicsPanel() {
  const [slots, setSlots] = useState<TopicConfigSlot[]>([]);
  const [categories, setCategories] = useState<Record<string, Category>>({});
  const [editingIdx, setEditingIdx] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);

  const load = async () => {
    try {
      const cfg: any = await api.topicConfig();
      setCategories(cfg.categories ?? {});
      setSlots(
        cfg.slots?.length > 0
          ? cfg.slots
          : SLOTS.map((slot) => ({ slot, category: "news_india", custom_topic: null }))
      );
      setDirty(false);
    } catch {
      setSlots(SLOTS.map((slot) => ({ slot, category: "news_india", custom_topic: null })));
    }
  };

  useEffect(() => { load(); }, []);

  const setCategory = (idx: number, cat: string) => {
    setSlots((prev) => prev.map((s, i) => i === idx ? { ...s, category: cat } : s));
    setDirty(true);
  };

  const startEdit  = (idx: number) => { setEditingIdx(idx); setDraft(slots[idx]?.custom_topic ?? ""); };
  const cancelEdit = () => setEditingIdx(null);

  const commitEdit = () => {
    if (editingIdx === null) return;
    setSlots((prev) =>
      prev.map((s, i) => i === editingIdx ? { ...s, custom_topic: draft.trim() || null } : s)
    );
    setEditingIdx(null);
    setDirty(true);
  };

  const clearCustom = (idx: number) => {
    setSlots((prev) => prev.map((s, i) => i === idx ? { ...s, custom_topic: null } : s));
    setDirty(true);
  };

  const saveAll = async () => {
    setSaving(true);
    try {
      await api.saveTopicConfig(slots);
      setDirty(false);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">Topics & Categories</h1>
          <p className="text-sm mt-1" style={{ color: "var(--muted)" }}>
            Assign a content category per slot. Pin a specific topic to override auto-trending.
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={load}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs transition-all glass glass-hover"
            style={{ color: "var(--muted)" }}>
            <RefreshCw size={12} /> Reset
          </button>
          <button
            onClick={saveAll}
            disabled={!dirty || saving}
            className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-semibold transition-all disabled:opacity-40 disabled:cursor-not-allowed"
            style={{
              background: saved
                ? "rgba(34,197,94,0.15)"
                : "linear-gradient(135deg, rgba(79,195,247,0.2) 0%, rgba(124,58,237,0.2) 100%)",
              border: `1px solid ${saved ? "rgba(34,197,94,0.4)" : "rgba(79,195,247,0.4)"}`,
              color: saved ? "#4ade80" : "#4FC3F7",
            }}
          >
            {saved ? <Check size={12} /> : <Save size={12} />}
            {saved ? "Saved!" : saving ? "Saving…" : "Save Changes"}
          </button>
        </div>
      </div>

      {/* Category legend chips */}
      <div className="glass rounded-xl p-4">
        <p className="text-xs font-semibold mb-3" style={{ color: "#475569" }}>AVAILABLE CATEGORIES</p>
        <div className="flex flex-wrap gap-2">
          {Object.entries(categories).map(([key, cat]) => (
            <div
              key={key}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs"
              style={{ background: `${cat.color}12`, border: `1px solid ${cat.color}30`, color: cat.color }}
            >
              <span>{CATEGORY_EMOJI[key] ?? "📋"}</span>
              {cat.label}
            </div>
          ))}
        </div>
      </div>

      {/* Slot rows */}
      <div className="space-y-3">
        {slots.map((slot, idx) => {
          const cat = categories[slot.category];
          const hasCustom = !!slot.custom_topic;

          return (
            <div
              key={slot.slot}
              className="glass rounded-2xl p-4 transition-all duration-200"
              style={{
                border: hasCustom
                  ? "1px solid rgba(79,195,247,0.3)"
                  : cat
                  ? `1px solid ${cat.color}20`
                  : "1px solid var(--border)",
              }}
            >
              <div className="flex items-center gap-3 flex-wrap">
                {/* Time badge */}
                <div
                  className="w-16 shrink-0 text-center py-1.5 rounded-lg text-xs font-mono font-bold"
                  style={{
                    background: cat ? `${cat.color}15` : "rgba(79,195,247,0.08)",
                    color: cat?.color ?? "#4FC3F7",
                    border: `1px solid ${cat ? `${cat.color}30` : "rgba(79,195,247,0.2)"}`,
                  }}
                >
                  {slot.slot}
                </div>

                {/* Slot number */}
                <span className="text-xs font-bold w-5 text-center" style={{ color: "#475569" }}>
                  {idx + 1}
                </span>

                {/* Category dropdown */}
                <CategoryDropdown
                  value={slot.category}
                  categories={categories}
                  onSelect={(c) => setCategory(idx, c)}
                />

                <span className="text-xs" style={{ color: "#1e293b" }}>→</span>

                {/* Custom topic editor / auto indicator */}
                <div className="flex-1 min-w-0 flex items-center gap-2">
                  {editingIdx === idx ? (
                    <>
                      <input
                        autoFocus
                        value={draft}
                        onChange={(e) => setDraft(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") commitEdit();
                          if (e.key === "Escape") cancelEdit();
                        }}
                        className="flex-1 min-w-0 bg-transparent text-sm text-white outline-none border-b pb-0.5"
                        style={{ borderColor: "#4FC3F7" }}
                        placeholder="Enter a specific topic to pin for this slot…"
                      />
                      <button onClick={commitEdit}
                        className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0"
                        style={{ background: "rgba(34,197,94,0.15)", color: "#4ade80" }}>
                        <Check size={13} />
                      </button>
                      <button onClick={cancelEdit}
                        className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0"
                        style={{ background: "rgba(239,68,68,0.1)", color: "#f87171" }}>
                        <X size={13} />
                      </button>
                    </>
                  ) : hasCustom ? (
                    <>
                      <span className="text-xs px-2 py-0.5 rounded font-semibold shrink-0"
                        style={{ background: "rgba(79,195,247,0.1)", color: "#4FC3F7",
                          border: "1px solid rgba(79,195,247,0.25)" }}>
                        PINNED
                      </span>
                      <p className="text-sm text-white truncate flex-1">{slot.custom_topic}</p>
                      <button onClick={() => startEdit(idx)}
                        className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0 transition-all"
                        style={{ background: "rgba(79,195,247,0.08)", color: "#4FC3F7" }}>
                        <Pencil size={12} />
                      </button>
                      <button onClick={() => clearCustom(idx)}
                        className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0 transition-all"
                        style={{ background: "rgba(239,68,68,0.08)", color: "#f87171" }}>
                        <X size={12} />
                      </button>
                    </>
                  ) : (
                    <>
                      <p className="text-sm italic flex-1" style={{ color: "#475569" }}>
                        Auto — trending {cat?.label ?? ""} from Google Trends
                      </p>
                      <button onClick={() => startEdit(idx)}
                        className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs transition-all shrink-0"
                        style={{ background: "rgba(79,195,247,0.06)",
                          border: "1px solid rgba(79,195,247,0.15)", color: "#4FC3F7" }}>
                        <Pencil size={10} /> Pin topic
                      </button>
                    </>
                  )}
                </div>
              </div>

              {cat && (
                <p className="text-xs mt-2 ml-32"
                  style={{ color: "#334155", borderLeft: `2px solid ${cat.color}25`, paddingLeft: "8px" }}>
                  {cat.description}
                </p>
              )}
            </div>
          );
        })}
      </div>

      <p className="text-xs" style={{ color: "#334155" }}>
        Saved to{" "}
        <code className="font-mono text-[11px]" style={{ color: "#475569" }}>topic_config.json</code>
        {" "}— takes effect on the next pipeline run.
      </p>
    </div>
  );
}
