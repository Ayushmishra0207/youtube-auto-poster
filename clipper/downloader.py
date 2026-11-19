"""Download a source video with yt-dlp (≤1080p MP4) — cached per video id."""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Callable

from clipper.common import SOURCES_DIR, ffmpeg_dir_for_ytdlp, log

_ID_SAFE = re.compile(r"[^0-9A-Za-z_-]")


def _ydl_opts(extra: dict | None = None) -> dict:
    opts = {
        "quiet": True,
        "noprogress": True,
        "no_warnings": True,
        "noplaylist": True,
        "ffmpeg_location": ffmpeg_dir_for_ytdlp(),
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


def source_id(info: dict) -> str:
    return _ID_SAFE.sub("_", f"{info.get('extractor_key', 'src')}_{info.get('id', 'video')}")


def info_to_meta(info: dict, url: str) -> dict:
    return {
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


# ── Fast path for long videos ───────────────────────────────────────────────────
# Downloading a 10-hour stream in 1080p meant ~17 GB and hours of decoding just
# to *find* the moments. Instead: analyse from the audio track (~60 MB/hour) and
# a 144-240p video-only copy (scene cuts), then fetch only the chosen sections in HD.

HD_FORMAT = ("bv*[height<=1080][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=1080][vcodec^=avc1]+ba/"
             "bv*[height<=1080][vcodec^=vp09]+ba/bv*[height<=1080]+ba/b[height<=1080]/b")


def _download_one(url: str, fmt: str, out_base: Path, on_progress=None) -> Path:
    """yt-dlp download of one format into out_base.<ext>; cached if present."""
    import yt_dlp
    existing = sorted(p for p in out_base.parent.glob(out_base.name + ".*") if not p.name.endswith((".part", ".ytdl")))
    if existing:
        if on_progress:
            on_progress(1.0)
        return existing[0]

    def hook(d: dict) -> None:
        if on_progress and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if total:
                on_progress(min(0.99, d.get("downloaded_bytes", 0) / total))

    opts = _ydl_opts({"format": fmt, "outtmpl": str(out_base) + ".%(ext)s", "progress_hooks": [hook]})
    with yt_dlp.YoutubeDL(opts) as ydl:
        result = ydl.extract_info(url, download=True)
        path = Path(ydl.prepare_filename(result))
    if not path.exists():
        found = sorted(out_base.parent.glob(out_base.name + ".*"))
        if not found:
            raise RuntimeError(f"Download produced no file for format {fmt}")
        path = found[0]
    if on_progress:
        on_progress(1.0)
    return path


def download_analysis_media(url: str, info: dict, on_progress=None) -> tuple[Path, Path | None]:
    """Audio-only + low-res video-only copies, fetched in parallel. Returns (audio, lowres_video|None)."""
    from concurrent.futures import ThreadPoolExecutor
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    vid = source_id(info)
    prog = {"a": 0.0, "v": 0.0}

    def report():
        if on_progress:
            on_progress(0.7 * prog["a"] + 0.3 * prog["v"])

    def track(key):
        def f(p):
            prog[key] = p
            report()
        return f

    with ThreadPoolExecutor(max_workers=2) as pool:
        fa = pool.submit(_download_one, url, "ba[ext=m4a]/ba", SOURCES_DIR / f"{vid}.audio", track("a"))
        fv = pool.submit(_download_one, url,
                         "wv*[height>=144][vcodec^=avc1]/wv*[height>=144]/wv",
                         SOURCES_DIR / f"{vid}.lowres", track("v"))
        audio = fa.result()
        try:
            lowres = fv.result()
        except Exception as e:   # scene cuts are a bonus signal, not required
            log.warning("Low-res video download failed (%s) — continuing without scene cuts", e)
            lowres = None
    return audio, lowres


def get_hd_streams(url: str) -> list[dict]:
    """Resolve the HD video (+audio) stream URLs once per job; sections are then cut
    straight from them with ffmpeg (~10 s each vs ~70 s via yt-dlp's ranged download,
    which re-resolves the video every time). URLs stay valid for hours."""
    import yt_dlp
    with yt_dlp.YoutubeDL(_ydl_opts({"format": HD_FORMAT})) as ydl:
        info = ydl.extract_info(url, download=False)
    fmts = info.get("requested_formats") or [info]
    return [{"url": f["url"], "headers": f.get("http_headers") or {},
             "has_video": f.get("vcodec") not in (None, "none"),
             "has_audio": f.get("acodec") not in (None, "none")} for f in fmts]


def fetch_section(url: str, streams: list[dict] | None, start: float, end: float, out_path: Path,
                  local_src: Path | None = None) -> Path:
    """Exact [start, end] of the HD video as a local mp4 (fast lossless-ish intermediate).
    Cut from `local_src` if a full HD copy is already on disk, else from the streams."""
    from clipper.common import run_ffmpeg
    out_path.parent.mkdir(parents=True, exist_ok=True)
    start = max(0.0, start)
    if local_src is not None:
        run_ffmpeg(["-y", "-ss", f"{start:.3f}", "-i", str(local_src), "-t", f"{end - start:.3f}",
                    "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "ultrafast",
                    "-crf", "16", "-c:a", "aac", "-b:a", "192k", str(out_path)], timeout=900)
        return out_path
    if streams:
        try:
            args = ["-y"]
            for st in streams:
                hdr = "".join(f"{k}: {v}\r\n" for k, v in st["headers"].items())
                args += ["-headers", hdr, "-ss", f"{start:.3f}", "-i", st["url"]]
            vi = next((i for i, st in enumerate(streams) if st["has_video"]), 0)
            ai = next((i for i, st in enumerate(streams) if st["has_audio"]), None)
            args += ["-t", f"{end - start:.3f}", "-map", f"{vi}:v:0"]
            if ai is not None:
                args += ["-map", f"{ai}:a:0", "-c:a", "aac", "-b:a", "192k"]
            # Re-encoding (ultrafast, near-lossless) is what makes the cut frame-exact
            args += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "16", str(out_path)]
            run_ffmpeg(args, timeout=900)
            return out_path
        except Exception as e:
            log.warning("Direct section fetch failed (%s) — falling back to yt-dlp", e)
    return download_section(url, start, end, out_path)


def download_section(url: str, start: float, end: float, out_path: Path) -> Path:
    """Fetch only [start, end] of the HD video. force_keyframes_at_cuts makes yt-dlp
    re-encode at the cut points, so the file starts exactly at `start` (caption
    timing depends on that)."""
    import yt_dlp
    from yt_dlp.utils import download_range_func
    out_path.parent.mkdir(parents=True, exist_ok=True)
    base = out_path.with_suffix("")
    opts = _ydl_opts({
        "format": HD_FORMAT,
        "merge_output_format": "mp4",
        "outtmpl": str(base) + ".%(ext)s",
        "download_ranges": download_range_func(None, [(max(0.0, start), end)]),
        "force_keyframes_at_cuts": True,
    })
    with yt_dlp.YoutubeDL(opts) as ydl:
        result = ydl.extract_info(url, download=True)
        produced = Path(ydl.prepare_filename(result)).with_suffix(".mp4")
    if not produced.exists():
        found = sorted(p for p in base.parent.glob(base.name + ".*") if p.suffix in (".mp4", ".mkv", ".webm"))
        if not found:
            raise RuntimeError("Section download produced no file")
        produced = found[0]
    if produced != out_path:
        shutil.move(str(produced), str(out_path))
    return out_path


def download(url: str, on_progress: Callable[[float], None] | None = None,
             info: dict | None = None) -> tuple[Path, dict]:
    """Full HD download (short videos). Return (local mp4 path, metadata). Cached per video id."""
    import yt_dlp

    info = info or fetch_info(url)
    if info.get("is_live"):
        raise ValueError("Live streams can't be clipped until they've finished.")
    vid = source_id(info)
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    target = SOURCES_DIR / f"{vid}.mp4"

    meta = info_to_meta(info, url)

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
        "format": HD_FORMAT,
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
