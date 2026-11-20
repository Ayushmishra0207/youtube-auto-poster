"""
Daily pipeline scheduler.

Timeline (every day):
  14:30 IST  -> pipeline kicks off, generates 8 videos
  ~17:30 IST -> all uploads done, scheduled for 18:30-19:40 IST
  18:30 IST  -> Video 1 goes live   (prime-time Hindi audience)
  18:40 IST  -> Video 2 goes live
  ...
  19:40 IST  -> Video 8 goes live

Run as a background service:
  python scheduler.py

Or run once immediately:
  python scheduler.py --now
"""
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
from generate_short_now import SHORT_LOCK_FILE, _next_short_index, build_short_script
from pipeline import locking, media_store, state_store
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


def _acquire_lock() -> bool:
    """Return True if lock was acquired, False if another run is in progress."""
    if locking.acquire(LOCK_FILE):
        return True
    log.warning("Another pipeline is running (PID %s) — aborting this run.", locking.lock_owner(LOCK_FILE))
    return False


def _release_lock():
    locking.release(LOCK_FILE)


# ___ Helpers __________________________________________________________________

def _ist_slot_to_utc(slot_str: str, run_start: datetime | None = None) -> datetime:
    """
    Publish time (UTC) for an "HH:MM" IST slot.

    Anchored to when the run *started*, not when the upload happens: slots
    earlier than the run start (e.g. the 11:00 Shorts slot for a 14:30 run)
    belong to tomorrow, but a slot that merely passed while we were rendering
    (8 renders finishing after 18:30) is published shortly instead of being
    pushed a full day onto the next run's identical slot.
    """
    now_ist = datetime.now(IST)
    start = (run_start or now_ist).astimezone(IST)
    h, m = map(int, slot_str.split(":"))
    target = start.replace(hour=h, minute=m, second=0, microsecond=0)
    if target < start:
        target += timedelta(days=1)
    if target < now_ist + timedelta(minutes=5):
        target = (now_ist + timedelta(minutes=15)).replace(second=0, microsecond=0)
    return target.astimezone(timezone.utc)


def _save_youtube_id(work_dir: Path, video_id: str) -> None:
    """The dashboard's "uploaded" status, the duplicate-upload guard, and the
    engagement auto-comments all key off this file."""
    try:
        (work_dir / "youtube_id.txt").write_text(video_id, encoding="utf-8")
    except OSError as exc:
        log.warning("Could not record YouTube id %s in %s: %s", video_id, work_dir, exc)


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
    media_store.cleanup(KEEP_OUTPUT_DAYS)   # cloud index + stored previews (no-op locally)


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

    # state_store: the JSON files locally; in the cloud the dashboard's saved
    # config lives in the database (a GitHub runner only has the repo's copy)
    try:
        cfg = state_store.load(TOPIC_CONFIG_FILE.name, {}) or {}
        categories   = cfg.get("categories", {})
        slot_categories = cfg.get("slots", [])
    except Exception as e:
        log.warning("Could not read topic_config.json: %s", e)

    override_topics: list = []
    try:
        override_topics = state_store.load(TOPICS_OVERRIDE.name, []) or []
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
        if not any(voices):
            # Otherwise create_video skips every section and a ~9 s title+outro
            # video gets uploaded as a public scheduled video.
            raise RuntimeError("No section voice-over could be generated (all TTS providers failed)")
        script = _append_chapters_to_description(script, voices)

        # 3. Images
        log.info("[%d] Fetching background images...", index)
        images = fetch_all_section_images(
            script["sections"],
            PEXELS_API_KEY,
            str(work_dir / "images"),
        )

        # 4. Persist script for the dashboard API (locale tag lets the
        # engagement-comment/Community-post automation pick the right language;
        # category tag lets the dashboard's manual "Upload to YouTube" button
        # look up the correct yt_category_id instead of hardcoding one)
        script["_locale"] = locale.code
        script["_category"] = category
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
        media_store.publish(work_dir, base_dir.name, "video", index, slot_str)   # cloud only; no-op locally

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
    """Generate all 8 videos and schedule them for upload."""
    if not _acquire_lock():
        return  # another pipeline is running — skip silently
    # try/finally: an early return or crash used to leave pipeline.lock behind,
    # and in daemon mode (same live PID) that blocked every later day's run.
    try:
        _run_pipeline_locked()
    finally:
        _release_lock()


