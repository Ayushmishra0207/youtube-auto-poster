"""
On-demand regeneration of ONE long-form video slot, in place — used by the
dashboard's per-video "Regenerate" button (spawned as its own subprocess
via api/main.py). Re-runs script/voice/images/thumbnail/video for that slot
using the same topic-resolution rules as the daily pipeline (topic_config.json
custom_topic -> trending -> fallback); does not re-upload.

Usage:
  python regenerate_video.py --date 2026-07-18 --index 3
"""
import argparse
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import NEWS_CATEGORIES, NEWS_TTS_RATE, OUTPUT_DIR
from pipeline.accounts import get_account
from pipeline.locales import get_locale
from pipeline.logger import log
from scheduler import _load_slot_plan, _run_single_video

IST = timezone(timedelta(hours=5, minutes=30))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Output date folder, e.g. 2026-07-18")
    parser.add_argument("--index", type=int, required=True, help="Video slot index (1-7)")
    parser.add_argument("--locale", default="", help="Override the slot's configured locale for this regeneration")
    parser.add_argument("--account", default="default", help="Account id")
    args = parser.parse_args()

    account = get_account(args.account)
    if not account:
        log.error("Unknown account '%s'", args.account)
        sys.exit(1)

    base_dir = account.output_dir / args.date if args.date else account.output_dir / datetime.now(IST).strftime("%Y-%m-%d")
    work_dir = base_dir / f"video_{args.index:02d}"

    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)

    slot_plan = _load_slot_plan(account)
    if args.index < 1 or args.index > len(slot_plan):
        log.error("Regenerate video: index %d out of range (1-%d)", args.index, len(slot_plan))
        sys.exit(1)
    plan = slot_plan[args.index - 1]
    locale = get_locale(args.locale) if args.locale.strip() else plan.get("locale")

    log.info("[regen-video %d] Regenerating (locale=%s): %s",
             args.index, locale.code if locale else "hi", plan["topic"])

    rate = NEWS_TTS_RATE if plan.get("category") in NEWS_CATEGORIES else None
    meta = _run_single_video(
        topic=plan["topic"],
        slot_str=plan["slot"],
        index=args.index,
        base_dir=base_dir,
        category_style=plan.get("category_style", ""),
        voice_rate=rate,
        category=plan.get("category", ""),
        category_color=plan.get("category_color", ""),
        category_label=plan.get("category_label", ""),
        locale=locale,
        account_dir=account.dir,
    )
    if not meta:
        log.error("[regen-video %d] Failed", args.index)
        sys.exit(1)

    log.info("[regen-video %d] Done: %s", args.index, meta["title"])


if __name__ == "__main__":
    main()
