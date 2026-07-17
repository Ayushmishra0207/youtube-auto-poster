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

_BASE_URL = "https://image.pollinations.ai/prompt"
_TIMEOUT = 45

_STYLE = (
    "photorealistic, professional news documentary photography, "
    "cinematic lighting, wide angle, high resolution, sharp focus, "
    "no text, no watermark"
)


def generate_image(prompt: str, output_path: str,
                   width: int = 1920, height: int = 1080) -> str | None:
    """
    Generate one image for `prompt` via Pollinations.ai and save to output_path.
    Returns the saved path on success, None on any failure.
    """
    try:
        full_prompt = f"{prompt}, {_STYLE}"
        url = f"{_BASE_URL}/{urllib.parse.quote(full_prompt)}"

        resp = requests.get(
            url,
            params={"width": width, "height": height, "nologo": "true"},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()

        if not resp.content or len(resp.content) < 1024:
            log.warning("Pollinations returned an empty/tiny image for: %s", prompt[:50])
            return None

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(resp.content)

        log.info("Pollinations image → %s  (%s)", Path(output_path).name, prompt[:40])
        return output_path

    except Exception as exc:
        log.warning("Pollinations image failed ('%s'): %s", prompt[:50], exc)
        return None
