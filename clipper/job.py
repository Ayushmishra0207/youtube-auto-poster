"""Orchestrates one clip job: download → analyse → transcribe → plan → render."""
from __future__ import annotations

import json
import os
import random
import re
import secrets
import time
import traceback
from datetime import datetime
from pathlib import Path

from clipper import analyzer, downloader, planner, renderer, transcriber
from clipper.common import CLIPS_DIR, SOURCES_DIR, JobStatus, find_music_track, log, probe
from clipper.modes import CAPTION_STYLES, LENGTH_PRESETS, NO_CAPTIONS, get_mode

# Full transcription above this length is slow on CPU; action-type modes then
# transcribe only the strongest signal windows instead.
FULL_TRANSCRIBE_MAX_S = float(os.getenv("CLIPPER_FULL_TRANSCRIBE_MAX_MIN", "25")) * 60

# Above this length, never download the full HD video: analyse from audio + a 144p
# copy and fetch only the chosen sections in HD (a 10 h stream was 17 GB / 25 min).
FAST_PATH_MIN_S = float(os.getenv("CLIPPER_FAST_PATH_MIN_MIN", "15")) * 60

DEFAULT_REQUEST = {
    "url": "",
    "mode": "gta6_action",
    "num_clips": 3,
    "length": "auto",
    "layout": "blur_fit",
    "caption_style": "auto",
    "language": "auto",
    "title_language": "hinglish",
    "hook_text": True,
    "watermark": "",
    "audio_mode": "original",
    "credit_source": True,
    "use_ai": True,
    # ── "Split into parts" (series) mode ──
    "job_type": "viral",          # viral | series
    "part_seconds": 60,           # length of each part (UI: 30-60)
    "range_start": 0.0,           # optional: only split this window of the source (seconds)
    "range_end": 0.0,             # 0 = until the end
    "series_title": "",           # optional banner on top of every part
    "part_label": "Part {n}",     # text under the video; {n} = part number, {total} = number of parts
    "source_file": "",            # an uploaded file in output/clips/_sources (instead of a URL)
}


def new_job(request: dict) -> Path:
    req = {**DEFAULT_REQUEST, **{k: v for k, v in request.items() if k in DEFAULT_REQUEST}}
    req["num_clips"] = max(1, min(10, int(req["num_clips"])))
    job_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
    job_dir = CLIPS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "job.json").write_text(json.dumps(req, ensure_ascii=False, indent=2), encoding="utf-8")
    JobStatus(job_dir).update(
        job_id=job_id, state="queued", stage="queued", progress=0, message="Waiting to start",
        error="", created_at=time.time(), request=req, source={}, clips=[], pid=0,
    )
    return job_dir


def _words_in(words: list[dict], start: float, end: float) -> list[dict]:
    return [{"start": w["start"] - start, "end": min(w["end"], end) - start, "text": w["text"]}
            for w in words if w["start"] >= start - 0.05 and w["start"] < end - 0.1]


def _hashtag(t: str) -> str:
    t = re.sub(r"[^\w]", "", t.lstrip("#"))
    return f"#{t}" if t else ""


