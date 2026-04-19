"""
Download stock background images from Pexels (free tier, 200 req/hr).
Falls back to None if no API key is provided - video_creator uses gradients instead.

fetch_all_section_images() now returns list[list[str|None]] — multiple images
per section so the video can cycle through them (one image every few seconds).
"""
import os
from pathlib import Path

import requests

from pipeline.logger import log
from pipeline.retry import with_retry

PEXELS_API = "https://api.pexels.com/v1/search"
TIMEOUT    = 15  # seconds
MAX_IMAGES_PER_SECTION = 5  # number of images to fetch per section


@with_retry(max_attempts=3, base_delay=2.0, exceptions=(requests.exceptions.RequestException,))
def _fetch_with_retry(query: str, api_key: str, output_path: str, result_index: int) -> str | None:
    """Inner fetch — retried on network/HTTP errors. Returns path or None."""
    resp = requests.get(
        PEXELS_API,
        headers={"Authorization": api_key},
        params={
            "query":       query,
            "per_page":    5,
            "orientation": "landscape",
            "size":        "large",
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    photos = resp.json().get("photos", [])

    if not photos:
        return None

    idx     = min(result_index, len(photos) - 1)
    img_url = photos[idx]["src"]["large2x"]

    img_resp = requests.get(img_url, timeout=TIMEOUT)
    img_resp.raise_for_status()

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(img_resp.content)

    return output_path


def fetch_image(
    query: str,
    api_key: str,
    output_path: str,
    result_index: int = 0,
) -> str | None:
    """
    Download the best-matching landscape image for `query`.
    Returns the saved file path or None on failure / missing key.
    """
    if not api_key:
        return None

    try:
        return _fetch_with_retry(query, api_key, output_path, result_index)
    except Exception as exc:
        log.warning("Image fetch failed ('%s'): %s — using gradient fallback", query, exc)
        return None


def fetch_all_section_images(
    sections: list,
    api_key: str,
    output_dir: str,
) -> list[list[str | None]]:
    """
    Fetch multiple background images per section using the `image_searches` array.
    Returns list[list[str|None]] — outer list is per-section, inner list is per-image.

    If a section only has the old `image_search` string field (backward compat),
    it is treated as a single-query section.
    """
    results: list[list[str | None]] = []

    for i, section in enumerate(sections):
        # Support both new (image_searches list) and old (image_search string) formats
        queries = section.get("image_searches") or []
        if isinstance(queries, str):
            queries = [queries]
        if not queries:
            fallback = section.get("image_search", "india news background")
            queries = [fallback]

        # Limit to MAX_IMAGES_PER_SECTION
        queries = queries[:MAX_IMAGES_PER_SECTION]

        section_images: list[str | None] = []
        for j, query in enumerate(queries):
            path = os.path.join(output_dir, f"bg_{i:02d}_{j:02d}.jpg")
            img  = fetch_image(query, api_key, path, result_index=j % 3)
            section_images.append(img)
            status = "ok" if img else "gradient"
            log.info("Image %d.%d [%s]  %s", i + 1, j + 1, status, query[:50])

        # Ensure at least one entry (None = gradient fallback)
        if not section_images:
            section_images = [None]

        results.append(section_images)

    return results
