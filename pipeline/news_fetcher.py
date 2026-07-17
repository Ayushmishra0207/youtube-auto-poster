"""
Fetch real breaking-news headlines from Google News RSS (free, no API key).

Used by the Shorts pipeline so scripts cover actual events from the last
1-2 days instead of hallucinated news.
"""
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

from pipeline.logger import log
from pipeline.retry import with_retry

# Google News RSS feeds (Hindi, India edition)
_FEEDS = {
    "india": "https://news.google.com/rss?hl=hi-IN&gl=IN&ceid=IN:hi",
    "world": "https://news.google.com/rss/headlines/section/topic/WORLD?hl=hi-IN&gl=IN&ceid=IN:hi",
    "business": "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=hi-IN&gl=IN&ceid=IN:hi",
}

_TIMEOUT = 15


@with_retry(max_attempts=3, base_delay=2.0, exceptions=(requests.exceptions.RequestException,))
def _fetch_feed(url: str) -> list[dict]:
    resp = requests.get(url, timeout=_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    root = ET.fromstring(resp.content)

    items = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        pub   = (item.findtext("pubDate") or "").strip()
        if not title:
            continue
        try:
            published = parsedate_to_datetime(pub)
        except Exception:
            published = None
        items.append({"title": title, "published": published})
    return items


def get_breaking_headlines(feed: str = "india", max_age_hours: int = 48, limit: int = 15) -> list[str]:
    """
    Return up to `limit` headline strings from the given feed
    ("india" | "world" | "business"), no older than max_age_hours.
    Returns [] on failure — callers must handle the empty case.
    """
    url = _FEEDS.get(feed, _FEEDS["india"])
    try:
        items = _fetch_feed(url)
    except Exception as exc:
        log.warning("News feed '%s' failed: %s", feed, exc)
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    fresh = [
        it["title"] for it in items
        if it["published"] is None or it["published"] >= cutoff
    ]
    log.info("News feed '%s': %d fresh headlines (of %d total)", feed, len(fresh), len(items))
    return fresh[:limit]
