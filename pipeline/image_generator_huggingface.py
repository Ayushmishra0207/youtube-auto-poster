"""
AI image generation using HuggingFace Inference API (free tier).

Uses FLUX.1-schnell via HuggingFace's own hf-inference provider —
included in the free tier with rate limits.

Requires: pip install huggingface_hub Pillow
API token: HUGGINGFACE_API_KEY in .env (huggingface.co → Settings → Access Tokens,
           permission: "Make calls to the serverless Inference API")
"""
from pathlib import Path

from config import HUGGINGFACE_API_KEY
from pipeline.logger import log

_MODEL = "black-forest-labs/FLUX.1-schnell"

_STYLE = (
    "photorealistic, professional news documentary photography, "
    "cinematic lighting, 16:9 wide angle, high resolution, sharp focus, "
    "no text, no watermark"
)

_client = None


def _get_client():
    global _client
    if _client is None:
        from huggingface_hub import InferenceClient
        _client = InferenceClient(
            provider="hf-inference",
            token=HUGGINGFACE_API_KEY,
        )
    return _client


def generate_image(prompt: str, output_path: str) -> str | None:
    """
    Generate one image for `prompt` via HF Inference and save to output_path.
    Returns the saved path on success, None on any failure.
    """
    if not HUGGINGFACE_API_KEY:
        return None

    try:
        client = _get_client()
        full_prompt = f"{prompt}, {_STYLE}"

        image = client.text_to_image(
            prompt=full_prompt,
            model=_MODEL,
        )

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path, format="JPEG", quality=92)

        log.info("HuggingFace image saved: %s  (%s)", Path(output_path).name, prompt[:40])
        return output_path

    except Exception as exc:
        log.warning("HuggingFace image failed ('%s'): %s", prompt[:50], exc)
        return None
