"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Users, Eye, Film, ThumbsUp, MessageSquare, RefreshCw, ExternalLink, Lock, Globe } from "lucide-react";

interface ChannelInfo {
  id: string;
  title: string;
  description: string;
  thumbnail: string;
  subscribers: number;
  total_views: number;
  video_count: number;
  hidden_subscribers: boolean;
}

interface RecentVideo {
  id: string;
  title: string;
  published_at: string;
  thumbnail: string;
  views: number;
  likes: number;
  comments: number;
  privacy: string;
  url: string;
}

function fmt(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000)     return (n / 1_000).toFixed(1) + "K";
  return String(n);
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const d = Math.floor(diff / 86400000);
  const h = Math.floor(diff / 3600000);
  const m = Math.floor(diff / 60000);
  if (d > 0)  return `${d}d ago`;
  if (h > 0)  return `${h}h ago`;
  if (m > 0)  return `${m}m ago`;
  return "just now";
}

function StatCard({ icon, label, value, sub, color = "#4FC3F7" }: {
  icon: React.ReactNode; label: string; value: string; sub?: string; color?: string;
}) {
  return (
    <div className="glass rounded-2xl p-5 flex flex-col gap-3" style={{ boxShadow: "var(--shadow-card)" }}>
      <div className="w-9 h-9 rounded-xl flex items-center justify-center"
        style={{ background: `${color}18`, color }}>
        {icon}
      </div>
      <div>
        <p className="text-2xl font-bold text-white">{value}</p>
        <p className="text-sm mt-0.5" style={{ color: "var(--muted)" }}>{label}</p>
        {sub && <p className="text-xs mt-1" style={{ color }}>{sub}</p>}
      </div>
    </div>
  );
}

function MiniBar({ value, max, color }: { value: number; max: number; color: string }) {
  const pct = max > 0 ? Math.max(4, (value / max) * 100) : 4;
  return (
    <div className="flex items-center gap-2 mt-1">
      <div className="flex-1 h-1.5 rounded-full" style={{ background: "rgba(255,255,255,0.06)" }}>
        <div
          className="h-1.5 rounded-full transition-all duration-700"
          style={{ width: `${pct}%`, background: color, boxShadow: `0 0 6px ${color}60` }}
        />
      </div>
      <span className="text-xs font-mono w-12 text-right" style={{ color: "var(--muted)" }}>
        {fmt(value)}
      </span>
    </div>
  );
}

