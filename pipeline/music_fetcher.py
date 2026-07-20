"""
Vibe-matched background music via the Jamendo API (free, royalty-free
tracks — https://developer.jamendo.com, get a free client_id).

Falls back to None (caller uses the fixed BG_MUSIC_PATH track or skips
music) if no client_id is configured or the API/download fails.
"""
import os

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


def get_music_for_category(category: str) -> str | None:
    """
    Return a local file path to a background-music track matching the
    content category's vibe, downloading + caching it on first use
    (one track per category, reused every time after).
    Returns None if Jamendo isn't configured or the fetch fails.
    """
    if not JAMENDO_CLIENT_ID:
        return None

    key = (category or "").strip() or "default"
    cache_path = str(BG_MUSIC_DIR / f"{key}.mp3")
    if os.path.exists(cache_path):
        return cache_path

    tags = CATEGORY_MUSIC_TAGS.get(key, DEFAULT_MUSIC_TAGS)
    try:
        path = _fetch_jamendo_track(tags, cache_path)
        if path:
            log.info("Music [%s] fetched from Jamendo (tags=%s) -> %s", key, tags, path)
            return path
    except Exception as exc:
        log.warning("Jamendo music fetch failed for category '%s': %s", key, exc)
    return None
