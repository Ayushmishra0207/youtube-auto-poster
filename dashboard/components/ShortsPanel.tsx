"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, authedMediaUrl, authHeaders } from "@/lib/api";
import type { ShortMeta } from "@/lib/types";
import { Play, X, Upload, ExternalLink, CheckCircle, Sparkles, Newspaper, Globe2, TrendingUp, ChevronDown, Check } from "lucide-react";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface ContentType {
  label: string;
  emoji: string;
  color: string;
}

const CONTENT_TYPES: Record<string, ContentType> = {
  news:           { label: "News",           emoji: "📰", color: "#4FC3F7" },
  funny:          { label: "Funny",          emoji: "😂", color: "#facc15" },
  story:          { label: "Story",          emoji: "📖", color: "#a78bfa" },
  short_story:    { label: "Short Story",    emoji: "✍️", color: "#c084fc" },
  motivational:   { label: "Motivational",   emoji: "🔥", color: "#fb923c" },
  entertainment:  { label: "Entertainment",  emoji: "🎭", color: "#f472b6" },
  bollywood:      { label: "Bollywood",      emoji: "🎬", color: "#e879f9" },
  history:        { label: "History",        emoji: "🏛️", color: "#94a3b8" },
  imagination:    { label: "Imagination",    emoji: "💭", color: "#818cf8" },
  devotional:     { label: "Devotional",     emoji: "🕉️", color: "#fbbf24" },
  sports:         { label: "Sports",         emoji: "🏆", color: "#4ade80" },
  tech:           { label: "Tech",           emoji: "🔬", color: "#22d3ee" },
  comedy_skit:    { label: "Comedy Skit",    emoji: "🎪", color: "#f59e0b" },
  horror_mystery: { label: "Horror/Mystery", emoji: "👻", color: "#64748b" },
  books:          { label: "Books",          emoji: "📚", color: "#60a5fa" },
  poetry:         { label: "Poetry",         emoji: "🪶", color: "#f0abfc" },
};

const CONTENT_TYPE_GRID_WIDTH = 380;

