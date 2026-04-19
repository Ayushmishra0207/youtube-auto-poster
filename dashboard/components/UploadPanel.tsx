"use client";

import { useState, useRef, useCallback } from "react";
import {
  Upload, FileVideo, X, CheckCircle, AlertCircle,
  ExternalLink, Image, Clock, Tag, AlignLeft, Hash,
} from "lucide-react";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const CATEGORIES = [
  { id: "25", label: "News & Politics" },
  { id: "22", label: "People & Blogs" },
  { id: "24", label: "Entertainment" },
  { id: "27", label: "Education" },
  { id: "28", label: "Science & Technology" },
  { id: "17", label: "Sports" },
  { id: "26", label: "How-to & Style" },
  { id: "29", label: "Non-profits & Activism" },
];

function formatBytes(b: number) {
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  if (b < 1024 * 1024 * 1024) return `${(b / (1024 * 1024)).toFixed(1)} MB`;
  return `${(b / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function Field({ label, icon, children }: { label: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="flex items-center gap-1.5 text-xs font-medium" style={{ color: "#94a3b8" }}>
        <span style={{ color: "#4FC3F7" }}>{icon}</span>
        {label}
      </label>
      {children}
    </div>
  );
}

const inputCls = "w-full px-3 py-2 rounded-xl text-sm text-white placeholder-slate-600 outline-none transition-all";
const inputStyle = {
  background: "rgba(255,255,255,0.04)",
  border: "1px solid rgba(255,255,255,0.08)",
};
const inputFocusStyle = {
  borderColor: "rgba(79,195,247,0.4)",
  boxShadow: "0 0 0 2px rgba(79,195,247,0.08)",
};

function StyledInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  const [focused, setFocused] = useState(false);
  return (
    <input
      {...props}
      className={inputCls}
      style={{ ...inputStyle, ...(focused ? inputFocusStyle : {}) }}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
    />
  );
}

function StyledTextarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const [focused, setFocused] = useState(false);
  return (
    <textarea
      {...props}
      className={inputCls + " resize-none"}
      style={{ ...inputStyle, ...(focused ? inputFocusStyle : {}) }}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
    />
  );
}

function StyledSelect(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className={inputCls + " cursor-pointer"}
      style={{ ...inputStyle, color: "white" }}
    />
  );
}

export default function UploadPanel() {
  const [videoFile, setVideoFile]       = useState<File | null>(null);
  const [thumbFile, setThumbFile]       = useState<File | null>(null);
  const [title, setTitle]               = useState("");
  const [description, setDescription]   = useState("");
  const [tags, setTags]                 = useState("");
  const [categoryId, setCategoryId]     = useState("25");
  const [privacy, setPrivacy]           = useState("public");
  const [scheduleTime, setScheduleTime] = useState("");
  const [dragging, setDragging]         = useState(false);
  const [uploading, setUploading]       = useState(false);
  const [result, setResult]             = useState<{ url: string; studio_url: string } | null>(null);
  const [error, setError]               = useState("");

  const videoRef = useRef<HTMLInputElement>(null);
  const thumbRef  = useRef<HTMLInputElement>(null);

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f && (f.type.startsWith("video/") || f.name.match(/\.(mp4|mov|avi|mkv|webm)$/i))) {
      setVideoFile(f);
    }
  }, []);

  const handleSubmit = async () => {
    if (!videoFile) { setError("Please select a video file."); return; }
    if (!title.trim()) { setError("Title is required."); return; }

    setUploading(true);
    setError("");
    setResult(null);

    const fd = new FormData();
    fd.append("video", videoFile);
    fd.append("title", title.trim());
    fd.append("description", description);
    fd.append("tags", tags);
    fd.append("category_id", categoryId);
    fd.append("privacy", privacy);
    if (scheduleTime) fd.append("schedule_time", new Date(scheduleTime).toISOString());
    if (thumbFile) fd.append("thumbnail", thumbFile);

    try {
      const res = await fetch(`${BASE}/api/upload`, { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Upload failed");
      setResult(data);
      // Reset form on success
      setVideoFile(null);
      setThumbFile(null);
      setTitle("");
      setDescription("");
      setTags("");
    } catch (e: any) {
      setError(e.message || "Upload failed. Check that the API is running.");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="space-y-6 max-w-3xl">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white">Manual Upload</h1>
        <p className="text-sm mt-1" style={{ color: "var(--muted)" }}>
          Upload any video directly to YouTube — pipeline videos or your own recordings.
        </p>
      </div>

      {/* Success banner */}
      {result && (
        <div
          className="flex items-center justify-between px-4 py-3 rounded-xl text-sm"
          style={{ background: "rgba(34,197,94,0.1)", border: "1px solid rgba(34,197,94,0.3)" }}
        >
          <div className="flex items-center gap-2" style={{ color: "#4ade80" }}>
            <CheckCircle size={16} />
            <span>Uploaded successfully!</span>
          </div>
          <div className="flex gap-3">
            <a
              href={result.url}
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-1 text-xs hover:underline"
              style={{ color: "#4FC3F7" }}
            >
              Watch <ExternalLink size={11} />
            </a>
            <a
              href={result.studio_url}
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-1 text-xs hover:underline"
              style={{ color: "#94a3b8" }}
            >
              Edit in Studio <ExternalLink size={11} />
            </a>
          </div>
        </div>
      )}

      {/* Error banner */}
      {error && (
        <div
          className="flex items-center gap-2 px-4 py-3 rounded-xl text-sm"
          style={{ background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.3)", color: "#f87171" }}
        >
          <AlertCircle size={15} />
          {error}
        </div>
      )}

      {/* Drop zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => !videoFile && videoRef.current?.click()}
        className="relative rounded-2xl p-8 flex flex-col items-center justify-center gap-3 transition-all duration-200"
        style={{
          background: dragging
            ? "rgba(79,195,247,0.08)"
            : videoFile
            ? "rgba(34,197,94,0.06)"
            : "rgba(255,255,255,0.02)",
          border: `2px dashed ${dragging ? "#4FC3F7" : videoFile ? "rgba(34,197,94,0.4)" : "rgba(255,255,255,0.1)"}`,
          cursor: videoFile ? "default" : "pointer",
          minHeight: 160,
        }}
      >
        <input
          ref={videoRef}
          type="file"
          accept="video/*"
          className="hidden"
          onChange={(e) => e.target.files?.[0] && setVideoFile(e.target.files[0])}
        />

        {videoFile ? (
          <div className="flex items-center justify-between w-full">
            <div className="flex items-center gap-3">
              <div
                className="w-10 h-10 rounded-xl flex items-center justify-center"
                style={{ background: "rgba(34,197,94,0.15)", color: "#4ade80" }}
              >
                <FileVideo size={20} />
              </div>
              <div>
                <p className="text-sm font-medium text-white">{videoFile.name}</p>
                <p className="text-xs" style={{ color: "var(--muted)" }}>{formatBytes(videoFile.size)}</p>
              </div>
            </div>
            <button
              onClick={(e) => { e.stopPropagation(); setVideoFile(null); }}
              className="w-7 h-7 rounded-lg flex items-center justify-center transition-colors hover:bg-red-500/20"
              style={{ color: "#94a3b8" }}
            >
              <X size={14} />
            </button>
          </div>
        ) : (
          <>
            <div
              className="w-12 h-12 rounded-2xl flex items-center justify-center"
              style={{ background: "rgba(79,195,247,0.1)", color: "#4FC3F7" }}
            >
              <Upload size={22} />
            </div>
            <div className="text-center">
              <p className="text-sm font-medium text-white">
                {dragging ? "Drop it here" : "Drag & drop your video"}
              </p>
              <p className="text-xs mt-1" style={{ color: "var(--muted)" }}>
                or click to browse · MP4, MOV, AVI, MKV
              </p>
            </div>
          </>
        )}
      </div>

      {/* Form */}
      <div className="glass rounded-2xl p-6 space-y-5">
        {/* Title */}
        <Field label="Title (Hindi / English)" icon={<AlignLeft size={12} />}>
          <StyledInput
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. आज की बड़ी खबरें | Today's Top News"
            maxLength={100}
          />
          <p className="text-right text-xs mt-0.5" style={{ color: "var(--muted)" }}>
            {title.length}/100
          </p>
        </Field>

        {/* Description */}
        <Field label="Description" icon={<AlignLeft size={12} />}>
          <StyledTextarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Video description… (Hindi or English)"
            rows={4}
            maxLength={5000}
          />
        </Field>

        {/* Tags */}
        <Field label="Tags (comma-separated)" icon={<Tag size={12} />}>
          <StyledInput
            value={tags}
            onChange={(e) => setTags(e.target.value)}
            placeholder="news, hindi news, India, breaking news"
          />
        </Field>

        {/* Category + Privacy */}
        <div className="grid grid-cols-2 gap-4">
          <Field label="Category" icon={<Hash size={12} />}>
            <StyledSelect value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
              {CATEGORIES.map((c) => (
                <option key={c.id} value={c.id}>{c.label}</option>
              ))}
            </StyledSelect>
          </Field>

          <Field label="Privacy" icon={<Hash size={12} />}>
            <StyledSelect value={privacy} onChange={(e) => setPrivacy(e.target.value)}>
              <option value="public">Public</option>
              <option value="private">Private</option>
              <option value="unlisted">Unlisted</option>
            </StyledSelect>
          </Field>
        </div>

        {/* Schedule time */}
        <Field label="Schedule publish time (optional)" icon={<Clock size={12} />}>
          <StyledInput
            type="datetime-local"
            value={scheduleTime}
            onChange={(e) => setScheduleTime(e.target.value)}
          />
          <p className="text-xs mt-0.5" style={{ color: "var(--muted)" }}>
            Leave blank to publish immediately (or use the privacy setting above).
          </p>
        </Field>

        {/* Thumbnail */}
        <Field label="Thumbnail (optional)" icon={<Image size={12} />}>
          <div className="flex items-center gap-3">
            <input
              ref={thumbRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => e.target.files?.[0] && setThumbFile(e.target.files[0])}
            />
            <button
              onClick={() => thumbRef.current?.click()}
              className="px-3 py-2 rounded-xl text-xs font-medium transition-all"
              style={{
                background: "rgba(79,195,247,0.08)",
                border: "1px solid rgba(79,195,247,0.2)",
                color: "#4FC3F7",
              }}
            >
              {thumbFile ? "Change image" : "Choose image"}
            </button>
            {thumbFile && (
              <span className="text-xs truncate max-w-xs" style={{ color: "#94a3b8" }}>
                {thumbFile.name} ({formatBytes(thumbFile.size)})
              </span>
            )}
          </div>
          <p className="text-xs mt-1" style={{ color: "var(--muted)" }}>
            JPG/PNG, 1280×720 recommended. Requires channel phone verification.
          </p>
        </Field>
      </div>

      {/* Upload button */}
      <button
        onClick={handleSubmit}
        disabled={uploading || !videoFile}
        className="w-full py-3.5 rounded-xl text-sm font-semibold flex items-center justify-center gap-2 transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed"
        style={{
          background: uploading
            ? "rgba(79,195,247,0.1)"
            : "linear-gradient(135deg, rgba(79,195,247,0.25) 0%, rgba(124,58,237,0.25) 100%)",
          border: "1px solid rgba(79,195,247,0.35)",
          color: "#4FC3F7",
          boxShadow: "0 0 20px rgba(79,195,247,0.1)",
        }}
      >
        {uploading ? (
          <>
            <div className="w-4 h-4 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin" />
            Uploading to YouTube… this may take a few minutes
          </>
        ) : (
          <>
            <Upload size={16} />
            Upload to YouTube
          </>
        )}
      </button>

      <p className="text-xs text-center" style={{ color: "var(--muted)" }}>
        Large files (&gt;500 MB) may time out on the cloud API — use local mode for those.
      </p>
    </div>
  );
}
