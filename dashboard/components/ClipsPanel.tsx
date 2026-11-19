"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, authedMediaUrl, uploadClip } from "@/lib/api";
import type { ClipJob, ClipOptions, ClipRequest, ClipResult } from "@/lib/types";
import {
  Scissors, Flame, Laugh, Clapperboard, Sunset, BookOpen, Wand2, Link2, ClipboardPaste,
  Download, Copy, Upload, ExternalLink, CheckCircle, Trash2, Play, Square, Info, Sparkles, Check,
} from "lucide-react";

const MODE_ICON: Record<string, React.ReactNode> = {
  gta6_action:    <Flame size={16} />,
  gta6_funny:     <Laugh size={16} />,
  gta6_trailer:   <Clapperboard size={16} />,
  gta6_cinematic: <Sunset size={16} />,
  gta6_story:     <BookOpen size={16} />,
  general:        <Wand2 size={16} />,
};

const STAGE_LABEL: Record<string, string> = {
  queued: "Queued", download: "Downloading", analyze: "Analysing",
  transcribe: "Transcribing", plan: "Picking moments", render: "Rendering",
  done: "Done", failed: "Failed",
};

const DEFAULT_REQ: ClipRequest = {
  url: "", mode: "gta6_action", num_clips: 3, length: "auto", layout: "blur_fit",
  caption_style: "auto", language: "auto", title_language: "hinglish", hook_text: true,
  watermark: "@bitnomad1", audio_mode: "original", credit_source: true, use_ai: true,
};

const fmtTime = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

// ── Small UI pieces ─────────────────────────────────────────────────────────────

function Segmented<T extends string>({
  value, options, onChange,
}: { value: T; options: { value: T; label: string; disabled?: boolean; title?: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="flex flex-wrap gap-1 p-1 rounded-lg" style={{ background: "rgba(255,255,255,0.03)", border: "1px solid var(--border)" }}>
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            disabled={o.disabled}
            title={o.title}
            onClick={() => onChange(o.value)}
            className="px-2.5 py-1 rounded-md text-xs font-medium transition-all disabled:opacity-35 disabled:cursor-not-allowed"
            style={{
              background: active ? "rgba(79,195,247,0.15)" : "transparent",
              color: active ? "#4FC3F7" : "#94a3b8",
              boxShadow: active ? "inset 0 0 0 1px rgba(79,195,247,0.35)" : "none",
            }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline gap-2">
        <p className="text-xs font-semibold text-slate-300">{label}</p>
        {hint && <p className="text-[10px]" style={{ color: "var(--muted)" }}>{hint}</p>}
      </div>
      {children}
    </div>
  );
}

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button type="button" onClick={() => onChange(!checked)} className="flex items-center gap-2 text-xs text-slate-300">
      <span
        className="w-8 h-[18px] rounded-full relative transition-colors shrink-0"
        style={{ background: checked ? "rgba(79,195,247,0.55)" : "rgba(255,255,255,0.1)" }}
      >
        <span
          className="absolute top-[2px] w-[14px] h-[14px] rounded-full bg-white transition-all"
          style={{ left: checked ? 16 : 2 }}
        />
      </span>
      {label}
    </button>
  );
}

// ── Clip card ───────────────────────────────────────────────────────────────────

