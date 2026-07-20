# Instagram Reels Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cross-post every YouTube Short this pipeline already generates to Instagram as a Reel, published at the same scheduled slot time, manageable from a new "Instagram" tab in the existing dashboard.

**Architecture:** Shorts are enqueued into a persisted JSON queue (`instagram_queue.json`) right after their YouTube upload; a background poller in `api/main.py` (same shape as the existing `_engagement_loop`) fires each entry once its target time arrives — uploading the MP4 to Cloudflare R2 for a temporary presigned URL, publishing it via Instagram's Graph API container flow, then deleting the R2 object. Failures retry with backoff and are marked `failed` in the queue without blocking anything else.

**Tech Stack:** Python (FastAPI backend, existing pipeline modules), boto3 (Cloudflare R2, S3-compatible API), `requests` (Instagram Graph API), Next.js/React/TypeScript (dashboard), same Tailwind styling conventions already used across the dashboard's panels.

## Global Constraints

- This project has **no automated test suite** (confirmed: no pytest, no `tests/` directory — see `CLAUDE.md`: "There is no test suite. The `--now` flag is the standard way to test pipeline changes end-to-end"). This plan follows that existing convention: verification steps use small ad-hoc scripts (run via `python -c` or a Bash heredoc, using `unittest.mock` from the stdlib where a live credential would otherwise be required) rather than introducing a new pytest suite. Nothing from these verification steps is committed — only the implementation files are.
- All new env-driven config values default to an empty string and the feature must no-op gracefully when unset, matching the existing `PEXELS_API_KEY` pattern in `config.py` — never crash the pipeline for someone who hasn't done the Meta/R2 setup yet.
- Network calls wrapped with `@with_retry` from `pipeline/retry.py` (3 attempts, 5s base delay), matching the retry table already documented in `CLAUDE.md`.
- A failed Instagram post must never raise out of the background poll loop or block the YouTube upload path it's wired alongside.
- New dependency: `boto3` (Cloudflare R2 exposes an S3-compatible API) — added to both `requirements.txt` and `api/requirements.txt`.
- Follow existing code conventions exactly: `from pipeline.logger import log` for logging, lazy `from pipeline.x import y` inside functions where the caller (`api/main.py`, `scheduler.py`) already does this for optional pipeline features (see `_engagement_loop`, `_run_shorts`).

---

### Task 1: Config values and dependencies

**Files:**
- Modify: `config.py` (append new section at end, after `SLIDE_COLORS`)
- Modify: `requirements.txt`
- Modify: `api/requirements.txt`

**Interfaces:**
- Produces: `config.INSTAGRAM_APP_ID`, `config.INSTAGRAM_APP_SECRET`, `config.INSTAGRAM_ACCESS_TOKEN`, `config.INSTAGRAM_PAGE_ID`, `config.INSTAGRAM_BUSINESS_ACCOUNT_ID`, `config.R2_ACCOUNT_ID`, `config.R2_ACCESS_KEY_ID`, `config.R2_SECRET_ACCESS_KEY`, `config.R2_BUCKET_NAME`, `config.INSTAGRAM_POLL_SECONDS` (int, default 300) — all consumed by Tasks 2, 3, 5, 6.

- [ ] **Step 1: Add the config block**

Append to `config.py`:

```python
# ─── Instagram Reels automation ────────────────────────────────────────────────
# Cross-posts the same vertical MP4s already rendered for YouTube Shorts.
# See INSTAGRAM_SETUP.md for the one-time manual Meta Developer app / Facebook
# Page linking steps, then run setup_instagram_auth.py to fill these in.
INSTAGRAM_APP_ID              = os.getenv("INSTAGRAM_APP_ID", "")
INSTAGRAM_APP_SECRET          = os.getenv("INSTAGRAM_APP_SECRET", "")
INSTAGRAM_ACCESS_TOKEN        = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
INSTAGRAM_PAGE_ID             = os.getenv("INSTAGRAM_PAGE_ID", "")
INSTAGRAM_BUSINESS_ACCOUNT_ID = os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID", "")

# Cloudflare R2 — temporary public hosting for each Reel's video file, since
# Instagram's Graph API requires a public URL (no direct file upload). Uses a
# presigned URL (1h expiry), so the R2 bucket itself never needs to be public.
R2_ACCOUNT_ID        = os.getenv("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID     = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET_NAME       = os.getenv("R2_BUCKET_NAME", "")

# How often the background poller (api/main.py::_instagram_loop) checks for
# queued Reels whose scheduled time has arrived. Tighter than the 15-minute
# engagement poll since Reel timing is user-visible.
INSTAGRAM_POLL_SECONDS = int(os.getenv("INSTAGRAM_POLL_SECONDS", str(5 * 60)))
```

- [ ] **Step 2: Add the `boto3` dependency**

Append `boto3>=1.34.0` as a new line to `requirements.txt` and to `api/requirements.txt`.

- [ ] **Step 3: Install it and verify config loads**

Run:
```bash
pip install boto3
python -c "import config; assert config.INSTAGRAM_POLL_SECONDS == 300; assert config.R2_BUCKET_NAME == ''; print('OK')"
```
Expected output: `OK`

- [ ] **Step 4: Commit**

```bash
git add config.py requirements.txt api/requirements.txt
git commit -m "feat: add Instagram/R2 config values and boto3 dependency"
```

---

### Task 2: `pipeline/instagram_uploader.py` — R2 hosting + Graph API publish

**Files:**
- Create: `pipeline/instagram_uploader.py`

**Interfaces:**
- Consumes: `config.INSTAGRAM_ACCESS_TOKEN`, `config.INSTAGRAM_BUSINESS_ACCOUNT_ID`, `config.R2_ACCOUNT_ID`, `config.R2_ACCESS_KEY_ID`, `config.R2_SECRET_ACCESS_KEY`, `config.R2_BUCKET_NAME` (Task 1); `pipeline.retry.with_retry`; `pipeline.logger.log`.
- Produces: `publish_reel(video_path: str, caption: str) -> str` (returns Instagram media id, raises on unrecoverable failure) — consumed by Task 3's `run_pending_posts()`.

- [ ] **Step 1: Write a verification script exercising the intended behavior**

Save as a throwaway file, e.g. `_verify_task2.py` (not committed):

