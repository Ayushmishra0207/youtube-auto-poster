"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { VideoMeta } from "@/lib/types";
import { Clock, Upload, CheckCircle } from "lucide-react";

const SLOTS = ["18:30","18:40","18:50","19:00","19:10","19:20","19:30"];

export default function ScheduleTimeline() {
  const [videos, setVideos] = useState<VideoMeta[]>([]);

  useEffect(() => {
    api.videos().then((r: any) => setVideos(r.videos));
    const id = setInterval(() => api.videos().then((r: any) => setVideos(r.videos)), 10000);
    return () => clearInterval(id);
  }, []);

  const bySlot = SLOTS.map((slot) => ({
    slot,
    video: videos.find((v) => v.slot === slot) ?? null,
  }));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Schedule</h1>
        <p className="text-sm mt-1" style={{ color: "var(--muted)" }}>
          Upload timeline — 7 slots from 18:30 to 19:30 IST, every 10 minutes
        </p>
      </div>

      {/* Timeline */}
      <div className="glass rounded-2xl p-6">
        <div className="relative">
          {/* Vertical line */}
          <div
            className="absolute left-6 top-0 bottom-0 w-px"
            style={{ background: "linear-gradient(180deg, #4FC3F7 0%, rgba(79,195,247,0.1) 100%)" }}
          />

          <div className="space-y-4">
            {bySlot.map(({ slot, video }, i) => {
              const filled = video !== null;
              const done = video?.status === "ready";

              return (
                <div key={slot} className="flex gap-5 items-start relative">
                  {/* Timeline dot */}
                  <div
                    className="relative z-10 w-12 h-12 shrink-0 rounded-full flex items-center justify-center text-xs font-mono font-bold transition-all"
                    style={{
                      background: done
                        ? "rgba(34,197,94,0.15)"
                        : filled
                        ? "rgba(79,195,247,0.15)"
                        : "rgba(255,255,255,0.04)",
                      border: `1px solid ${done ? "rgba(34,197,94,0.4)" : filled ? "rgba(79,195,247,0.4)" : "rgba(255,255,255,0.1)"}`,
                      color: done ? "#4ade80" : filled ? "#4FC3F7" : "#475569",
                      boxShadow: done
                        ? "0 0 12px rgba(34,197,94,0.15)"
                        : filled
                        ? "0 0 12px rgba(79,195,247,0.15)"
                        : "none",
                    }}
                  >
                    {done ? <CheckCircle size={18} /> : filled ? <Upload size={16} /> : <Clock size={16} />}
                  </div>

                  {/* Content */}
                  <div
                    className="flex-1 rounded-xl p-4 transition-all duration-200"
                    style={{
                      background: done
                        ? "rgba(34,197,94,0.05)"
                        : filled
                        ? "rgba(79,195,247,0.05)"
                        : "rgba(255,255,255,0.02)",
                      border: `1px solid ${done ? "rgba(34,197,94,0.15)" : filled ? "rgba(79,195,247,0.12)" : "rgba(255,255,255,0.05)"}`,
                    }}
                  >
                    <div className="flex items-center justify-between">
                      <span
                        className="text-sm font-mono font-semibold"
                        style={{ color: filled ? "#e2e8f0" : "#475569" }}
                      >
                        {slot} IST
                      </span>
                      {video && (
                        <span
                          className="text-xs px-2 py-0.5 rounded-full"
                          style={{
                            background: done ? "rgba(34,197,94,0.15)" : "rgba(79,195,247,0.12)",
                            color: done ? "#4ade80" : "#4FC3F7",
                          }}
                        >
                          {done ? "Uploaded" : video.status}
                        </span>
                      )}
                    </div>

                    {video ? (
                      <p className="text-xs mt-1.5 line-clamp-1" style={{ color: "var(--muted)" }}>
                        {video.title}
                      </p>
                    ) : (
                      <p className="text-xs mt-1.5 italic" style={{ color: "#334155" }}>
                        Slot {i + 1} — not yet generated
                      </p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-6 text-xs" style={{ color: "var(--muted)" }}>
        {[
          { color: "#4FC3F7", label: "Generating / Uploading" },
          { color: "#4ade80", label: "Uploaded & Scheduled" },
          { color: "#334155", label: "Empty slot" },
        ].map(({ color, label }) => (
          <div key={label} className="flex items-center gap-1.5">
            <div className="w-2.5 h-2.5 rounded-full" style={{ background: color }} />
            {label}
          </div>
        ))}
      </div>
    </div>
  );
}
