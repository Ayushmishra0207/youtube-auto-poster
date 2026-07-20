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
from pathlib import Path

import requests

from pipeline.logger import log
from pipeline.retry import with_retry

PEXELS_API       = "https://api.pexels.com/v1/search"
PEXELS_VIDEO_API = "https://api.pexels.com/videos/search"
TIMEOUT    = 15
MAX_IMAGES_PER_SECTION = 10  # number of images per section


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
    idx     = min(result_index, len(photos) - 1)
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
    idx = min(result_index, len(videos) - 1)
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
