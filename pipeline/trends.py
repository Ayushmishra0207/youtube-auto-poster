"""
Fetch trending / most-searched topics for the active locale's region.

Strategy:
  1. Google Trends real-time trending searches (locale.trends_pn)
  2. YouTube trending videos (get_youtube_trending_topics, optionally
     filtered to one YouTube category — a stronger signal than Google
     Trends for "what's actually getting watched/pushed on YouTube right
     now" in that specific vertical, since Google Trends is generic web
     search interest and doesn't know what YouTube's own algorithm favors)
  3. Hard-coded evergreen fallback if both fail

Topic strings here are just research subjects fed into generate_script() —
they don't need to be pre-translated into the target language, since the
LLM writes the final script in the target language regardless of what
language the topic string itself is in.
"""
import random
import re
from typing import List

from pytrends.request import TrendReq

from pipeline.locales import Locale, get_locale

# A lot of real trending-video titles are emoji/hashtag reaction noise
# ("😤...#shorts") that makes a poor script topic even though the video
# itself is genuinely trending — strip that noise and reject anything with
# too little real text left, rather than feeding it straight to the LLM.
_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000026FF\U00002700-\U000027BF\U0001F1E6-\U0001F1FF]+"
)
_HASHTAG_RE = re.compile(r"#\S+")


def _clean_trending_title(title: str) -> str | None:
    """Strip emoji/hashtags from a raw trending-video title; None if too
    little real informative text remains to be a usable topic."""
    cleaned = _HASHTAG_RE.sub("", title)
    cleaned = _EMOJI_RE.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -|:")
    words = [w for w in re.findall(r"[\wऀ-ॿ]+", cleaned) if len(w) > 2]
    return cleaned if len(words) >= 3 else None


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


def get_youtube_trending_topics(num: int = 5, locale: Locale | None = None,
                                video_category_id: str | None = None) -> List[str]:
    """
    Real YouTube trending-video titles for the locale's region, optionally
    filtered to one YouTube category (e.g. "17" for Sports, "28" for
    Science & Tech — see topic_config.json's yt_category_id per category).
    Reuses the uploader's existing OAuth credentials (pipeline/uploader.py)
    instead of needing a separate API key — videos.list with chart=mostPopular
    is a public read endpoint, so the broad `youtube` scope already granted
    covers it.

    Not every category has trending-chart data for every region — an empty
    result here is expected and normal, not an error; callers should fall
    back to Google Trends / fallback_topics.
    """
    locale = locale or get_locale(None)
    try:
        from pipeline.uploader import _get_service
        svc = _get_service()
        params = {
            "part": "snippet",
            "chart": "mostPopular",
            "regionCode": locale.news_gl,
            # Over-fetch — _clean_trending_title rejects pure emoji/hashtag
            # noise, so pull more raw results than needed to still have `num`
            # usable topics left after cleaning.
            "maxResults": min(max(num * 3, 10), 50),
        }
        if video_category_id:
            params["videoCategoryId"] = video_category_id
        resp = svc.videos().list(**params).execute()
        cleaned = (
            _clean_trending_title(item.get("snippet", {}).get("title", ""))
            for item in resp.get("items", [])
        )
        return [t for t in cleaned if t][:num]
    except Exception as e:
        print(f"  [warn]  YouTube Trending failed for {locale.code} (category={video_category_id}): {e}")
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
