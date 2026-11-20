"""
Persistent queue for Instagram Reel posts, polled by api/main.py's
_instagram_loop(). Mirrors pipeline/engagement.py's state-file pattern:
Instagram's Graph API has no native "publish later" (unlike YouTube's
publishAt), so each Short is enqueued here right after its YouTube upload
(scheduler.py), and a background poller publishes it once the same slot
time arrives.
"""
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from config import OUTPUT_DIR
from pipeline import state_store
from pipeline.logger import log

QUEUE_KEY = "instagram_queue.json"     # state_store: file locally, app_state row in the cloud
_DEFAULT = {"posts": []}


def _load_state() -> dict:
    st = state_store.load(QUEUE_KEY, _DEFAULT)
    return st if isinstance(st, dict) else {"posts": []}


def _mutate(fn):
    """Re-read → change → save atomically (row lock in the cloud, file lock locally).
    The scheduler (enqueue) and the poller (run_pending_posts, which spends minutes
    publishing) used to each save their own stale copy, dropping newly queued Reels."""
    return state_store.mutate(QUEUE_KEY, fn, _DEFAULT)


def _cloud_ref(video_path: str) -> str:
    """In the cloud the worker's disk is gone by publish time — reference the
    Short's copy in Supabase Storage ("media:<key>") instead of a local path."""
    from pipeline import media_store
    if not media_store.enabled():
        return str(video_path)
    p = Path(video_path).resolve()
    try:
        rel = p.relative_to(Path(OUTPUT_DIR).resolve())   # <date>/short_NN/short.mp4
    except ValueError:
        return str(video_path)
    date, folder = rel.parts[0], rel.parts[1]
    kind, _, num = folder.partition("_")
    item = media_store.get_item(date, kind, int(num)) if num.isdigit() else None
    return f"media:{item['preview_key']}" if item and item.get("preview_key") else str(video_path)


def _local_video(video_path: str, tmpdir: str) -> str:
    if video_path.startswith("media:"):
        from pipeline import media_store
        return str(media_store.download(video_path[len("media:"):], Path(tmpdir) / "reel.mp4"))
    return video_path


def enqueue(video_path: str, caption: str, publish_at_utc: datetime) -> str:
    """Queue a Reel for posting once publish_at_utc arrives. Returns the entry id."""
    entry_id = uuid.uuid4().hex[:12]
    _mutate(lambda state: state.setdefault("posts", []).append({
        "id": entry_id,
        "video_path": _cloud_ref(video_path),
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
            with tempfile.TemporaryDirectory() as td:
                media_id = publish_reel(_local_video(p["video_path"], td), p["caption"])
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
