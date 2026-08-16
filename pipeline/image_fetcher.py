"""
Background image pipeline:
Pollinations (free, unlimited, primary) → Pexels (stock) → gradient.

HuggingFace (FLUX.1-schnell) and Gemini (Imagen 4) were removed from this
chain on 2026-07-19 — both providers were failing on every single call
(HuggingFace: FLUX.1-schnell returns 410 Gone, deprecated on the hf-inference
router; Gemini: imagen-4.0-generate-001 returns 404, deprecated for new
users) and were just wasting a full retry+backoff cycle before falling
through. Re-add them only after confirming a currently-working model/route.

fetch_all_section_images() returns list[list[str|None]] — one inner list per
section, each containing paths to multiple images that video_creator cycles through.
"""
import os
import re
from difflib import SequenceMatcher
from pathlib import Path

import requests

from pipeline.logger import log
from pipeline.retry import with_retry

PEXELS_API       = "https://api.pexels.com/v1/search"
PEXELS_VIDEO_API = "https://api.pexels.com/videos/search"
TIMEOUT    = 15
MAX_IMAGES_PER_SECTION = 10  # number of images per section


# ── Pexels relevance check ─────────────────────────────────────────────────────
# Pexels' own search is a blind keyword match with no semantic disambiguation —
# an ambiguous query like "Congress party protest press conference" (India's
# Congress party) can return a generic press-conference clip from anywhere in
# the world, and the code used to accept whichever result landed at a fixed
# round-robin index with zero check. Both photo and video results always carry
# a descriptive slug in their own `url` (Pexels auto-generates it from the
# asset's title), and photos also carry a separate `alt` text — use whichever
# text Pexels gives us to reject a result with no real overlap with the query.

_PEXELS_SLUG_RE = re.compile(r"/(?:photo|video)/([a-z0-9-]+)-\d+/?$")


def _pexels_slug_text(url: str) -> str:
    m = _PEXELS_SLUG_RE.search(url or "")
    return m.group(1).replace("-", " ") if m else ""


def _relevance_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 3}


def _matches_query(query: str, *texts: str) -> bool:
    """
    Loose overlap check (not the strict Wikipedia one below — Pexels'
    alt/slug text is a full descriptive phrase, not a title, so requiring
    "no extra words" would reject almost everything). No text to check
    against at all means we can't reject, so it passes rather than
    discarding a possibly-fine result for lack of data.
    """
    query_words = _relevance_words(query)
    text_words: set[str] = set()
    for t in texts:
        text_words |= _relevance_words(t)
    if not query_words or not text_words:
        return True
    overlap = query_words & text_words
    return len(overlap) / len(query_words) >= 0.34


def _best_matching_index(items: list, query: str, preferred_idx: int, text_fn) -> int | None:
    """
    Prefer `preferred_idx` (keeps the existing per-slot variety cycling) if
    it's a plausible match for the query; otherwise scan the other returned
    results for one that is. None means nothing among the returned results
    plausibly matches — better to fall through to the next image source
    than confidently attach an unrelated clip/photo.
    """
    order = [preferred_idx] + [i for i in range(len(items)) if i != preferred_idx]
    for i in order:
        if _matches_query(query, text_fn(items[i])):
            return i
    return None


# ── Pexels fallback ───────────────────────────────────────────────────────────

