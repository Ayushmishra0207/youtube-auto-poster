"""
Daily pipeline scheduler.

Timeline (every day):
  14:30 IST  -> pipeline kicks off, generates 7 videos
  ~17:30 IST -> all uploads done, scheduled for 18:30-19:30 IST
  18:30 IST  -> Video 1 goes live   (prime-time Hindi audience)
  18:40 IST  -> Video 2 goes live
  ...
  19:30 IST  -> Video 7 goes live

Run as a background service:
  python scheduler.py

Or run once immediately:
  python scheduler.py --now
"""
import json
import os
import shutil
import sys
# Force UTF-8 output so Hindi titles print correctly on Windows
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import schedule

from config import (
    BASE_DIR,
    KEEP_OUTPUT_DAYS,
    NEWS_CATEGORIES,
    NEWS_TTS_RATE,
    OUTPUT_DIR,
    PEXELS_API_KEY,
    SHORTS_PER_DAY,
    SHORTS_UPLOAD_SLOTS,
    UPLOAD_SLOTS_IST,
    GENERATION_LEAD_HOURS,
)
from generate_short_now import build_short_script
from pipeline.image_fetcher import fetch_all_section_images
from pipeline.locales import DEFAULT_LOCALE, Locale, get_locale
from pipeline.logger import log
from pipeline.script_generator import generate_script
from pipeline.shorts_creator import create_short
from pipeline.text_utils import safe_truncate
from pipeline.trends import get_trending_topics
from pipeline.uploader import upload_thumbnail, upload_video
from pipeline.video_creator import VIDEO_CLIP_EXTS, build_chapters, create_thumbnail, create_video
from pipeline.voice_generator import generate_section_voices

TOPIC_CONFIG_FILE = BASE_DIR / "topic_config.json"
TOPICS_OVERRIDE   = BASE_DIR / "topics_override.json"

# IST offset = UTC+5:30
IST = timezone(timedelta(hours=5, minutes=30))

# ─── Lock file (prevents concurrent pipeline runs) ────────────────────────────
LOCK_FILE = BASE_DIR / "pipeline.lock"


def _pid_running(pid: int) -> bool:
    """Return True if the given PID is alive (Windows-compatible)."""
    import subprocess
    try:
        r = subprocess.run(
            ["tasklist", "/fi", f"PID eq {pid}", "/nh"],
            capture_output=True, text=True, timeout=5
        )
        return str(pid) in r.stdout
    except Exception:
        return False


def _try_create_lock() -> bool:
    """Atomically create the lock file with our PID. False if it already exists —
    O_CREAT|O_EXCL is a single kernel syscall, so two processes racing to create
    it can never both succeed (unlike a separate exists-check + write)."""
    try:
        fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w") as f:
            f.write(str(os.getpid()))
        return True
    except FileExistsError:
        return False


def _acquire_lock() -> bool:
    """Return True if lock was acquired, False if another run is in progress."""
    if _try_create_lock():
        return True

    # Lock file already exists — check whether it's stale (dead PID) and, if
    # so, clear it and retry once. Two racing processes can both reach here
    # and both try to remove the file, but only one of the retried
    # _try_create_lock() calls can win the exclusive-create race.
    try:
        pid = int(LOCK_FILE.read_text().strip())
        if _pid_running(pid):
            log.warning("Another pipeline is running (PID %d) — aborting this run.", pid)
            return False
        log.info("Removing stale lock file (PID %d no longer running).", pid)
    except Exception:
        pass
    LOCK_FILE.unlink(missing_ok=True)

    if _try_create_lock():
        return True
    log.warning("Lost the race to acquire pipeline.lock — another run just started. Aborting.")
    return False


def _release_lock():
    LOCK_FILE.unlink(missing_ok=True)


# ___ Helpers __________________________________________________________________

def _ist_slot_to_utc(slot_str: str) -> datetime:
    """Convert "HH:MM" IST string (today) to a UTC datetime."""
    now_ist = datetime.now(IST)
    h, m = map(int, slot_str.split(":"))
    naive = now_ist.replace(hour=h, minute=m, second=0, microsecond=0)
    if naive < now_ist:
        naive += timedelta(days=1)
    return naive.astimezone(timezone.utc)


