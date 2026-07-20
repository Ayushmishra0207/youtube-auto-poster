"""
Fetch real breaking-news headlines from Google News RSS (free, no API key).

Used by the Shorts pipeline so scripts cover actual events from the last
1-2 days instead of hallucinated news. Locale-aware: the "india" feed key
means "home country" news for whichever locale is active (hl/gl/ceid come
from pipeline/locales.py), not literally India once a different region is
selected — "world"/"business" keep the same Google News topic IDs across
all locales, only the language/country query params change.
"""
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

from pipeline.locales import Locale, get_locale
from pipeline.logger import log
from pipeline.retry import with_retry

_FEED_PATHS = {
    "india": "https://news.google.com/rss",
    "world": "https://news.google.com/rss/headlines/section/topic/WORLD",
    "business": "https://news.google.com/rss/headlines/section/topic/BUSINESS",
}

_TIMEOUT = 15


def _feed_url(feed: str, locale: Locale) -> str:
    base = _FEED_PATHS.get(feed, _FEED_PATHS["india"])
    return f"{base}?hl={locale.news_hl}&gl={locale.news_gl}&ceid={locale.news_ceid}"


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


def get_breaking_headlines(feed: str = "india", max_age_hours: int = 48, limit: int = 15,
                           locale: Locale | None = None) -> list[str]:
    """
    Return up to `limit` headline strings from the given feed
    ("india" | "world" | "business" — "india" means home-country news for
    the active locale), no older than max_age_hours.
    Returns [] on failure — callers must handle the empty case.
    """
    locale = locale or get_locale(None)
    url = _feed_url(feed, locale)
    try:
        items = _fetch_feed(url)
    except Exception as exc:
        log.warning("News feed '%s' (locale=%s) failed: %s", feed, locale.code, exc)
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    fresh = [
        it["title"] for it in items
        if it["published"] is None or it["published"] >= cutoff
    ]
    log.info("News feed '%s' (locale=%s): %d fresh headlines (of %d total)",
             feed, locale.code, len(fresh), len(items))
    return fresh[:limit]
