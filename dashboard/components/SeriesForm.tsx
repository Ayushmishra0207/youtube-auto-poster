"use client";

import { useMemo, useRef, useState } from "react";
import { api, uploadClipSource } from "@/lib/api";
import type { ClipOptions, ClipRequest } from "@/lib/types";
import { Link2, Upload, ClipboardPaste, ListOrdered, FileVideo, X } from "lucide-react";

/** "1:30" / "01:02:03" / "90" → seconds; "" → 0; invalid → NaN */
function parseTime(v: string): number {
  const t = v.trim();
  if (!t) return 0;
  if (!/^\d+(:\d{1,2}){0,2}$/.test(t)) return NaN;
  return t.split(":").reduce((acc, part) => acc * 60 + Number(part), 0);
}

const fmt = (s: number) => {
  s = Math.round(s);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
};

/** Same rule as clipper/series.plan_parts: a tail under 10 s joins the previous part. */
function countParts(total: number, len: number): number {
  if (total <= 0) return 0;
  let n = Math.ceil(total / len - 1e-9);
  if (n > 1 && total - len * (n - 1) < 10) n -= 1;
  return n;
}

const chip = (active: boolean) => ({
  background: active ? "rgba(79,195,247,0.15)" : "transparent",
  color: active ? "#4FC3F7" : "#94a3b8",
  boxShadow: active ? "inset 0 0 0 1px rgba(79,195,247,0.35)" : "none",
});