def _today_output_dir() -> Path:
    """Return date-stamped output directory, e.g. output/2024-01-15/"""
    date_str = datetime.now(IST).strftime("%Y-%m-%d")
    d = Path(OUTPUT_DIR) / date_str
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cleanup_old_output():
    """Delete dated output directories older than KEEP_OUTPUT_DAYS."""
    cutoff = datetime.now(IST).date() - timedelta(days=KEEP_OUTPUT_DAYS)
    removed = 0
    for entry in Path(OUTPUT_DIR).iterdir():
        if not entry.is_dir():
            continue
        try:
            folder_date = datetime.strptime(entry.name, "%Y-%m-%d").date()
        except ValueError:
            continue   # skip non-date directories
        if folder_date < cutoff:
            shutil.rmtree(entry, ignore_errors=True)
            log.info("Cleaned up old output: %s", entry.name)
            removed += 1
    if removed:
        log.info("Disk cleanup: removed %d old output directories", removed)


# ___ Step helpers _____________________________________________________________

def _load_slot_plan() -> list[dict]:
    """
    Build the per-slot plan from topic_config.json + topics_override.json.

    Resolution order (highest priority first):
      1. custom_topic set in topic_config.json for this slot
      2. Text in topics_override.json for this slot (legacy override)
      3. Trending topic fetched for the category's search_query
      4. Category's fallback_topics (if trending fails)

    Returns a list of dicts: [{slot, topic, category, category_style, yt_category_id}, ...]
    """
    import random as _random

    categories = {}
    slot_categories = []

    if TOPIC_CONFIG_FILE.exists():
        try:
            cfg = json.loads(TOPIC_CONFIG_FILE.read_text(encoding="utf-8"))
            categories   = cfg.get("categories", {})
            slot_categories = cfg.get("slots", [])
        except Exception as e:
            log.warning("Could not read topic_config.json: %s", e)

    override_topics: list = []
    if TOPICS_OVERRIDE.exists():
        try:
            override_topics = json.loads(TOPICS_OVERRIDE.read_text(encoding="utf-8"))
        except Exception:
            pass

    plan = []
    for i, slot_str in enumerate(UPLOAD_SLOTS_IST):
        # Determine category for this slot
        slot_cfg = slot_categories[i] if i < len(slot_categories) else {}
        cat_key  = slot_cfg.get("category", "")
        cat_info = categories.get(cat_key, {})

        # 1. custom_topic in topic_config
        custom = slot_cfg.get("custom_topic") or ""
        if custom.strip():
            topic = custom.strip()
        # 2. legacy override list
        elif i < len(override_topics) and override_topics[i].strip():
            topic = override_topics[i].strip()
        else:
            topic = None   # will fetch from trends / fallback below

        locale = get_locale(slot_cfg.get("locale") or DEFAULT_LOCALE)

        plan.append({
            "slot":            slot_str,
            "topic":           topic,
            "category":        cat_key,
            "category_color":  cat_info.get("color", ""),
            "search_query":    cat_info.get("search_query", ""),
            "category_style":  cat_info.get("prompt_style", ""),
            "yt_category_id":  cat_info.get("yt_category_id", "25"),
            "fallback_topics": cat_info.get("fallback_topics", []),
            "locale":          locale,
        })

    # For slots without a fixed topic, fetch trends grouped by (search_query, locale)
    needs_fetch = [p for p in plan if p["topic"] is None]
    if needs_fetch:
        from collections import defaultdict
        by_query: dict[tuple, list] = defaultdict(list)
        for p in needs_fetch:
            by_query[(p["search_query"] or "general", p["locale"].code)].append(p)

        for (query, locale_code), slots_needing in by_query.items():
            n = len(slots_needing)
            locale = slots_needing[0]["locale"]
            fetched: list[str] = []
            if query and query != "general":
                try:
                    from pytrends.request import TrendReq
                    pt = TrendReq(hl=locale.news_hl, tz=330, timeout=(10, 30))
                    df = pt.trending_searches(pn=locale.trends_pn)
                    all_trends = [str(t).strip() for t in df[0].dropna().tolist() if t]
                    # Try to find trends that match the query keywords
                    keywords = query.lower().split()
                    matched = [t for t in all_trends if any(k in t.lower() for k in keywords)]
                    fetched = (matched or all_trends)[:n]
                except Exception as e:
                    log.warning("Trends fetch failed for query '%s' (locale=%s): %s", query, locale_code, e)

            for j, p in enumerate(slots_needing):
                if j < len(fetched):
                    p["topic"] = fetched[j]
                else:
                    fallbacks = p["fallback_topics"]
                    if fallbacks:
                        p["topic"] = _random.choice(fallbacks)
                    else:
                        # final fallback: general trending for this slot's locale
                        general = get_trending_topics(1, locale=p["locale"])
                        p["topic"] = general[0] if general else f"{p['locale'].label} news today"

    return plan