def run_job(job_dir: Path) -> None:
    status = JobStatus(job_dir)
    req = {**DEFAULT_REQUEST, **json.loads((job_dir / "job.json").read_text(encoding="utf-8"))}
    status.update(pid=os.getpid(), started_at=time.time())
    if req.get("job_type") == "series":
        from clipper.series import run_series
        return run_series(job_dir, req, status)
    mode = get_mode(req["mode"])
    n = int(req["num_clips"])
    preset = LENGTH_PRESETS.get(req["length"]) or (mode.min_len, mode.max_len)
    min_len, max_len = preset
    wav = job_dir / "audio.wav"

    try:
        # 1 ── Download ───────────────────────────────────────────────────────
        status.stage("download", 1, "Fetching video info")
        yinfo = downloader.fetch_info(req["url"])
        if yinfo.get("is_live"):
            raise ValueError("Live streams can't be clipped until they've finished.")
        meta = downloader.info_to_meta(yinfo, req["url"])
        full_file = SOURCES_DIR / f"{downloader.source_id(yinfo)}.mp4"
        # Long videos always analyse from audio + 144p (decoding a cached 17 GB HD
        # file for scene cuts takes hours); a cached HD file is only used to cut sections.
        fast = meta["duration"] > FAST_PATH_MIN_S
        local_hd = full_file if (fast and full_file.exists()) else None
        dl_progress = lambda p: status.stage("download", 2 + 16 * p, f"Downloading {int(p * 100)}%")  # noqa: E731

        src: Path | None = None          # full HD file (short videos only)
        if fast:
            # Long video: analyse from audio + a 144p copy; HD only for the chosen sections
            status.stage("download", 2, f"Long video ({meta['duration'] / 60:.0f} min) — downloading audio + preview only")
            audio_src, scene_src = downloader.download_analysis_media(req["url"], yinfo, on_progress=dl_progress)
            info = probe(audio_src)
            info.has_audio = True
        else:
            src, meta = downloader.download(req["url"], on_progress=dl_progress, info=yinfo)
            info = probe(src)
            audio_src, scene_src = src, src
        meta["duration"] = info.duration
        status.update(source=meta)
        if info.duration < 8:
            raise ValueError("Video is too short to clip (under 8 seconds).")
        min_len = min(min_len, max(5, int(info.duration * 0.8)))
        max_len = min(max_len, int(info.duration))

        # 2 ── Signals ────────────────────────────────────────────────────────
        status.stage("analyze", 19, "Analysing audio and scene changes")
        energy = None
        if info.has_audio:
            transcriber.extract_audio(audio_src, wav)
            energy = analyzer.audio_energy(wav)
        import numpy as np
        energy = energy if energy is not None else np.zeros((0, 2), dtype=np.float32)
        cuts = analyzer.scene_cuts(scene_src) if scene_src else []
        status.stage("analyze", 26, f"Found {len(cuts)} scene cuts")

        # 3 ── Transcribe ─────────────────────────────────────────────────────
        words: list[dict] = []
        segments: list[dict] = []
        covered: list[tuple[float, float]] = []      # audio ranges already transcribed
        speech_heavy = mode.w_speech >= 0.45
        speech_light = mode.w_speech < 0.3           # action / cinematic
        if info.has_audio:
            ranges: list[tuple[float, float]] | None = None
            if speech_light or info.duration > FULL_TRANSCRIBE_MAX_S:
                # Moments are found from loudness + scene cuts first; Whisper (CPU,
                # ~real-time on Hindi) then only runs where it matters. Speech-light
                # modes need words just for the final clips' subtitles (transcribed
                # after picking) — plus a few top candidates so the AI can write
                # titles. Long talk-heavy videos transcribe more candidate windows.
                pre = analyzer.per_second_features(info.duration, energy, cuts, [])
                k = (n * 2 if req["use_ai"] else 0) if speech_light else n * (6 if speech_heavy else 3)
                cands = analyzer.find_candidates(info.duration, pre, mode, min_len, max_len, k) if k else []
                ranges = _merge([(max(0, c["start"] - 10), min(info.duration, c["end"] + 10)) for c in cands])
                log.info("Transcribing %d focused region(s) now (%.0f s of %.0f s)",
                         len(ranges), sum(b - a for a, b in ranges), info.duration)
            if ranges is None or ranges:
                status.stage("transcribe", 27, "Loading speech model")
                tr = transcriber.transcribe(
                    wav, language=req["language"], prompt=mode.whisper_prompt, ranges=ranges,
                    total_duration=info.duration,
                    on_progress=lambda p: status.stage("transcribe", 28 + 32 * p, f"Transcribing {int(p * 100)}%"),
                )
                words, segments = tr["words"], tr["segments"]
                covered = ranges if ranges is not None else [(0.0, info.duration)]
                status.update(detected_language=tr["language"])

        # 4 ── Pick moments ───────────────────────────────────────────────────
        status.stage("plan", 61, "Scoring moments")
        feats = analyzer.per_second_features(info.duration, energy, cuts, words)
        candidates = analyzer.find_candidates(info.duration, feats, mode, min_len, max_len, max(n * 3, 6))
        planned = None
        if req["use_ai"]:
            status.stage("plan", 63, "AI is picking the most viral moments")
            planned = planner.plan_with_claude(meta, mode, segments, candidates, n, min_len, max_len,
                                               info.duration, req["title_language"])
        if planned:
            picks = planned
            # If Claude returned fewer than asked, top up from signal candidates
            for c in candidates:
                if len(picks) >= n:
                    break
                if all(c["end"] <= p["start"] or c["start"] >= p["end"] for p in picks):
                    picks.append(c)
        else:
            picks = candidates[:n]
        picks = sorted(picks[:n], key=lambda p: p["start"])

        # Subtitles need words for every picked clip — transcribe whatever part of
        # the picks (±3 s, so boundary snapping sees nearby words) isn't covered yet.
        if info.has_audio:
            missing = _uncovered([(max(0.0, p["start"] - 3), min(info.duration, p["end"] + 3)) for p in picks],
                                 covered)
            if missing:
                status.stage("transcribe", 62, "Transcribing the chosen clips")
                tr = transcriber.transcribe(
                    wav, language=req["language"], prompt=mode.whisper_prompt, ranges=missing,
                    total_duration=info.duration,
                    on_progress=lambda p: status.stage("transcribe", 62 + 2 * p, f"Subtitles {int(p * 100)}%"),
                )
                words = sorted(words + tr["words"], key=lambda w: w["start"])
                segments = sorted(segments + tr["segments"], key=lambda s_: s_["start"])
                status.update(detected_language=tr["language"] or status.data.get("detected_language", ""))

        # 5 ── Render ─────────────────────────────────────────────────────────
        style_key = mode.caption_style if req["caption_style"] == "auto" else req["caption_style"]
        style = None if style_key == NO_CAPTIONS else CAPTION_STYLES.get(style_key, CAPTION_STYLES["impact"])
        music = find_music_track() if req["audio_mode"] != "original" else None
        if req["audio_mode"] != "original" and music is None:
            log.warning("No music in assets/music — keeping original audio")
        fallback_hooks = list(mode.fallback_hooks or ("WATCH TILL THE END",))
        random.Random(job_dir.name).shuffle(fallback_hooks)
        streams = None
        if fast and not local_hd:
            status.stage("render", 64, "Resolving HD stream")
            try:
                streams = downloader.get_hd_streams(req["url"])
            except Exception as ex:   # fetch_section falls back to yt-dlp per clip
                log.warning("Could not resolve HD streams (%s)", ex)
        results = []
        for i, p in enumerate(picks, 1):
            s, e = analyzer.snap(p["start"], p["end"], words, cuts, info.duration, min_len, max_len)
            hook = (p.get("hook_text") or fallback_hooks[(i - 1) % len(fallback_hooks)]) \
                if req["hook_text"] else ""
            clip_dir = job_dir / f"clip_{i:02d}"
            if fast:
                # Only this clip's seconds in HD, cut frame-exactly → render from 0
                status.stage("render", 65 + 34 * (i - 1) / len(picks), f"Fetching HD section for clip {i} of {len(picks)}")
                clip_src = downloader.fetch_section(req["url"], streams, s, e, clip_dir / "section.mp4",
                                                    local_src=local_hd)
                clip_info, rs, re_ = probe(clip_src), 0.0, e - s
            else:
                clip_src, clip_info, rs, re_ = src, info, s, e
            status.stage("render", 65 + 34 * (i - 0.5) / len(picks), f"Rendering clip {i} of {len(picks)}")
            renderer.render_clip(
                clip_src, clip_info, rs, re_, clip_dir, mode, _words_in(words, s, e),
                renderer.RenderOptions(
                    layout=req["layout"], caption_style=style, hook_text=hook,
                    watermark=req["watermark"].strip(), audio_mode=req["audio_mode"] if music else "original",
                    music_path=music,
                ),
            )
            if fast:
                (clip_dir / "section.mp4").unlink(missing_ok=True)   # intermediate only
            clip_meta = _clip_metadata(i, s, e, p, hook, meta, mode, req)
            (clip_dir / "clip.json").write_text(json.dumps(clip_meta, ensure_ascii=False, indent=2), encoding="utf-8")
            results.append(clip_meta)
            status.update(clips=results)

        status.update(state="done", stage="done", progress=100, message=f"{len(results)} clip(s) ready",
                      finished_at=time.time())
        log.info("Job %s done — %d clips", job_dir.name, len(results))
    except Exception as e:
        log.error("Job %s failed: %s\n%s", job_dir.name, e, traceback.format_exc())
        status.update(state="failed", stage="failed", error=str(e)[:800], message="Failed",
                      finished_at=time.time())
        raise
    finally:
        wav.unlink(missing_ok=True)   # ~2 MB per minute of video — never keep it