```python
from unittest.mock import patch, MagicMock

with patch("pipeline.instagram_uploader.boto3") as mock_boto3, \
     patch("pipeline.instagram_uploader.requests") as mock_requests:

    mock_s3 = MagicMock()
    mock_s3.generate_presigned_url.return_value = "https://example.com/presigned.mp4"
    mock_boto3.client.return_value = mock_s3

    mock_requests.exceptions.RequestException = Exception  # for @with_retry's exceptions tuple

    create_resp = MagicMock(); create_resp.json.return_value = {"id": "container123"}
    poll_resp   = MagicMock(); poll_resp.json.return_value = {"status_code": "FINISHED"}
    publish_resp = MagicMock(); publish_resp.json.return_value = {"id": "media456"}
    mock_requests.post.side_effect = [create_resp, publish_resp]
    mock_requests.get.return_value = poll_resp

    import pipeline.instagram_uploader as iu
    media_id = iu.publish_reel("/tmp/fake.mp4", "test caption")
    assert media_id == "media456", media_id
    mock_s3.upload_file.assert_called_once()
    mock_s3.delete_object.assert_called_once()  # cleanup ran even on the happy path
    print("OK: happy path")

    # Cleanup must still run if publishing fails partway through
    mock_s3.reset_mock()
    mock_requests.post.side_effect = [create_resp, RuntimeError("boom")]
    try:
        iu.publish_reel("/tmp/fake.mp4", "test caption")
        raise AssertionError("expected an exception")
    except RuntimeError:
        pass
    mock_s3.delete_object.assert_called_once()
    print("OK: cleanup runs even when publish fails")
```

