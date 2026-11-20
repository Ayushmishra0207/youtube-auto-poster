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
via pipeline.state_store ("engagement_state.json" locally, the app_state table
in the cloud) so a restart doesn't re-comment or lose drafts.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from config import ENGAGEMENT_AUTO_COMMENT, ENGAGEMENT_MAX_DRAFTS, OUTPUT_DIR
from pipeline import media_store, state_store
from pipeline.locales import get_locale
from pipeline.logger import log
from pipeline.uploader import post_engagement_comment

STATE_KEY = "engagement_state.json"
_DEFAULT_STATE = {"commented": [], "drafts": []}


def _load_state() -> dict:
    state = state_store.load(STATE_KEY, _DEFAULT_STATE)
    return state if isinstance(state, dict) else dict(_DEFAULT_STATE)


def _iter_uploaded():
    """Yield (kind, key, youtube_id, script) for every uploaded video/Short."""
    if media_store.enabled():   # cloud: outputs live in the index, not on this disk
        for it in media_store.list_items():
            if it.get("youtube_id"):
                key = f"{it['date']}/{it['kind']}_{it['index']:02d}"
                yield it["kind"], key, it["youtube_id"], it.get("script") or {}
        return
    for kind, key, item_dir in _iter_uploaded_items():
        yield kind, key, (item_dir / "youtube_id.txt").read_text().strip(), _read_script(item_dir)


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
    newly_commented: set[str] = set()
    new_draft = None
    latest = None  # (kind, key, script) — most recent upload seen this pass

    for kind, key, yt_id, script in _iter_uploaded():
        locale = get_locale(script.get("_locale") or "hi")
        latest = (kind, key, script)

        if key in commented or not ENGAGEMENT_AUTO_COMMENT or not yt_id:
            continue

        comment_text = f"{locale.like_share_cta} 💬"  # speech-balloon emoji
        if post_engagement_comment(yt_id, comment_text):
            newly_commented.add(key)

    # Top up the draft queue from the single most recent upload, if it doesn't
    # already have a pending draft and we're under the cap.
    if latest and len(drafts) < ENGAGEMENT_MAX_DRAFTS:
        kind, key, script = latest
        already_drafted = any(d.get("source") == key for d in drafts)
        title = script.get("title", "")
        if not already_drafted and title:
            try:
                from pipeline.community_post import generate_community_post
                locale = get_locale(script.get("_locale") or "hi")
                draft = generate_community_post(title, script.get("description", ""), locale=locale)
                new_draft = {
                    "id": f"{key.replace('/', '-')}",
                    "text": draft.get("text", ""),
                    "hashtags": draft.get("hashtags", []),
                    "source": key,
                    "kind": kind,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                log.info("Community post draft generated for %s", key)
            except Exception as exc:
                log.warning("Community post draft generation failed for %s: %s", key, exc)

    # Merge into the *current* state: the pass took a while (comments, an LLM call)
    # and a draft may have been dismissed meanwhile — don't resurrect it.
    def apply(st: dict) -> int:
        st["commented"] = sorted(set(st.get("commented", [])) | newly_commented)
        ds = st.setdefault("drafts", [])
        if new_draft and not any(d.get("source") == new_draft["source"] for d in ds):
            ds.append(new_draft)
        st["drafts"] = ds[-ENGAGEMENT_MAX_DRAFTS:]
        return len(st["drafts"])

    draft_count = state_store.mutate(STATE_KEY, apply, _DEFAULT_STATE)
    return {"posted_comments": len(newly_commented), "draft_count": draft_count}


def dismiss_draft(draft_id: str) -> bool:
    """Remove a draft from the queue (after it's been posted manually, or to discard it)."""
    def apply(st: dict) -> bool:
        before = len(st.get("drafts", []))
        st["drafts"] = [d for d in st.get("drafts", []) if d.get("id") != draft_id]
        return len(st["drafts"]) < before
    return state_store.mutate(STATE_KEY, apply, _DEFAULT_STATE)


def list_drafts() -> list:
    return _load_state().get("drafts", [])
