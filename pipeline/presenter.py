"""
A consistent, fictional AI "presenter" cutout for thumbnails — the
arms-crossed anchor-in-a-suit figure seen in professional news-channel
thumbnails, composited over the video's own background image.

This is a synthetic character, not a real person — generated once and
reused across every thumbnail (regenerating a new random face each time
would look inconsistent, like a different host every video). Do not
prompt for, or represent this as, any specific real named individual.

Pipeline: generate a portrait with Pollinations (free, already used
elsewhere in this project) → cut the person out from whatever background
it produced via rembg (a real ML background-removal model, not a chroma-key
hack — Pollinations doesn't reliably follow "plain background" instructions,
so this works regardless of what backdrop it actually generates) → cache
the cutout on disk permanently, since the whole point is one fixed identity.
"""
from pathlib import Path
from typing import Optional

from config import ASSETS_DIR
from pipeline.logger import log

PRESENTER_DIR = ASSETS_DIR / "presenter"
CUTOUT_PATH = PRESENTER_DIR / "host_cutout.png"

_PROMPT = (
    "professional Indian male TV news anchor, early 30s, dark navy business suit, "
    "red necktie, arms crossed confidently, serious authoritative expression, "
    "waist-up studio portrait, shot straight-on, even studio lighting, "
    "photorealistic, sharp focus, high detail, centered"
)


def _generate_and_cut_out() -> Optional[str]:
    from pipeline.image_generator_pollinations import generate_image

    PRESENTER_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = str(PRESENTER_DIR / "_host_raw.jpg")

    raw = generate_image(_PROMPT, raw_path, width=768, height=1024)
    if not raw:
        log.warning("Presenter generation failed (Pollinations returned nothing)")
        return None

    try:
        from PIL import Image
        from rembg import remove

        img = Image.open(raw).convert("RGB")
        cutout = remove(img)
        CUTOUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        cutout.save(CUTOUT_PATH)
        log.info("Presenter cutout generated -> %s", CUTOUT_PATH)
        return str(CUTOUT_PATH)
    except Exception as exc:
        log.warning("Presenter background removal failed: %s", exc)
        return None


def get_presenter_cutout() -> Optional[str]:
    """
    Path to the cached presenter cutout PNG (transparent background),
    generating it once on first call. Returns None if generation/removal
    ever fails — callers should just skip the presenter in that case,
    same as any other optional visual element in this pipeline.
    """
    if CUTOUT_PATH.exists():
        return str(CUTOUT_PATH)
    return _generate_and_cut_out()
