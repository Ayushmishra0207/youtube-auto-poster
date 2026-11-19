"""Download a source video with yt-dlp (≤1080p MP4) — cached per video id."""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Callable

from clipper.common import SOURCES_DIR, ffmpeg_exe, log

_ID_SAFE = re.compile(r"[^0-9A-Za-z_-]")


def _ydl_opts(extra: dict | None = None) -> dict:
    opts = {
        "quiet": True,
        "noprogress": True,
        "no_warnings": True,
        "noplaylist": True,
        "ffmpeg_location": ffmpeg_exe(),
        # YouTube serves some formats only after solving a JS challenge; Node is
        # the runtime available on this machine (yt-dlp also accepts deno/bun).
        "js_runtimes": {"node": {}},
        "retries": 5,
        "fragment_retries": 5,
    }
    if os.getenv("CLIPPER_YTDLP_REMOTE_EJS", "") == "1":
        opts["remote_components"] = ["ejs:github"]
    cookies = os.getenv("CLIPPER_YTDLP_COOKIES", "").strip()
    if cookies:
        opts["cookiefile"] = cookies
    if extra:
        opts.update(extra)
    return opts


def fetch_info(url: str) -> dict:
    import yt_dlp
    with yt_dlp.YoutubeDL(_ydl_opts({"skip_download": True})) as ydl:
        info = ydl.extract_info(url, download=False)
    if info.get("_type") == "playlist":
        raise ValueError("That link is a playlist — paste a single video link.")
    return info


def download(url: str, on_progress: Callable[[float], None] | None = None) -> tuple[Path, dict]:
    """Return (local mp4 path, metadata). Re-uses an earlier download of the same video."""
    import yt_dlp

    info = fetch_info(url)
    if info.get("is_live"):
        raise ValueError("Live streams can't be clipped until they've finished.")
    vid = _ID_SAFE.sub("_", f"{info.get('extractor_key', 'src')}_{info.get('id', 'video')}")
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    target = SOURCES_DIR / f"{vid}.mp4"

    meta = {
        "id": info.get("id", ""),
        "url": info.get("webpage_url") or url,
        "title": info.get("title", ""),
        "channel": info.get("channel") or info.get("uploader") or "",
        "channel_url": info.get("channel_url") or info.get("uploader_url") or "",
        "duration": float(info.get("duration") or 0),
        "thumbnail": info.get("thumbnail", ""),
        "description": (info.get("description") or "")[:1500],
        "tags": (info.get("tags") or [])[:20],
        "chapters": [
            {"start": c.get("start_time", 0), "end": c.get("end_time", 0), "title": c.get("title", "")}
            for c in (info.get("chapters") or [])
        ],
    }

    if target.exists() and target.stat().st_size > 0:
        log.info("Using cached source %s", target.name)
        if on_progress:
            on_progress(1.0)
        return target, meta

    def hook(d: dict) -> None:
        if on_progress and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if total:
                on_progress(min(0.99, d.get("downloaded_bytes", 0) / total))

    tmp_tmpl = str(SOURCES_DIR / f"{vid}.part_dl.%(ext)s")
    opts = _ydl_opts({
        # Prefer H.264: YouTube's AV1 streams decode ~10x slower with this ffmpeg build
        "format": ("bv*[height<=1080][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=1080][vcodec^=avc1]+ba/"
                   "bv*[height<=1080][vcodec^=vp09]+ba/bv*[height<=1080]+ba/b[height<=1080]/b"),
        "merge_output_format": "mp4",
        "outtmpl": tmp_tmpl,
        "progress_hooks": [hook],
    })
    log.info("Downloading %s (%s)", meta["title"], meta["url"])
    with yt_dlp.YoutubeDL(opts) as ydl:
        result = ydl.extract_info(url, download=True)
        produced = Path(ydl.prepare_filename(result)).with_suffix(".mp4")

    if not produced.exists():
        # yt-dlp can keep a different container if merging wasn't needed
        candidates = sorted(SOURCES_DIR.glob(f"{vid}.part_dl.*"))
        if not candidates:
            raise RuntimeError("Download finished but no video file was produced.")
        produced = candidates[0]
    shutil.move(str(produced), str(target))
    for leftover in SOURCES_DIR.glob(f"{vid}.part_dl.*"):
        leftover.unlink(missing_ok=True)
    if on_progress:
        on_progress(1.0)
    return target, meta