def _append_chapters_to_description(script: dict, voices: list) -> dict:
    """Append real YouTube chapter markers to script['description'] in place."""
    chapters_text = build_chapters(script, voices)
    if chapters_text.strip():
        script["description"] = (script.get("description", "") or "").rstrip() + "\n\n" + chapters_text
    return script


def _run_single_video(topic: str, slot_str: str, index: int, base_dir: Path,
                      category_style: str = "", voice_rate: str | None = None,
                      category: str = "", category_color: str = "",
                      locale: Locale | None = None) -> dict | None:
    """Full pipeline for one trending topic. Returns video metadata or None."""
    locale = locale or get_locale(None)
    work_dir = base_dir / f"video_{index:02d}"
    work_dir.mkdir(parents=True, exist_ok=True)

    log.info("[%d] Starting (locale=%s): %s", index, locale.code, topic)

    try:
        # 1. Script
        log.info("[%d] Generating script...", index)
        script = generate_script(topic, category_style=category_style, locale=locale)
        log.info("[%d] Title: %s", index, script["title"])

        # 2. Voice
        log.info("[%d] Generating voice-over...", index)
        voices = generate_section_voices(
            script["sections"],
            str(work_dir / "voices"),
            rate=voice_rate,
            locale=locale,
        )
        script = _append_chapters_to_description(script, voices)

        # 3. Images
        log.info("[%d] Fetching background images...", index)
        images = fetch_all_section_images(
            script["sections"],
            PEXELS_API_KEY,
            str(work_dir / "images"),
        )

        # 4. Persist script for the dashboard API (locale tag lets the
        # engagement-comment/Community-post automation pick the right language)
        script["_locale"] = locale.code
        import json as _json
        with open(work_dir / "script.json", "w", encoding="utf-8") as _f:
            _json.dump(script, _f, ensure_ascii=False, indent=2)

        # 5. Thumbnail — news-style composite built from this video's own images
        # (video clips are excluded — create_thumbnail needs real still images)
        thumbnail_path = str(work_dir / "thumbnail.jpg")
        flat_images = [
            p for section in images for p in section
            if p and not p.lower().endswith(VIDEO_CLIP_EXTS)
        ]
        # Spread picks across sections for visual variety
        picks = flat_images[:: max(1, len(flat_images) // 3)][:3] if flat_images else []
        create_thumbnail(script, thumbnail_path, image_paths=picks, locale=locale, category_color=category_color, category=category)

        # 5. Video
        video_path = str(work_dir / "final.mp4")
        log.info("[%d] Rendering video...", index)
        create_video(script, voices, images, video_path, category=category, locale=locale)
        log.info("[%d] Video ready: %s", index, video_path)

        return {
            "path":           video_path,
            "thumbnail_path": thumbnail_path,
            "title":          script["title"],
            "description":    script.get("description", ""),
            "tags":           script.get("tags", []),
            "slot":           slot_str,
            "yt_language":    locale.yt_language,
        }

    except Exception as exc:
        log.error("[%d] Pipeline failed for '%s': %s", index, topic, exc, exc_info=True)
        return None


# ___ Main pipeline ____________________________________________________________

def run_pipeline():
    """Generate all 7 videos and schedule them for upload."""
    if not _acquire_lock():
        return  # another pipeline is running — skip silently

    now_ist = datetime.now(IST)
    log.info("=" * 60)
    log.info("YouTube Auto-Poster started | %s IST", now_ist.strftime("%d %b %Y, %H:%M"))
    log.info("Target slots: %s", ", ".join(UPLOAD_SLOTS_IST))

    base_dir = _today_output_dir()

    # __ Build per-slot topic plan ____________________________________________
    log.info("Building slot plan from topic_config.json...")
    slot_plan = _load_slot_plan()
    for p in slot_plan:
        log.info("  Slot %s → [%s] %s", p["slot"], p["category"] or "auto", p["topic"])

    # __ Generate all videos __________________________________________________
    videos = []
    for i, plan in enumerate(slot_plan, start=1):
        # News-category videos get a faster, more urgent voice
        rate = NEWS_TTS_RATE if plan.get("category") in NEWS_CATEGORIES else None
        meta = _run_single_video(
            topic=plan["topic"],
            slot_str=plan["slot"],
            index=i,
            base_dir=base_dir,
            category_style=plan.get("category_style", ""),
            voice_rate=rate,
            category=plan.get("category", ""),
            category_color=plan.get("category_color", ""),
            locale=plan.get("locale"),
        )
        if meta:
            meta["yt_category_id"] = plan.get("yt_category_id", "25")
            videos.append(meta)

    if not videos:
        log.error("No videos generated — aborting upload step.")
        return

    # __ Upload + schedule ____________________________________________________
    log.info("Uploading %d videos to YouTube...", len(videos))
    for v in videos:
        publish_utc = _ist_slot_to_utc(v["slot"])
        log.info("Uploading: %s → %s IST", v["title"][:60], v["slot"])
        try:
            vid_id = upload_video(
                video_path=v["path"],
                title=v["title"],
                description=v["description"],
                tags=v["tags"],
                publish_at_utc=publish_utc,
                category_id=v.get("yt_category_id", "25"),
                yt_language=v.get("yt_language", "hi"),
            )
            upload_thumbnail(vid_id, v["thumbnail_path"])
        except Exception as e:
            log.error("Upload failed for '%s': %s", v["title"][:60], e, exc_info=True)

    # __ YouTube Shorts (3 per day: India / World / Business breaking news) ___
    try:
        _run_shorts(base_dir)
    except Exception as e:
        log.error("Shorts stage failed: %s", e, exc_info=True)

    # __ Disk cleanup ________________________________________________________
    log.info("Running disk cleanup (keep last %d days)...", KEEP_OUTPUT_DAYS)
    _cleanup_old_output()

    log.info("Pipeline complete. Videos scheduled for 18:30–19:30 IST.")
    log.info("=" * 60)
    _release_lock()


# ___ YouTube Shorts ___________________________________________________________

# Each daily short gets its own news feed + focus
_SHORTS_PLAN = [
    {"feed": "india",         "focus": "India breaking news"},
    {"feed": "world",         "focus": "World breaking news"},
    {"feed": "business",      "focus": "Business and economy breaking news"},
    {"feed": "entertainment", "focus": "Entertainment and Bollywood breaking news"},
    {"feed": "sports",        "focus": "Sports breaking news"},
]


def _run_shorts(base_dir: Path):
    """Generate and upload the daily YouTube Shorts (breaking news, 1.5x voice)."""
    log.info("-" * 60)
    log.info("Generating %d YouTube Shorts...", SHORTS_PER_DAY)

    for i in range(1, SHORTS_PER_DAY + 1):
        plan = _SHORTS_PLAN[(i - 1) % len(_SHORTS_PLAN)]
        work_dir = base_dir / f"short_{i:02d}"
        work_dir.mkdir(parents=True, exist_ok=True)

        locale = get_locale(plan.get("locale") or DEFAULT_LOCALE)
        try:
            # 1-2. Real headlines + script (Claude → OpenRouter → Gemini chain)
            try:
                script = build_short_script(feed=plan["feed"], locale=locale)
            except ValueError as exc:
                log.warning("Short %d: %s — skipping", i, exc)
                continue

            script["_locale"] = locale.code
            import json as _json
            with open(work_dir / "script.json", "w", encoding="utf-8") as _f:
                _json.dump(script, _f, ensure_ascii=False, indent=2)

            # 3. Render vertical short (voice at 1.5x inside)
            video_path = create_short(script, str(work_dir), category="news", locale=locale)

            # 4. Upload with a scheduled publish slot
            slot = SHORTS_UPLOAD_SLOTS[(i - 1) % len(SHORTS_UPLOAD_SLOTS)]
            title = script.get("title", f"आज की बड़ी खबरें {i}")
            if "#shorts" not in title.lower():
                title = safe_truncate(title, 82, suffix=" #Shorts")
            log.info("Uploading Short %d: %s → %s IST", i, title[:60], slot)
            upload_video(
                video_path=video_path,
                title=title,
                description=script.get("description", "#Shorts #News"),
                tags=script.get("tags", []),
                publish_at_utc=_ist_slot_to_utc(slot),
                yt_language=locale.yt_language,
            )
        except Exception as e:
            log.error("Short %d failed: %s", i, e, exc_info=True)

    log.info("Shorts stage complete.")


# ___ Entry point ______________________________________________________________

if __name__ == "__main__":
    if "--now" in sys.argv:
        run_pipeline()
    else:
        first_h, first_m = map(int, UPLOAD_SLOTS_IST[0].split(":"))
        gen_h   = first_h - GENERATION_LEAD_HOURS
        trigger = f"{gen_h:02d}:{first_m:02d}"

        log.info("Scheduler active — pipeline fires daily at %s IST (Ctrl+C to stop)", trigger)

        schedule.every().day.at(trigger).do(run_pipeline)

        while True:
            schedule.run_pending()
            time.sleep(30)
