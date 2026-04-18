"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { VideoMeta, VideoScript } from "@/lib/types";
import { Play, Image as ImageIcon, FileJson, X, ChevronDown } from "lucide-react";
import dynamic from "next/dynamic";

const VideoPreview = dynamic(() => import("./VideoPreview"), { ssr: false });

function StatusBadge({ status }: { status: VideoMeta["status"] }) {
  const map: Record<string, string> = {
    ready: "badge-ready",
    rendering: "badge-rendering",
    generating: "badge-generating",
    pending: "badge-pending",
    failed: "badge-failed",
  };
  const labels: Record<string, string> = {
    ready: "Ready", rendering: "Rendering…", generating: "Generating…",
    pending: "Pending", failed: "Failed",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${map[status] ?? "badge-pending"}`}>
      {labels[status] ?? status}
    </span>
  );
}

function VideoCard({ video, onPlay }: { video: VideoMeta; onPlay: (v: VideoMeta) => void }) {
  return (
    <div className="glass glass-hover rounded-2xl overflow-hidden transition-all duration-200 group">
      {/* Thumbnail */}
      <div
        className="relative h-36 bg-navy-900 flex items-center justify-center overflow-hidden"
        style={{ background: "linear-gradient(135deg, #1a1a2e 0%, #16213e 100%)" }}
      >
        {video.has_thumbnail ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={`http://localhost:8000${video.thumbnail_url}`}
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
      <div className="p-4 space-y-2">
        <div className="flex items-start justify-between gap-2">
          <p className="text-sm font-medium text-white leading-snug line-clamp-2">{video.title}</p>
          <StatusBadge status={video.status} />
        </div>
        {video.title_english && (
          <p className="text-xs line-clamp-1" style={{ color: "var(--muted)" }}>{video.title_english}</p>
        )}
        <div className="flex items-center gap-2 pt-1">
          <span className="text-xs font-mono" style={{ color: "#64748b" }}>#{video.index}</span>
          {video.has_script && (
            <span className="text-xs" style={{ color: "rgba(79,195,247,0.6)" }}>
              <FileJson size={11} className="inline mr-0.5" />script
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

export default function VideoGrid() {
  const [videos, setVideos] = useState<VideoMeta[]>([]);
  const [playing, setPlaying] = useState<VideoMeta | null>(null);
  const [script, setScript] = useState<VideoScript | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.videos().then((r: any) => { setVideos(r.videos); setLoading(false); });
    const id = setInterval(() => api.videos().then((r: any) => setVideos(r.videos)), 10000);
    return () => clearInterval(id);
  }, []);

  const openPlayer = async (v: VideoMeta) => {
    setPlaying(v);
    if (v.has_script) {
      try {
        const s: any = await api.script(v.date, v.index);
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

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Videos</h1>
        <p className="text-sm mt-1" style={{ color: "var(--muted)" }}>
          {videos.length} video{videos.length !== 1 ? "s" : ""} generated today
        </p>
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
            <VideoCard key={v.index} video={v} onPlay={openPlayer} />
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
              <button
                onClick={closePlayer}
                className="w-8 h-8 rounded-lg flex items-center justify-center transition-all"
                style={{ background: "rgba(255,255,255,0.06)", color: "#94a3b8" }}
              >
                <X size={15} />
              </button>
            </div>

            {/* Player */}
            <div className="p-6">
              <VideoPreview video={playing} script={script} />
            </div>

            {/* Script sections */}
            {script && (
              <div
                className="px-6 pb-6 border-t"
                style={{ borderColor: "var(--border)" }}
              >
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