function ClipCard({ jobId, clip, onUploaded }: { jobId: string; clip: ClipResult; onUploaded: () => void }) {
  const [playing, setPlaying]     = useState(false);
  const [copied, setCopied]       = useState(false);
  const [uploading, setUploading] = useState(false);
  const [err, setErr]             = useState("");

  const copy = async () => {
    await navigator.clipboard.writeText(`${clip.title}\n\n${clip.description}`);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const upload = async () => {
    if (!confirm(`Upload "${clip.title}" to YouTube as a public Short?`)) return;
    setUploading(true);
    setErr("");
    try {
      await uploadClip(jobId, clip.index);
      onUploaded();
    } catch (e: any) {
      setErr(e.message || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const scoreColor = clip.score >= 80 ? "#4ade80" : clip.score >= 60 ? "#fbbf24" : "#94a3b8";

  return (
    <div className="glass rounded-2xl overflow-hidden flex flex-col">
      <div className="relative bg-black" style={{ aspectRatio: "9 / 16" }}>
        {playing ? (
          <video src={authedMediaUrl(clip.video_url)} controls autoPlay playsInline className="w-full h-full object-contain" />
        ) : (
          <button onClick={() => setPlaying(true)} className="group absolute inset-0 w-full h-full" aria-label={`Play clip ${clip.index}`}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={authedMediaUrl(clip.thumbnail_url)} alt="" className="w-full h-full object-cover" />
            <span className="absolute inset-0 flex items-center justify-center bg-black/20 group-hover:bg-black/40 transition-colors">
              <span className="w-12 h-12 rounded-full flex items-center justify-center" style={{ background: "rgba(79,195,247,0.9)" }}>
                <Play size={20} className="text-slate-900 ml-0.5" fill="currentColor" />
              </span>
            </span>
          </button>
        )}
        <span className="absolute top-2 left-2 text-[10px] font-bold px-1.5 py-0.5 rounded-md tabular-nums"
              style={{ background: "rgba(0,0,0,0.7)", color: scoreColor }}
              title={clip.picked_by === "ai" ? "AI virality estimate" : "Signal score (audio + scene + speech)"}>
          {clip.picked_by === "ai" && <Sparkles size={9} className="inline mr-0.5 -mt-0.5" />}{clip.score}
        </span>
        <span className="absolute top-2 right-2 text-[10px] px-1.5 py-0.5 rounded-md tabular-nums text-slate-200" style={{ background: "rgba(0,0,0,0.7)" }}>
          {Math.round(clip.duration)}s
        </span>
      </div>

      <div className="p-3 flex flex-col gap-2 flex-1">
        <p className="text-sm font-semibold text-white leading-snug line-clamp-2">{clip.title}</p>
        <p className="text-[11px] leading-snug line-clamp-2" style={{ color: "var(--muted)" }}>{clip.reason}</p>
        <p className="text-[10px] tabular-nums" style={{ color: "var(--muted)" }}>
          From {fmtTime(clip.start)} → {fmtTime(clip.end)}
        </p>

        <div className="mt-auto grid grid-cols-2 gap-1.5 pt-1">
          <a
            href={authedMediaUrl(`${clip.video_url}?download=1`)}
            className="flex items-center justify-center gap-1 px-2 py-1.5 rounded-lg text-xs font-medium"
            style={{ background: "rgba(255,255,255,0.05)", border: "1px solid var(--border)", color: "#cbd5e1" }}
          >
            <Download size={12} /> MP4
          </a>
          <button
            onClick={copy}
            className="flex items-center justify-center gap-1 px-2 py-1.5 rounded-lg text-xs font-medium"
            style={{ background: "rgba(255,255,255,0.05)", border: "1px solid var(--border)", color: "#cbd5e1" }}
          >
            {copied ? <Check size={12} /> : <Copy size={12} />} {copied ? "Copied" : "Text"}
          </button>
        </div>

        {clip.youtube_url ? (
          <a href={clip.youtube_url} target="_blank" rel="noreferrer"
             className="flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-lg text-xs font-medium"
             style={{ background: "rgba(34,197,94,0.12)", border: "1px solid rgba(34,197,94,0.3)", color: "#4ade80" }}>
            <CheckCircle size={12} /> On YouTube <ExternalLink size={10} />
          </a>
        ) : (
          <button onClick={upload} disabled={uploading}
                  className="flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-lg text-xs font-medium disabled:opacity-50"
                  style={{ background: "rgba(79,195,247,0.1)", border: "1px solid rgba(79,195,247,0.25)", color: "#4FC3F7" }}>
            {uploading
              ? <><span className="w-3 h-3 border border-cyan-400 border-t-transparent rounded-full animate-spin" /> Uploading…</>
              : <><Upload size={12} /> Upload as Short</>}
          </button>
        )}
        {err && <p className="text-[10px] text-red-400 leading-tight">{err}</p>}
      </div>
    </div>
  );
}

// ── Job card ────────────────────────────────────────────────────────────────────

function JobCard({ job, modeLabel, onChange }: { job: ClipJob; modeLabel: string; onChange: () => void }) {
  const active = job.state === "running" || job.state === "queued";
  const [busy, setBusy] = useState(false);

  const cancel = async () => {
    setBusy(true);
    try { await api.cancelClipJob(job.job_id); } finally { setBusy(false); onChange(); }
  };
  const remove = async () => {
    if (!confirm("Delete this job and all its clips from disk?")) return;
    setBusy(true);
    try { await api.deleteClipJob(job.job_id); } finally { setBusy(false); onChange(); }
  };

  return (
    <div className="glass rounded-2xl p-4 space-y-4">
      <div className="flex items-start gap-3">
        <div className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
             style={{ background: "rgba(124,58,237,0.15)", color: "#a78bfa" }}>
          {MODE_ICON[job.request?.mode] ?? <Scissors size={16} />}
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-white truncate">{job.source?.title || job.request?.url}</p>
          <p className="text-xs truncate" style={{ color: "var(--muted)" }}>
            {modeLabel}
            {job.source?.channel ? ` · ${job.source.channel}` : ""}
            {job.source?.duration ? ` · ${fmtTime(job.source.duration)}` : ""}
            {` · ${new Date(job.created_at * 1000).toLocaleString()}`}
          </p>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {job.state === "done" && <span className="text-xs px-2 py-0.5 rounded-full font-medium badge-ready">{job.clips.length} clips</span>}
          {job.state === "failed" && <span className="text-xs px-2 py-0.5 rounded-full font-medium badge-failed">Failed</span>}
          {active ? (
            <button onClick={cancel} disabled={busy} title="Cancel"
                    className="w-7 h-7 rounded-lg flex items-center justify-center hover:bg-white/10 disabled:opacity-40" style={{ color: "#f87171" }}>
              <Square size={13} />
            </button>
          ) : (
            <button onClick={remove} disabled={busy} title="Delete"
                    className="w-7 h-7 rounded-lg flex items-center justify-center hover:bg-white/10 disabled:opacity-40" style={{ color: "#64748b" }}>
              <Trash2 size={14} />
            </button>
          )}
        </div>
      </div>

      {active && (
        <div className="space-y-1.5">
          <div className="flex justify-between text-xs">
            <span className="text-slate-300">{STAGE_LABEL[job.stage] ?? job.stage} — {job.message}</span>
            <span className="tabular-nums" style={{ color: "#4FC3F7" }}>{Math.round(job.progress)}%</span>
          </div>
          <div className="h-1.5 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.07)" }}>
            <div className="h-full rounded-full transition-all duration-700"
                 style={{ width: `${Math.max(3, job.progress)}%`, background: "linear-gradient(90deg,#4FC3F7,#7c3aed)" }} />
          </div>
        </div>
      )}

      {job.state === "failed" && job.error && (
        <p className="text-xs rounded-lg px-3 py-2 whitespace-pre-wrap break-words"
           style={{ background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.25)", color: "#fca5a5" }}>
          {job.error}
        </p>
      )}

      {job.clips.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
          {job.clips.map((c) => <ClipCard key={c.index} jobId={job.job_id} clip={c} onUploaded={onChange} />)}
        </div>
      )}
    </div>
  );
}

// ── Panel ───────────────────────────────────────────────────────────────────────

export default function ClipsPanel() {
  const [opts, setOpts]       = useState<ClipOptions | null>(null);
  const [req, setReq]         = useState<ClipRequest>(DEFAULT_REQ);
  const [jobs, setJobs]       = useState<ClipJob[]>([]);
  const [loadErr, setLoadErr] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [msg, setMsg]         = useState<{ text: string; ok: boolean } | null>(null);

  const set = <K extends keyof ClipRequest>(k: K, v: ClipRequest[K]) => setReq((r) => ({ ...r, [k]: v }));

  const refresh = useCallback(async () => {
    try {
      const r = await api.clipJobs();
      setJobs(r.jobs);
      setLoadErr("");
    } catch {
      setLoadErr("Can't reach the API — is the backend running?");
    }
  }, []);

  useEffect(() => {
    api.clipOptions().then((o) => {
      setOpts(o);
      setReq((r) => ({ ...r, mode: o.default_mode }));
    }).catch(() => setLoadErr("Can't reach the API — is the backend running?"));
    refresh();
  }, [refresh]);

  const anyActive = jobs.some((j) => j.state === "running" || j.state === "queued");
  useEffect(() => {
    const id = setInterval(refresh, anyActive ? 2500 : 15000);
    return () => clearInterval(id);
  }, [anyActive, refresh]);

  const modeLabels = useMemo(
    () => Object.fromEntries((opts?.modes ?? []).map((m) => [m.key, m.label])),
    [opts],
  );
  const selectedMode = opts?.modes.find((m) => m.key === req.mode);

  const paste = async () => {
    try { set("url", (await navigator.clipboard.readText()).trim()); } catch { /* clipboard blocked */ }
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!req.url.trim()) return;
    setSubmitting(true);
    setMsg(null);
    try {
      const r = await api.createClipJob({ ...req, url: req.url.trim() });
      setMsg({ text: r.message, ok: r.ok });
      if (r.ok) {
        set("url", "");
        refresh();
      }
    } catch (e: any) {
      setMsg({ text: e.message?.includes("400") ? "Check the link and options" : "Failed to reach API", ok: false });
    } finally {
      setSubmitting(false);
    }
  };

  const lengthLabel = (key: string, range: [number, number] | null) =>
    key === "auto"
      ? `Auto${selectedMode ? ` (${selectedMode.min_len}–${selectedMode.max_len}s)` : ""}`
      : `${range![0]}–${range![1]}s`;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl md:text-2xl font-bold text-white flex items-center gap-2">
          <Scissors size={22} style={{ color: "#4FC3F7" }} /> Viral Clip Maker
        </h1>
        <p className="text-sm mt-1" style={{ color: "var(--muted)" }}>
          Paste a YouTube link → get vertical, captioned clips of the best moments. Built for GTA 6.
        </p>
      </div>

      {opts && !opts.available && (
        <div className="flex gap-2.5 rounded-xl p-4 text-sm leading-relaxed"
             style={{ background: "rgba(79,195,247,0.06)", border: "1px solid rgba(79,195,247,0.25)", color: "#bae6fd" }}>
          <Info size={16} className="shrink-0 mt-0.5" />
          <p>{opts.unavailable_reason}</p>
        </div>
      )}

      <form onSubmit={submit} className="glass rounded-2xl p-4 md:p-5 space-y-5"
            style={opts && !opts.available ? { opacity: 0.5, pointerEvents: "none" } : undefined}>
        {/* URL */}
        <div className="flex gap-2">
          <div className="flex-1 flex items-center gap-2 px-3 rounded-lg" style={{ background: "rgba(255,255,255,0.04)", border: "1px solid var(--border-strong)" }}>
            <Link2 size={15} className="shrink-0" style={{ color: "#64748b" }} />
            <input
              value={req.url}
              onChange={(e) => set("url", e.target.value)}
              placeholder="https://www.youtube.com/watch?v=…"
              className="flex-1 bg-transparent py-2.5 text-sm text-white outline-none min-w-0"
              inputMode="url"
              aria-label="YouTube video link"
            />
            <button type="button" onClick={paste} title="Paste from clipboard" className="shrink-0 p-1 rounded hover:bg-white/10" style={{ color: "#94a3b8" }}>
              <ClipboardPaste size={15} />
            </button>
          </div>
          <button
            type="submit"
            disabled={submitting || !req.url.trim()}
            className="px-4 md:px-5 rounded-lg text-sm font-semibold flex items-center gap-2 transition-all disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
            style={{ background: "linear-gradient(135deg,#4FC3F7 0%,#7c3aed 100%)", color: "white" }}
          >
            {submitting ? <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" /> : <Scissors size={15} />}
            <span className="hidden sm:inline">Make clips</span>
          </button>
        </div>
        {msg && <p className="text-xs -mt-3" style={{ color: msg.ok ? "#4ade80" : "#f87171" }}>{msg.text}</p>}

        {/* Mode */}
        <Field label="Mode" hint="what counts as a viral moment">
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
            {(opts?.modes ?? []).map((m) => {
              const active = m.key === req.mode;
              return (
                <button
                  key={m.key}
                  type="button"
                  onClick={() => set("mode", m.key)}
                  className="text-left p-3 rounded-xl transition-all"
                  style={{
                    background: active ? "rgba(79,195,247,0.08)" : "rgba(255,255,255,0.02)",
                    border: `1px solid ${active ? "rgba(79,195,247,0.5)" : "var(--border)"}`,
                  }}
                >
                  <div className="flex items-center gap-2 text-sm font-semibold" style={{ color: active ? "#4FC3F7" : "#e2e8f0" }}>
                    {MODE_ICON[m.key]} {m.label}
                  </div>
                  <p className="text-[11px] mt-1 leading-snug" style={{ color: "var(--muted)" }}>{m.description}</p>
                </button>
              );
            })}
          </div>
        </Field>

        <div className="grid md:grid-cols-2 gap-5">
          <Field label="Number of clips">
            <Segmented
              value={String(req.num_clips)}
              options={["1", "2", "3", "4", "5", "6", "8", "10"].map((v) => ({ value: v, label: v }))}
              onChange={(v) => set("num_clips", Number(v))}
            />
          </Field>
          <Field label="Clip length">
            <Segmented
              value={req.length}
              options={(opts?.lengths ?? []).map((l) => ({ value: l.key, label: lengthLabel(l.key, l.range) }))}
              onChange={(v) => set("length", v)}
            />
          </Field>
          <Field label="Captions" hint="word-by-word highlight">
            <Segmented
              value={req.caption_style}
              options={[{ value: "auto", label: "Auto" }, ...(opts?.caption_styles ?? []).map((s) => ({ value: s.key, label: s.label }))]}
              onChange={(v) => set("caption_style", v)}
            />
          </Field>
          <Field label="Layout">
            <Segmented
              value={req.layout}
              options={[{ value: "blur_fit", label: "Blur background (full frame)" }, { value: "center_crop", label: "Full-screen crop" }]}
              onChange={(v) => set("layout", v)}
            />
          </Field>
          <Field label="Speech language" hint="for subtitles">
            <Segmented
              value={req.language}
              options={[{ value: "auto", label: "Auto-detect" }, { value: "hi", label: "Hindi" }, { value: "en", label: "English" }]}
              onChange={(v) => set("language", v)}
            />
          </Field>
          <Field label="Title / hook language">
            <Segmented
              value={req.title_language}
              options={[{ value: "hinglish", label: "Hinglish" }, { value: "hindi", label: "Hindi" }, { value: "english", label: "English" }]}
              onChange={(v) => set("title_language", v)}
            />
          </Field>
          <Field label="Audio" hint={opts && !opts.music_available ? "add an .mp3 to assets/music to enable music" : opts?.music_track}>
            <Segmented
              value={req.audio_mode}
              options={[
                { value: "original", label: "Original" },
                { value: "original_music", label: "Original + music", disabled: !opts?.music_available },
                { value: "music_only", label: "Music only", disabled: !opts?.music_available },
              ]}
              onChange={(v) => set("audio_mode", v)}
            />
          </Field>
          <Field label="Watermark" hint="your channel handle">
            <input
              value={req.watermark}
              onChange={(e) => set("watermark", e.target.value)}
              maxLength={40}
              placeholder="@yourchannel"
              className="w-full px-3 py-2 rounded-lg text-sm text-white outline-none"
              style={{ background: "rgba(255,255,255,0.04)", border: "1px solid var(--border)" }}
            />
          </Field>
        </div>

        <div className="flex flex-wrap gap-x-6 gap-y-3 pt-1">
          <Toggle checked={req.use_ai} onChange={(v) => set("use_ai", v)} label="AI picks moments & writes titles (Claude)" />
          <Toggle checked={req.hook_text} onChange={(v) => set("hook_text", v)} label="Hook banner on top" />
          <Toggle checked={req.credit_source} onChange={(v) => set("credit_source", v)} label="Credit source in description" />
        </div>

        <div className="flex gap-2.5 rounded-xl p-3 text-[11px] leading-relaxed"
             style={{ background: "rgba(251,191,36,0.06)", border: "1px solid rgba(251,191,36,0.2)", color: "#fcd34d" }}>
          <Info size={14} className="shrink-0 mt-0.5" />
          <p>
            Every clip is reframed to 9:16 with zoom, colour grade, captions, a hook banner, your watermark and a progress bar.
            These edits make the clip your own creative work, but <b>they don&apos;t stop Content ID claims or copyright strikes</b> on someone else&apos;s video.
            The safe sources are your own gameplay, official Rockstar trailers used with your commentary, and creators who&apos;ve given you permission.
          </p>
        </div>
      </form>

      {loadErr && <p className="text-sm text-red-400">{loadErr}</p>}

      <div className="space-y-4">
        {jobs.length === 0 && !loadErr && (
          <div className="glass rounded-2xl p-8 text-center text-sm" style={{ color: "var(--muted)" }}>
            No clip jobs yet. Paste a link above to make your first clips.
          </div>
        )}
        {jobs.map((j) => (
          <JobCard key={j.job_id} job={j} modeLabel={modeLabels[j.request?.mode] ?? j.request?.mode} onChange={refresh} />
        ))}
      </div>
    </div>
  );
}
