"""
Fetch trending / most-searched topics for the active locale's region.

Strategy:
  1. Google Trends real-time trending searches (locale.trends_pn)
  2. YouTube trending videos (requires YouTube API key)
  3. Hard-coded evergreen fallback if both fail

Topic strings here are just research subjects fed into generate_script() —
they don't need to be pre-translated into the target language, since the
LLM writes the final script in the target language regardless of what
language the topic string itself is in.
"""
import random
import requests
from typing import List

from pytrends.request import TrendReq

from pipeline.locales import Locale, get_locale


def get_trending_topics(num: int = 7, locale: Locale | None = None) -> List[str]:
    """Return `num` trending topics for the locale's region, best-effort."""
    locale = locale or get_locale(None)
    topics = _from_google_trends(num, locale)

    if len(topics) < num:
        topics += _evergreen_fallback(locale)

    # Deduplicate while preserving order
    seen, unique = set(), []
    for t in topics:
        if t.lower() not in seen:
            seen.add(t.lower())
            unique.append(t)

    return unique[:num]


# ___ Sources ___________________________________________________________________

def _from_google_trends(num: int, locale: Locale) -> List[str]:
    """Pull real-time trending searches for the locale's country."""
    try:
        pt = TrendReq(hl=locale.news_hl, tz=330, timeout=(10, 30))
        df = pt.trending_searches(pn=locale.trends_pn)
        topics = df[0].dropna().tolist()
        return [str(t).strip() for t in topics[:num] if t]
    except Exception as e:
        print(f"  [warn]  Google Trends failed for {locale.code}: {e}")
        return []


def _from_youtube_trending(api_key: str, num: int = 7, locale: Locale | None = None) -> List[str]:
    """Extract topics from YouTube trending videos (optional, call manually)."""
    locale = locale or get_locale(None)
    try:
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={
                "part": "snippet",
                "chart": "mostPopular",
                "regionCode": locale.news_gl,
                "maxResults": num,
                "key": api_key,
            },
            timeout=10,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        return [item["snippet"]["title"] for item in items]
    except Exception as e:
        print(f"  [warn]  YouTube Trending failed for {locale.code}: {e}")
        return []


def _evergreen_fallback(locale: Locale | None = None) -> List[str]:
    """
    Last-resort topic pool if both real sources fail. English is fine here —
    these are just research subjects for the LLM, not user-facing text; the
    LLM still writes the final script in locale.language_name.
    """
    locale = locale or get_locale(None)
    country = locale.label.split(" (")[0]  # e.g. "India" from "India (Hindi)"
    pool = [
        f"{country} latest news today",
        f"Entertainment news {country}",
        f"Sports news {country} today",
        f"{country} stock market today",
        f"Weather update {country}",
        f"{country} politics news",
        f"Technology news {country}",
        f"Health tips {locale.language_name}",
        f"Jobs and economy news {country}",
        f"Viral trending story {country}",
    ]
    random.shuffle(pool)
    return pool