export default function SeriesForm({ opts, onStarted }: { opts: ClipOptions | null; onStarted: () => void }) {
  const [sourceKind, setSourceKind] = useState<"link" | "file">("link");
  const [url, setUrl] = useState("");
  const [uploaded, setUploaded] = useState<{ source_file: string; filename: string; duration: number } | null>(null);
  const [uploadPct, setUploadPct] = useState<number | null>(null);
  const [partSeconds, setPartSeconds] = useState(60);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [seriesTitle, setSeriesTitle] = useState("");
  const [partLabel, setPartLabel] = useState("Part {n}");
  const [captions, setCaptions] = useState("none");
  const [language, setLanguage] = useState("auto");
  const [layout, setLayout] = useState<"blur_fit" | "center_crop">("blur_fit");
  const [watermark, setWatermark] = useState("@bitnomad1");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const fromS = parseTime(from), toS = parseTime(to);
  const timeError = Number.isNaN(fromS) || Number.isNaN(toS)
    ? "Use times like 1:30 or 1:02:03"
    : toS && toS <= fromS ? "'To' must be after 'From'" : "";

  const estimate = useMemo(() => {
    if (!uploaded || timeError) return "";
    const end = toS ? Math.min(toS, uploaded.duration) : uploaded.duration;
    const n = countParts(end - fromS, partSeconds);
    return n > 0 ? `${fmt(end - fromS)} of video → ${n} part${n > 1 ? "s" : ""}` : "";
  }, [uploaded, fromS, toS, partSeconds, timeError]);

  const pickFile = async (f: File | undefined) => {
    if (!f) return;
    setMsg(null);
    setUploaded(null);
    setUploadPct(0);
    try {
      setUploaded(await uploadClipSource(f, setUploadPct));
    } catch (e: any) {
      setMsg({ text: e?.message || "Upload failed", ok: false });
    } finally {
      setUploadPct(null);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!opts) return setMsg({ text: "Settings are still loading — try again in a few seconds.", ok: false });
    if (!opts.available) return setMsg({ text: opts.unavailable_reason, ok: false });
    if (timeError) return setMsg({ text: timeError, ok: false });
    if (sourceKind === "link" && !url.trim()) return setMsg({ text: "Paste a video link first.", ok: false });
    if (sourceKind === "file" && !uploaded) return setMsg({ text: "Upload a video file first.", ok: false });
    setBusy(true);
    setMsg(null);
    const req: ClipRequest = {
      url: sourceKind === "link" ? url.trim() : "",
      mode: opts.default_mode, num_clips: 1, length: "auto", layout, caption_style: captions,
      language, title_language: "hinglish", hook_text: false, watermark,
      audio_mode: "original", credit_source: sourceKind === "link", use_ai: false,
      job_type: "series", part_seconds: partSeconds, range_start: fromS, range_end: toS,
      series_title: seriesTitle, part_label: partLabel, source_file: sourceKind === "file" ? uploaded!.source_file : "",
    };
    try {
      const r = await api.createClipJob(req);
      setMsg({ text: r.ok ? "Started — the parts appear below as they finish." : r.message, ok: r.ok });
      if (r.ok) { setUrl(""); onStarted(); }
    } catch (e: any) {
      const m = String(e?.message ?? "");
      setMsg({
        text: m.includes("503") ? "Clip Maker isn't available on this server — it runs on your PC."
          : m.includes("400") ? "Check the link, file and times" : `Couldn't start: ${m || "server unreachable"}`,
        ok: false,
      });
    } finally {
      setBusy(false);
    }
  };

  const inputCls = "w-full px-3 py-2 rounded-lg text-sm text-white outline-none";
  const inputStyle = { background: "rgba(255,255,255,0.04)", border: "1px solid var(--border)" };

  return (
    <form onSubmit={submit} className="glass rounded-2xl p-4 md:p-5 space-y-5"
          style={opts && !opts.available ? { opacity: 0.5, pointerEvents: "none" } : undefined}>
      {/* Source: link or file */}
      <div className="space-y-2">
        <div className="flex gap-1 p-1 rounded-lg w-fit" style={{ background: "rgba(255,255,255,0.03)", border: "1px solid var(--border)" }}>
          {([["link", "YouTube link", <Link2 key="l" size={13} />], ["file", "Upload a video", <Upload key="u" size={13} />]] as const).map(([k, label, icon]) => (
            <button key={k} type="button" onClick={() => { setSourceKind(k); setMsg(null); }}
                    className="flex items-center gap-1.5 px-3 py-1 rounded-md text-xs font-medium" style={chip(sourceKind === k)}>
              {icon}{label}
            </button>
          ))}
        </div>

        {sourceKind === "link" ? (
          <div className="flex items-center gap-2 px-3 rounded-lg" style={{ background: "rgba(255,255,255,0.04)", border: "1px solid var(--border-strong)" }}>
            <Link2 size={15} className="shrink-0" style={{ color: "#64748b" }} />
            <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://www.youtube.com/watch?v=…"
                   className="flex-1 bg-transparent py-2.5 text-sm text-white outline-none min-w-0" inputMode="url" aria-label="Video link" />
            <button type="button" title="Paste from clipboard" className="shrink-0 p-1 rounded hover:bg-white/10" style={{ color: "#94a3b8" }}
                    onClick={async () => { try { setUrl((await navigator.clipboard.readText()).trim()); } catch { /* blocked */ } }}>
              <ClipboardPaste size={15} />
            </button>
          </div>
        ) : (
          <div className="rounded-lg p-3 flex items-center gap-3" style={{ background: "rgba(255,255,255,0.03)", border: "1px dashed var(--border-strong)" }}>
            <input ref={fileRef} type="file" accept="video/*,.mkv" className="hidden" onChange={(e) => pickFile(e.target.files?.[0])} />
            {uploaded ? (
              <>
                <FileVideo size={18} style={{ color: "#4FC3F7" }} />
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-white truncate">{uploaded.filename}</p>
                  <p className="text-xs" style={{ color: "var(--muted)" }}>{fmt(uploaded.duration)} long</p>
                </div>
                <button type="button" onClick={() => setUploaded(null)} className="p-1 rounded hover:bg-white/10" style={{ color: "#94a3b8" }} title="Remove">
                  <X size={15} />
                </button>
              </>
            ) : uploadPct !== null ? (
              <div className="flex-1 space-y-1">
                <p className="text-xs text-slate-300">Uploading… {Math.round(uploadPct * 100)}%</p>
                <div className="h-1.5 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.07)" }}>
                  <div className="h-full rounded-full" style={{ width: `${Math.max(3, uploadPct * 100)}%`, background: "linear-gradient(90deg,#4FC3F7,#7c3aed)" }} />
                </div>
              </div>
            ) : (
              <button type="button" onClick={() => fileRef.current?.click()}
                      className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm" style={{ background: "rgba(79,195,247,0.1)", color: "#4FC3F7" }}>
                <Upload size={15} /> Choose a video file (MP4, MOV, MKV…)
              </button>
            )}
          </div>
        )}
      </div>

      <div className="grid md:grid-cols-2 gap-5">
        <div className="space-y-1.5">
          <p className="text-xs font-semibold text-slate-300">Part length: <span style={{ color: "#4FC3F7" }}>{partSeconds} seconds</span></p>
          <input type="range" min={30} max={60} step={5} value={partSeconds}
                 onChange={(e) => setPartSeconds(Number(e.target.value))} className="w-full accent-cyan-400" aria-label="Part length in seconds" />
          <div className="flex justify-between text-[10px]" style={{ color: "var(--muted)" }}><span>30s</span><span>45s</span><span>60s</span></div>
        </div>
        <div className="space-y-1.5">
          <p className="text-xs font-semibold text-slate-300">Only this part of the video <span className="font-normal" style={{ color: "var(--muted)" }}>(optional)</span></p>
          <div className="flex items-center gap-2">
            <input value={from} onChange={(e) => setFrom(e.target.value)} placeholder="From 0:00" className={inputCls} style={inputStyle} aria-label="From time" />
            <span className="text-xs" style={{ color: "var(--muted)" }}>to</span>
            <input value={to} onChange={(e) => setTo(e.target.value)} placeholder="To (end)" className={inputCls} style={inputStyle} aria-label="To time" />
          </div>
          {timeError && <p className="text-[11px] text-red-400">{timeError}</p>}
        </div>
        <div className="space-y-1.5">
          <p className="text-xs font-semibold text-slate-300">Text under the video <span className="font-normal" style={{ color: "var(--muted)" }}>{"{n}"} = part number</span></p>
          <input value={partLabel} onChange={(e) => setPartLabel(e.target.value)} maxLength={40} className={inputCls} style={inputStyle}
                 placeholder="Part {n}" aria-label="Part label" />
          <p className="text-[10px]" style={{ color: "var(--muted)" }}>
            e.g. &ldquo;Part {"{n}"}&rdquo;, &ldquo;भाग {"{n}"}&rdquo; or &ldquo;Part {"{n}"}/{"{total}"}&rdquo; → Part 1, Part 2, …
          </p>
        </div>
        <div className="space-y-1.5">
          <p className="text-xs font-semibold text-slate-300">Title on top <span className="font-normal" style={{ color: "var(--muted)" }}>(optional)</span></p>
          <input value={seriesTitle} onChange={(e) => setSeriesTitle(e.target.value)} maxLength={60} className={inputCls} style={inputStyle}
                 placeholder="e.g. GTA 6 Trailer Breakdown" aria-label="Series title" />
        </div>
        <div className="space-y-1.5">
          <p className="text-xs font-semibold text-slate-300">Subtitles</p>
          <div className="flex flex-wrap gap-1 p-1 rounded-lg" style={{ background: "rgba(255,255,255,0.03)", border: "1px solid var(--border)" }}>
            {[{ key: "none", label: "Off" }, ...(opts?.caption_styles ?? []).filter((s) => s.key !== "none")].map((s) => (
              <button key={s.key} type="button" onClick={() => setCaptions(s.key)} className="px-2.5 py-1 rounded-md text-xs font-medium" style={chip(captions === s.key)}>
                {s.label}
              </button>
            ))}
          </div>
          {captions !== "none" && (
            <div className="flex gap-1 pt-1">
              {[["auto", "Auto-detect"], ["hi", "Hindi"], ["en", "English"]].map(([k, l]) => (
                <button key={k} type="button" onClick={() => setLanguage(k)} className="px-2.5 py-1 rounded-md text-[11px]" style={chip(language === k)}>{l}</button>
              ))}
            </div>
          )}
        </div>
        <div className="space-y-1.5">
          <p className="text-xs font-semibold text-slate-300">Layout</p>
          <div className="flex flex-wrap gap-1 p-1 rounded-lg" style={{ background: "rgba(255,255,255,0.03)", border: "1px solid var(--border)" }}>
            {([["blur_fit", "Blur background (full frame)"], ["center_crop", "Full-screen crop"]] as const).map(([k, l]) => (
              <button key={k} type="button" onClick={() => setLayout(k)} className="px-2.5 py-1 rounded-md text-xs font-medium" style={chip(layout === k)}>{l}</button>
            ))}
          </div>
        </div>
        <div className="space-y-1.5">
          <p className="text-xs font-semibold text-slate-300">Watermark</p>
          <input value={watermark} onChange={(e) => setWatermark(e.target.value)} maxLength={40} className={inputCls} style={inputStyle} aria-label="Watermark" />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <button type="submit" disabled={busy || uploadPct !== null}
                className="px-5 py-2.5 rounded-lg text-sm font-semibold flex items-center gap-2 disabled:opacity-40"
                style={{ background: "linear-gradient(135deg,#4FC3F7 0%,#7c3aed 100%)", color: "white" }}>
          {busy ? <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" /> : <ListOrdered size={15} />}
          Split into parts
        </button>
        {estimate && <span className="text-xs" style={{ color: "var(--muted)" }}>{estimate}</span>}
        {msg && <span className="text-xs" style={{ color: msg.ok ? "#4ade80" : "#f87171" }}>{msg.text}</span>}
      </div>
    </form>
  );
}
