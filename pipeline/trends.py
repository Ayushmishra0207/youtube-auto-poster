"""
Fetch trending / most-searched topics for India.

Strategy:
  1. Google Trends real-time trending searches (India)
  2. YouTube trending videos (requires YouTube API key)
  3. Hard-coded evergreen fallback if both fail
"""
import time
import random
import requests
from typing import List

from pytrends.request import TrendReq


def get_trending_topics(num: int = 7) -> List[str]:
    """Return `num` trending topics, best-effort."""
    topics = _from_google_trends(num)

    if len(topics) < num:
        topics += _evergreen_fallback()

    # Deduplicate while preserving order
    seen, unique = set(), []
    for t in topics:
        if t.lower() not in seen:
            seen.add(t.lower())
            unique.append(t)

    return unique[:num]


# ___ Sources ___________________________________________________________________

def _from_google_trends(num: int) -> List[str]:
    """Pull real-time trending searches for India."""
    try:
        pt = TrendReq(hl="hi-IN", tz=330, timeout=(10, 30))
        df = pt.trending_searches(pn="india")
        topics = df[0].dropna().tolist()
        return [str(t).strip() for t in topics[:num] if t]
    except Exception as e:
        print(f"  [warn]  Google Trends failed: {e}")
        return []


def _from_youtube_trending(api_key: str, num: int = 7, region: str = "IN") -> List[str]:
    """Extract topics from YouTube trending videos (optional, call manually)."""
    try:
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={
                "part": "snippet",
                "chart": "mostPopular",
                "regionCode": region,
                "maxResults": num,
                "key": api_key,
            },
            timeout=10,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        return [item["snippet"]["title"] for item in items]
    except Exception as e:
        print(f"  [warn]  YouTube Trending failed: {e}")
        return []


def _evergreen_fallback() -> List[str]:
    pool = [
        "India latest news today",
        "Bollywood news Hindi",
        "Cricket score today India",
        "Share market India today",
        "Weather update India",
        "Indian politics news",
        "Technology news India",
        "Health tips Hindi",
        "Jobs news India",
        "Sports news India today",
    ]
    random.shuffle(pool)
    return pool