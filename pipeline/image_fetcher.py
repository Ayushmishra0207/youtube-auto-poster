"""
Background image pipeline:
HuggingFace (primary) → Gemini → Pollinations (free, unlimited) → Pexels (stock) → gradient.

fetch_all_section_images() returns list[list[str|None]] — one inner list per
section, each containing paths to multiple images that video_creator cycles through.
"""
import os
from pathlib import Path

import requests

from pipeline.logger import log
from pipeline.retry import with_retry

PEXELS_API = "https://api.pexels.com/v1/search"
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


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_all_section_images(
    sections: list,
    api_key: str,
    output_dir: str,
) -> list[list[str | None]]:
    """
    Fetch/generate multiple background images per section.

    Priority per image slot:
      1. HuggingFace FLUX.1-schnell (free AI-generated, most relevant)
      2. Gemini Imagen 4 (AI-generated fallback)
      3. Pollinations.ai (free, unlimited AI-generated fallback)
      4. Pexels stock photo (real photography fallback)
      5. None → video_creator uses dark gradient

    Returns list[list[str|None]] — outer = sections, inner = images per section.
    """
    # Import here so each provider is optional
    try:
        from pipeline.image_generator_huggingface import generate_image as hf_img
        from config import HUGGINGFACE_API_KEY
        use_hf = bool(HUGGINGFACE_API_KEY)
    except ImportError:
        use_hf = False
        hf_img = None
        HUGGINGFACE_API_KEY = ""

    try:
        from pipeline.image_generator_gemini import generate_image as gemini_img
        from config import GEMINI_API_KEY
        use_gemini = bool(GEMINI_API_KEY)
    except ImportError:
        use_gemini = False
        gemini_img = None
        GEMINI_API_KEY = ""

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

            # 1. Try HuggingFace FLUX.1-schnell (free)
            if use_hf and hf_img:
                img = hf_img(query, img_path)
                if img:
                    log.info("Image %d.%d [huggingface] %s", i + 1, j + 1, query[:45])

            # 2. Fall back to Gemini Imagen 4
            if not img and use_gemini and gemini_img:
                img = gemini_img(query, img_path)
                if img:
                    log.info("Image %d.%d [gemini] %s", i + 1, j + 1, query[:45])

            # 3. Fall back to Pollinations.ai (free, unlimited, no key needed)
            if not img:
                img = pollinations_img(query, img_path)
                if img:
                    log.info("Image %d.%d [pollinations] %s", i + 1, j + 1, query[:45])

            # 4. Fall back to Pexels
            if not img:
                img = fetch_image_pexels(query, api_key, img_path, result_index=j % 3)
                if img:
                    log.info("Image %d.%d [pexels]  %s", i + 1, j + 1, query[:45])

            # 5. Log gradient fallback
            if not img:
                log.info("Image %d.%d [gradient fallback] %s", i + 1, j + 1, query[:45])

            section_images.append(img)

        results.append(section_images or [None])

    return results
