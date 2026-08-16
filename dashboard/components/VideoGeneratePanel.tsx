"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAccount } from "@/lib/accountContext";

export default function VideoGeneratePanel() {
  const { accountId } = useAccount();
  const [categories, setCategories] = useState<Record<string, { label: string }>>({});
  const [category, setCategory] = useState("");
  const [customTopic, setCustomTopic] = useState("");
  const [locale, setLocale] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState("");

  useEffect(() => {
    api.getAccountTopicConfig(accountId).then((cfg) => {
      setCategories(cfg.categories || {});
      const keys = Object.keys(cfg.categories || {});
      if (keys.length) setCategory(keys[0]);
    });
  }, [accountId]);

  // Fire-and-forget: the backend spawns generate_video_now.py and answers
  // straight away (mirroring the Shorts panel), so this only reports whether
  // generation STARTED. The finished video — and its YouTube link — appears
  // in the video grid, which polls /api/videos.
  const generate = async () => {
    setBusy(true);
    setResult("");
    try {
      const res = await api.generateVideo(accountId, category, customTopic, locale);
      if (res.ok === false) {
        setResult(res.message ?? "Could not start generation");
      } else {
        setResult(res.message ?? "Generation started — the video will appear in the grid in a few minutes.");
      }
    } catch (e) {
      // Input errors (unknown account/category/locale) come back as a non-2xx
      // response — unwrap() in api.ts embeds the backend's real detail text in
      // this Error's message, so surface that instead of a generic one.
      setResult(`Failed: ${e instanceof Error ? e.message : String(e)}`);
    }
    setBusy(false);
  };

  return (
    <div className="p-4 rounded-xl border border-slate-700">
      <h3 className="font-semibold mb-3">Generate a long-form video now</h3>
      <div className="flex flex-col gap-3">
        <select value={category} onChange={(e) => setCategory(e.target.value)} className="bg-transparent border border-slate-700 rounded-lg px-3 py-2 text-sm">
          {Object.entries(categories).map(([key, c]) => (
            <option key={key} value={key}>{c.label}</option>
          ))}
        </select>
        <input
          value={customTopic}
          onChange={(e) => setCustomTopic(e.target.value)}
          placeholder="Optional custom topic — leave blank for a fresh trending topic"
          className="bg-transparent border border-slate-700 rounded-lg px-3 py-2 text-sm"
        />
        <input
          value={locale}
          onChange={(e) => setLocale(e.target.value)}
          placeholder="Optional locale override (e.g. hi, en) — leave blank for account default"
          className="bg-transparent border border-slate-700 rounded-lg px-3 py-2 text-sm"
        />
        <button onClick={generate} disabled={busy || !category} className="bg-blue-600 rounded-lg px-4 py-2 text-sm font-medium disabled:opacity-50">
          {busy ? "Starting…" : "Generate"}
        </button>
        {result && <p className="text-xs text-slate-400">{result}</p>}
      </div>
    </div>
  );
}
