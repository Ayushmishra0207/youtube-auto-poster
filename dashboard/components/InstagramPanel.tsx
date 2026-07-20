"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { InstagramPost } from "@/lib/types";
import { Instagram, RefreshCw, Sparkles, Clock, CheckCircle, XCircle } from "lucide-react";

function StatusBadge({ status }: { status: InstagramPost["status"] }) {
  const map: Record<string, { cls: string; label: string; icon: React.ReactNode }> = {
    pending: { cls: "badge-pending",  label: "Pending", icon: <Clock size={11} /> },
    posted:  { cls: "badge-uploaded", label: "Posted",  icon: <CheckCircle size={11} /> },
    failed:  { cls: "badge-failed",   label: "Failed",  icon: <XCircle size={11} /> },
  };
  const { cls, label, icon } = map[status] ?? { cls: "badge-pending", label: status, icon: null };
  return (
    <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium ${cls}`}>
      {icon}{label}
    </span>
  );
}

function PostCard({ post, onRetried }: { post: InstagramPost; onRetried: () => void }) {
  const [retrying, setRetrying] = useState(false);

  const handleRetry = async () => {
    setRetrying(true);
    try {
      await api.retryInstagramPost(post.id);
      onRetried();
    } finally {
      setRetrying(false);
    }
  };

  const targetLocal = new Date(post.publish_at_utc).toLocaleString();

  return (
    <div className="glass rounded-2xl p-5 space-y-3" style={{ border: "1px solid var(--border)" }}>
      <div className="flex items-center justify-between gap-2">
        <StatusBadge status={post.status} />
        <span className="text-xs" style={{ color: "var(--muted)" }}>{targetLocal}</span>
      </div>
      <p className="text-sm text-white whitespace-pre-wrap leading-relaxed">{post.caption}</p>
      {post.status === "failed" && post.error && (
        <p className="text-xs" style={{ color: "#f87171" }}>{post.error}</p>
      )}
      {post.status === "failed" && (
        <button
          onClick={handleRetry}
          disabled={retrying}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium w-full justify-center transition-all disabled:opacity-50"
          style={{ background: "rgba(79,195,247,0.1)", border: "1px solid rgba(79,195,247,0.25)", color: "#4FC3F7" }}
        >
          <RefreshCw size={12} className={retrying ? "animate-spin" : ""} />
          {retrying ? "Retrying…" : "Retry"}
        </button>
      )}
    </div>
  );
}

export default function InstagramPanel() {
  const [posts, setPosts]     = useState<InstagramPost[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [msg, setMsg]         = useState<{ text: string; ok: boolean } | null>(null);

  const refresh = () =>
    api.instagramPosts()
      .then((r) => setPosts(r.posts))
      .catch(() => {})
      .finally(() => setLoading(false));

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 15000);
    return () => clearInterval(id);
  }, []);

  const handleRunNow = async () => {
    setRunning(true);
    setMsg(null);
    try {
      const res = await api.runInstagramNow();
      setMsg({ text: `Pass complete — ${res.posted} posted, ${res.failed} failed.`, ok: true });
      refresh();
    } catch {
      setMsg({ text: "Failed to reach API", ok: false });
    } finally {
      setRunning(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="w-6 h-6 border-2 border-cyan-DEFAULT border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  const pending = posts.filter((p) => p.status === "pending").length;
  const failed  = posts.filter((p) => p.status === "failed").length;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Instagram Reels</h1>
        <p className="text-sm mt-1" style={{ color: "var(--muted)" }}>
          {pending} queued · {failed} failed — cross-posted automatically from your YouTube Shorts
        </p>
      </div>

      <button
        onClick={handleRunNow}
        disabled={running}
        className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-semibold transition-all disabled:opacity-50"
        style={{
          background: "linear-gradient(135deg, rgba(79,195,247,0.2) 0%, rgba(124,58,237,0.2) 100%)",
          border: "1px solid var(--border-strong)",
          color: "#4FC3F7",
        }}
      >
        {running ? (
          <div className="w-3 h-3 border border-cyan-400 border-t-transparent rounded-full animate-spin" />
        ) : (
          <Sparkles size={13} />
        )}
        {running ? "Running…" : "Post due Reels now"}
      </button>
      {msg && <p className="text-xs" style={{ color: msg.ok ? "#4ade80" : "#f87171" }}>{msg.text}</p>}

      {posts.length === 0 ? (
        <div className="glass rounded-2xl p-12 text-center" style={{ borderStyle: "dashed", borderColor: "rgba(79,195,247,0.15)" }}>
          <Instagram size={28} className="mx-auto mb-3" style={{ color: "rgba(79,195,247,0.3)" }} />
          <p className="text-sm" style={{ color: "var(--muted)" }}>
            No Reels queued yet. New entries appear here automatically whenever a YouTube Short is generated.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {posts.slice().reverse().map((p) => (
            <PostCard key={p.id} post={p} onRetried={refresh} />
          ))}
        </div>
      )}
    </div>
  );
}
