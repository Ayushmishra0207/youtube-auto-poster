# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Fully automated Hindi YouTube video pipeline. Every day at 2:30 AM IST it fetches 7 trending topics from Google Trends (India), generates Hindi scripts via Claude API, synthesizes voice with gTTS, fetches background images from Pexels, assembles MP4s with MoviePy, uploads them to YouTube with scheduled publish times, and sets custom thumbnails.

## Setup (One-Time)

```bash
pip install -r requirements.txt
python setup_fonts.py          # downloads Noto Sans Devanagari fonts
python setup_auth.py           # YouTube OAuth flow → saves youtube_token.pickle
```

Copy `.env.example` to `.env` and set:
- `ANTHROPIC_API_KEY` — required (Claude script generation)
- `PEXELS_API_KEY` — optional (falls back to gradient backgrounds if absent)
- `KEEP_OUTPUT_DAYS` — optional, default `3` (days of output to retain on disk)

**After upgrading:** If you had an older `youtube_token.pickle`, run `python setup_auth.py` again — it detects and replaces stale tokens that lack thumbnail scope.

## Running

```bash
# Run the full pipeline immediately (for testing)
python scheduler.py --now

# Start as a daily daemon (fires at 2:30 AM IST)
python scheduler.py

# Install as a Windows Task Scheduler job (run once as Administrator)
python install_task.py

# Check / remove the scheduled task
python install_task.py --status
python install_task.py --remove
```

There is no test suite. The `--now` flag is the standard way to test pipeline changes end-to-end.

## Architecture

Linear pipeline — `scheduler.py` orchestrates 7 videos per day:

```
trends.py            → get_trending_topics()           Google Trends (India)
script_generator.py  → generate_script()               Claude API → JSON (cached prompt)
voice_generator.py   → generate_section_voices()       gTTS MP3s
image_fetcher.py     → fetch_all_section_images()      Pexels JPEGs (or None → gradient)
video_creator.py     → create_thumbnail()              JPEG for YouTube thumbnail
video_creator.py     → create_video()                  MoviePy → MP4
uploader.py          → upload_video()                  YouTube API (scheduled publish)
uploader.py          → upload_thumbnail()              YouTube thumbnails API
```

Output is written to date-stamped directories: `output/YYYY-MM-DD/video_NN/`. Directories older than `KEEP_OUTPUT_DAYS` are deleted automatically after each pipeline run.

### Key Files

- [config.py](config.py) — single source of truth for all paths, API keys, video specs (1920×1080, 24fps, 4000k), upload slots, font paths, gradient color pairs, logging, and YouTube metadata
- [pipeline/logger.py](pipeline/logger.py) — rotating file logger (`logs/pipeline.log`, 5 MB × 7 files); used by all modules via `from pipeline.logger import log`
- [pipeline/retry.py](pipeline/retry.py) — `@with_retry(max_attempts, base_delay, exceptions)` decorator with exponential back-off + jitter
- [pipeline/script_generator.py](pipeline/script_generator.py) — calls Claude `claude-opus-4-6`; the system prompt is marked `cache_control=ephemeral` so it is cached after the first call (saves ~80% of prompt tokens per run); expects JSON back with shape `{title, title_english, description, tags, thumbnail_text, sections: [{id, heading, narration, key_points, image_search}]}`
- [pipeline/video_creator.py](pipeline/video_creator.py) — core rendering: title card (5s) → content slides (voice duration + 0.8s tail) → outro CTA (5s); `create_thumbnail()` saves the title card as JPEG for upload
- [pipeline/uploader.py](pipeline/uploader.py) — Google OAuth 2.0; token persisted in `youtube_token.pickle`; `upload_thumbnail()` gracefully skips if channel not phone-verified (403)
- [scheduler.py](scheduler.py) — top-level orchestrator: generates videos, uploads with scheduled publish times, then purges old output dirs

### Video Assembly

Each content slide composites: Pexels background image (or dark gradient fallback) + dark overlay + Hindi heading + narration preview (PIL/Pillow), synced to its gTTS voice clip. All slides concatenated with background music at 12% volume.

### Claude Script Contract

`script_generator.py` splits the prompt into:
- **System message** (cached): persona, JSON schema, rules
- **User message** (dynamic, per topic): `Create a complete video script about: "{topic}"`

