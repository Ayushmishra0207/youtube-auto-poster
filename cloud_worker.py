"""
Entry point for GitHub Actions runs (.github/workflows/autoposter.yml, engagement.yml).

  python cloud_worker.py pipeline                          daily run (8 videos + Shorts + uploads)
  python cloud_worker.py regenerate_video  '{"date":"2026-11-20","index":3}'
  python cloud_worker.py generate_short    '{"feed":"india","topic":"","content_type":"news","count":1}'
  python cloud_worker.py regenerate_short  '{"date":"…","index":2,"feed":"india","topic":"","content_type":"news"}'
  python cloud_worker.py upload            '{"date":"…","kind":"video","index":3}'
  python cloud_worker.py engagement                        CTA comments + Community drafts + Instagram queue

Args arrive as JSON (TASK_ARGS env var or argv[2]) — never interpolated into a
shell, so dashboard input can't inject commands into the workflow.
State lives in Supabase (DATABASE_URL); the runner's disk is discarded afterwards.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Non-secret settings saved from the dashboard (KEEP_OUTPUT_DAYS, TTS_*, …) must be
# in the environment before config.py is imported, because it reads them at import.
SETTINGS_KEY = "settings.json"
OVERRIDABLE = {"KEEP_OUTPUT_DAYS", "TTS_VOICE", "TTS_RATE", "TTS_PITCH", "SHORTS_PER_DAY",
               "NEWS_TTS_RATE", "SHORTS_TTS_RATE"}


def _apply_settings_overrides() -> None:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return
    try:
        import psycopg
        with psycopg.connect(url, prepare_threshold=None, connect_timeout=15) as conn:
            row = conn.execute("SELECT value FROM app_state WHERE key = %s", (SETTINGS_KEY,)).fetchone()
        for k, v in (json.loads(row[0]) if row else {}).items():
            if k in OVERRIDABLE and str(v).strip():
                os.environ[k] = str(v)
    except Exception as exc:   # table may not exist yet on the very first run
        print(f"[worker] settings overrides not applied: {exc}")


_apply_settings_overrides()
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import OUTPUT_DIR  # noqa: E402
from pipeline import media_store  # noqa: E402
from pipeline.logger import log  # noqa: E402

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FEEDS = {"india", "world", "business", "entertainment", "sports"}


def _date(args: dict) -> str:
    d = str(args.get("date", ""))
    if not _DATE_RE.match(d):
        raise SystemExit(f"invalid date {d!r}")
    return d


def _index(args: dict) -> int:
    i = int(args.get("index", 0))
    if not 1 <= i <= 99:
        raise SystemExit(f"invalid index {i}")
    return i


def _run_module(script: str, argv: list[str]) -> int:
    """Run one of the existing CLIs in-process-equivalent (own interpreter, same env)."""
    return subprocess.call([sys.executable, script, *argv])


def task_pipeline(_: dict) -> int:
    import scheduler
    scheduler.run_pipeline()
    return 0


def task_regenerate_video(args: dict) -> int:
    return _run_module("regenerate_video.py", ["--date", _date(args), "--index", str(_index(args))])


def _short_argv(args: dict) -> list[str]:
    feed = str(args.get("feed", "india"))
    if feed not in FEEDS:
        raise SystemExit(f"invalid feed {feed!r}")
    argv = ["--feed", feed]
    topic = str(args.get("topic", "")).strip()[:200]
    if topic:
        argv += ["--topic", topic]
    ctype = str(args.get("content_type", "news"))
    if re.fullmatch(r"[a-z_]{2,30}", ctype):
        argv += ["--content-type", ctype]
    locale = str(args.get("locale", "")).strip()
    if locale and re.fullmatch(r"[A-Za-z-]{2,10}", locale):
        argv += ["--locale", locale]
    return argv


def task_generate_short(args: dict) -> int:
    count = max(1, min(5, int(args.get("count", 1))))
    return _run_module("generate_short_now.py", [*_short_argv(args), "--count", str(count)])


def task_regenerate_short(args: dict) -> int:
    return _run_module("generate_short_now.py",
                       [*_short_argv(args), "--date", _date(args), "--index", str(_index(args))])


def _fetch_hd(item: dict, date: str, idx: int, dest: Path) -> Path:
    """Full-quality long video from the GitHub artifact of the run that rendered it."""
    art = item.get("hd_artifact") or {}
    run_id, name = str(art.get("run_id", "")), art.get("name", "hd-videos")
    if not run_id.isdigit():
        raise SystemExit("No full-quality file recorded for this video — regenerate it first.")
    with tempfile.TemporaryDirectory() as td:
        rc = subprocess.call(["gh", "run", "download", run_id, "-n", name, "-D", td])
        if rc != 0:
            raise SystemExit("The full-quality file has expired (artifacts are kept 3 days) — regenerate the video.")
        found = list(Path(td).rglob(f"{date}/video_{idx:02d}/final.mp4"))
        if not found:
            raise SystemExit("This run's artifact doesn't contain that video — regenerate it.")
        dest.parent.mkdir(parents=True, exist_ok=True)
        found[0].replace(dest)
    return dest


def task_upload(args: dict) -> int:
    """Dashboard "Upload to YouTube" in the cloud: publish an existing render ~5 min from now."""
    from pipeline.uploader import upload_thumbnail, upload_video
    date, kind, idx = _date(args), str(args.get("kind", "video")), _index(args)
    if kind not in ("video", "short"):
        raise SystemExit("kind must be video or short")
    item = media_store.get_item(date, kind, idx)
    if not item:
        raise SystemExit(f"No {kind} {idx} on {date}")
    if item.get("youtube_id"):
        log.info("%s %s/%d already uploaded (%s) — nothing to do", kind, date, idx, item["youtube_id"])
        return 0
    work = Path(OUTPUT_DIR) / date / f"{kind}_{idx:02d}"
    if kind == "video":
        video = _fetch_hd(item, date, idx, work / "final.mp4")
    else:   # Shorts are stored at full quality
        video = media_store.download(item["preview_key"], work / "short.mp4")
    script = item.get("script") or {}
    title = item.get("title") or f"{kind} {idx}"
    if kind == "short" and "#shorts" not in title.lower():
        title = title[:90] + " #Shorts"
    from pipeline import state_store
    from pipeline.locales import DEFAULT_LOCALE, LOCALES
    lang = getattr(LOCALES.get(script.get("_locale") or DEFAULT_LOCALE), "yt_language", "hi")
    category_id = "25"
    if kind == "video":   # the slot's real category (e.g. movie_explained → Film & Animation)
        cats = (state_store.load("topic_config.json", {}) or {}).get("categories", {})
        category_id = str(cats.get(script.get("_category", ""), {}).get("yt_category_id") or "25")
    vid = upload_video(
        video_path=str(video), title=title, description=item.get("description", ""),
        tags=item.get("tags", []), publish_at_utc=datetime.now(timezone.utc) + timedelta(minutes=5),
        category_id=category_id, yt_language=lang,
    )
    if item.get("thumb_key"):
        try:
            thumb = media_store.download(item["thumb_key"], work / "thumbnail.jpg")
            upload_thumbnail(vid, str(thumb))
        except Exception as exc:
            log.warning("Thumbnail upload skipped: %s", exc)
    media_store.update_item(date, kind, idx, youtube_id=vid, status="uploaded")
    log.info("Uploaded %s %s/%d → https://youtube.com/watch?v=%s (public in ~5 min)", kind, date, idx, vid)
    return 0


def task_engagement(_: dict) -> int:
    from pipeline.engagement import run_engagement_pass
    from pipeline.instagram_queue import run_pending_posts
    rc = 0
    for name, fn in (("engagement", run_engagement_pass), ("instagram", run_pending_posts)):
        try:
            log.info("%s pass: %s", name, fn())
        except Exception as exc:
            log.error("%s pass failed: %s", name, exc, exc_info=True)
            rc = 1
    return rc


TASKS = {
    "pipeline": task_pipeline,
    "regenerate_video": task_regenerate_video,
    "generate_short": task_generate_short,
    "regenerate_short": task_regenerate_short,
    "upload": task_upload,
    "engagement": task_engagement,
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in TASKS:
        print(f"usage: cloud_worker.py <{'|'.join(TASKS)}> [json-args]", file=sys.stderr)
        return 2
    raw = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("TASK_ARGS", "") or "{}"
    try:
        args = json.loads(raw)
        if not isinstance(args, dict):
            raise ValueError
    except ValueError:
        print(f"invalid JSON args: {raw[:200]!r}", file=sys.stderr)
        return 2
    if media_store.enabled():
        import db
        db.init_db()
    return TASKS[sys.argv[1]](args)


if __name__ == "__main__":
    sys.exit(main())
