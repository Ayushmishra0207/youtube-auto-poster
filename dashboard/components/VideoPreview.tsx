"use client";

/**
 * VideoPreview — shows the rendered MP4 if available, otherwise
 * renders an animated Remotion-powered slide preview from the script JSON.
 */
import { useRef } from "react";
import type { VideoMeta, VideoScript } from "@/lib/types";
import { authedMediaUrl } from "@/lib/api";

// Slide colors matching Python SLIDE_COLORS
const SLIDE_COLORS = [
  ["#1a1a2e", "#16213e"],
  ["#0f3460", "#533483"],
  ["#1B262C", "#0F4C75"],
  ["#16213e", "#0f3460"],
  ["#2D132C", "#1A1A2E"],
  ["#1B1B2F", "#2C3333"],
  ["#000428", "#004e92"],
];

function TitleCard({ title, thumbnailText }: { title: string; thumbnailText: string }) {
  const [c1, c2] = SLIDE_COLORS[0];
  return (
    <div
      className="relative w-full aspect-video flex flex-col items-center justify-center p-8 text-center"
      style={{ background: `linear-gradient(180deg, ${c1} 0%, ${c2} 100%)` }}
    >
      <p className="text-2xl font-bold text-white leading-snug drop-shadow-lg">{title}</p>
      <div className="w-24 h-0.5 my-3" style={{ background: "#4FC3F7" }} />
      {thumbnailText && (
        <p className="text-sm font-medium" style={{ color: "#4FC3F7" }}>{thumbnailText}</p>
      )}
    </div>
  );
}

function SectionSlide({
  heading, narration, index,
}: {
  heading: string; narration: string; index: number;
}) {
  const [c1, c2] = SLIDE_COLORS[(index + 1) % SLIDE_COLORS.length];
  return (
    <div
      className="relative w-full aspect-video flex flex-col justify-start p-8 overflow-hidden"
      style={{ background: `linear-gradient(180deg, ${c1} 0%, ${c2} 100%)` }}
    >
      <p className="text-lg font-bold text-white leading-snug mb-2 drop-shadow">{heading}</p>
      <div className="w-full h-0.5 mb-3" style={{ background: "#4FC3F7" }} />
      <p className="text-xs leading-relaxed line-clamp-6" style={{ color: "#e2e8f0", opacity: 0.85 }}>
        {narration.slice(0, 300)}{narration.length > 300 ? "…" : ""}
      </p>
    </div>
  );
}

function OutroCard() {
  return (
    <div
      className="relative w-full aspect-video flex flex-col items-center justify-center p-8 text-center"
      style={{ background: "linear-gradient(180deg, #000428 0%, #004e92 100%)" }}
    >
      <p className="text-2xl font-bold drop-shadow-lg" style={{ color: "#ff4444" }}>
        चैनल को Subscribe करें
      </p>
      <p className="text-base mt-3 text-white">Like, Share और घंटी दबाना न भूलें!</p>
    </div>
  );
}

export default function VideoPreview({
  video, script,
}: {
  video: VideoMeta;
  script: VideoScript | null;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);

  // If MP4 is ready, play it directly
  if (video.has_video) {
    return (
      <video
        ref={videoRef}
        controls
        className="w-full rounded-xl"
        style={{ background: "#000", maxHeight: "400px" }}
        src={authedMediaUrl(video.video_url)}
      >
        Your browser does not support video.
      </video>
    );
  }

  // No MP4 yet — show script-based slide preview
  if (!script) {
    return (
      <div
        className="w-full aspect-video rounded-xl flex items-center justify-center"
        style={{ background: "linear-gradient(135deg, #1a1a2e 0%, #16213e 100%)" }}
      >
        <div className="text-center">
          <div className="w-8 h-8 border-2 border-cyan-DEFAULT border-t-transparent rounded-full animate-spin mx-auto mb-3" />
          <p className="text-xs" style={{ color: "var(--muted)" }}>Rendering in progress…</p>
        </div>
      </div>
    );
  }

  // Remotion-style slide carousel preview
  const slides = [
    <TitleCard key="title" title={script.title} thumbnailText={script.thumbnail_text} />,
    ...script.sections.map((s, i) => (
      <SectionSlide key={s.id} heading={s.heading} narration={s.narration} index={i} />
    )),
    <OutroCard key="outro" />,
  ];

  return <SlideCarousel slides={slides} />;
}

function SlideCarousel({ slides }: { slides: React.ReactNode[] }) {
  const [current, setCurrent] = useState(0);

  return (
    <div className="space-y-3">
      <div className="rounded-xl overflow-hidden relative" style={{ border: "1px solid var(--border)" }}>
        {slides[current]}
        {/* Navigation arrows */}
        <button
          onClick={() => setCurrent((c) => Math.max(0, c - 1))}
          disabled={current === 0}
          className="absolute left-2 top-1/2 -translate-y-1/2 w-8 h-8 rounded-full flex items-center justify-center transition-all disabled:opacity-20"
          style={{ background: "rgba(0,0,0,0.6)", color: "#fff", backdropFilter: "blur(4px)" }}
        >
          ‹
        </button>
        <button
          onClick={() => setCurrent((c) => Math.min(slides.length - 1, c + 1))}
          disabled={current === slides.length - 1}
          className="absolute right-2 top-1/2 -translate-y-1/2 w-8 h-8 rounded-full flex items-center justify-center transition-all disabled:opacity-20"
          style={{ background: "rgba(0,0,0,0.6)", color: "#fff", backdropFilter: "blur(4px)" }}
        >
          ›
        </button>
        {/* Slide counter */}
        <div
          className="absolute bottom-2 right-3 text-xs font-mono"
          style={{ color: "rgba(255,255,255,0.6)" }}
        >
          {current + 1} / {slides.length}
        </div>
      </div>
      {/* Dot indicators */}
      <div className="flex items-center justify-center gap-1.5">
        {slides.map((_, i) => (
          <button
            key={i}
            onClick={() => setCurrent(i)}
            className="rounded-full transition-all duration-200"
            style={{
              width: i === current ? "16px" : "6px",
              height: "6px",
              background: i === current ? "#4FC3F7" : "rgba(255,255,255,0.2)",
            }}
          />
        ))}
      </div>
      <p className="text-center text-xs" style={{ color: "var(--muted)" }}>
        Script preview · MP4 not yet rendered
      </p>
    </div>
  );
}

// useState import fix — must be at module level
import { useState } from "react";
