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

# Set for the rest of this process once we see a quota/billing error, so we
# stop retrying (and logging) a provider that's already known to be exhausted
# for every remaining image request this run.
_quota_exhausted = False


def _get_client():
    global _client
    if _client is None:
        from huggingface_hub import InferenceClient
        _client = InferenceClient(
            provider="hf-inference",
            token=HUGGINGFACE_API_KEY,
        )
    return _client


def _is_quota_error(exc: Exception) -> bool:
    msg = str(exc)
    return "402" in msg or "Payment Required" in msg or "quota" in msg.lower()


def generate_image(prompt: str, output_path: str) -> str | None:
    """
    Generate one image for `prompt` via HF Inference and save to output_path.
    Returns the saved path on success, None on any failure.
    """
    global _quota_exhausted

    if not HUGGINGFACE_API_KEY or _quota_exhausted:
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
        if _is_quota_error(exc):
            _quota_exhausted = True
            log.warning("HuggingFace quota exhausted — skipping HuggingFace for the rest of this run")
        else:
            log.warning("HuggingFace image failed ('%s'): %s", prompt[:50], exc)
        return None
