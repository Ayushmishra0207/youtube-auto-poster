"""
On-demand long-form video generator — used by the dashboard's "Generate a
long-form video now" panel (each click spawns this as its own subprocess via
api/main.py, exactly like generate_short_now.py does for Shorts).

Generation + upload takes minutes, far longer than any HTTP request should
live, so the API fires this off and returns immediately; the dashboard then
polls /api/videos and the new video appears once it's done.

Usage:
  python generate_video_now.py --account default --category news_india
  python generate_video_now.py --account default --category sports --topic "IPL 2026 final"
  python generate_video_now.py --account hindi2 --category news_world --locale en
"""
import argparse
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pipeline.logger import log
from scheduler import generate_video_now


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", default="default", help="Account id")
    parser.add_argument("--category", required=True, help="topic_config.json category key")
    parser.add_argument("--topic", default="", help="Custom topic; blank = pick a fresh trending one")
    parser.add_argument("--locale", default="", help="Locale override; blank = the account's own locale")
    args = parser.parse_args()

    try:
        meta = generate_video_now(args.account, args.category, args.topic, args.locale)
    except Exception as exc:
        log.error("[generate-video] Failed for account '%s', category '%s': %s",
                  args.account, args.category, exc, exc_info=True)
        sys.exit(1)

    log.info("[generate-video] Done: %s → https://youtube.com/watch?v=%s",
             meta.get("title", ""), meta.get("youtube_id", ""))


if __name__ == "__main__":
    main()
