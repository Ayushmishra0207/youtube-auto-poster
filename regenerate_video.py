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
import re
import shutil
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import NEWS_CATEGORIES, NEWS_TTS_RATE, OUTPUT_DIR
from pipeline.locales import get_locale
from pipeline.logger import log
from scheduler import _load_slot_plan, _run_single_video


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Output date folder, e.g. 2026-07-18")
    parser.add_argument("--index", type=int, required=True, help="Video slot index (1-8)")
    parser.add_argument("--locale", default="", help="Override the slot's configured locale for this regeneration")
    args = parser.parse_args()

    base_dir = Path(OUTPUT_DIR) / args.date
    work_dir = base_dir / f"video_{args.index:02d}"

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.date):
        log.error("Regenerate video: invalid --date %r (expected YYYY-MM-DD)", args.date)
        sys.exit(1)

    # Validate BEFORE touching anything — the old code deleted the slot first, so a
    # bad index or a provider outage destroyed a good (maybe already uploaded) video.
    slot_plan = _load_slot_plan()
    if args.index < 1 or args.index > len(slot_plan):
        log.error("Regenerate video: index %d out of range (1-%d)", args.index, len(slot_plan))
        sys.exit(1)
    plan = slot_plan[args.index - 1]
    locale = get_locale(args.locale) if args.locale.strip() else plan.get("locale")

    log.info("[regen-video %d] Regenerating (locale=%s): %s",
             args.index, locale.code if locale else "hi", plan["topic"])

    rate = NEWS_TTS_RATE if plan.get("category") in NEWS_CATEGORIES else None
    # Render into a scratch dir (not named video_* so the dashboard ignores it)
    # and swap it in only on success.
    staging = base_dir / f".regen_video_{args.index:02d}"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    meta = _run_single_video(
        topic=plan["topic"],
        slot_str=plan["slot"],
        index=args.index,
        base_dir=staging,
        category_style=plan.get("category_style", ""),
        voice_rate=rate,
        category=plan.get("category", ""),
        category_color=plan.get("category_color", ""),
        locale=locale,
    )
    if not meta:
        shutil.rmtree(staging, ignore_errors=True)
        log.error("[regen-video %d] Failed — the existing video was left untouched", args.index)
        sys.exit(1)

    new_dir = staging / f"video_{args.index:02d}"
    if work_dir.exists():
        old_id = work_dir / "youtube_id.txt"
        if old_id.exists():
            # The regenerated file is NOT on YouTube; keep a record of the old upload
            (new_dir / "previous_youtube_id.txt").write_text(old_id.read_text(encoding="utf-8"), encoding="utf-8")
        shutil.rmtree(work_dir, ignore_errors=True)
    shutil.move(str(new_dir), str(work_dir))
    shutil.rmtree(staging, ignore_errors=True)

    log.info("[regen-video %d] Done: %s", args.index, meta["title"])


if __name__ == "__main__":
    main()
