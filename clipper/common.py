"""Shared paths, logging, ffmpeg helpers and the job status file."""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path

BASE_DIR    = Path(__file__).resolve().parent.parent
CLIPS_DIR   = BASE_DIR / "output" / "clips"
SOURCES_DIR = CLIPS_DIR / "_sources"
FONTS_DIR   = BASE_DIR / "assets" / "fonts"
MUSIC_DIRS  = [BASE_DIR / "assets" / "music" / "clips", BASE_DIR / "assets" / "music"]
LOG_DIR     = BASE_DIR / "logs"

JOB_ID_RE = re.compile(r"^[0-9A-Za-z_-]{6,64}$")

# Hide the console window that every subprocess would otherwise flash on Windows
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


# ── Logging ─────────────────────────────────────────────────────────────────────

def get_logger() -> logging.Logger:
    log = logging.getLogger("clipper")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    LOG_DIR.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [CLIPPER] %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = RotatingFileHandler(LOG_DIR / "clipper.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(sh)
    return log


log = get_logger()


# ── ffmpeg ──────────────────────────────────────────────────────────────────────

def ffmpeg_exe() -> str:
    """ffmpeg binary. The imageio-ffmpeg build is preferred: it ships libass +
    HarfBuzz, which the burned-in captions (incl. Devanagari) depend on."""
    override = os.getenv("CLIPPER_FFMPEG", "").strip()
    if override:
        return override
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        found = shutil.which("ffmpeg")
        if not found:
            raise RuntimeError("ffmpeg not found — run: pip install imageio-ffmpeg")
        return found


def run_ffmpeg(args: list[str], cwd: Path | None = None, timeout: float | None = None) -> str:
    """Run ffmpeg; return stderr. Raise RuntimeError with the stderr tail on failure."""
    cmd = [ffmpeg_exe(), "-hide_banner", "-nostdin", *args]
    proc = subprocess.run(
        cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout, creationflags=_NO_WINDOW,
    )
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-12:])
        raise RuntimeError(f"ffmpeg failed (exit {proc.returncode}):\n{tail}")
    return proc.stderr


@dataclass
class MediaInfo:
    duration: float
    width: int
    height: int
    has_audio: bool


def probe(path: Path) -> MediaInfo:
    """Read duration / size / audio presence from `ffmpeg -i` (no ffprobe needed)."""
    proc = subprocess.run(
        [ffmpeg_exe(), "-hide_banner", "-i", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=_NO_WINDOW,
    )
    err = proc.stderr
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err)
    if not m:
        raise RuntimeError(f"Could not read media duration of {path.name}")
    duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    v = re.search(r"Stream #\d+:\d+.*?Video:.*?(\d{2,5})x(\d{2,5})", err)
    width, height = (int(v.group(1)), int(v.group(2))) if v else (1920, 1080)
    # Honour rotation metadata from phone recordings
    if re.search(r"rotate\s*:\s*-?(90|270)", err) or re.search(r"rotation of -?(90|270)", err):
        width, height = height, width
    return MediaInfo(duration=duration, width=width, height=height, has_audio="Audio:" in err)


def even(x: float) -> int:
    n = int(round(x))
    return n - (n % 2)


def find_music_track() -> Path | None:
    for d in MUSIC_DIRS:
        if d.exists():
            tracks = sorted(p for p in d.iterdir() if p.suffix.lower() in (".mp3", ".m4a", ".wav", ".aac", ".ogg"))
            if tracks:
                return tracks[0]
    return None


# ── Job status file (read by the API / dashboard) ───────────────────────────────

class JobStatus:
    """status.json inside a job dir. Written atomically so readers never see half a file."""

    def __init__(self, job_dir: Path):
        self.path = job_dir / "status.json"
        self.data: dict = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}

    def update(self, **fields) -> None:
        self.data.update(fields)
        self.data["updated_at"] = time.time()
        payload = json.dumps(self.data, ensure_ascii=False, indent=2)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(payload, encoding="utf-8")
        # On Windows the replace fails while the API has status.json open for
        # reading — that read takes milliseconds, so a short retry is enough.
        for attempt in range(20):
            try:
                os.replace(tmp, self.path)
                return
            except PermissionError:
                time.sleep(0.05 * (attempt + 1))
        log.warning("Could not update %s (file locked) — will retry on next update", self.path.name)

    def stage(self, stage: str, progress: float, message: str = "") -> None:
        bucket = (stage, int(progress) // 10)
        if bucket != getattr(self, "_last_logged", None):
            self._last_logged = bucket
            log.info("[%s] %s %s", self.path.parent.name, stage, message)
        # Progress callbacks fire many times a second; the dashboard polls every 2.5 s
        now = time.time()
        if stage == self.data.get("stage") and now - getattr(self, "_last_write", 0) < 0.75:
            return
        self._last_write = now
        self.update(state="running", stage=stage, progress=round(max(0.0, min(100.0, progress)), 1), message=message)