@with_retry(max_attempts=3, base_delay=2.0, exceptions=(requests.exceptions.RequestException,))
def _fetch_pexels(query: str, api_key: str, output_path: str, result_index: int,
                  orientation: str = "landscape") -> str | None:
    resp = requests.get(
        PEXELS_API,
        headers={"Authorization": api_key},
        params={"query": query, "per_page": 5, "orientation": orientation, "size": "large"},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    photos = resp.json().get("photos", [])
    if not photos:
        return None
    idx = _best_matching_index(
        photos, query, min(result_index, len(photos) - 1),
        lambda p: p.get("alt", "") + " " + _pexels_slug_text(p.get("url", "")),
    )
    if idx is None:
        log.info("Pexels: no result plausibly matches '%s' — skipping", query[:45])
        return None
    img_url = photos[idx]["src"]["large2x"]
    img_resp = requests.get(img_url, timeout=TIMEOUT)
    img_resp.raise_for_status()
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(img_resp.content)
    return output_path


def fetch_image_pexels(query: str, api_key: str, output_path: str, result_index: int = 0,
                       orientation: str = "landscape") -> str | None:
    if not api_key:
        return None
    try:
        return _fetch_pexels(query, api_key, output_path, result_index, orientation)
    except Exception as exc:
        log.warning("Pexels failed ('%s'): %s", query[:40], exc)
        return None


# ── Pexels stock video (real animated clips) ─────────────────────────────────

@with_retry(max_attempts=2, base_delay=2.0, exceptions=(requests.exceptions.RequestException,))
def _fetch_pexels_video(query: str, api_key: str, output_path: str, result_index: int = 0,
                        orientation: str = "landscape") -> str | None:
    resp = requests.get(
        PEXELS_VIDEO_API,
        headers={"Authorization": api_key},
        params={"query": query, "per_page": 5, "orientation": orientation},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    videos = resp.json().get("videos", [])
    if not videos:
        return None
    idx = _best_matching_index(
        videos, query, min(result_index, len(videos) - 1),
        lambda v: _pexels_slug_text(v.get("url", "")),
    )
    if idx is None:
        log.info("Pexels video: no result plausibly matches '%s' — skipping", query[:45])
        return None
    files = [f for f in videos[idx].get("video_files", []) if f.get("file_type") == "video/mp4"]
    if not files:
        return None
    # Prefer the file closest to our target width, so we don't download 4K for nothing
    files.sort(key=lambda f: abs((f.get("width") or 0) - 1280))
    video_resp = requests.get(files[0]["link"], timeout=30)
    video_resp.raise_for_status()
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(video_resp.content)
    return output_path


def fetch_video_pexels(query: str, api_key: str, output_path: str, result_index: int = 0,
                       orientation: str = "landscape") -> str | None:
    """Short real stock-video clip for visual variety, instead of a static image."""
    if not api_key:
        return None
    try:
        return _fetch_pexels_video(query, api_key, output_path, result_index, orientation)
    except Exception as exc:
        log.warning("Pexels video failed ('%s'): %s", query[:40], exc)
        return None


# ── Wikipedia (real photo of a named person/place/org) ────────────────────────
# Used when a query names a specific real entity (a politician, celebrity,
# athlete, landmark, ...) — Pexels/Pollinations can't return an actual photo
# of a named individual (Pexels is generic stock, and Pollinations is
# generative, so "asking" it for a real person either fails or, worse,
# fabricates a fake likeness of a real identifiable public figure, which this
# project should never do). Wikipedia's own page thumbnail is a real,
# properly-licensed photo instead.
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
# Wikimedia's API blocks requests with no/generic User-Agent (returns 403) —
# https://meta.wikimedia.org/wiki/User-Agent_policy requires an identifying one.
_WIKI_HEADERS = {"User-Agent": "youtube-auto-poster/1.0 (https://github.com/bitnomad1; contact via repo)"}


def _words_similar(a: str, b: str) -> bool:
    """Exact match, or close enough to cover transliteration/spelling
    variants (e.g. "Zelensky" vs the page's "Zelenskyy")."""
    return a == b or SequenceMatcher(None, a, b).ratio() >= 0.82


_TITLE_STOPWORDS = {"and", "the", "for", "with", "from", "of", "in", "on", "vs", "v"}


def _title_matches_query(query: str, title: str) -> bool:
    """
    Reject a Wikipedia match that isn't actually a page about the named
    entity we searched for. A word-overlap check alone isn't enough: e.g.
    querying "Donald Trump Iran" can resolve to the real article "Donald
    Trump and fascism", which shares 2 of 3 query words but is a thematic/
    analytical page whose lead photo could be anything (a protest, a
    cartoon, ...) — not a photo of the person. So beyond requiring most of
    the query's words to appear in the title (fuzzy match, since
    Hindi-to-English transliteration of a name varies, e.g. "Zelensky" vs
    the page's "Zelenskyy"), also require the title introduce NO extra
    significant word beyond the query — a real biography/place page's title
    is just the name itself, while an analytical/thematic title adds its own
    topic word ("fascism", "controversy", "protests", ...). Biased to reject
    more often: a missed real photo just falls back to Pexels/Pollinations/
    the template, which is a far smaller problem than attaching a wrong or
    inflammatory image to a real named person.
    """
    query_words = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 2]
    title_words = [w for w in re.findall(r"[a-z0-9]+", title.lower())
                   if len(w) > 2 and w not in _TITLE_STOPWORDS]
    if not query_words or not title_words:
        return False

    unexplained = [tw for tw in title_words if not any(_words_similar(tw, qw) for qw in query_words)]
    if unexplained:
        return False

    matched = sum(1 for qw in query_words if any(_words_similar(qw, tw) for tw in title_words))
    return matched / len(query_words) >= 0.5


def _resolve_wikipedia_title(query: str) -> str | None:
    """
    Two-tier lookup: opensearch (title/prefix matching — precise, but only
    matches when `query` is close to the real title verbatim) first, then
    list=search (full-text, fuzzier — needed because our extracted entity
    string is a regex guess that often carries extra trailing words like
    "... Ukraine" or a slightly different spelling, which opensearch's strict
    prefix matching rejects outright). Either tier's result must still pass
    _title_matches_query before being trusted.
    """
    search_resp = requests.get(
        WIKIPEDIA_API,
        params={"action": "opensearch", "search": query, "limit": 1,
                "namespace": 0, "format": "json"},
        headers=_WIKI_HEADERS,
        timeout=TIMEOUT,
    )
    search_resp.raise_for_status()
    data = search_resp.json()
    titles = data[1] if len(data) > 1 else []
    if titles and _title_matches_query(query, titles[0]):
        return titles[0]

    fulltext_resp = requests.get(
        WIKIPEDIA_API,
        params={"action": "query", "list": "search", "srsearch": query,
                "format": "json", "srlimit": 1},
        headers=_WIKI_HEADERS,
        timeout=TIMEOUT,
    )
    fulltext_resp.raise_for_status()
    results = fulltext_resp.json().get("query", {}).get("search", [])
    if results and _title_matches_query(query, results[0]["title"]):
        return results[0]["title"]

    return None


@with_retry(max_attempts=2, base_delay=2.0, exceptions=(requests.exceptions.RequestException,))
def _fetch_wikipedia_image(query: str, output_path: str) -> str | None:
    title = _resolve_wikipedia_title(query)
    if not title:
        log.info("No confident Wikipedia match for '%s' — skipping", query)
        return None

    img_resp = requests.get(
        WIKIPEDIA_API,
        params={"action": "query", "titles": title, "prop": "pageimages",
                "format": "json", "pithumbsize": 1280},
        headers=_WIKI_HEADERS,
        timeout=TIMEOUT,
    )
    img_resp.raise_for_status()
    pages = img_resp.json().get("query", {}).get("pages", {})
    page = next(iter(pages.values()), {})
    thumb_url = page.get("thumbnail", {}).get("source")
    if not thumb_url:
        return None

    photo_resp = requests.get(thumb_url, headers=_WIKI_HEADERS, timeout=TIMEOUT)
    photo_resp.raise_for_status()
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(photo_resp.content)
    return output_path


def fetch_wikipedia_image(query: str, output_path: str) -> str | None:
    """Real photo for a named entity via its Wikipedia page thumbnail, or None."""
    try:
        return _fetch_wikipedia_image(query, output_path)
    except Exception as exc:
        log.warning("Wikipedia image failed ('%s'): %s", query[:40], exc)
        return None


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_all_section_images(
    sections: list,
    api_key: str,
    output_dir: str,
) -> list[list[str | None]]:
    """
    Fetch/generate multiple background images per section.

    Priority per image slot:
      1. Pollinations.ai (free, unlimited AI-generated, primary)
      2. Pexels stock photo (real photography fallback)
      3. None → video_creator uses dark gradient

    Returns list[list[str|None]] — outer = sections, inner = images per section.
    """
    from pipeline.image_generator_pollinations import generate_image as pollinations_img

    results: list[list[str | None]] = []

    for i, section in enumerate(sections):
        queries: list[str] = section.get("image_searches") or []
        if isinstance(queries, str):
            queries = [queries]
        if not queries:
            queries = [section.get("image_search", "india news background")]
        queries = queries[:MAX_IMAGES_PER_SECTION]

        section_images: list[str | None] = []

        for j, query in enumerate(queries):
            img: str | None = None
            img_path = os.path.join(output_dir, f"bg_{i:02d}_{j:02d}.jpg")

            # 0. First slot per section: try a real stock video clip for
            #    visual variety (animated motion instead of a still photo).
            if j == 0 and api_key:
                video_path = os.path.join(output_dir, f"bg_{i:02d}_{j:02d}.mp4")
                vid = fetch_video_pexels(query, api_key, video_path, result_index=0)
                if vid:
                    log.info("Image %d.%d [pexels video] %s", i + 1, j + 1, query[:45])
                    section_images.append(vid)
                    continue

            # 1. Pollinations.ai (free, unlimited, no key needed, primary)
            img = pollinations_img(query, img_path)
            if img:
                log.info("Image %d.%d [pollinations] %s", i + 1, j + 1, query[:45])

            # 2. Fall back to Pexels
            if not img:
                img = fetch_image_pexels(query, api_key, img_path, result_index=j % 3)
                if img:
                    log.info("Image %d.%d [pexels]  %s", i + 1, j + 1, query[:45])

            # 3. Log gradient fallback
            if not img:
                log.info("Image %d.%d [gradient fallback] %s", i + 1, j + 1, query[:45])

            section_images.append(img)

        results.append(section_images or [None])

    return results
