"""
Persistent queue for Instagram Reel posts, polled by api/main.py's
_instagram_loop(). Mirrors pipeline/engagement.py's state-file pattern:
Instagram's Graph API has no native "publish later" (unlike YouTube's
publishAt), so each Short is enqueued here right after its YouTube upload
(scheduler.py), and a background poller publishes it once the same slot
time arrives.
"""
import json
import os
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
    # Atomic: a reader must never see a half-written file
    tmp = INSTAGRAM_QUEUE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, INSTAGRAM_QUEUE_FILE)


_QUEUE_LOCK = INSTAGRAM_QUEUE_FILE.with_name("instagram_queue.lock")


def _mutate(fn):
    """Re-read → change → save under a cross-process lock. The scheduler (enqueue)
    and the API's poller (run_pending_posts, which spends minutes publishing)
    used to each save their own stale copy, silently dropping newly queued Reels."""
    from pipeline import locking
    if not locking.acquire_wait(_QUEUE_LOCK, timeout_s=60, poll_s=0.2):
        raise RuntimeError("instagram_queue.json is locked by another process")
    try:
        state = _load_state()
        result = fn(state)
        _save_state(state)
        return result
    finally:
        locking.release(_QUEUE_LOCK)


def enqueue(video_path: str, caption: str, publish_at_utc: datetime) -> str:
    """Queue a Reel for posting once publish_at_utc arrives. Returns the entry id."""
    entry_id = uuid.uuid4().hex[:12]
    _mutate(lambda state: state.setdefault("posts", []).append({
        "id": entry_id,
        "video_path": str(video_path),
        "caption": caption,
        "publish_at_utc": publish_at_utc.astimezone(timezone.utc).isoformat(),
        "status": "pending",
        "error": None,
        "instagram_media_id": None,
    }))
    log.info("Instagram Reel queued (%s), publishes at %s", entry_id, publish_at_utc)
    return entry_id


def list_posts() -> list:
    return _load_state().get("posts", [])


def retry_post(entry_id: str) -> bool:
    """Reset a failed entry back to pending so the next poll retries it."""
    def reset(state):
        for p in state.get("posts", []):
            if p["id"] == entry_id and p["status"] == "failed":
                p["status"] = "pending"
                p["error"] = None
                return True
        return False
    return _mutate(reset)


def run_pending_posts() -> dict:
    """One pass: publish any pending entry whose publish_at_utc has arrived.
    Never raises — a failed post is recorded on its own entry and skipped,
    so it can't block the rest of the queue or the caller's loop.

    No-ops (leaving all entries as "pending") if Instagram/R2 credentials
    aren't configured, so this never breaks the pipeline for someone who
    hasn't done the Meta setup yet."""
    import config

    state = _load_state()

    if not (
        config.INSTAGRAM_ACCESS_TOKEN
        and config.INSTAGRAM_BUSINESS_ACCOUNT_ID
        and config.R2_ACCOUNT_ID
        and config.R2_ACCESS_KEY_ID
        and config.R2_SECRET_ACCESS_KEY
        and config.R2_BUCKET_NAME
    ):
        pending_count = sum(1 for p in state.get("posts", []) if p["status"] == "pending")
        log.info(
            "Instagram/R2 credentials not configured — skipping %d pending Reel(s)",
            pending_count,
        )
        return {"posted": 0, "failed": 0}

    from pipeline.instagram_uploader import publish_reel  # lazy: avoids importing
                                                            # boto3/requests at module
                                                            # load if Instagram isn't configured
    now = datetime.now(timezone.utc)
    posted, failed = 0, 0

    for p in state.get("posts", []):
        if p["status"] != "pending":
            continue
        target = datetime.fromisoformat(p["publish_at_utc"])
        if target > now:
            continue
        try:
            media_id = publish_reel(p["video_path"], p["caption"])
            _set_entry(p["id"], status="posted", instagram_media_id=media_id, error=None)
            posted += 1
            log.info("Instagram Reel posted (%s) -> media id %s", p["id"], media_id)
        except Exception as exc:
            _set_entry(p["id"], status="failed", error=str(exc))
            failed += 1
            log.error("Instagram Reel %s failed: %s", p["id"], exc)

    return {"posted": posted, "failed": failed}


def _set_entry(entry_id: str, **fields) -> None:
    """Update one entry by id on a fresh read (see _mutate)."""
    def apply(state):
        for e in state.get("posts", []):
            if e["id"] == entry_id:
                e.update(fields)
    _mutate(apply)
