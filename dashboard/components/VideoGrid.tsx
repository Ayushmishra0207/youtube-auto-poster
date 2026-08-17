"use client";

import { useEffect, useState } from "react";
import { api, authedMediaUrl, authHeaders } from "@/lib/api";
import { useAccount } from "@/lib/accountContext";
import type { VideoMeta, VideoScript } from "@/lib/types";
import { Play, Image as ImageIcon, FileJson, X, Upload, ExternalLink, CheckCircle } from "lucide-react";
import dynamic from "next/dynamic";

const VideoPreview = dynamic(() => import("./VideoPreview"), { ssr: false });

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function StatusBadge({ status }: { status: VideoMeta["status"] }) {
  const map: Record<string, { cls: string; label: string }> = {
    ready:      { cls: "badge-ready",      label: "Ready" },
    uploaded:   { cls: "badge-uploaded",   label: "Uploaded" },
    rendering:  { cls: "badge-rendering",  label: "Rendering…" },
    generating: { cls: "badge-generating", label: "Generating…" },
    pending:    { cls: "badge-pending",    label: "Pending" },
    failed:     { cls: "badge-failed",     label: "Failed" },
  };
  const { cls, label } = map[status] ?? { cls: "badge-pending", label: status };
  return <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${cls}`}>{label}</span>;
}

function UploadButton({
  video,
  accountId,
  onUploaded,
}: {
  video: VideoMeta;
  accountId: string;
  onUploaded: (index: number, videoId: string, url: string) => void;
}) {
  const [uploading, setUploading] = useState(false);
  const [err, setErr]             = useState("");

  const handle = async () => {
    setUploading(true);
    setErr("");
    try {
      const res  = await fetch(`${BASE}/api/upload-generated/${video.date}/${video.index}?account_id=${encodeURIComponent(accountId)}`, { method: "POST", headers: authHeaders() });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Upload failed");
      onUploaded(video.index, data.video_id, data.url);
    } catch (e: any) {
      setErr(e.message || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  if (video.status === "uploaded" && video.youtube_url) {
    return (
      <a
        href={video.youtube_url}
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

  if (!video.has_video) return null;

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

function VideoCard({
  video,
  accountId,
  onPlay,
  onUploaded,
}: {
  video: VideoMeta;
  accountId: string;
  onPlay: (v: VideoMeta) => void;
  onUploaded: (index: number, videoId: string, url: string) => void;
}) {
  return (
    <div className="glass glass-hover rounded-2xl overflow-hidden transition-all duration-200 group flex flex-col">
      {/* Thumbnail */}
      <div
        className="relative h-36 flex items-center justify-center overflow-hidden"
        style={{ background: "linear-gradient(135deg, #1a1a2e 0%, #16213e 100%)" }}
      >
        {video.has_thumbnail ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={authedMediaUrl(video.thumbnail_url)}
            alt={video.title_english || video.title}
            className="w-full h-full object-cover"
          />
        ) : (
          <ImageIcon size={32} style={{ color: "rgba(79,195,247,0.3)" }} />
        )}

        {/* Slot badge */}
        <div
          className="absolute top-2 left-2 text-xs px-2 py-0.5 rounded font-mono font-semibold"
          style={{ background: "rgba(0,0,0,0.7)", color: "#4FC3F7", backdropFilter: "blur(4px)" }}
        >
          {video.slot}
        </div>

        {/* Uploaded overlay badge */}
        {video.status === "uploaded" && (
          <div
            className="absolute top-2 right-2 flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded font-semibold"
            style={{ background: "rgba(34,197,94,0.85)", color: "white", backdropFilter: "blur(4px)" }}
          >
            <CheckCircle size={9} />
            Live
          </div>
        )}

        {/* Play overlay */}
        {video.has_video && (
          <button
            onClick={() => onPlay(video)}
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

      {/* Info */}
      <div className="p-4 space-y-2 flex-1 flex flex-col">
        <div className="flex items-start justify-between gap-2">
          <p className="text-sm font-medium text-white leading-snug line-clamp-2 flex-1">{video.title}</p>
          <StatusBadge status={video.status} />
        </div>
        {video.title_english && (
          <p className="text-xs line-clamp-1" style={{ color: "var(--muted)" }}>{video.title_english}</p>
        )}
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono" style={{ color: "#64748b" }}>#{video.index}</span>
          {video.has_script && (
            <span className="text-xs" style={{ color: "rgba(79,195,247,0.6)" }}>
              <FileJson size={11} className="inline mr-0.5" />script
            </span>
          )}
        </div>

        {/* Upload / YouTube button */}
        <div className="mt-auto pt-2">
          <UploadButton video={video} accountId={accountId} onUploaded={onUploaded} />
        </div>
      </div>
    </div>
  );
}

export default function VideoGrid() {
  const { accountId } = useAccount();
  const [videos, setVideos]   = useState<VideoMeta[]>([]);
  const [playing, setPlaying] = useState<VideoMeta | null>(null);
  const [script, setScript]   = useState<VideoScript | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.videos(undefined, accountId).then((r: any) => { setVideos(r.videos); setLoading(false); }).catch(() => setLoading(false));
    const id = setInterval(() => api.videos(undefined, accountId).then((r: any) => setVideos(r.videos)).catch(() => {}), 10000);
    return () => clearInterval(id);
  }, [accountId]);

  const handleUploaded = (index: number, videoId: string, url: string) => {
    setVideos((prev) =>
      prev.map((v) =>
        v.index === index
          ? { ...v, status: "uploaded", youtube_id: videoId, youtube_url: url }
          : v
      )
    );
  };

  const openPlayer = async (v: VideoMeta) => {
    setPlaying(v);
    if (v.has_script) {
      try {
        const s: any = await api.script(v.date, v.index, accountId);
        setScript(s);
      } catch { setScript(null); }
    }
  };

  const closePlayer = () => { setPlaying(null); setScript(null); };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="w-6 h-6 border-2 border-cyan-DEFAULT border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  const uploaded  = videos.filter((v) => v.status === "uploaded").length;
  const ready     = videos.filter((v) => v.status === "ready").length;

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Videos</h1>
          <p className="text-sm mt-1" style={{ color: "var(--muted)" }}>
            {videos.length} generated · {uploaded} uploaded · {ready} ready to upload
          </p>
        </div>
      </div>

      {videos.length === 0 ? (
        <div
          className="glass rounded-2xl p-12 text-center"
          style={{ borderStyle: "dashed", borderColor: "rgba(79,195,247,0.15)" }}
        >
          <p className="text-sm" style={{ color: "var(--muted)" }}>
            No videos generated yet today. Hit <strong style={{ color: "#4FC3F7" }}>Run Now</strong> to start.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {videos.map((v) => (
            <VideoCard key={v.index} video={v} accountId={accountId} onPlay={openPlayer} onUploaded={handleUploaded} />
          ))}
        </div>
      )}

      {/* Video player modal */}
      {playing && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ background: "rgba(2,6,23,0.9)", backdropFilter: "blur(16px)" }}
          onClick={closePlayer}
        >
          <div
            className="glass rounded-3xl overflow-hidden w-full max-w-4xl"
            style={{ border: "1px solid var(--border-strong)" }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal header */}
            <div
              className="flex items-center justify-between px-6 py-4 border-b"
              style={{ borderColor: "var(--border)" }}
            >
              <div>
                <p className="font-semibold text-white text-sm leading-snug">{playing.title}</p>
                {playing.title_english && (
                  <p className="text-xs mt-0.5" style={{ color: "var(--muted)" }}>{playing.title_english}</p>
                )}
              </div>
              <div className="flex items-center gap-2">
                {playing.youtube_url && (
                  <a
                    href={playing.youtube_url}
                    target="_blank"
                    rel="noreferrer"
                    className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium"
                    style={{ background: "rgba(34,197,94,0.12)", color: "#4ade80", border: "1px solid rgba(34,197,94,0.3)" }}
                  >
                    <ExternalLink size={11} /> YouTube
                  </a>
                )}
                <button
                  onClick={closePlayer}
                  className="w-8 h-8 rounded-lg flex items-center justify-center transition-all"
                  style={{ background: "rgba(255,255,255,0.06)", color: "#94a3b8" }}
                >
                  <X size={15} />
                </button>
              </div>
            </div>

            {/* Player */}
            <div className="p-6">
              <VideoPreview video={playing} script={script} />
            </div>

            {/* Script sections */}
            {script && (
              <div className="px-6 pb-6 border-t" style={{ borderColor: "var(--border)" }}>
                <p className="text-xs font-semibold mt-4 mb-3" style={{ color: "var(--muted)" }}>
                  SCRIPT SECTIONS
                </p>
                <div className="space-y-2 max-h-48 overflow-y-auto">
                  {script.sections.map((s) => (
                    <div key={s.id} className="text-xs space-y-0.5">
                      <p className="font-medium" style={{ color: "#4FC3F7" }}>{s.heading}</p>
                      <p className="line-clamp-2" style={{ color: "var(--muted)" }}>{s.narration.slice(0, 120)}…</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