function ContentTypeDropdown({ value, onSelect }: { value: string; onSelect: (key: string) => void }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState({ top: 0, left: 0 });
  const btnRef = useRef<HTMLButtonElement>(null);
  const current = CONTENT_TYPES[value] ?? CONTENT_TYPES.news;

  const handleOpen = () => {
    if (btnRef.current) {
      const r = btnRef.current.getBoundingClientRect();
      // Keep the (wider, 2-column) panel on-screen even when the button
      // sits near the right edge, instead of letting it overflow the viewport.
      const left = Math.min(r.left, window.innerWidth - CONTENT_TYPE_GRID_WIDTH - 16);
      setPos({ top: r.bottom + 4, left: Math.max(8, left) });
    }
    setOpen((o) => !o);
  };

  return (
    <div>
      <button
        ref={btnRef}
        onClick={handleOpen}
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-all"
        style={{
          background: `${current.color}18`,
          border: `1px solid ${current.color}40`,
          color: current.color,
        }}
      >
        <span>{current.emoji}</span>
        <span>{current.label}</span>
        <ChevronDown size={12} className={`transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && createPortal(
        <>
          <div style={{ position: "fixed", inset: 0, zIndex: 9998 }} onClick={() => setOpen(false)} />
          <div
            style={{
              position: "fixed",
              top: pos.top,
              left: pos.left,
              width: CONTENT_TYPE_GRID_WIDTH,
              // All 16 content types fit in this 2-column grid at once — no
              // scrolling needed on any normal screen. maxHeight/overflow
              // stay only as a safety net for very short viewports.
              maxHeight: "80vh",
              overflowY: "auto",
              zIndex: 9999,
              background: "#080c18",
              border: "1px solid rgba(79,195,247,0.25)",
              borderRadius: "12px",
              boxShadow: "0 20px 60px rgba(0,0,0,0.9)",
              padding: "8px",
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: "4px",
            }}
          >
            {Object.entries(CONTENT_TYPES).map(([key, ct]) => (
              <button
                key={key}
                onClick={() => { onSelect(key); setOpen(false); }}
                style={{
                  width: "100%",
                  display: "flex",
                  alignItems: "center",
                  gap: "8px",
                  padding: "8px 10px",
                  fontSize: "13px",
                  textAlign: "left",
                  borderRadius: "8px",
                  background: key === value ? "rgba(255,255,255,0.05)" : "transparent",
                  border: "none",
                  cursor: "pointer",
                  color: key === value ? ct.color : "#e2e8f0",
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.06)")}
                onMouseLeave={(e) => (e.currentTarget.style.background = key === value ? "rgba(255,255,255,0.05)" : "transparent")}
              >
                <span>{ct.emoji}</span>
                <span style={{ flex: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{ct.label}</span>
                {key === value && <Check size={12} style={{ flexShrink: 0, color: ct.color }} />}
              </button>
            ))}
          </div>
        </>,
        document.body
      )}
    </div>
  );
}

const FEEDS: { id: "india" | "world" | "business"; label: string; icon: React.ReactNode }[] = [
  { id: "india",    label: "India",    icon: <Newspaper size={13} /> },
  { id: "world",    label: "World",    icon: <Globe2 size={13} /> },
  { id: "business", label: "Business", icon: <TrendingUp size={13} /> },
];

function StatusBadge({ status }: { status: ShortMeta["status"] }) {
  const map: Record<string, { cls: string; label: string }> = {
    ready:      { cls: "badge-ready",      label: "Ready" },
    uploaded:   { cls: "badge-uploaded",   label: "Uploaded" },
    generating: { cls: "badge-generating", label: "Generating…" },
    pending:    { cls: "badge-pending",    label: "Pending" },
    failed:     { cls: "badge-failed",     label: "Failed" },
  };
  const { cls, label } = map[status] ?? { cls: "badge-pending", label: status };
  return <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${cls}`}>{label}</span>;
}

function UploadButton({
  short,
  onUploaded,
}: {
  short: ShortMeta;
  onUploaded: (index: number, videoId: string, url: string) => void;
}) {
  const [uploading, setUploading] = useState(false);
  const [err, setErr]             = useState("");

  const handle = async () => {
    setUploading(true);
    setErr("");
    try {
      const res  = await fetch(`${BASE}/api/shorts/upload/${short.date}/${short.index}`, { method: "POST", headers: authHeaders() });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Upload failed");
      onUploaded(short.index, data.video_id, data.url);
    } catch (e: any) {
      setErr(e.message || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  if (short.status === "uploaded" && short.youtube_url) {
    return (
      <a
        href={short.youtube_url}
        target="_blank"
        rel="noreferrer"
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium w-full justify-center transition-all"
        style={{ background: "rgba(34,197,94,0.12)", border: "1px solid rgba(34,197,94,0.3)", color: "#4ade80" }}
      >
        <CheckCircle size={12} />
        View on YouTube
        <ExternalLink size={10} />
      </a>
    );
  }

  if (!short.has_video) return null;

  return (
    <div className="space-y-1">
      <button
        onClick={handle}
        disabled={uploading}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium w-full justify-center transition-all disabled:opacity-50"
        style={{
          background: uploading ? "rgba(79,195,247,0.06)" : "rgba(79,195,247,0.1)",
          border: "1px solid rgba(79,195,247,0.25)",
          color: "#4FC3F7",
        }}
      >
        {uploading ? (
          <>
            <div className="w-3 h-3 border border-cyan-400 border-t-transparent rounded-full animate-spin" />
            Uploading…
          </>
        ) : (
          <>
            <Upload size={12} />
            Upload to YouTube
          </>
        )}
      </button>
      {err && <p className="text-[10px] text-center text-red-400 leading-tight">{err}</p>}
    </div>
  );
}

function ShortCard({
  short,
  onPlay,
  onUploaded,
}: {
  short: ShortMeta;
  onPlay: (s: ShortMeta) => void;
  onUploaded: (index: number, videoId: string, url: string) => void;
}) {
  return (
    <div className="glass glass-hover rounded-2xl overflow-hidden transition-all duration-200 group flex flex-col">
      {/* Vertical thumbnail (9:16) */}
      <div
        className="relative w-full flex items-center justify-center overflow-hidden"
        style={{ aspectRatio: "9/16", background: "linear-gradient(135deg, #1a1a2e 0%, #16213e 100%)" }}
      >
        {short.has_thumbnail ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={authedMediaUrl(short.thumbnail_url)}
            alt={short.title}
            className="w-full h-full object-cover"
          />
        ) : (
          <Sparkles size={28} style={{ color: "rgba(79,195,247,0.3)" }} />
        )}

        <div
          className="absolute top-2 left-2 flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded font-semibold"
          style={{ background: "rgba(220,30,30,0.85)", color: "white", backdropFilter: "blur(4px)" }}
        >
          #Shorts
        </div>

        {short.status === "uploaded" && (
          <div
            className="absolute top-2 right-2 flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded font-semibold"
            style={{ background: "rgba(34,197,94,0.85)", color: "white", backdropFilter: "blur(4px)" }}
          >
            <CheckCircle size={9} />
            Live
          </div>
        )}

        {short.has_video && (
          <button
            onClick={() => onPlay(short)}
            className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-all duration-200"
            style={{ background: "rgba(0,0,0,0.5)" }}
          >
            <div
              className="w-12 h-12 rounded-full flex items-center justify-center"
              style={{ background: "rgba(79,195,247,0.9)", boxShadow: "0 0 20px rgba(79,195,247,0.4)" }}
            >
              <Play size={20} className="text-navy-950 ml-0.5" fill="currentColor" />
            </div>
          </button>
        )}
      </div>

      <div className="p-4 space-y-2 flex-1 flex flex-col">
        <div className="flex items-start justify-between gap-2">
          <p className="text-sm font-medium text-white leading-snug line-clamp-2 flex-1">{short.title}</p>
          <StatusBadge status={short.status} />
        </div>
        <span className="text-xs font-mono" style={{ color: "#64748b" }}>#{short.index}</span>
        <div className="mt-auto pt-2">
          <UploadButton short={short} onUploaded={onUploaded} />
        </div>
      </div>
    </div>
  );
}

function GeneratePanel({ onGenerated }: { onGenerated: () => void }) {
  const [feed, setFeed]           = useState<"india" | "world" | "business">("india");
  const [customTopic, setCustomTopic] = useState("");
  const [contentType, setContentType] = useState("news");
  const [generating, setGenerating] = useState(false);
  const [msg, setMsg]             = useState<{ text: string; ok: boolean } | null>(null);

  const usingCustomTopic = customTopic.trim().length > 0;

  const handle = async () => {
    setGenerating(true);
    setMsg(null);
    try {
      const res: any = await api.generateShort(feed, customTopic.trim(), contentType);
      if (res?.ok === false) {
        setMsg({ text: res.message ?? "Could not start generation", ok: false });
      } else {
        setMsg({ text: "Generating… this takes a few minutes.", ok: true });
        onGenerated();
      }
    } catch {
      setMsg({ text: "Failed to reach API", ok: false });
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="glass rounded-2xl p-5 space-y-3">
      <div className="flex items-center gap-2">
        <Sparkles size={16} style={{ color: "#4FC3F7" }} />
        <h2 className="text-sm font-semibold text-white">Generate a Short now</h2>
      </div>
      <p className="text-xs" style={{ color: "var(--muted)" }}>
        Pulls real breaking headlines from the last 48 hours, writes a 60-second Hindi script at 1.5x voice speed, and renders a vertical video.
      </p>

      <div className="flex flex-wrap items-center gap-2">
        {FEEDS.map((f) => (
          <button
            key={f.id}
            onClick={() => setFeed(f.id)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all"
            style={{
              background: feed === f.id ? "rgba(79,195,247,0.15)" : "rgba(255,255,255,0.04)",
              border: `1px solid ${feed === f.id ? "rgba(79,195,247,0.4)" : "var(--border)"}`,
              color: feed === f.id ? "#4FC3F7" : "#94a3b8",
              opacity: usingCustomTopic ? 0.4 : 1,
            }}
          >
            {f.icon}
            {f.label}
          </button>
        ))}
      </div>

      <div
        className="rounded-xl p-3 space-y-2"
        style={{ background: "rgba(255,255,255,0.03)", border: "1px solid var(--border)" }}
      >
        <p className="text-xs font-semibold" style={{ color: "#64748b" }}>OR — CUSTOM TOPIC</p>
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={customTopic}
            onChange={(e) => setCustomTopic(e.target.value)}
            placeholder="Type any topic, e.g. 'IPL 2026 auction shockers'…"
            className="flex-1 min-w-[200px] bg-transparent text-sm text-white outline-none border-b pb-1"
            style={{ borderColor: usingCustomTopic ? "#4FC3F7" : "var(--border)" }}
          />
          <ContentTypeDropdown value={contentType} onSelect={setContentType} />
        </div>
      </div>

      <div className="flex justify-end">
        <button
          onClick={handle}
          disabled={generating}
          className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-semibold transition-all disabled:opacity-50"
          style={{
            background: "linear-gradient(135deg, rgba(79,195,247,0.2) 0%, rgba(124,58,237,0.2) 100%)",
            border: "1px solid var(--border-strong)",
            color: "#4FC3F7",
          }}
        >
          {generating ? (
            <div className="w-3 h-3 border border-cyan-400 border-t-transparent rounded-full animate-spin" />
          ) : (
            <Sparkles size={13} />
          )}
          {generating ? "Starting…" : "Generate Short"}
        </button>
      </div>
      {msg && (
        <p className="text-xs" style={{ color: msg.ok ? "#4ade80" : "#f87171" }}>{msg.text}</p>
      )}
    </div>
  );
}

export default function ShortsPanel() {
  const [shorts, setShorts]       = useState<ShortMeta[]>([]);
  const [playing, setPlaying]     = useState<ShortMeta | null>(null);
  const [loading, setLoading]     = useState(true);
  const [isGenerating, setIsGenerating] = useState(false);

  const refresh = () => api.shorts().then((r: any) => {
    setShorts(r.shorts);
    setIsGenerating(r.is_generating);
    setLoading(false);
  });

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 8000);
    return () => clearInterval(id);
  }, []);

  const handleUploaded = (index: number, videoId: string, url: string) => {
    setShorts((prev) =>
      prev.map((s) => (s.index === index ? { ...s, status: "uploaded", youtube_id: videoId, youtube_url: url } : s))
    );
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="w-6 h-6 border-2 border-cyan-DEFAULT border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  const uploaded = shorts.filter((s) => s.status === "uploaded").length;
  const ready    = shorts.filter((s) => s.status === "ready").length;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">YouTube Shorts</h1>
        <p className="text-sm mt-1" style={{ color: "var(--muted)" }}>
          {shorts.length} generated · {uploaded} uploaded · {ready} ready to upload
          {isGenerating && <span style={{ color: "#4FC3F7" }}> · generating…</span>}
        </p>
      </div>

      <GeneratePanel onGenerated={refresh} />

      {shorts.length === 0 ? (
        <div
          className="glass rounded-2xl p-12 text-center"
          style={{ borderStyle: "dashed", borderColor: "rgba(79,195,247,0.15)" }}
        >
          <p className="text-sm" style={{ color: "var(--muted)" }}>
            No Shorts generated today yet. 3 are generated automatically after the daily pipeline run, or hit{" "}
            <strong style={{ color: "#4FC3F7" }}>Generate Short</strong> above to make one now.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
          {shorts.map((s) => (
            <ShortCard key={s.index} short={s} onPlay={setPlaying} onUploaded={handleUploaded} />
          ))}
        </div>
      )}

      {playing && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ background: "rgba(0,0,0,0.85)" }}
          onClick={() => setPlaying(null)}
        >
          <div className="relative" style={{ maxHeight: "90vh" }} onClick={(e) => e.stopPropagation()}>
            <button
              onClick={() => setPlaying(null)}
              className="absolute -top-10 right-0 w-8 h-8 rounded-full flex items-center justify-center"
              style={{ background: "rgba(255,255,255,0.1)", color: "white" }}
            >
              <X size={16} />
            </button>
            <video
              src={authedMediaUrl(playing.video_url)}
              controls
              autoPlay
              className="rounded-xl"
              style={{ maxHeight: "90vh", aspectRatio: "9/16" }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
