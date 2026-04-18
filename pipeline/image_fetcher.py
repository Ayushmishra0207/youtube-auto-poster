"""
Download stock background images from Pexels (free tier, 200 req/hr).
Falls back to None if no API key is provided - video_creator uses gradients instead.
"""
import os
from pathlib import Path

import requests

from pipeline.logger import log
from pipeline.retry import with_retry

PEXELS_API = "https://api.pexels.com/v1/search"
TIMEOUT    = 15  # seconds


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
) -> list[str | None]:
    """Fetch one background image per section. Returns list (may contain None)."""
    results = []
    for i, section in enumerate(sections):
        query = section.get("image_search", "india news background")
        path  = os.path.join(output_dir, f"bg_{i:02d}.jpg")
        img   = fetch_image(query, api_key, path, result_index=i % 3)
        results.append(img)
        status = "ok" if img else "gradient"
        log.info("Image %d [%s]  %s", i + 1, status, query[:50])
    return results
