"""
Vibe-matched background music. Checks a local curated pool first (one
subfolder per vibe-tag combo under assets/music/pool/, e.g. hand-picked
news tracks) and picks a random track from it each call, so repeated
renders don't all get the identical clip. Falls back to the Jamendo API
(free, royalty-free tracks — https://developer.jamendo.com, get a free
client_id) if no pool exists for that vibe. If Jamendo isn't configured
(or fails), falls back further to a random track from ANY vibe pool on
disk, so every category still gets real royalty-free music instead of
none — only returns None if assets/music/pool/ has no tracks at all.
"""
import os
import random

import requests

from config import BG_MUSIC_DIR, CATEGORY_MUSIC_TAGS, DEFAULT_MUSIC_TAGS, JAMENDO_CLIENT_ID
from pipeline.logger import log
from pipeline.retry import with_retry

_JAMENDO_API = "https://api.jamendo.com/v3.0/tracks/"
_TIMEOUT = 15


@with_retry(max_attempts=2, base_delay=2.0, exceptions=(requests.exceptions.RequestException,))
def _fetch_jamendo_track(tags: str, output_path: str) -> str | None:
    resp = requests.get(
        _JAMENDO_API,
        params={
            "client_id": JAMENDO_CLIENT_ID,
            "format": "json",
            "limit": 5,
            "tags": tags,
            "audioformat": "mp32",
            "boost": "popularity_total",
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    tracks = resp.json().get("results", [])
    if not tracks:
        return None
    url = tracks[0].get("audio")
    if not url:
        return None

    audio_resp = requests.get(url, timeout=30)
    audio_resp.raise_for_status()
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(audio_resp.content)
    return output_path


def _pool_dir_for_tags(tags: str):
    """Local curated-track pool, shared by every category with the same vibe tags."""
    return BG_MUSIC_DIR / "pool" / tags.replace(",", "_")


def _random_track_from_any_pool() -> str | None:
    """
    Random pick from ALL tracks across every vibe subfolder under
    assets/music/pool/, regardless of category. Used when a category has
    no dedicated vibe pool (and no Jamendo key to fetch one) — so every
    video still gets real, royalty-free background music instead of
    silently playing none.
    """
    pool_root = BG_MUSIC_DIR / "pool"
    if not pool_root.is_dir():
        return None
    all_tracks = list(pool_root.glob("*/*.mp3"))
    return str(random.choice(all_tracks)) if all_tracks else None


def get_music_for_category(category: str) -> str | None:
    """
    Return a local file path to a background-music track matching the
    content category's vibe.

    1. Local curated pool (assets/music/pool/<tags>/*.mp3) — random pick
       each call if any tracks were manually placed there.
    2. Jamendo API — downloads + caches one track per category on first
       use (reused every time after), if a pool track wasn't found.
    3. Any track from any other vibe pool on disk — a random real
       royalty-free track beats no music at all for a category that has
       neither its own pool nor a configured Jamendo key.

    Returns None only if there's no local pool at all and Jamendo is
    unconfigured/fails.
    """
    key = (category or "").strip() or "default"
    tags = CATEGORY_MUSIC_TAGS.get(key, DEFAULT_MUSIC_TAGS)

    pool_dir = _pool_dir_for_tags(tags)
    if pool_dir.is_dir():
        pool_tracks = list(pool_dir.glob("*.mp3"))
        if pool_tracks:
            return str(random.choice(pool_tracks))

    if not JAMENDO_CLIENT_ID:
        return _random_track_from_any_pool()

    cache_path = str(BG_MUSIC_DIR / f"{key}.mp3")
    if os.path.exists(cache_path):
        return cache_path

    try:
        path = _fetch_jamendo_track(tags, cache_path)
        if path:
            log.info("Music [%s] fetched from Jamendo (tags=%s) -> %s", key, tags, path)
            return path
    except Exception as exc:
        log.warning("Jamendo music fetch failed for category '%s': %s", key, exc)
    return _random_track_from_any_pool()
