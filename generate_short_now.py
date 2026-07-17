"""
On-demand YouTube Shorts generator — used by the dashboard's "Generate Short"
button (each click spawns this as its own subprocess via api/main.py).

Usage:
  python generate_short_now.py --feed india
  python generate_short_now.py --feed world
  python generate_short_now.py --feed business
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import BASE_DIR, OUTPUT_DIR
from pipeline.logger import log
from pipeline.news_fetcher import get_breaking_headlines
from pipeline.script_generator import generate_shorts_script
from pipeline.shorts_creator import create_short

IST = timezone(timedelta(hours=5, minutes=30))

_FOCUS_BY_FEED = {
    "india": "India breaking news",
    "world": "World breaking news",
    "business": "Business and economy breaking news",
}

SHORT_LOCK_FILE = BASE_DIR / "short_generate.lock"


def _today_output_dir() -> Path:
    date_str = datetime.now(IST).strftime("%Y-%m-%d")
    d = Path(OUTPUT_DIR) / date_str
    d.mkdir(parents=True, exist_ok=True)
    return d


def _next_short_index(base_dir: Path) -> int:
    existing = [int(p.name.split("_")[1]) for p in base_dir.glob("short_*") if p.name.split("_")[1].isdigit()]
    return (max(existing) + 1) if existing else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--feed", choices=["india", "world", "business"], default="india")
    args = parser.parse_args()

    SHORT_LOCK_FILE.write_text(str(__import__("os").getpid()))
    try:
        base_dir = _today_output_dir()
        index = _next_short_index(base_dir)
        work_dir = base_dir / f"short_{index:02d}"
        work_dir.mkdir(parents=True, exist_ok=True)

        log.info("[manual-short %d] Generating (feed=%s)...", index, args.feed)

        headlines = get_breaking_headlines(args.feed, max_age_hours=48, limit=15)
        if len(headlines) < 3:
            log.error("[manual-short %d] Only %d fresh headlines for feed '%s' — aborting",
                      index, len(headlines), args.feed)
            sys.exit(1)

        script = generate_shorts_script(headlines, focus=_FOCUS_BY_FEED[args.feed])
        with open(work_dir / "script.json", "w", encoding="utf-8") as f:
            json.dump(script, f, ensure_ascii=False, indent=2)

        create_short(script, str(work_dir))
        log.info("[manual-short %d] Done: %s", index, work_dir)

    finally:
        SHORT_LOCK_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