If you change the JSON schema shape, update both the system prompt in [pipeline/script_generator.py](pipeline/script_generator.py) and the downstream consumers in [pipeline/video_creator.py](pipeline/video_creator.py) and [pipeline/voice_generator.py](pipeline/voice_generator.py).

### Retry Behaviour

| Module | Retries | Delay | Exceptions caught |
|---|---|---|---|
| script_generator | 3 | 5s base | `anthropic.APIError`, `APIConnectionError`, `ValueError` |
| voice_generator | 3 | 3s base | `gTTSError`, `OSError` |
| image_fetcher | 3 | 2s base | `requests.exceptions.RequestException` |

A failed voice clip results in that section being skipped in the video (not a full abort) — but if *every* section's voice fails the video is aborted rather than uploading a ~9 s title+outro. A failed image falls back to a gradient slide. A failed script (including valid JSON missing `sections`/`items`) aborts that video entirely.

### Locks and upload bookkeeping

- `pipeline/locking.py` owns `pipeline.lock`, `short_generate.lock` and `instagram_queue.lock` (atomic create, stale takeover by rename, PID check that works on Windows *and* Linux). Use it — don't hand-roll `tasklist` checks.
- After every YouTube upload write `youtube_id.txt` into the item's folder: dashboard status, the duplicate-upload guard and engagement comments all depend on it.
- Run YouTube metadata through `pipeline/text_utils.fit_youtube_tags` / `fit_youtube_text` (500-char tag budget counting quotes on multi-word tags; 5000 **bytes** of description).

## Viral Clip Maker (`clipper/`)

Separate from the daily pipeline: paste a YouTube link in the dashboard's **Clip Maker** tab (or `python clip_now.py --url ... --mode gta6_action`) → vertical 1080×1920 captioned clips in `output/clips/<job_id>/clip_NN/`.

```
downloader.py   yt-dlp, ≤1080p, prefers H.264 (AV1 decodes ~10× slower with the bundled ffmpeg); cached in output/clips/_sources/
analyzer.py     per-second audio energy/onsets, scene cuts, speech density → sliding-window scores weighted per mode
transcriber.py  faster-whisper word timestamps (CLIPPER_WHISPER_MODEL, default "small"); samples passed as numpy (PyAV decode is broken)
planner.py      Claude picks moments + writes hook/title/description (structured JSON); falls back to signal picks on any failure
subtitles.py    ASS file: word-by-word highlighted captions, hook banner, watermark (Devanagari switches to Noto Sans Devanagari)
renderer.py     ffmpeg: blur-fit or centre-crop reframe, zoom, grade, captions, progress bar, loudnorm, optional music bed
job.py          orchestration; state in status.json, read by /api/clips*
```

- Dependencies live in `requirements-clipper.txt`, **not** `requirements.txt`: too heavy for Render's free plan. `/api/clips/options` reports `available: false` there and the tab tells the user to run it locally.
- ffmpeg is the imageio-ffmpeg binary (libass + HarfBuzz). Captions are burned with `ass=` run from the clip dir with relative paths, because Windows drive-letter colons break ffmpeg filter args.
- `yt-dlp[default]` is required (bundles `yt-dlp-ejs`; without it YouTube returns HTTP 403).

## Configuration

All tunable values live in `config.py`. Important constants:

| Setting | Value |
|---|---|
| Resolution | 1920×1080 |
| FPS | 24 |
| Bitrate | 4000k |
| Music volume | 12% |
| Videos per day | 8 (`UPLOAD_SLOTS_IST`) |
| Upload window | 18:30–19:40 IST |
| Generation trigger | 14:30 IST (first slot − `GENERATION_LEAD_HOURS`) |
| Output retention | 3 days |
| TTS language | `hi` (Hindi) |
| YouTube category | 25 (News & Politics) |
| Log location | `logs/pipeline.log` |

## Production Deployment

1. Run `python setup_auth.py` (once) to authenticate YouTube OAuth
2. Run `python install_task.py` from an elevated terminal to register the Windows Task Scheduler job (runs `scheduler.py --now` daily at 14:30)
3. Ensure Windows timezone is set to IST (UTC+5:30)
4. Logs are at `logs/pipeline.log` — check here if videos don't appear on the channel
