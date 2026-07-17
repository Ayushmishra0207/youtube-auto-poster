"""
AI image generation using Google Gemini Imagen 3.

Generates photorealistic 16:9 background images for video sections.
Used as the primary image source; Pexels is the fallback.

Requires: pip install google-genai
API key: GEMINI_API_KEY in .env (Google AI Studio → aistudio.google.com)
"""
import time
from pathlib import Path

from config import GEMINI_API_KEY
from pipeline.logger import log

# Style suffix added to every prompt for news/documentary look
_STYLE = (
    "photorealistic, professional news documentary photography, "
    "cinematic lighting, 16:9 wide angle, high resolution, sharp focus"
)

_client = None

# Set for the rest of this process once we see a quota/billing error, so we
# stop retrying (and logging) a provider that's already known to be exhausted
# for every remaining image request this run.
_quota_exhausted = False


def _get_client():
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def _is_quota_error(exc: Exception) -> bool:
    msg = str(exc)
    return (
        "only available on paid plans" in msg
        or "RESOURCE_EXHAUSTED" in msg
        or "429" in msg
    )


def generate_image(
    prompt: str,
    output_path: str,
) -> str | None:
    """
    Generate one image for `prompt` using Imagen 3 and save to output_path.
    Returns the saved path on success, None on any failure.
    """
    global _quota_exhausted

    if not GEMINI_API_KEY or _quota_exhausted:
        return None

    try:
        from google.genai import types

        client = _get_client()
        full_prompt = f"{prompt}, {_STYLE}"

        response = client.models.generate_images(
            model="imagen-4.0-generate-001",
            prompt=full_prompt,
            config=types.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio="16:9",
                safety_filter_level="BLOCK_LOW_AND_ABOVE",
            ),
        )

        if not response.generated_images:
            log.warning("Gemini Imagen returned no images for: %s", prompt[:50])
            return None

        image_bytes = response.generated_images[0].image.image_bytes
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(image_bytes)

        log.info("Gemini image → %s  (%s)", Path(output_path).name, prompt[:40])
        return output_path

    except Exception as exc:
        if _is_quota_error(exc):
            _quota_exhausted = True
            log.warning("Gemini Imagen quota exhausted — skipping Gemini image-gen for the rest of this run")
        else:
            log.warning("Gemini image failed ('%s'): %s", prompt[:50], exc)
        return None


def generate_section_images(
    queries: list[str],
    output_dir: str,
    section_index: int,
    rate_limit_delay: float = 1.0,
) -> list[str | None]:
    """
    Generate one image per query for a single section.
    Adds a small delay between requests to respect rate limits.
    Returns list of paths (None where generation failed).
    """
    results: list[str | None] = []
    for j, query in enumerate(queries):
        path = str(Path(output_dir) / f"bg_{section_index:02d}_{j:02d}.jpg")
        img = generate_image(query, path)
        results.append(img)
        if img and j < len(queries) - 1:
            time.sleep(rate_limit_delay)
    return results