def _uncovered(wanted: list[tuple[float, float]], covered: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Parts of `wanted` not inside any `covered` range (merged, ≥1 s pieces)."""
    out: list[tuple[float, float]] = []
    for a, b in _merge(wanted):
        cur = a
        for ca, cb in _merge(covered):
            if cb <= cur or ca >= b:
                continue
            if ca > cur:
                out.append((cur, ca))
            cur = max(cur, cb)
        if b > cur:
            out.append((cur, b))
    return [(a, b) for a, b in out if b - a >= 1.0]


def _merge(ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for a, b in sorted(ranges):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _clip_metadata(i: int, s: float, e: float, pick: dict, hook: str, meta: dict, mode, req: dict) -> dict:
    title = pick.get("title") or _smart_title(hook or meta.get("title", "Clip"))
    if not pick.get("title") and mode.key.startswith("gta6") and "GTA" not in title.upper():
        title = f"{title} | GTA 6"
    tags = [_hashtag(t) for t in (pick.get("hashtags") or list(mode.hashtags))]
    tags = [t for t in dict.fromkeys(tags) if t]
    if "#Shorts" not in tags:
        tags.append("#Shorts")
    desc = pick.get("description") or f"{_smart_title(hook) if hook else title}\n\nFollow for more {mode.label.split('·')[0].strip()} clips!"
    if req["credit_source"] and meta.get("title"):
        desc += f"\n\nSource: \"{meta['title']}\" by {meta.get('channel') or 'the original creator'} — {meta.get('url', '')}"
    desc += "\n\n" + " ".join(tags)
    return {
        "index": i,
        "start": s,
        "end": e,
        "duration": round(e - s, 2),
        "hook_text": hook,
        "title": title[:100],
        "description": desc[:4900],
        "hashtags": tags,
        "tags": [t.lstrip("#") for t in tags],
        "score": int(pick.get("virality_score") or max(1, min(99, int(50 + 20 * float(pick.get("score", 0)))))),
        "reason": pick.get("reason") or _signal_reason(pick.get("signals") or {}),
        "picked_by": "ai" if pick.get("virality_score") else "signals",
        "yt_category": mode.yt_category,
    }


_KEEP_UPPER = {"GTA", "VI", "NPC", "OMG", "WTF", "FPS", "PS5", "PC", "XBOX"}


def _smart_title(text: str) -> str:
    """'GTA 6 NPCS ARE WILD' → 'GTA 6 NPCs Are Wild' (keeps acronyms upper-case)."""
    out = []
    for w in text.split():
        core = re.sub(r"[^\w]", "", w).upper()
        if core in _KEEP_UPPER or any(ch.isdigit() for ch in w):
            out.append(w.upper())
        elif core.endswith("S") and core[:-1] in _KEEP_UPPER:      # plural acronym: NPCs
            i = w.upper().rfind("S")
            out.append(w.upper()[:i] + "s" + w[i + 1:])
        else:
            out.append(w.capitalize())
    return " ".join(out)[:100]


def _signal_reason(sig: dict) -> str:
    bits = []
    if sig.get("energy", 0) > 0.6:
        bits.append("big audio peaks")
    if sig.get("cuts_per_10s", 0) > 2:
        bits.append("fast action")
    if sig.get("words_per_s", 0) > 1.8:
        bits.append("dense commentary")
    if sig.get("hook", 0) > 0.8:
        bits.append("strong opening")
    return ("Picked for " + ", ".join(bits)) if bits else "Highest-scoring window by audio/scene signals"
