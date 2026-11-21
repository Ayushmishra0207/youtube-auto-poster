"""
"Split into parts": cut a whole video (YouTube link or uploaded file) into
consecutive vertical Shorts of a chosen length, each labelled "Part 1",
"Part 2", … under the video — for posting a long video as a numbered series.

Reuses the viral clipper's pieces: downloader (full HD — every second is used),
transcriber (optional subtitles), renderer (9:16 layout, label, watermark).
"""
from __future__ import annotations

import json
import math
import re
import time
import traceback
from pathlib import Path

from clipper import downloader, renderer, transcriber
from clipper.common import SOURCES_DIR, JobStatus, log, probe
from clipper.modes import CAPTION_STYLES, NO_CAPTIONS, SERIES_MODE

UPLOAD_NAME_RE = re.compile(r"^upload_[0-9a-f]{12}\.(mp4|mov|mkv|webm|avi|m4v)$")
MIN_LAST_PART = 10.0      # a shorter tail is merged into the previous part


def plan_parts(start: float, end: float, part_len: float, words: list[dict] | None = None) -> list[tuple[float, float]]:
    """Consecutive (start, end) parts of ~part_len seconds covering [start, end].
    Boundaries move up to ±1.5 s into a pause between words, so no part starts or
    ends mid-word. A tail under MIN_LAST_PART seconds joins the previous part."""
    total = end - start
    if total <= 0:
        return []
    n = max(1, math.ceil(total / part_len - 1e-9))
    cuts = [start + part_len * i for i in range(1, n)]
    if n > 1 and end - cuts[-1] < MIN_LAST_PART:
        cuts.pop()
    if words:
        gaps = [((a["end"] + b["start"]) / 2) for a, b in zip(words, words[1:]) if b["start"] - a["end"] > 0.25]
        snapped = []
        for c in cuts:
            near = [g for g in gaps if abs(g - c) <= 1.5]
            snapped.append(min(near, key=lambda g: abs(g - c)) if near else c)
        cuts = snapped
    edges = [start, *cuts, end]
    return [(round(a, 2), round(b, 2)) for a, b in zip(edges, edges[1:]) if b - a > 0.5]


def _fmt(t: float) -> str:
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"


def _source(req: dict, status: JobStatus) -> tuple[Path, dict]:
    name = (req.get("source_file") or "").strip()
    if name:
        if not UPLOAD_NAME_RE.match(name) or not (SOURCES_DIR / name).exists():
            raise ValueError("The uploaded video wasn't found — upload it again.")
        status.stage("download", 15, "Using the uploaded video")
        meta_file = SOURCES_DIR / (name + ".json")
        meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
        return SOURCES_DIR / name, {"title": meta.get("filename", "Video"), "channel": "", "url": "",
                                    "thumbnail": "", "duration": 0}
    status.stage("download", 1, "Fetching video info")
    return downloader.download(
        req["url"], on_progress=lambda p: status.stage("download", 2 + 16 * p, f"Downloading {int(p * 100)}%"))


def run_series(job_dir: Path, req: dict, status: JobStatus) -> None:
    wav = job_dir / "audio.wav"
    try:
        src, meta = _source(req, status)
        info = probe(src)
        meta["duration"] = info.duration
        status.update(source=meta)

        a = max(0.0, float(req.get("range_start") or 0))
        b = float(req.get("range_end") or 0) or info.duration
        b = min(b, info.duration)
        if b - a < 5:
            raise ValueError("The selected time range is shorter than 5 seconds.")
        part_len = max(15.0, min(180.0, float(req.get("part_seconds") or 60)))

        # Optional subtitles: transcribe the selected range once, before cutting
        words: list[dict] = []
        style_key = SERIES_MODE.caption_style if req["caption_style"] == "auto" else req["caption_style"]
        style = None if style_key == NO_CAPTIONS else CAPTION_STYLES.get(style_key, CAPTION_STYLES["clean"])
        if style and info.has_audio:
            status.stage("transcribe", 20, "Preparing audio for subtitles")
            transcriber.extract_audio(src, wav)
            tr = transcriber.transcribe(
                wav, language=req["language"], ranges=[(a, b)], total_duration=info.duration,
                on_progress=lambda p: status.stage("transcribe", 22 + 28 * p, f"Subtitles {int(p * 100)}%"),
            )
            words = tr["words"]
            status.update(detected_language=tr["language"])

        parts = plan_parts(a, b, part_len, words)
        total = len(parts)
        status.stage("render", 50, f"Splitting into {total} part(s) of ~{int(part_len)} s")
        log.info("Series %s: %d parts of ~%ds from %s–%s", job_dir.name, total, part_len, _fmt(a), _fmt(b))

        label_tpl = (req.get("part_label") or "Part {n}").strip()[:40]
        series_title = (req.get("series_title") or "").strip()[:60]
        base_title = series_title or meta.get("title") or "Video"
        results = []
        for i, (s, e) in enumerate(parts, 1):
            status.stage("render", 50 + 49 * (i - 1) / total, f"Rendering part {i} of {total}")
            label = label_tpl.replace("{n}", str(i)).replace("{total}", str(total))
            clip_words = [{"start": w["start"] - s, "end": min(w["end"], e) - s, "text": w["text"]}
                          for w in words if s - 0.05 <= w["start"] < e - 0.1]
            renderer.render_clip(
                src, info, s, e, job_dir / f"clip_{i:02d}", SERIES_MODE, clip_words,
                renderer.RenderOptions(layout=req["layout"], caption_style=style, hook_text=series_title,
                                       watermark=(req.get("watermark") or "").strip(), part_label=label),
            )
            clip_meta = _part_metadata(i, total, s, e, label, base_title, meta, req)
            (job_dir / f"clip_{i:02d}" / "clip.json").write_text(
                json.dumps(clip_meta, ensure_ascii=False, indent=2), encoding="utf-8")
            results.append(clip_meta)
            status.update(clips=results)

        status.update(state="done", stage="done", progress=100, message=f"{total} part(s) ready",
                      finished_at=time.time())
        log.info("Series %s done — %d parts", job_dir.name, total)
    except Exception as e:
        log.error("Series job %s failed: %s\n%s", job_dir.name, e, traceback.format_exc())
        status.update(state="failed", stage="failed", error=str(e)[:800], message="Failed", finished_at=time.time())
        raise
    finally:
        wav.unlink(missing_ok=True)


def _part_metadata(i: int, total: int, s: float, e: float, label: str, base_title: str,
                   meta: dict, req: dict) -> dict:
    suffix = f" | {label}"
    title = (base_title[: 100 - len(suffix)].rstrip() + suffix)[:100]
    tags = ["#Shorts", f"#Part{i}"]
    desc = f"{base_title} — {label} of {total}.\nFollow so you don't miss the next part!"
    if req.get("credit_source") and meta.get("url"):
        desc += f"\n\nSource: \"{meta.get('title', '')}\" by {meta.get('channel') or 'the original creator'} — {meta['url']}"
    desc += "\n\n" + " ".join(tags)
    return {
        "index": i, "start": s, "end": e, "duration": round(e - s, 2),
        "hook_text": label, "title": title, "description": desc[:4900],
        "hashtags": tags, "tags": [t.lstrip("#") for t in tags],
        "score": 0, "reason": f"{label} of {total} · {_fmt(s)}–{_fmt(e)} of the source",
        "picked_by": "series", "part": i, "parts_total": total, "yt_category": SERIES_MODE.yt_category,
    }
