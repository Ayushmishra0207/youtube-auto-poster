"use client";

import { useState } from "react";
import { RefreshCw } from "lucide-react";

/**
 * Re-runs generation for one existing video/Short slot in place
 * (POST /api/videos|shorts/{date}/{index}/regenerate). Shows a spinner while
 * the backend reports `is_regenerating` for that slot.
 */
export default function RegenerateButton({
  isRegenerating,
  start,
  title,
  onStarted,
}: {
  isRegenerating?: boolean;
  start: () => Promise<{ ok: boolean; message?: string }>;
  title?: string;
  onStarted: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr]   = useState("");

  const handle = async () => {
    if (!confirm("Regenerate this one from scratch? The current file will be replaced.")) return;
    setBusy(true);
    setErr("");
    try {
      const res = await start();
      if (res?.ok === false) setErr(res.message ?? "Could not start regeneration");
      else onStarted();
    } catch {
      setErr("Failed to reach API");
    } finally {
      setBusy(false);
    }
  };

  if (isRegenerating) {
    return (
      <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium w-full justify-center"
           style={{ background: "rgba(124,58,237,0.08)", border: "1px solid rgba(124,58,237,0.25)", color: "#a78bfa" }}>
        <div className="w-3 h-3 border border-violet-400 border-t-transparent rounded-full animate-spin" />
        Regenerating…
      </div>
    );
  }

  return (
    <div className="space-y-1">
      <button
        onClick={handle}
        disabled={busy}
        title={title}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium w-full justify-center transition-all disabled:opacity-50"
        style={{ background: "rgba(255,255,255,0.04)", border: "1px solid var(--border)", color: "#94a3b8" }}
      >
        <RefreshCw size={12} className={busy ? "animate-spin" : ""} />
        Regenerate
      </button>
      {err && <p className="text-[10px] text-center text-red-400 leading-tight">{err}</p>}
    </div>
  );
}
