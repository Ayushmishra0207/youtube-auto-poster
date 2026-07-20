"""
Post-upload engagement automation, run on a poll loop (see api/main.py):

  1. Auto-post a localized CTA comment on every video/Short that has been
     uploaded to YouTube but hasn't been commented on yet (real, supported
     API — pipeline.uploader.post_engagement_comment).
  2. Keep a rolling queue of draft Community-post captions generated from
     the most recent upload (pipeline.community_post) — YouTube's
     Community tab has no public API, so these are for a human to copy
     into YouTube Studio, not auto-published.

State (which items were already commented on, and the draft queue) persists
in ENGAGEMENT_STATE_FILE so a restart doesn't re-comment or lose drafts.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from config import BASE_DIR, ENGAGEMENT_AUTO_COMMENT, ENGAGEMENT_MAX_DRAFTS, OUTPUT_DIR
from pipeline.locales import get_locale
from pipeline.logger import log
from pipeline.uploader import post_engagement_comment

ENGAGEMENT_STATE_FILE = BASE_DIR / "engagement_state.json"


def _load_state() -> dict:
    if ENGAGEMENT_STATE_FILE.exists():
        try:
            return json.loads(ENGAGEMENT_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            log.warning("engagement_state.json unreadable — starting fresh")
    return {"commented": [], "drafts": []}


def _save_state(state: dict) -> None:
    ENGAGEMENT_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _iter_uploaded_items():
    """Yield (kind, key, item_dir) for every video_NN/short_NN dir with a real youtube_id.txt."""
    out = Path(OUTPUT_DIR)
    if not out.exists():
        return
    for date_dir in sorted(p for p in out.iterdir() if p.is_dir()):
        for item_dir in sorted(p for p in date_dir.iterdir() if p.is_dir()):
            if not (item_dir / "youtube_id.txt").exists():
                continue
            if item_dir.name.startswith("video_"):
                kind = "video"
            elif item_dir.name.startswith("short_"):
                kind = "short"
            else:
                continue
            yield kind, f"{date_dir.name}/{item_dir.name}", item_dir


def _read_script(item_dir: Path) -> dict:
    p = item_dir / "script.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def run_engagement_pass() -> dict:
    """One pass: post any missing CTA comments, then top up the draft queue. Returns a summary."""
    state = _load_state()
    commented = set(state.get("commented", []))
    drafts = state.get("drafts", [])
    posted_now = 0
    latest = None  # (kind, key, item_dir, script) — most recent upload seen this pass

    for kind, key, item_dir in _iter_uploaded_items():
        script = _read_script(item_dir)
        locale = get_locale(script.get("_locale") or "hi")
        latest = (kind, key, item_dir, script)

        if key in commented:
            continue
        if not ENGAGEMENT_AUTO_COMMENT:
            continue

        yt_id = (item_dir / "youtube_id.txt").read_text().strip()
        if not yt_id:
            continue

        comment_text = f"{locale.like_share_cta} \U0001F4AC"  # speech-balloon emoji
        if post_engagement_comment(yt_id, comment_text):
            commented.add(key)
            posted_now += 1

    state["commented"] = sorted(commented)

    # Top up the draft queue from the single most recent upload, if it doesn't
    # already have a pending draft and we're under the cap.
    if latest and len(drafts) < ENGAGEMENT_MAX_DRAFTS:
        kind, key, item_dir, script = latest
        already_drafted = any(d.get("source") == key for d in drafts)
        title = script.get("title", "")
        if not already_drafted and title:
            try:
                from pipeline.community_post import generate_community_post
                locale = get_locale(script.get("_locale") or "hi")
                draft = generate_community_post(title, script.get("description", ""), locale=locale)
                drafts.append({
                    "id": f"{key.replace('/', '-')}",
                    "text": draft.get("text", ""),
                    "hashtags": draft.get("hashtags", []),
                    "source": key,
                    "kind": kind,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
                log.info("Community post draft generated for %s", key)
            except Exception as exc:
                log.warning("Community post draft generation failed for %s: %s", key, exc)

    state["drafts"] = drafts[-ENGAGEMENT_MAX_DRAFTS:]
    _save_state(state)
    return {"posted_comments": posted_now, "draft_count": len(state["drafts"])}


def dismiss_draft(draft_id: str) -> bool:
    """Remove a draft from the queue (after it's been posted manually, or to discard it)."""
    state = _load_state()
    before = len(state.get("drafts", []))
    state["drafts"] = [d for d in state.get("drafts", []) if d.get("id") != draft_id]
    _save_state(state)
    return len(state["drafts"]) < before


def list_drafts() -> list:
    return _load_state().get("drafts", [])