- [ ] **Step 2: Run it to confirm it fails (module doesn't exist yet)**

Run: `python _verify_task2.py`
Expected: `ModuleNotFoundError: No module named 'pipeline.instagram_uploader'`

- [ ] **Step 3: Write the implementation**

Create `pipeline/instagram_uploader.py`:

```python
"""
Upload a rendered Reel to Cloudflare R2 for temporary public hosting, then
publish it to Instagram via the Graph API's two-step container flow
(create container -> poll until processed -> publish). R2 is used purely as
a presigned-URL relay: Instagram's Graph API requires a public video URL and
has no direct file-upload path, unlike YouTube's MediaFileUpload.

One-time setup: see INSTAGRAM_SETUP.md, then run setup_instagram_auth.py.
"""
import time
import uuid

import boto3
import requests

from config import (
    INSTAGRAM_ACCESS_TOKEN,
    INSTAGRAM_BUSINESS_ACCOUNT_ID,
    R2_ACCOUNT_ID,
    R2_ACCESS_KEY_ID,
    R2_SECRET_ACCESS_KEY,
    R2_BUCKET_NAME,
)
from pipeline.logger import log
from pipeline.retry import with_retry

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"
CONTAINER_POLL_INTERVAL_SECONDS = 5
CONTAINER_POLL_MAX_ATTEMPTS = 24  # ~2 minutes total
PRESIGNED_URL_EXPIRY_SECONDS = 3600


def _get_r2_client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    )


@with_retry(max_attempts=3, base_delay=5, exceptions=(Exception,))
def upload_to_r2(video_path: str) -> tuple[str, str]:
    """Upload video_path to R2, return (presigned_public_url, r2_key)."""
    r2_key = f"reels/{uuid.uuid4().hex}.mp4"
    client = _get_r2_client()
    client.upload_file(video_path, R2_BUCKET_NAME, r2_key, ExtraArgs={"ContentType": "video/mp4"})
    public_url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": R2_BUCKET_NAME, "Key": r2_key},
        ExpiresIn=PRESIGNED_URL_EXPIRY_SECONDS,
    )
    log.info("Uploaded %s to R2 (key=%s), presigned URL expires in %ds", video_path, r2_key, PRESIGNED_URL_EXPIRY_SECONDS)
    return public_url, r2_key


def delete_from_r2(r2_key: str) -> None:
    try:
        _get_r2_client().delete_object(Bucket=R2_BUCKET_NAME, Key=r2_key)
        log.info("Deleted R2 object %s", r2_key)
    except Exception as exc:
        log.warning("Failed to delete R2 object %s: %s", r2_key, exc)


@with_retry(max_attempts=3, base_delay=5, exceptions=(requests.exceptions.RequestException,))
def _create_container(video_url: str, caption: str) -> str:
    resp = requests.post(
        f"{GRAPH_API_BASE}/{INSTAGRAM_BUSINESS_ACCOUNT_ID}/media",
        data={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "access_token": INSTAGRAM_ACCESS_TOKEN,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def _wait_until_ready(container_id: str) -> None:
    for _ in range(CONTAINER_POLL_MAX_ATTEMPTS):
        resp = requests.get(
            f"{GRAPH_API_BASE}/{container_id}",
            params={"fields": "status_code", "access_token": INSTAGRAM_ACCESS_TOKEN},
            timeout=30,
        )
        resp.raise_for_status()
        status = resp.json().get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"Instagram container {container_id} failed processing")
        time.sleep(CONTAINER_POLL_INTERVAL_SECONDS)
    raise TimeoutError(f"Instagram container {container_id} did not finish processing in time")


@with_retry(max_attempts=3, base_delay=5, exceptions=(requests.exceptions.RequestException,))
def _publish_container(container_id: str) -> str:
    resp = requests.post(
        f"{GRAPH_API_BASE}/{INSTAGRAM_BUSINESS_ACCOUNT_ID}/media_publish",
        data={"creation_id": container_id, "access_token": INSTAGRAM_ACCESS_TOKEN},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def publish_reel(video_path: str, caption: str) -> str:
    """Upload video_path to R2, publish it to Instagram as a Reel, then always
    clean up the R2 object. Returns the Instagram media id. Raises on
    unrecoverable failure — the caller (pipeline.instagram_queue) is
    responsible for catching and recording it."""
    public_url, r2_key = upload_to_r2(video_path)
    try:
        container_id = _create_container(public_url, caption)
        _wait_until_ready(container_id)
        return _publish_container(container_id)
    finally:
        delete_from_r2(r2_key)
```

- [ ] **Step 4: Run the verification script again to confirm it passes**

Run: `python _verify_task2.py`
Expected output:
```
OK: happy path
OK: cleanup runs even when publish fails
```

- [ ] **Step 5: Delete the throwaway script and confirm the module imports cleanly with no credentials set**

```bash
rm _verify_task2.py
python -c "import pipeline.instagram_uploader; print('OK: imports with no credentials set')"
```
Expected: `OK: imports with no credentials set` (nothing calls the network at import time).

- [ ] **Step 6: Commit**

```bash
git add pipeline/instagram_uploader.py
git commit -m "feat: add Instagram Graph API publisher with R2 presigned-URL hosting"
```

---

### Task 3: `pipeline/instagram_queue.py` — persisted publish queue

**Files:**
- Create: `pipeline/instagram_queue.py`

**Interfaces:**
- Consumes: `config.BASE_DIR`; `pipeline.logger.log`; `pipeline.instagram_uploader.publish_reel(video_path: str, caption: str) -> str` (Task 2, imported lazily inside `run_pending_posts`).
- Produces: `enqueue(video_path: str, caption: str, publish_at_utc: datetime) -> str` (consumed by Task 4's `scheduler.py` change); `list_posts() -> list[dict]`, `retry_post(entry_id: str) -> bool`, `run_pending_posts() -> dict` (all three consumed by Task 5's `api/main.py` endpoints/loop). Each queue entry dict has keys: `id, video_path, caption, publish_at_utc, status, error, instagram_media_id` where `status` is `"pending" | "posted" | "failed"`.

- [ ] **Step 1: Write a verification script**

Save as `_verify_task3.py` (not committed), pointed at a scratch state file so it doesn't touch the real `instagram_queue.json`:

```python
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pipeline.instagram_queue as q

scratch = Path("_verify_task3_state.json")
if scratch.exists():
    scratch.unlink()
q.INSTAGRAM_QUEUE_FILE = scratch  # point the module at a throwaway file

# enqueue + list_posts
past = datetime.now(timezone.utc) - timedelta(minutes=1)
future = datetime.now(timezone.utc) + timedelta(hours=1)
due_id    = q.enqueue("/tmp/a.mp4", "caption A", past)
future_id = q.enqueue("/tmp/b.mp4", "caption B", future)
posts = q.list_posts()
assert len(posts) == 2
assert all(p["status"] == "pending" for p in posts)
print("OK: enqueue + list_posts")

# run_pending_posts only acts on entries whose time has passed, and never raises
with patch("pipeline.instagram_uploader.publish_reel") as mock_publish:
    mock_publish.side_effect = ["media789"]
    result = q.run_pending_posts()
assert result == {"posted": 1, "failed": 0}, result
posts = {p["id"]: p for p in q.list_posts()}
assert posts[due_id]["status"] == "posted"
assert posts[due_id]["instagram_media_id"] == "media789"
assert posts[future_id]["status"] == "pending"  # not due yet, left alone
mock_publish.assert_called_once_with("/tmp/a.mp4", "caption A")
print("OK: run_pending_posts publishes only due entries")

# a failure is recorded, not raised
past2 = datetime.now(timezone.utc) - timedelta(minutes=1)
fail_id = q.enqueue("/tmp/c.mp4", "caption C", past2)
with patch("pipeline.instagram_uploader.publish_reel") as mock_publish:
    mock_publish.side_effect = RuntimeError("network down")
    result = q.run_pending_posts()  # must not raise
assert result == {"posted": 0, "failed": 1}, result
posts = {p["id"]: p for p in q.list_posts()}
assert posts[fail_id]["status"] == "failed"
assert "network down" in posts[fail_id]["error"]
print("OK: failures are recorded, not raised")

# retry_post resets a failed entry back to pending
assert q.retry_post(fail_id) is True
posts = {p["id"]: p for p in q.list_posts()}
assert posts[fail_id]["status"] == "pending"
assert posts[fail_id]["error"] is None
assert q.retry_post("nonexistent") is False
print("OK: retry_post")

scratch.unlink()
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `python _verify_task3.py`
Expected: `ModuleNotFoundError: No module named 'pipeline.instagram_queue'`

- [ ] **Step 3: Write the implementation**

Create `pipeline/instagram_queue.py`:

```python
"""
Persistent queue for Instagram Reel posts, polled by api/main.py's
_instagram_loop(). Mirrors pipeline/engagement.py's state-file pattern:
Instagram's Graph API has no native "publish later" (unlike YouTube's
publishAt), so each Short is enqueued here right after its YouTube upload
(scheduler.py), and a background poller publishes it once the same slot
time arrives.
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from config import BASE_DIR
from pipeline.logger import log

INSTAGRAM_QUEUE_FILE = BASE_DIR / "instagram_queue.json"


def _load_state() -> dict:
    if INSTAGRAM_QUEUE_FILE.exists():
        try:
            return json.loads(INSTAGRAM_QUEUE_FILE.read_text(encoding="utf-8"))
        except Exception:
            log.warning("instagram_queue.json unreadable — starting fresh")
    return {"posts": []}


def _save_state(state: dict) -> None:
    INSTAGRAM_QUEUE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def enqueue(video_path: str, caption: str, publish_at_utc: datetime) -> str:
    """Queue a Reel for posting once publish_at_utc arrives. Returns the entry id."""
    state = _load_state()
    entry_id = uuid.uuid4().hex[:12]
    state["posts"].append({
        "id": entry_id,
        "video_path": str(video_path),
        "caption": caption,
        "publish_at_utc": publish_at_utc.astimezone(timezone.utc).isoformat(),
        "status": "pending",
        "error": None,
        "instagram_media_id": None,
    })
    _save_state(state)
    log.info("Instagram Reel queued (%s), publishes at %s", entry_id, publish_at_utc)
    return entry_id


def list_posts() -> list:
    return _load_state().get("posts", [])


def retry_post(entry_id: str) -> bool:
    """Reset a failed entry back to pending so the next poll retries it."""
    state = _load_state()
    for p in state["posts"]:
        if p["id"] == entry_id and p["status"] == "failed":
            p["status"] = "pending"
            p["error"] = None
            _save_state(state)
            return True
    return False


def run_pending_posts() -> dict:
    """One pass: publish any pending entry whose publish_at_utc has arrived.
    Never raises — a failed post is recorded on its own entry and skipped,
    so it can't block the rest of the queue or the caller's loop."""
    from pipeline.instagram_uploader import publish_reel  # lazy: avoids importing
                                                            # boto3/requests at module
                                                            # load if Instagram isn't configured
    state = _load_state()
    now = datetime.now(timezone.utc)
    posted, failed = 0, 0

    for p in state["posts"]:
        if p["status"] != "pending":
            continue
        target = datetime.fromisoformat(p["publish_at_utc"])
        if target > now:
            continue
        try:
            media_id = publish_reel(p["video_path"], p["caption"])
            p["status"] = "posted"
            p["instagram_media_id"] = media_id
            posted += 1
            log.info("Instagram Reel posted (%s) -> media id %s", p["id"], media_id)
        except Exception as exc:
            p["status"] = "failed"
            p["error"] = str(exc)
            failed += 1
            log.error("Instagram Reel %s failed: %s", p["id"], exc)

    _save_state(state)
    return {"posted": posted, "failed": failed}
```

- [ ] **Step 4: Run the verification script again to confirm it passes**

Run: `python _verify_task3.py`
Expected output:
```
OK: enqueue + list_posts
OK: run_pending_posts publishes only due entries
OK: failures are recorded, not raised
OK: retry_post
```

- [ ] **Step 5: Delete the throwaway script**

```bash
rm _verify_task3.py
```

- [ ] **Step 6: Add `instagram_queue.json` to `.gitignore`** (it's runtime state, like `instagram_queue.json`'s sibling `engagement_state.json` — check whether `engagement_state.json` is already ignored)

Run: `grep -n "engagement_state" .gitignore`
- If found, add `instagram_queue.json` right next to it in `.gitignore`.
- If not found, add both `engagement_state.json` and `instagram_queue.json` as new lines in `.gitignore`.

- [ ] **Step 7: Commit**

```bash
git add pipeline/instagram_queue.py .gitignore
git commit -m "feat: add Instagram Reel publish queue with retry support"
```

---

### Task 4: Wire Short generation into the Instagram queue

**Files:**
- Modify: `scheduler.py` (inside `_run_shorts`, right after the existing `upload_video(...)` call — see current lines ~469-476)

**Interfaces:**
- Consumes: `pipeline.instagram_queue.enqueue(video_path, caption, publish_at_utc)` (Task 3); existing locals already in scope at that point in `_run_shorts`: `video_path`, `script`, `slot`, `_ist_slot_to_utc`.

- [ ] **Step 1: Make the change**

In `scheduler.py`, find:

```python
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
```

Replace with:

```python
            upload_video(
                video_path=video_path,
                title=title,
                description=script.get("description", "#Shorts #News"),
                tags=script.get("tags", []),
                publish_at_utc=_ist_slot_to_utc(slot),
                yt_language=locale.yt_language,
            )

            try:
                from pipeline.instagram_queue import enqueue as ig_enqueue
                ig_caption = f"{script.get('title', '')}\n\n{script.get('description', '')}"[:2200]
                ig_enqueue(video_path, ig_caption, publish_at_utc=_ist_slot_to_utc(slot))
            except Exception as ig_exc:
                log.warning("Instagram enqueue failed for Short %d: %s", i, ig_exc)
        except Exception as e:
            log.error("Short %d failed: %s", i, e, exc_info=True)
```

(The Instagram enqueue is wrapped in its own try/except so a queue-write failure can never affect a YouTube upload that has already succeeded — matches the "retry + skip, never block" requirement from the spec.)

- [ ] **Step 2: Verify the change is syntactically correct and the new import resolves**

Run:
```bash
python -c "import ast; ast.parse(open('scheduler.py', encoding='utf-8').read()); print('OK: scheduler.py parses')"
python -c "from pipeline.instagram_queue import enqueue; print('OK: import resolves')"
```
Expected: both print their `OK: ...` line.

- [ ] **Step 3: Commit**

```bash
git add scheduler.py
git commit -m "feat: enqueue each Short for Instagram cross-posting after YouTube upload"
```

---

### Task 5: `api/main.py` — background poller + queue endpoints

**Files:**
- Modify: `api/main.py`

**Interfaces:**
- Consumes: `config.INSTAGRAM_POLL_SECONDS` (Task 1); `pipeline.instagram_queue.list_posts()`, `retry_post(id)`, `run_pending_posts()` (Task 3).
- Produces: `GET /api/instagram/posts`, `POST /api/instagram/posts/{id}/retry`, `POST /api/instagram/run` — consumed by Task 7's dashboard `api.ts` client.

- [ ] **Step 1: Import the new config value**

Find:
```python
from config import ENGAGEMENT_POLL_SECONDS, UPLOAD_SLOTS_IST
```
Replace with:
```python
from config import ENGAGEMENT_POLL_SECONDS, INSTAGRAM_POLL_SECONDS, UPLOAD_SLOTS_IST
```

- [ ] **Step 2: Start the background loop at startup**

Find:
```python
@app.on_event("startup")
async def _startup():
    init_db()
    asyncio.create_task(_engagement_loop())
```
Replace with:
```python
@app.on_event("startup")
async def _startup():
    init_db()
    asyncio.create_task(_engagement_loop())
    asyncio.create_task(_instagram_loop())
```

- [ ] **Step 3: Add the loop function**

Immediately after the existing `_engagement_loop` function (right before `def _session_token_from_request`), add:

```python
async def _instagram_loop():
    """Background poll loop: publish queued Instagram Reels once their
    scheduled time arrives. See pipeline/instagram_queue.py for the actual
    work — this loop just ticks it on a timer, same shape as _engagement_loop."""
    from pipeline.instagram_queue import run_pending_posts
    while True:
        try:
            result = await asyncio.to_thread(run_pending_posts)
            if result["posted"] or result["failed"]:
                log.info("Instagram pass: %s", result)
        except Exception as exc:
            log.error("Instagram pass failed: %s", exc, exc_info=True)
        await asyncio.sleep(INSTAGRAM_POLL_SECONDS)
```

- [ ] **Step 4: Add the endpoints**

Immediately after the existing `# ── Community-post drafts + engagement automation` section's three endpoints (right before `# ── WebSocket log stream`), add:

```python
# ── Instagram Reels queue ────────────────────────────────────────────────────
# See _instagram_loop() above and pipeline/instagram_queue.py. Each YouTube
# Short is enqueued automatically (scheduler.py); this section exposes that
# queue's status to the dashboard and allows a manual "run now" / retry.

@app.get("/api/instagram/posts")
async def get_instagram_posts():
    from pipeline.instagram_queue import list_posts
    return {"posts": list_posts()}

@app.post("/api/instagram/posts/{post_id}/retry")
async def retry_instagram_post(post_id: str):
    from pipeline.instagram_queue import retry_post
    ok = retry_post(post_id)
    if not ok:
        raise HTTPException(404, "Post not found or not in a failed state")
    return {"ok": True}

@app.post("/api/instagram/run")
async def run_instagram_now():
    """Force an Instagram publish pass right now instead of waiting for the next poll tick."""
    from pipeline.instagram_queue import run_pending_posts
    result = await asyncio.to_thread(run_pending_posts)
    return {"ok": True, **result}
```

- [ ] **Step 5: Verify the app still imports and starts**

Run:
```bash
python -c "import ast; ast.parse(open('api/main.py', encoding='utf-8').read()); print('OK: api/main.py parses')"
```
Then start the server briefly and confirm the new routes are registered:
```bash
python -c "
import api.main as m
paths = [r.path for r in m.app.routes]
assert '/api/instagram/posts' in paths
assert '/api/instagram/posts/{post_id}/retry' in paths
assert '/api/instagram/run' in paths
print('OK: routes registered')
"
```
Expected: `OK: api/main.py parses` then `OK: routes registered`.

- [ ] **Step 6: Commit**

```bash
git add api/main.py
git commit -m "feat: add Instagram queue background poller and API endpoints"
```

---

### Task 6: `api/main.py` — Instagram/R2 credential settings

**Files:**
- Modify: `api/main.py` (the `SettingsPayload` class and `get_settings`/`save_settings` endpoints)

**Interfaces:**
- Consumes: existing `_read_env()`, `_write_env()` helpers already defined in `api/main.py`.
- Produces: 9 new fields on `GET /api/settings` / `POST /api/settings` — consumed by Task 8's dashboard settings UI.

- [ ] **Step 1: Extend `SettingsPayload`**

Find:
```python
class SettingsPayload(BaseModel):
    ANTHROPIC_API_KEY: Optional[str] = None
    PEXELS_API_KEY: Optional[str] = None
    KEEP_OUTPUT_DAYS: Optional[str] = None
    TTS_VOICE: Optional[str] = None
    TTS_RATE: Optional[str] = None
    TTS_PITCH: Optional[str] = None
    SHORTS_PER_DAY: Optional[str] = None
```
Replace with:
```python
class SettingsPayload(BaseModel):
    ANTHROPIC_API_KEY: Optional[str] = None
    PEXELS_API_KEY: Optional[str] = None
    KEEP_OUTPUT_DAYS: Optional[str] = None
    TTS_VOICE: Optional[str] = None
    TTS_RATE: Optional[str] = None
    TTS_PITCH: Optional[str] = None
    SHORTS_PER_DAY: Optional[str] = None
    INSTAGRAM_APP_ID: Optional[str] = None
    INSTAGRAM_APP_SECRET: Optional[str] = None
    INSTAGRAM_ACCESS_TOKEN: Optional[str] = None
    INSTAGRAM_PAGE_ID: Optional[str] = None
    INSTAGRAM_BUSINESS_ACCOUNT_ID: Optional[str] = None
    R2_ACCOUNT_ID: Optional[str] = None
    R2_ACCESS_KEY_ID: Optional[str] = None
    R2_SECRET_ACCESS_KEY: Optional[str] = None
    R2_BUCKET_NAME: Optional[str] = None
```

- [ ] **Step 2: Extend `get_settings`**

Find the `return { ... }` block inside `get_settings` (ends with `"upload_slots": UPLOAD_SLOTS,`). Add these entries right before that closing `"upload_slots"` line — actual secrets masked as `"***"` (matching the existing `ANTHROPIC_API_KEY`/`PEXELS_API_KEY` pattern), IDs left plain since they aren't sensitive on their own:

```python
        "INSTAGRAM_APP_ID": env.get("INSTAGRAM_APP_ID", ""),
        "INSTAGRAM_APP_SECRET": "***" if env.get("INSTAGRAM_APP_SECRET") else "",
        "INSTAGRAM_ACCESS_TOKEN": "***" if env.get("INSTAGRAM_ACCESS_TOKEN") else "",
        "INSTAGRAM_PAGE_ID": env.get("INSTAGRAM_PAGE_ID", ""),
        "INSTAGRAM_BUSINESS_ACCOUNT_ID": env.get("INSTAGRAM_BUSINESS_ACCOUNT_ID", ""),
        "R2_ACCOUNT_ID": env.get("R2_ACCOUNT_ID", ""),
        "R2_ACCESS_KEY_ID": "***" if env.get("R2_ACCESS_KEY_ID") else "",
        "R2_SECRET_ACCESS_KEY": "***" if env.get("R2_SECRET_ACCESS_KEY") else "",
        "R2_BUCKET_NAME": env.get("R2_BUCKET_NAME", ""),
```

`save_settings` needs no changes — it already generically writes any non-`None`, non-`"***"` field from the payload to `.env`.

- [ ] **Step 3: Verify**

Run:
```bash
python -c "
import ast
ast.parse(open('api/main.py', encoding='utf-8').read())
import api.main as m
fields = set(m.SettingsPayload.model_fields.keys())
assert 'INSTAGRAM_ACCESS_TOKEN' in fields
assert 'R2_BUCKET_NAME' in fields
print('OK')
"
```
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add api/main.py
git commit -m "feat: expose Instagram/R2 credentials through the settings API"
```

---

### Task 7: Dashboard types + API client methods

**Files:**
- Modify: `dashboard/lib/types.ts`
- Modify: `dashboard/lib/api.ts`

**Interfaces:**
- Produces: `InstagramPost` type; `api.instagramPosts()`, `api.retryInstagramPost(id)`, `api.runInstagramNow()`, extended `Settings` type with the 9 new fields — all consumed by Task 8's `InstagramPanel.tsx`.

- [ ] **Step 1: Add the `InstagramPost` type and extend `Settings`**

In `dashboard/lib/types.ts`, add at the end:

```ts
export interface InstagramPost {
  id: string;
  video_path: string;
  caption: string;
  publish_at_utc: string;
  status: "pending" | "posted" | "failed";
  error: string | null;
  instagram_media_id: string | null;
}
```

Find:
```ts
export interface Settings {
  ANTHROPIC_API_KEY: string;
  PEXELS_API_KEY: string;
  KEEP_OUTPUT_DAYS: string;
  upload_slots: string[];
}
```
Replace with:
```ts
export interface Settings {
  ANTHROPIC_API_KEY: string;
  PEXELS_API_KEY: string;
  KEEP_OUTPUT_DAYS: string;
  INSTAGRAM_APP_ID: string;
  INSTAGRAM_APP_SECRET: string;
  INSTAGRAM_ACCESS_TOKEN: string;
  INSTAGRAM_PAGE_ID: string;
  INSTAGRAM_BUSINESS_ACCOUNT_ID: string;
  R2_ACCOUNT_ID: string;
  R2_ACCESS_KEY_ID: string;
  R2_SECRET_ACCESS_KEY: string;
  R2_BUCKET_NAME: string;
  upload_slots: string[];
}
```

- [ ] **Step 2: Add API client methods**

In `dashboard/lib/api.ts`, add near the top (after the existing imports/consts, before `function fetchWithTimeout`):
```ts
import type { InstagramPost } from "./types";
```

Find the `export const api = { ... }` object and add these three lines inside it (anywhere among the other entries, e.g. right after the `shortScript` line):
```ts
  instagramPosts:     ()               => get<{ posts: InstagramPost[] }>("/api/instagram/posts"),
  retryInstagramPost: (id: string)     => post(`/api/instagram/posts/${id}/retry`),
  runInstagramNow:    ()               => post<{ ok: boolean; posted: number; failed: number }>("/api/instagram/run"),
```

- [ ] **Step 3: Verify the dashboard still type-checks**

Run:
```bash
cd dashboard && npx tsc --noEmit
```
Expected: no new errors referencing `InstagramPost`, `instagramPosts`, `retryInstagramPost`, or `runInstagramNow` (pre-existing unrelated errors, if any, are out of scope for this change).

- [ ] **Step 4: Commit**

```bash
git add dashboard/lib/types.ts dashboard/lib/api.ts
git commit -m "feat: add Instagram post type and API client methods"
```

---

### Task 8: `InstagramPanel.tsx` dashboard component

**Files:**
- Create: `dashboard/components/InstagramPanel.tsx`

**Interfaces:**
- Consumes: `api.instagramPosts()`, `api.retryInstagramPost(id)`, `api.runInstagramNow()` (Task 7); `InstagramPost` type (Task 7); existing CSS classes `glass`, `badge-pending`, `badge-uploaded`, `badge-failed` (already defined in `dashboard/app/globals.css`, used by `ShortsPanel.tsx`/`CommunityPanel.tsx`).
- Produces: default-exported `InstagramPanel` component — consumed by Task 9's `page.tsx`.

- [ ] **Step 1: Create the component**

Create `dashboard/components/InstagramPanel.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { InstagramPost } from "@/lib/types";
import { Instagram, RefreshCw, Sparkles, Clock, CheckCircle, XCircle } from "lucide-react";

function StatusBadge({ status }: { status: InstagramPost["status"] }) {
  const map: Record<string, { cls: string; label: string; icon: React.ReactNode }> = {
    pending: { cls: "badge-pending",  label: "Pending", icon: <Clock size={11} /> },
    posted:  { cls: "badge-uploaded", label: "Posted",  icon: <CheckCircle size={11} /> },
    failed:  { cls: "badge-failed",   label: "Failed",  icon: <XCircle size={11} /> },
  };
  const { cls, label, icon } = map[status] ?? { cls: "badge-pending", label: status, icon: null };
  return (
    <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium ${cls}`}>
      {icon}{label}
    </span>
  );
}

function PostCard({ post, onRetried }: { post: InstagramPost; onRetried: () => void }) {
  const [retrying, setRetrying] = useState(false);

  const handleRetry = async () => {
    setRetrying(true);
    try {
      await api.retryInstagramPost(post.id);
      onRetried();
    } finally {
      setRetrying(false);
    }
  };

  const targetLocal = new Date(post.publish_at_utc).toLocaleString();

  return (
    <div className="glass rounded-2xl p-5 space-y-3" style={{ border: "1px solid var(--border)" }}>
      <div className="flex items-center justify-between gap-2">
        <StatusBadge status={post.status} />
        <span className="text-xs" style={{ color: "var(--muted)" }}>{targetLocal}</span>
      </div>
      <p className="text-sm text-white whitespace-pre-wrap leading-relaxed">{post.caption}</p>
      {post.status === "failed" && post.error && (
        <p className="text-xs" style={{ color: "#f87171" }}>{post.error}</p>
      )}
      {post.status === "failed" && (
        <button
          onClick={handleRetry}
          disabled={retrying}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium w-full justify-center transition-all disabled:opacity-50"
          style={{ background: "rgba(79,195,247,0.1)", border: "1px solid rgba(79,195,247,0.25)", color: "#4FC3F7" }}
        >
          <RefreshCw size={12} className={retrying ? "animate-spin" : ""} />
          {retrying ? "Retrying…" : "Retry"}
        </button>
      )}
    </div>
  );
}

export default function InstagramPanel() {
  const [posts, setPosts]     = useState<InstagramPost[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [msg, setMsg]         = useState<{ text: string; ok: boolean } | null>(null);

  const refresh = () =>
    api.instagramPosts()
      .then((r) => setPosts(r.posts))
      .catch(() => {})
      .finally(() => setLoading(false));

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 15000);
    return () => clearInterval(id);
  }, []);

  const handleRunNow = async () => {
    setRunning(true);
    setMsg(null);
    try {
      const res = await api.runInstagramNow();
      setMsg({ text: `Pass complete — ${res.posted} posted, ${res.failed} failed.`, ok: true });
      refresh();
    } catch {
      setMsg({ text: "Failed to reach API", ok: false });
    } finally {
      setRunning(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="w-6 h-6 border-2 border-cyan-DEFAULT border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  const pending = posts.filter((p) => p.status === "pending").length;
  const failed  = posts.filter((p) => p.status === "failed").length;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Instagram Reels</h1>
        <p className="text-sm mt-1" style={{ color: "var(--muted)" }}>
          {pending} queued · {failed} failed — cross-posted automatically from your YouTube Shorts
        </p>
      </div>

      <button
        onClick={handleRunNow}
        disabled={running}
        className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-semibold transition-all disabled:opacity-50"
        style={{
          background: "linear-gradient(135deg, rgba(79,195,247,0.2) 0%, rgba(124,58,237,0.2) 100%)",
          border: "1px solid var(--border-strong)",
          color: "#4FC3F7",
        }}
      >
        {running ? (
          <div className="w-3 h-3 border border-cyan-400 border-t-transparent rounded-full animate-spin" />
        ) : (
          <Sparkles size={13} />
        )}
        {running ? "Running…" : "Post due Reels now"}
      </button>
      {msg && <p className="text-xs" style={{ color: msg.ok ? "#4ade80" : "#f87171" }}>{msg.text}</p>}

      {posts.length === 0 ? (
        <div className="glass rounded-2xl p-12 text-center" style={{ borderStyle: "dashed", borderColor: "rgba(79,195,247,0.15)" }}>
          <Instagram size={28} className="mx-auto mb-3" style={{ color: "rgba(79,195,247,0.3)" }} />
          <p className="text-sm" style={{ color: "var(--muted)" }}>
            No Reels queued yet. New entries appear here automatically whenever a YouTube Short is generated.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {posts.slice().reverse().map((p) => (
            <PostCard key={p.id} post={p} onRetried={refresh} />
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify it type-checks**

Run:
```bash
cd dashboard && npx tsc --noEmit
```
Expected: no new errors referencing `InstagramPanel.tsx`.

- [ ] **Step 3: Commit**

```bash
git add dashboard/components/InstagramPanel.tsx
git commit -m "feat: add InstagramPanel dashboard component"
```

---

### Task 9: Wire the Instagram tab into navigation

**Files:**
- Modify: `dashboard/components/Sidebar.tsx`
- Modify: `dashboard/app/page.tsx`

**Interfaces:**
- Consumes: `InstagramPanel` default export (Task 8).

- [ ] **Step 1: Add the tab to `Sidebar.tsx`**

Find:
```tsx
import {
  LayoutDashboard, ListTodo, Film, ScrollText,
  CalendarClock, Settings, Zap, BarChart2, PlaySquare,
  Upload, Target, X, Sparkles,
} from "lucide-react";
```
Replace with:
```tsx
import {
  LayoutDashboard, ListTodo, Film, ScrollText,
  CalendarClock, Settings, Zap, BarChart2, PlaySquare,
  Upload, Target, X, Sparkles, Instagram,
} from "lucide-react";
```

Find:
```tsx
const NAV: { id: Tab; label: string; icon: React.ReactNode }[] = [
  { id: "overview",   label: "Overview",   icon: <LayoutDashboard size={18} /> },
  { id: "analytics",  label: "Analytics",  icon: <BarChart2 size={18} /> },
  { id: "topics",     label: "Topics",     icon: <ListTodo size={18} /> },
  { id: "videos",     label: "Videos",     icon: <Film size={18} /> },
  { id: "shorts",     label: "Shorts",     icon: <Sparkles size={18} /> },
  { id: "upload",     label: "Upload",     icon: <Upload size={18} /> },
  { id: "logs",       label: "Logs",       icon: <ScrollText size={18} /> },
  { id: "schedule",   label: "Schedule",   icon: <CalendarClock size={18} /> },
  { id: "settings",   label: "Settings",   icon: <Settings size={18} /> },
];
```
Replace with:
```tsx
const NAV: { id: Tab; label: string; icon: React.ReactNode }[] = [
  { id: "overview",   label: "Overview",   icon: <LayoutDashboard size={18} /> },
  { id: "analytics",  label: "Analytics",  icon: <BarChart2 size={18} /> },
  { id: "topics",     label: "Topics",     icon: <ListTodo size={18} /> },
  { id: "videos",     label: "Videos",     icon: <Film size={18} /> },
  { id: "shorts",     label: "Shorts",     icon: <Sparkles size={18} /> },
  { id: "instagram",  label: "Instagram",  icon: <Instagram size={18} /> },
  { id: "upload",     label: "Upload",     icon: <Upload size={18} /> },
  { id: "logs",       label: "Logs",       icon: <ScrollText size={18} /> },
  { id: "schedule",   label: "Schedule",   icon: <CalendarClock size={18} /> },
  { id: "settings",   label: "Settings",   icon: <Settings size={18} /> },
];
```

- [ ] **Step 2: Add the tab to `page.tsx`**

Find:
```tsx
import ShortsPanel from "@/components/ShortsPanel";
```
Replace with:
```tsx
import ShortsPanel from "@/components/ShortsPanel";
import InstagramPanel from "@/components/InstagramPanel";
```

Find:
```tsx
export type Tab = "overview" | "analytics" | "topics" | "videos" | "shorts" | "upload" | "logs" | "schedule" | "settings";
```
Replace with:
```tsx
export type Tab = "overview" | "analytics" | "topics" | "videos" | "shorts" | "instagram" | "upload" | "logs" | "schedule" | "settings";
```

Find:
```tsx
          {tab === "shorts"     && <ShortsPanel />}
```
Replace with:
```tsx
          {tab === "shorts"     && <ShortsPanel />}
          {tab === "instagram"  && <InstagramPanel />}
```

- [ ] **Step 3: Verify it type-checks and builds**

Run:
```bash
cd dashboard && npx tsc --noEmit
```
Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add dashboard/components/Sidebar.tsx dashboard/app/page.tsx
git commit -m "feat: add Instagram tab to dashboard navigation"
```

---

### Task 10: One-time Meta token setup script + setup doc

**Files:**
- Create: `setup_instagram_auth.py`
- Create: `INSTAGRAM_SETUP.md`

**Interfaces:**
- Consumes: nothing from earlier tasks (standalone script, reads credentials interactively from the terminal and writes to `.env`).
- Produces: `.env` entries `INSTAGRAM_APP_ID`, `INSTAGRAM_APP_SECRET`, `INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_PAGE_ID`, `INSTAGRAM_BUSINESS_ACCOUNT_ID` — consumed at runtime by Task 1's `config.py` values.

- [ ] **Step 1: Create `setup_instagram_auth.py`**

```python
"""
One-time Instagram Graph API token setup.

Usage:
  python setup_instagram_auth.py

Prerequisites (do these once in a browser first — see INSTAGRAM_SETUP.md):
  1. Instagram account converted to Business/Creator, linked to a Facebook Page.
  2. A Meta Developer app created, with the Instagram Graph API product added,
     and your account added as an Instagram Tester (a Development Mode
     requirement — only tester accounts can be posted to before App Review).
  3. A short-lived User Access Token generated via Graph API Explorer
     (developers.facebook.com/tools/explorer) with these permissions:
     instagram_basic, instagram_content_publish, pages_show_list,
     pages_read_engagement.

This script exchanges that short-lived token for a long-lived one (~60 days),
looks up your Facebook Page ID and linked Instagram Business Account ID, and
writes all 5 values into .env. Re-run it every ~60 days to refresh the token.
"""
from pathlib import Path

import requests

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"
ENV_FILE = Path(__file__).parent / ".env"


def _exchange_long_lived_token(app_id: str, app_secret: str, short_token: str) -> str:
    resp = requests.get(
        f"{GRAPH_API_BASE}/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": short_token,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _find_page_and_ig_account(long_token: str) -> tuple[str, str]:
    resp = requests.get(
        f"{GRAPH_API_BASE}/me/accounts",
        params={"access_token": long_token},
        timeout=30,
    )
    resp.raise_for_status()
    pages = resp.json().get("data", [])
    if not pages:
        raise RuntimeError("No Facebook Pages found for this account/token.")
    page_id = pages[0]["id"]

    resp = requests.get(
        f"{GRAPH_API_BASE}/{page_id}",
        params={"fields": "instagram_business_account", "access_token": long_token},
        timeout=30,
    )
    resp.raise_for_status()
    ig_account = resp.json().get("instagram_business_account")
    if not ig_account:
        raise RuntimeError(
            f"Page {page_id} has no linked Instagram Business account. "
            "Re-check the Facebook Page link in Instagram's "
            "'Professional account' settings (see INSTAGRAM_SETUP.md)."
        )
    return page_id, ig_account["id"]


def _write_env(updates: dict) -> None:
    existing = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                existing[k.strip()] = v.strip()
    existing.update(updates)
    ENV_FILE.write_text("\n".join(f"{k}={v}" for k, v in existing.items()) + "\n", encoding="utf-8")


if __name__ == "__main__":
    print("Instagram Graph API one-time setup")
    print("(See INSTAGRAM_SETUP.md if you haven't completed the browser steps yet.)\n")

    app_id      = input("Meta App ID: ").strip()
    app_secret  = input("Meta App Secret: ").strip()
    short_token = input("Short-lived User Access Token (from Graph API Explorer): ").strip()

    print("\nExchanging for a long-lived token...")
    long_token = _exchange_long_lived_token(app_id, app_secret, short_token)
    print("[ok] Long-lived token obtained (valid ~60 days).")

    print("Looking up your Facebook Page and linked Instagram Business account...")
    page_id, ig_account_id = _find_page_and_ig_account(long_token)
    print(f"[ok] Page ID: {page_id}")
    print(f"[ok] Instagram Business Account ID: {ig_account_id}")

    _write_env({
        "INSTAGRAM_APP_ID": app_id,
        "INSTAGRAM_APP_SECRET": app_secret,
        "INSTAGRAM_ACCESS_TOKEN": long_token,
        "INSTAGRAM_PAGE_ID": page_id,
        "INSTAGRAM_BUSINESS_ACCOUNT_ID": ig_account_id,
    })
    print("\nAll 5 values written to .env. Instagram Reels automation is ready")
    print("(assuming R2_* values are also set — see INSTAGRAM_SETUP.md).")
    print("Note: the long-lived token expires in ~60 days — re-run this script to refresh it.")
```

- [ ] **Step 2: Create `INSTAGRAM_SETUP.md`**

```markdown
# Instagram Reels Automation — One-Time Setup

Two independent things need setting up before Instagram cross-posting works:
(1) a Meta Developer app + Instagram Business account, (2) a Cloudflare R2
bucket for temporary video hosting. Both are free.

## Part 1: Instagram / Meta

1. **Convert Instagram to a Business/Creator account**: Instagram app → your
   profile → menu → Settings and privacy → **Professional account** → switch
   to Business or Creator.
2. **Link it to a Facebook Page**: from that same Professional account
   screen, connect (or create) a Facebook Page. If you don't have one:
   facebook.com/pages/create.
3. **Create a Meta Developer app**: developers.facebook.com/apps → Create App
   → type "Other" → use case "Business" → name it anything.
4. **Add the Instagram product**: in the app dashboard, Add Product →
   Instagram (Graph API) → Set up. Note the **App ID** and **App Secret**
   under App Settings → Basic.
5. **Add yourself as an Instagram Tester** (required while the app is in
   Development Mode — only tester accounts can be posted to before Meta's
   App Review): App Roles → Roles → Add People → Instagram Tester → your IG
   account. Then, in Instagram: Settings and privacy → Apps and websites →
   Tester Invites → accept.
6. **Generate a token**: Graph API Explorer
   (developers.facebook.com/tools/explorer) → select your app + Page →
   request permissions `instagram_basic`, `instagram_content_publish`,
   `pages_show_list`, `pages_read_engagement` → Generate Access Token.
7. Run `python setup_instagram_auth.py` and paste in the App ID, App Secret,
   and the token from step 6 — it handles the long-lived token exchange and
   writes everything to `.env` automatically.

## Part 2: Cloudflare R2 (temporary video hosting)

Instagram's API needs a public URL per video; R2's free tier (10GB storage,
no egress fees) covers this easily at this project's volume.

1. Sign up at dash.cloudflare.com (free) → enable R2 from the sidebar.
2. Create a bucket (e.g. `reels-temp`).
3. R2 → Manage API Tokens → Create API Token → permissions "Object Read &
   Write", scoped to that bucket → note the **Access Key ID** and **Secret
   Access Key** shown (only shown once).
4. Note your **Account ID** (shown in the R2 dashboard sidebar).
5. Add these 4 values to `.env` (or paste them into the dashboard's Instagram
   tab settings once built): `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`,
   `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`.

No public bucket access or custom domain is needed — the pipeline generates
a short-lived presigned URL per upload, valid for 1 hour, which is deleted
right after Instagram finishes processing the video.
```

- [ ] **Step 3: Verify the script at least imports and its functions are structurally sound**

Run:
```bash
python -c "import ast; ast.parse(open('setup_instagram_auth.py', encoding='utf-8').read()); print('OK: parses')"
```
Expected: `OK: parses`

(A full live run requires real Meta credentials from Part 1 above and can't be automated here — the user runs it manually once they've completed the browser steps.)

- [ ] **Step 4: Commit**

```bash
git add setup_instagram_auth.py INSTAGRAM_SETUP.md
git commit -m "feat: add Instagram token setup script and manual setup guide"
```

---

### Task 11: End-to-end manual verification

**Files:** none (verification only)

- [ ] **Step 1: Start both servers**

```bash
uvicorn api.main:app --reload --port 8000
```
(in a second terminal)
```bash
cd dashboard && npm run dev
```

- [ ] **Step 2: Confirm the Instagram tab renders**

Open the dashboard in a browser, log in, click the new **Instagram** tab. Expected: "No Reels queued yet." empty state (queue starts empty).

- [ ] **Step 3: Confirm a Short generation enqueues a Reel**

Trigger a single Short generation from the dashboard's Shorts tab (or `python scheduler.py --now` for a full run). After it completes, check `instagram_queue.json` was created in the project root with one `pending` entry, and refresh the Instagram tab — the entry should now appear with a "Pending" badge and the correct target time.

- [ ] **Step 4: Confirm the manual "run now" path works without real credentials configured**

Click **"Post due Reels now"** in the Instagram tab (with `INSTAGRAM_ACCESS_TOKEN`/R2 values still unset in `.env`). Expected: the entry flips to "Failed" with an error message about missing credentials (e.g. a 400 from the Graph API or a boto3 auth error) — confirming the failure path surfaces in the dashboard without crashing the pipeline or the API server.

- [ ] **Step 5: (Once real Meta + R2 credentials are set via `setup_instagram_auth.py` + `.env`) Confirm a real post succeeds**

Click **Retry** on the failed entry (or wait for its scheduled time and let the background poller pick it up). Expected: entry flips to "Posted", and the Reel appears on the linked Instagram account within a minute or two.
