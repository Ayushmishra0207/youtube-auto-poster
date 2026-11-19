"""
Viral Clip Maker — command line entry point.

  python clip_now.py --url "https://youtu.be/..." --mode gta6_action --clips 3
  python clip_now.py --job <job_id>          # run a job created by the dashboard/API

Modes: gta6_action, gta6_funny, gta6_trailer, gta6_cinematic, gta6_story, general
Output: output/clips/<job_id>/clip_NN/{clip.mp4, thumb.jpg, clip.json}
"""
import argparse
import sys

from dotenv import load_dotenv

load_dotenv()

from clipper.common import CLIPS_DIR, JOB_ID_RE  # noqa: E402
from clipper.job import new_job, run_job  # noqa: E402
from clipper.modes import MODES  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Turn a YouTube video into vertical viral clips")
    ap.add_argument("--job", help="existing job id under output/clips/")
    ap.add_argument("--url", help="YouTube (or any yt-dlp supported) video URL")
    ap.add_argument("--mode", default="gta6_action", choices=list(MODES))
    ap.add_argument("--clips", type=int, default=3)
    ap.add_argument("--length", default="auto", choices=["auto", "short", "medium", "long"])
    ap.add_argument("--layout", default="blur_fit", choices=["blur_fit", "center_crop"])
    ap.add_argument("--captions", default="auto", help="auto | impact | pop | neon | clean | minimal | none")
    ap.add_argument("--language", default="auto", help="speech language: auto | hi | en | ...")
    ap.add_argument("--title-language", default="hinglish", choices=["hinglish", "hindi", "english"])
    ap.add_argument("--watermark", default="")
    ap.add_argument("--audio", default="original", choices=["original", "original_music", "music_only"])
    ap.add_argument("--no-ai", action="store_true", help="skip Claude; pick moments by signals only")
    args = ap.parse_args()

    if args.job:
        if not JOB_ID_RE.match(args.job) or not (CLIPS_DIR / args.job / "job.json").exists():
            print(f"Job not found: {args.job}", file=sys.stderr)
            return 2
        job_dir = CLIPS_DIR / args.job
    elif args.url:
        job_dir = new_job({
            "url": args.url, "mode": args.mode, "num_clips": args.clips, "length": args.length,
            "layout": args.layout, "caption_style": args.captions, "language": args.language,
            "title_language": args.title_language, "watermark": args.watermark,
            "audio_mode": args.audio, "use_ai": not args.no_ai,
        })
        print(f"Job: {job_dir.name}")
    else:
        ap.error("pass --url or --job")

    try:
        run_job(job_dir)
    except Exception as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 1
    print(f"Done → {job_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