export default function AnalyticsPanel() {
  const [channel, setChannel] = useState<ChannelInfo | null>(null);
  const [videos, setVideos] = useState<RecentVideo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = async (showRefresh = false) => {
    if (showRefresh) setRefreshing(true);
    else setLoading(true);
    setError(null);
    try {
      const data: any = await api.analytics();
      setChannel(data.channel);
      setVideos(data.recent_videos ?? []);
    } catch (e: any) {
      setError(e.message ?? "Failed to load analytics");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => { load(); }, []);

  const maxViews = Math.max(...videos.map((v) => v.views), 1);

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3">
        <div className="w-7 h-7 border-2 border-t-transparent rounded-full animate-spin"
          style={{ borderColor: "#4FC3F7", borderTopColor: "transparent" }} />
        <p className="text-sm" style={{ color: "var(--muted)" }}>Loading YouTube analytics…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold text-white">Analytics</h1>
        <div className="glass rounded-2xl p-8 text-center space-y-4"
          style={{ border: "1px solid rgba(239,68,68,0.3)" }}>
          <p className="text-sm" style={{ color: "#f87171" }}>{error}</p>
          <p className="text-xs" style={{ color: "var(--muted)" }}>
            Make sure the API server is running and <code className="font-mono text-xs px-1" style={{ color: "#94a3b8" }}>youtube_token.pickle</code> exists.
          </p>
          <button onClick={() => load(true)}
            className="px-4 py-2 rounded-lg text-sm font-medium transition-all"
            style={{ background: "rgba(79,195,247,0.1)", border: "1px solid rgba(79,195,247,0.3)", color: "#4FC3F7" }}>
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Analytics</h1>
          <p className="text-sm mt-1" style={{ color: "var(--muted)" }}>
            YouTube channel performance — live from API
          </p>
        </div>
        <button onClick={() => load(true)} disabled={refreshing}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs transition-all glass glass-hover"
          style={{ color: "var(--muted)" }}>
          <RefreshCw size={12} className={refreshing ? "animate-spin" : ""} />
          Refresh
        </button>
      </div>

      {/* Channel header card */}
      {channel && (
        <div className="glass rounded-2xl p-4 sm:p-5 flex flex-col sm:flex-row sm:items-center gap-4"
          style={{ border: "1px solid rgba(79,195,247,0.15)" }}>
          <div className="flex items-center gap-3 flex-1 min-w-0">
            {channel.thumbnail && (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={channel.thumbnail} alt={channel.title}
                className="w-12 h-12 sm:w-14 sm:h-14 rounded-full object-cover shrink-0"
                style={{ border: "2px solid rgba(79,195,247,0.3)" }} />
            )}
            <div className="min-w-0">
              <p className="text-base sm:text-lg font-bold text-white truncate">{channel.title}</p>
              {channel.description && (
                <p className="text-xs mt-0.5 line-clamp-1" style={{ color: "var(--muted)" }}>
                  {channel.description}
                </p>
              )}
              <p className="text-xs mt-1 font-mono truncate" style={{ color: "#4FC3F7" }}>
                youtube.com/channel/{channel.id}
              </p>
            </div>
          </div>
          <a href={`https://studio.youtube.com`} target="_blank" rel="noopener noreferrer"
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-all self-start sm:self-auto shrink-0"
            style={{ background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.3)", color: "#f87171" }}>
            <ExternalLink size={11} />
            YouTube Studio
          </a>
        </div>
      )}

      {/* Stat cards */}
      {channel && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard
            icon={<Users size={18} />}
            label="Subscribers"
            value={channel.hidden_subscribers ? "Hidden" : fmt(channel.subscribers)}
            sub={channel.hidden_subscribers ? "Channel hides count" : undefined}
            color="#4FC3F7"
          />
          <StatCard
            icon={<Eye size={18} />}
            label="Total Views"
            value={fmt(channel.total_views)}
            sub="All-time channel views"
            color="#818CF8"
          />
          <StatCard
            icon={<Film size={18} />}
            label="Total Videos"
            value={fmt(channel.video_count)}
            sub="Uploaded to channel"
            color="#34D399"
          />
          <StatCard
            icon={<ThumbsUp size={18} />}
            label="Recent Videos"
            value={String(videos.length)}
            sub="Showing last 20"
            color="#F59E0B"
          />
        </div>
      )}

      {/* View performance chart */}
      {videos.length > 0 && (
        <div className="glass rounded-2xl p-6">
          <p className="text-sm font-semibold text-white mb-4">
            View Performance — Recent {videos.length} Videos
          </p>
          <div className="space-y-1">
            {videos.slice(0, 12).map((v) => (
              <div key={v.id} className="group">
                <div className="flex items-center justify-between text-xs mb-0.5">
                  <p className="truncate flex-1 pr-4 group-hover:text-white transition-colors"
                    style={{ color: "var(--muted)" }}>
                    {v.title.slice(0, 60)}{v.title.length > 60 ? "…" : ""}
                  </p>
                  <span className="shrink-0 font-mono text-xs" style={{ color: "#64748b" }}>
                    {timeAgo(v.published_at)}
                  </span>
                </div>
                <MiniBar value={v.views} max={maxViews} color="#4FC3F7" />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recent videos table */}
      <div className="glass rounded-2xl overflow-hidden">
        <div className="px-5 py-4 border-b flex items-center justify-between"
          style={{ borderColor: "var(--border)" }}>
          <p className="text-sm font-semibold text-white">Recent Uploads</p>
          <span className="text-xs px-2 py-0.5 rounded-full font-mono"
            style={{ background: "rgba(79,195,247,0.1)", color: "#4FC3F7" }}>
            {videos.length} videos
          </span>
        </div>

        <div className="divide-y" style={{ borderColor: "var(--border)" }}>
          {videos.length === 0 ? (
            <p className="px-5 py-8 text-sm text-center" style={{ color: "var(--muted)" }}>
              No videos found on this channel yet.
            </p>
          ) : (
            videos.map((v) => (
              <div key={v.id}
                className="flex items-center gap-3 px-4 sm:px-5 py-3 hover:bg-white/[0.02] transition-colors group">
                {/* Thumbnail */}
                <a href={v.url} target="_blank" rel="noopener noreferrer"
                  className="w-16 sm:w-20 h-10 sm:h-12 rounded-lg overflow-hidden shrink-0 block"
                  style={{ background: "rgba(255,255,255,0.04)" }}>
                  {v.thumbnail ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={v.thumbnail} alt={v.title} className="w-full h-full object-cover" />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center">
                      <Film size={14} style={{ color: "rgba(79,195,247,0.3)" }} />
                    </div>
                  )}
                </a>

                {/* Title + date */}
                <div className="flex-1 min-w-0">
                  <a href={v.url} target="_blank" rel="noopener noreferrer"
                    className="text-xs sm:text-sm font-medium line-clamp-2 sm:line-clamp-1 hover:underline text-white transition-colors"
                    style={{ textDecorationColor: "#4FC3F7" }}>
                    {v.title}
                  </a>
                  <div className="flex items-center gap-1.5 mt-0.5 flex-wrap">
                    <span className="text-xs" style={{ color: "var(--muted)" }}>
                      {new Date(v.published_at).toLocaleDateString("en-IN", {
                        day: "numeric", month: "short",
                      })}
                    </span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded flex items-center gap-0.5"
                      style={{
                        background: v.privacy === "public" ? "rgba(34,197,94,0.1)" : "rgba(100,116,139,0.1)",
                        color: v.privacy === "public" ? "#4ade80" : "#94a3b8",
                      }}>
                      {v.privacy === "public" ? <Globe size={8} /> : <Lock size={8} />}
                      {v.privacy}
                    </span>
                  </div>
                </div>

                {/* Stats — compact on mobile */}
                <div className="flex items-center gap-3 sm:gap-5 shrink-0">
                  <div className="text-right">
                    <div className="flex items-center gap-1 text-xs sm:text-sm font-semibold text-white">
                      <Eye size={11} style={{ color: "#4FC3F7" }} />
                      {fmt(v.views)}
                    </div>
                    <p className="text-[10px] hidden sm:block" style={{ color: "var(--muted)" }}>views</p>
                  </div>
                  <div className="hidden sm:block text-right">
                    <div className="flex items-center gap-1 text-sm font-semibold text-white">
                      <ThumbsUp size={11} style={{ color: "#34D399" }} />
                      {fmt(v.likes)}
                    </div>
                    <p className="text-[10px]" style={{ color: "var(--muted)" }}>likes</p>
                  </div>
                  <div className="hidden md:block text-right">
                    <div className="flex items-center gap-1 text-sm font-semibold text-white">
                      <MessageSquare size={11} style={{ color: "#818CF8" }} />
                      {fmt(v.comments)}
                    </div>
                    <p className="text-[10px]" style={{ color: "var(--muted)" }}>comments</p>
                  </div>
                  <a href={v.url} target="_blank" rel="noopener noreferrer"
                    className="w-7 h-7 rounded-lg flex items-center justify-center sm:opacity-0 sm:group-hover:opacity-100 transition-all"
                    style={{ background: "rgba(79,195,247,0.1)", color: "#4FC3F7" }}>
                    <ExternalLink size={13} />
                  </a>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
