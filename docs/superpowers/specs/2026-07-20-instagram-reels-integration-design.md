# Instagram Reels Automation — Design

## Problem

The pipeline generates vertical short-form video (`pipeline/shorts_creator.py`)
for YouTube Shorts, uploaded on a fixed daily schedule
(`config.SHORTS_UPLOAD_SLOTS`). That same content currently reaches only
YouTube. Cross-posting the same Reels to Instagram costs no extra generation
work — it's a new distribution channel for video that already exists — but
Instagram's Graph API differs from YouTube's in ways that shape the design:

1. **No local file upload.** The API requires a public video URL; the file
   must be hosted somewhere reachable, unlike YouTube's direct
   `MediaFileUpload`.
2. **No native "publish at a future time."** `media_publish` publishes
   immediately, whereas YouTube's `status.publishAt` handles scheduling
   natively. Since Shorts are generated hours before their scheduled upload
   slot (see `GENERATION_LEAD_HOURS` / `SHORTS_UPLOAD_SLOTS`), something has
   to hold each Reel and fire it at the right time.
3. **App Review gate.** While the Meta Developer app is in Development Mode,
   only accounts added as Instagram Testers can be posted to — fine for a
   single-channel personal automation, but a real constraint if this ever
   needed to post to other people's accounts.

## Decisions (from user input)

- New tab inside the **existing** dashboard app (not a separate deployment).
- Reels = the **same MP4s** already produced for YouTube Shorts; no separate
  Instagram-only content generation.
- Posting **mirrors** `SHORTS_UPLOAD_SLOTS` rather than running its own
  schedule.
- Captions are **derived from the existing script/title** already generated
  by `script_generator.py` — no extra LLM calls.
- Temporary public hosting via **Cloudflare R2** (free tier: 10 GB storage, no
  egress fees).
- On failure: retry with backoff, then **skip and log** — a failed Instagram
  post must never block YouTube uploads or the rest of the pipeline run.

## Architecture

### Scheduling: enqueue now, publish later

Mirrors the existing pattern already proven in this codebase for post-upload
engagement (`pipeline/engagement.py` + `_engagement_loop()` in `api/main.py`):
a background poller ticks on an interval and acts on a persisted JSON queue,
rather than trying to hold an in-process timer for hours.

```
scheduler.py::_run_shorts()
  → renders short_NN video (existing)
  → upload_video(...) to YouTube (existing)
  → instagram_queue.enqueue(video_path, caption, publish_at_utc=slot_time)  [NEW]

api/main.py startup
  → asyncio.create_task(_instagram_loop())  [NEW, same shape as _engagement_loop]
      → every INSTAGRAM_POLL_SECONDS: pipeline.instagram_queue.run_pending_posts()
          → for each queue entry where publish_at_utc has passed and status == "pending":
              1. upload_to_r2(video_path)          → public URL
              2. publish_reel(url, caption)         → IG media id (create + poll + publish)
              3. delete_from_r2(key)                → cleanup
              4. mark entry "posted" (or "failed" with error, after retries exhausted)
```

### New pipeline module: `pipeline/instagram_uploader.py`

Mirrors the shape of `pipeline/uploader.py`:

- `_get_r2_client()` — boto3 S3-compatible client, reads `R2_*` config values
- `upload_to_r2(video_path: str) -> tuple[str, str]` — returns `(public_url, r2_key)`
- `delete_from_r2(r2_key: str) -> None`
- `publish_reel(video_url: str, caption: str) -> str` — returns the IG media id:
  1. `POST /{ig-user-id}/media` with `media_type=REELS`, `video_url`, `caption`
  2. poll `GET /{container-id}?fields=status_code` until `FINISHED` (bounded
     retries — Instagram's video processing is asynchronous)
  3. `POST /{ig-user-id}/media_publish` with the container id
- All network calls wrapped with `@with_retry(max_attempts=3, base_delay=5,
  exceptions=(requests.RequestException,))`, consistent with the retry table
  in `CLAUDE.md`.

### New queue module: `pipeline/instagram_queue.py`

Mirrors the state-file pattern in `pipeline/engagement.py`:

- State file: `instagram_queue.json` — list of entries:
  `{id, video_path, caption, publish_at_utc, status, error, instagram_media_id}`
  where `status` is one of `pending | posted | failed`.
- `enqueue(video_path, caption, publish_at_utc) -> str` — appends an entry,
  returns its id.
- `run_pending_posts() -> dict` — scans for `pending` entries whose
  `publish_at_utc` has passed, attempts `instagram_uploader.publish_reel`,
  updates status; never raises (catches and records `error` on the entry
  instead), so one failure doesn't stop the rest of the batch.
- `list_posts() -> list` / `retry_post(id) -> bool` — for the dashboard API.

### `scheduler.py` change

In `_run_shorts()`, immediately after the existing `upload_video(...)` call
for each Short, add:

```python
from pipeline.instagram_queue import enqueue as ig_enqueue
...
caption = script.get("title", "") + "\n\n" + script.get("description", "")
ig_enqueue(video_path, caption[:2200], publish_at_utc=_ist_slot_to_utc(slot))
```

(2200 chars is Instagram's caption limit.) Wrapped in its own try/except so a
queue write failure can't affect the YouTube upload that already succeeded.

### `api/main.py` changes

- `_instagram_loop()` — same shape as `_engagement_loop()`, started via
  `asyncio.create_task` at startup, ticking every `INSTAGRAM_POLL_SECONDS`
  (default 300s — tighter than the 15-minute engagement poll since Reels
  timing is user-visible).
- New endpoints:
  - `GET /api/instagram/posts` — list queue entries (pending/posted/failed)
  - `POST /api/instagram/posts/{id}/retry` — manually retry a failed entry
  - `POST /api/instagram/run` — force a pass now (same pattern as
    `/api/community-posts/generate`)
- Extend `GET/POST /api/settings` to read/write the Instagram + R2 credential
  fields into `.env`, alongside the existing settings.

### Dashboard changes

- `Sidebar.tsx`: add an "Instagram" nav entry.
- `page.tsx`: add `"instagram"` to the `Tab` union, render
  `<InstagramPanel />`.
- New `dashboard/components/InstagramPanel.tsx` (modeled on
  `ShortsPanel.tsx` / `CommunityPanel.tsx`):
  - list of queue entries with thumbnail, caption preview, target time,
    status badge
  - "Retry" action on failed entries
  - "Run pass now" manual trigger button
  - credential fields (Meta App ID/Secret/token, Page ID, IG Business Account
    ID, R2 access key/secret/bucket) — either a new block in
    `SettingsPanel.tsx` or a dedicated settings section within
    `InstagramPanel.tsx`
- `lib/types.ts`: add `InstagramPost` type.
- `lib/api.ts`: add `listInstagramPosts()`, `retryInstagramPost(id)`,
  `runInstagramPass()`, extend settings get/set.

### One-time manual setup (not automated)

Documented separately (`INSTAGRAM_SETUP.md`, human click-path) plus a new
`setup_instagram_auth.py` script (mirrors `setup_auth.py`) that handles token
exchange/verification once the user has:
1. An Instagram Business/Creator account linked to a Facebook Page.
2. A Meta Developer app with the Instagram Graph API product added.
3. Their own account added as an Instagram Tester (Development Mode
   requirement).

`setup_instagram_auth.py` takes the short-lived token from Graph API Explorer
and exchanges it for a long-lived one, then writes all 5 credential values
into `.env`.

## Config additions (`config.py`)

```python
INSTAGRAM_APP_ID              = os.getenv("INSTAGRAM_APP_ID", "")
INSTAGRAM_APP_SECRET           = os.getenv("INSTAGRAM_APP_SECRET", "")
INSTAGRAM_ACCESS_TOKEN         = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
INSTAGRAM_PAGE_ID              = os.getenv("INSTAGRAM_PAGE_ID", "")
INSTAGRAM_BUSINESS_ACCOUNT_ID  = os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID", "")
R2_ACCOUNT_ID                  = os.getenv("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID               = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY           = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET_NAME                 = os.getenv("R2_BUCKET_NAME", "")
INSTAGRAM_POLL_SECONDS         = int(os.getenv("INSTAGRAM_POLL_SECONDS", str(5 * 60)))
```

All empty-string-default, same style as `PEXELS_API_KEY` — the feature simply
no-ops (queue entries stay `pending` forever, logged as skipped) if
credentials are unset, so this never breaks the pipeline for someone who
hasn't done the Meta setup yet.

New dependency: `boto3` (R2 exposes an S3-compatible API), added to
`requirements.txt` and `api/requirements.txt`.

## Error handling

- Network/API calls retry via `@with_retry` (3 attempts, 5s base delay,
  exponential backoff + jitter — matching the existing table in `CLAUDE.md`).
- After retries exhaust, the queue entry is marked `failed` with the error
  message attached, visible in the dashboard's Instagram tab. It is never
  raised out of `_instagram_loop()`, so the poller continues ticking normally
  and other queue entries are unaffected.
- Missing/invalid credentials produce a clear log message and leave entries
  `pending` rather than crashing the loop.

## Out of scope

- Instagram feed image/carousel posts (Reels only, per user decision).
- Automated Meta Developer app creation / App Review submission (manual,
  human-in-the-loop process, documented separately).
- Posting to other people's Instagram accounts (blocked by Development Mode
  until App Review, not attempted here).