def _run_pipeline_locked():
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

    # __ Upload + schedule ____________________________________________________
    if not videos:
        # Still run Shorts (separate news feeds) and cleanup below
        log.error("No long-form videos generated — skipping their upload step.")
    else:
        log.info("Uploading %d videos to YouTube...", len(videos))
    for v in videos:
        publish_utc = _ist_slot_to_utc(v["slot"], run_start=now_ist)
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
            _save_youtube_id(Path(v["path"]).parent, vid_id)
            media_store.publish(Path(v["path"]).parent, base_dir.name, "video",
                                int(Path(v["path"]).parent.name.split("_")[1]), v["slot"])
            upload_thumbnail(vid_id, v["thumbnail_path"])
        except Exception as e:
            log.error("Upload failed for '%s': %s", v["title"][:60], e, exc_info=True)

    # __ YouTube Shorts (5 per day: India / World / Business / Entertainment / Sports breaking news) ___
    try:
        _run_shorts(base_dir, run_start=now_ist)
    except Exception as e:
        log.error("Shorts stage failed: %s", e, exc_info=True)

    # __ Disk cleanup ________________________________________________________
    log.info("Running disk cleanup (keep last %d days)...", KEEP_OUTPUT_DAYS)
    _cleanup_old_output()

    log.info("Pipeline complete. Videos scheduled for %s–%s IST.", UPLOAD_SLOTS_IST[0], UPLOAD_SLOTS_IST[-1])
    log.info("=" * 60)


# ___ YouTube Shorts ___________________________________________________________

# Each daily short gets its own news feed + focus
_SHORTS_PLAN = [
    {"feed": "india",         "focus": "India breaking news"},
    {"feed": "world",         "focus": "World breaking news"},
    {"feed": "business",      "focus": "Business and economy breaking news"},
    {"feed": "entertainment", "focus": "Entertainment and Bollywood breaking news"},
    {"feed": "sports",        "focus": "Sports breaking news"},
]


def _run_shorts(base_dir: Path, run_start: datetime | None = None):
    """Generate and upload the daily YouTube Shorts (breaking news, 1.5x voice)."""
    log.info("-" * 60)
    log.info("Generating %d YouTube Shorts...", SHORTS_PER_DAY)

    # Share generate_short_now.py's lock: a dashboard "Generate Short" must not
    # render into the same folder at the same time.
    if not locking.acquire_wait(SHORT_LOCK_FILE, timeout_s=20 * 60):
        log.error("A manual Short generation held short_generate.lock for 20+ min — skipping daily Shorts.")
        return
    try:
        _run_shorts_locked(base_dir, run_start)
    finally:
        locking.release(SHORT_LOCK_FILE)


def _run_shorts_locked(base_dir: Path, run_start: datetime | None):
    for i in range(1, SHORTS_PER_DAY + 1):
        plan = _SHORTS_PLAN[(i - 1) % len(_SHORTS_PLAN)]
        # Next free short_NN — never overwrite Shorts made from the dashboard earlier today
        work_dir = base_dir / f"short_{_next_short_index(base_dir):02d}"
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
            short_idx = int(work_dir.name.split("_")[1])
            media_store.publish(work_dir, base_dir.name, "short", short_idx)

            # 4. Upload with a scheduled publish slot
            slot = SHORTS_UPLOAD_SLOTS[(i - 1) % len(SHORTS_UPLOAD_SLOTS)]
            title = script.get("title", f"आज की बड़ी खबरें {i}")
            if "#shorts" not in title.lower():
                title = safe_truncate(title, 82, suffix=" #Shorts")
            log.info("Uploading Short %d: %s → %s IST", i, title[:60], slot)
            publish_utc = _ist_slot_to_utc(slot, run_start=run_start)
            short_id = upload_video(
                video_path=video_path,
                title=title,
                description=script.get("description", "#Shorts #News"),
                tags=script.get("tags", []),
                publish_at_utc=publish_utc,
                yt_language=locale.yt_language,
            )
            _save_youtube_id(work_dir, short_id)
            media_store.publish(work_dir, base_dir.name, "short", short_idx)   # before IG enqueue (needs its storage copy)

            try:
                from pipeline.instagram_queue import enqueue as ig_enqueue
                ig_caption = f"{script.get('title', '')}\n\n{script.get('description', '')}"[:2200]
                ig_enqueue(video_path, ig_caption, publish_at_utc=publish_utc)
            except Exception as ig_exc:
                log.warning("Instagram enqueue failed for Short %d: %s", i, ig_exc)
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
