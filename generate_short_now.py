"""
On-demand YouTube Shorts generator — used by the dashboard's "Generate Short"
button and its per-short "Regenerate" button (each click spawns this as its
own subprocess via api/main.py).

Usage:
  python generate_short_now.py --feed india
  python generate_short_now.py --topic "IPL 2026 auction shockers"
  python generate_short_now.py --topic "IPL 2026 auction shockers" --content-type funny
  python generate_short_now.py --feed world --index 3   # regenerate short_03 in place
  python generate_short_now.py --locale es --count 5    # 5 Spanish shorts in one run
"""
import argparse
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import BASE_DIR, OUTPUT_DIR
from pipeline.locales import DEFAULT_LOCALE, Locale, get_locale
from pipeline import locking
from pipeline.logger import log
from pipeline.news_fetcher import get_breaking_headlines
from pipeline.script_generator import generate_shorts_script, generate_shorts_script_from_topic
from pipeline.shorts_creator import create_short
from pipeline.topic_history import filter_fresh, record_topic, recent_titles

IST = timezone(timedelta(hours=5, minutes=30))

_FOCUS_BY_FEED = {
    "india": "India breaking news",
    "world": "World breaking news",
    "business": "Business and economy breaking news",
    "entertainment": "Entertainment and Bollywood breaking news",
    "sports": "Sports breaking news",
}

SHORT_LOCK_FILE = BASE_DIR / "short_generate.lock"


def build_short_script(feed: str = "india", topic: str = "", locale: Locale | None = None,
                        content_type: str = "news") -> dict:
    """
    Generate a Shorts script from either a custom topic (creator's own
    choice of subject) or a real breaking-news feed. Shared by the
    "generate new" and "regenerate existing" flows.

    content_type only affects the custom-topic path — it selects the
    tone/style of the generated script (see pipeline.script_generator's
    _CONTENT_TYPE_TONE). Feed-based (breaking-news) generation ignores it.

    Filters out headlines that closely match a recently-generated Short's
    topic (pipeline.topic_history) so back-to-back generations don't keep
    leading with the same dominant headline (e.g. the top business story
    barely changes within a few hours) — falls back to the full headline
    list only if filtering would leave too few to work with.
    """
    locale = locale or get_locale(None)
    topic = (topic or "").strip()
    if topic:
        script = generate_shorts_script_from_topic(topic, locale=locale, content_type=content_type)
        record_topic(script.get("title", ""))
        return script

    headlines = get_breaking_headlines(feed, max_age_hours=48, limit=15, locale=locale)
    if len(headlines) < 3:
        raise ValueError(f"Only {len(headlines)} fresh headlines for feed '{feed}' (locale={locale.code})")

    fresh = filter_fresh(headlines)
    if len(fresh) < 3:
        log.info("Shorts topic history filtered too aggressively (%d/%d left) — using full headline list",
                 len(fresh), len(headlines))
        fresh = headlines

    script = generate_shorts_script(
        fresh,
        focus=_FOCUS_BY_FEED.get(feed, "India and world breaking news"),
        locale=locale,
        avoid_titles=recent_titles(),
    )
    record_topic(script.get("title", ""))
    return script


def _today_output_dir() -> Path:
    date_str = datetime.now(IST).strftime("%Y-%m-%d")
    d = Path(OUTPUT_DIR) / date_str
    d.mkdir(parents=True, exist_ok=True)
    return d


def _next_short_index(base_dir: Path) -> int:
    existing = [int(p.name.split("_")[1]) for p in base_dir.glob("short_*") if p.name.split("_")[1].isdigit()]
    return (max(existing) + 1) if existing else 1


def _acquire_lock() -> bool:
    """Return True if the lock was acquired, False if another run is genuinely in progress.
    Shared implementation (pipeline/locking.py) also works on Linux/Render, where the
    old tasklist-only PID check treated every lock as stale."""
    return locking.acquire(SHORT_LOCK_FILE)


def generate_one_short(base_dir: Path, feed: str, topic: str, index: int, locale: Locale,
                        content_type: str = "news") -> Path:
    """Build, render, and save one Short into base_dir/short_NN. Returns work_dir."""
    work_dir = base_dir / f"short_{index:02d}"
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    source = f"topic='{topic}' (content_type={content_type})" if topic.strip() else f"feed={feed}"
    log.info("[manual-short %d] Generating (%s, locale=%s)...", index, source, locale.code)

    script = build_short_script(feed=feed, topic=topic, locale=locale, content_type=content_type)
    script["_locale"] = locale.code
    script["_content_type"] = content_type
    with open(work_dir / "script.json", "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)

    category = content_type if topic.strip() else "news"
    create_short(script, str(work_dir), category=category, locale=locale)
    log.info("[manual-short %d] Done: %s", index, work_dir)
    return work_dir


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--feed", choices=["india", "world", "business", "entertainment", "sports"], default="india")
    parser.add_argument("--topic", default="", help="Custom topic — overrides --feed when set")
    parser.add_argument("--content-type", default="news", dest="content_type",
                        help="Tone/style for a custom-topic script (e.g. news, funny, story, devotional); ignored for feed-based generation")
    parser.add_argument("--index", type=int, default=0,
                        help="Regenerate this existing short_NN in place instead of creating a new one")
    parser.add_argument("--date", default="", help="Output date folder (YYYY-MM-DD); defaults to today")
    parser.add_argument("--locale", default=DEFAULT_LOCALE,
                        help="Locale code for language/tags/TTS/rendering (pipeline/locales.py); default hi")
    parser.add_argument("--count", type=int, default=1,
                        help="Number of Shorts to generate in this run (ignored when --index is set)")
    args = parser.parse_args()

    locale = get_locale(args.locale)

    if not _acquire_lock():
        log.warning("[manual-short] Another Short generation is already in progress — aborting this run.")
        sys.exit(1)
    try:
        base_dir = (Path(OUTPUT_DIR) / args.date) if args.date else _today_output_dir()
        base_dir.mkdir(parents=True, exist_ok=True)

        if args.index > 0:
            generate_one_short(base_dir, args.feed, args.topic, args.index, locale, content_type=args.content_type)
        else:
            count = max(1, args.count)
            failures = 0
            for _ in range(count):
                index = _next_short_index(base_dir)
                try:
                    generate_one_short(base_dir, args.feed, args.topic, index, locale, content_type=args.content_type)
                except Exception as exc:
                    failures += 1
                    log.error("[manual-short %d] Failed: %s", index, exc, exc_info=True)
            if failures == count:
                sys.exit(1)

    except Exception as exc:
        log.error("[manual-short] Failed: %s", exc, exc_info=True)
        sys.exit(1)
    finally:
        locking.release(SHORT_LOCK_FILE)


if __name__ == "__main__":
    main()
