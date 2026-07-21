"""
AI image generation using Pollinations.ai — free, unlimited, no API key.

Used as a fallback tier when HuggingFace/Gemini free quotas are exhausted,
so videos keep getting original AI-generated visuals instead of falling
all the way back to generic stock photos.
"""
import urllib.parse
from pathlib import Path

import requests

from pipeline.logger import log
from pipeline.retry import with_retry

_BASE_URL = "https://image.pollinations.ai/prompt"
_TIMEOUT = 45

_STYLE = (
    "photorealistic, professional news documentary photography, "
    "cinematic lighting, wide angle, high resolution, sharp focus, "
    "no text, no watermark"
)


class _EmptyImage(Exception):
    """Pollinations returned 200 OK but an empty/truncated body — retry-worthy,
    unlike a real HTTP error which requests already raises on its own."""


@with_retry(max_attempts=2, base_delay=2.0,
           exceptions=(requests.exceptions.RequestException, _EmptyImage))
def _fetch_pollinations(prompt: str, output_path: str, width: int, height: int) -> str:
    full_prompt = f"{prompt}, {_STYLE}"
    url = f"{_BASE_URL}/{urllib.parse.quote(full_prompt)}"

    resp = requests.get(
        url,
        params={"width": width, "height": height, "nologo": "true"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()

    if not resp.content or len(resp.content) < 1024:
        raise _EmptyImage(f"empty/tiny image for: {prompt[:50]}")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(resp.content)
    return output_path


def generate_image(prompt: str, output_path: str,
                   width: int = 1920, height: int = 1080) -> str | None:
    """
    Generate one image for `prompt` via Pollinations.ai and save to output_path.
    Retries once on a timeout/connection error or an empty response — a single
    45s-timeout provider call has no redundancy the way long-form videos do
    (5 images per section, many sections, so one bad call barely matters);
    for a Short, where each item gets exactly one image, one unretried
    timeout was enough to leave the whole item (and sometimes the whole
    Short) with zero background media. Returns the saved path on success,
    None if both attempts fail.
    """
    try:
        result = _fetch_pollinations(prompt, output_path, width, height)
        log.info("Pollinations image → %s  (%s)", Path(result).name, prompt[:40])
        return result
    except Exception as exc:
        log.warning("Pollinations image failed ('%s'): %s", prompt[:50], exc)
        return None
