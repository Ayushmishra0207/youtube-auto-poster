"""
Assemble the final MP4 from slides + voice-over + background music.
Compatible with MoviePy 2.x (uses with_* API).

Video structure
───────────────
  1. Title card   (5 s, music only)
  2. Sections     (voice duration + 0.8 s tail each)
               ↳  Each section cycles through multiple Pexels images
                  (one image sub-clip per query, equal duration split)
  3. Outro CTA    (5 s, music only)
"""
import os
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import moviepy as mpe

from config import (
    BG_MUSIC_PATH, BG_MUSIC_VOLUME,
    HINDI_FONT_BOLD, HINDI_FONT_REGULAR,
    SLIDE_COLORS, VIDEO_FPS, VIDEO_HEIGHT, VIDEO_WIDTH, VIDEO_BITRATE,
)
from pipeline.logger import log

# ─── Colour / image helpers ───────────────────────────────────────────────────

def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _gradient(c1: str, c2: str, w: int = VIDEO_WIDTH, h: int = VIDEO_HEIGHT) -> np.ndarray:
    r1, g1, b1 = _hex_to_rgb(c1)
    r2, g2, b2 = _hex_to_rgb(c2)
    t = np.linspace(0, 1, h)[:, None]
    r = (r1 + (r2 - r1) * t).astype(np.uint8) * np.ones((h, w), np.uint8)
    g = (g1 + (g2 - g1) * t).astype(np.uint8) * np.ones((h, w), np.uint8)
    b = (b1 + (b2 - b1) * t).astype(np.uint8) * np.ones((h, w), np.uint8)
    return np.stack([r, g, b], axis=-1)


def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_px: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for word in words:
        test = f"{cur} {word}".strip()
        if font.getbbox(test)[2] <= max_px:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


# ─── Slide renderers ──────────────────────────────────────────────────────────

def _title_card(title: str, thumbnail_text: str, colors: tuple) -> np.ndarray:
    bg = Image.fromarray(_gradient(*colors)).convert("RGB")
    draw = ImageDraw.Draw(bg)
    f_title = _load_font(HINDI_FONT_BOLD, 88)
    f_sub   = _load_font(HINDI_FONT_REGULAR, 50)

    lines   = _wrap(title, f_title, VIDEO_WIDTH - 200)
    total_h = len(lines) * 108
    y       = (VIDEO_HEIGHT - total_h) // 2 - 60

    for line in lines:
        w = f_title.getbbox(line)[2]
        draw.text(((VIDEO_WIDTH - w) // 2, y), line, font=f_title,
                  fill=(255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0))
        y += 108

    bar_y = y + 18
    draw.rectangle([(VIDEO_WIDTH // 2 - 220, bar_y),
                    (VIDEO_WIDTH // 2 + 220, bar_y + 4)], fill=(79, 195, 247))

    if thumbnail_text:
        tw = f_sub.getbbox(thumbnail_text)[2]
        draw.text(((VIDEO_WIDTH - tw) // 2, bar_y + 20), thumbnail_text,
                  font=f_sub, fill=(79, 195, 247))

    return np.array(bg)


def _section_slide(
    heading: str,
    narration: str,
    bg_path: Optional[str],
    colors: tuple,
) -> np.ndarray:
    """Render one slide frame — clean full-screen image, no text overlay."""
    if bg_path and os.path.exists(bg_path):
        bg = (Image.open(bg_path).convert("RGBA")
                   .resize((VIDEO_WIDTH, VIDEO_HEIGHT), Image.LANCZOS))
        # Very subtle vignette-only overlay so image stays vibrant
        overlay = Image.new("RGBA", (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0, 40))
        bg = Image.alpha_composite(bg, overlay).convert("RGB")
    else:
        bg = Image.fromarray(_gradient(*colors)).convert("RGB")

    return np.array(bg)


def _outro_card() -> np.ndarray:
    bg   = Image.fromarray(_gradient("#000428", "#004e92")).convert("RGB")
    draw = ImageDraw.Draw(bg)
    f1   = _load_font(HINDI_FONT_BOLD, 78)
    f2   = _load_font(HINDI_FONT_REGULAR, 48)

    msg1 = "चैनल को Subscribe करें"
    msg2 = "Like, Share और घंटी दबाना न भूलें!"

    w1   = f1.getbbox(msg1)[2]
    w2   = f2.getbbox(msg2)[2]

    draw.text(((VIDEO_WIDTH - w1) // 2, VIDEO_HEIGHT // 2 - 100),
              msg1, font=f1, fill=(255, 68, 68),
              stroke_width=2, stroke_fill=(0, 0, 0))
    draw.text(((VIDEO_WIDTH - w2) // 2, VIDEO_HEIGHT // 2 + 30),
              msg2, font=f2, fill=(255, 255, 255))

    return np.array(bg)


# ─── Audio loop helper (MoviePy 2.x compatible) ───────────────────────────────

def _loop_audio(audio: mpe.AudioFileClip, target_duration: float) -> mpe.AudioFileClip:
    """Tile an audio clip until it fills target_duration seconds."""
    if audio.duration >= target_duration:
        return audio.subclipped(0, target_duration)
    loops = int(target_duration / audio.duration) + 1
    tiled = mpe.concatenate_audioclips([audio] * loops)
    return tiled.subclipped(0, target_duration)


# ─── Multi-image section builder ──────────────────────────────────────────────

def _build_section_clip(
    section: dict,
    voice_path: str,
    bg_image_list: list[Optional[str]],
    color_pair: tuple,
) -> mpe.VideoClip:
    """
    Build a video clip for one section by cycling through multiple background images.
    The total duration is (voice_duration + 0.8 s tail).
    Each image gets an equal share of the total duration.
    """
    audio = mpe.AudioFileClip(voice_path)
    total_dur = audio.duration + 0.8

    # Filter out None entries but keep at least one slot (gradient fallback)
    images = [p for p in bg_image_list if p and os.path.exists(p)]
    if not images:
        images = [None]  # will render as gradient

    n = len(images)
    sub_dur = total_dur / n

    sub_clips: list[mpe.ImageClip] = []
    for img_path in images:
        frame = _section_slide(
            section["heading"],
            section["narration"],
            img_path,
            color_pair,
        )
        sub_clips.append(
            mpe.ImageClip(frame).with_duration(sub_dur).with_fps(VIDEO_FPS)
        )

    # Concatenate sub-clips, then attach audio
    if len(sub_clips) == 1:
        section_video = sub_clips[0]
    else:
        section_video = mpe.concatenate_videoclips(sub_clips, method="compose")

    return section_video.with_audio(audio)


# ─── Public API ───────────────────────────────────────────────────────────────

def create_thumbnail(script: dict, output_path: str) -> str:
    """
    Render the title card as a JPEG thumbnail (1920×1080).
    Returns the saved file path.
    YouTube recommends 1280×720 min; 1920×1080 is accepted and looks sharper.
    """
    arr = _title_card(
        script["title"],
        script.get("thumbnail_text", ""),
        SLIDE_COLORS[0],
    )
    img = Image.fromarray(arr)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "JPEG", quality=92, optimize=True)
    log.info("Thumbnail saved → %s", output_path)
    return output_path


def create_video(
    script: dict,
    voice_files: list[str],
    bg_images: list[list[Optional[str]]],
    output_path: str,
) -> str:
    """
    Render the complete video and write to output_path.

    bg_images: list[list[str|None]] — one inner list per section,
               each inner list contains paths to multiple background images
               that will be cycled through during that section.
               (Backward-compat: a flat list[str|None] is also accepted and
               wrapped automatically so old callers don't break.)
    """
    sections = script["sections"]

    # Backward-compat: if caller passes flat list[str|None], wrap each item
    if bg_images and not isinstance(bg_images[0], list):
        bg_images = [[img] for img in bg_images]  # type: ignore[assignment]

    clips: list[mpe.VideoClip] = []

    # ── 1. Title card (5 s, no voice) ────────────────────────────────────────
    title_arr = _title_card(
        script["title"],
        script.get("thumbnail_text", ""),
        SLIDE_COLORS[0],
    )
    clips.append(
        mpe.ImageClip(title_arr).with_duration(5).with_fps(VIDEO_FPS)
    )

    # ── 2. Content sections ───────────────────────────────────────────────────
    for i, (section, vpath) in enumerate(zip(sections, voice_files)):
        if not vpath or not os.path.exists(vpath):
            log.warning("Skipping section %d — no voice file", i + 1)
            continue

        # Get the image list for this section (safe default = [None])
        img_list: list[Optional[str]] = (
            bg_images[i] if i < len(bg_images) else [None]
        )

        color_pair = SLIDE_COLORS[(i + 1) % len(SLIDE_COLORS)]

        section_clip = _build_section_clip(section, vpath, img_list, color_pair)
        clips.append(section_clip)

    # ── 3. Outro (5 s, no voice) ──────────────────────────────────────────────
    clips.append(
        mpe.ImageClip(_outro_card()).with_duration(5).with_fps(VIDEO_FPS)
    )

    # ── 4. Concatenate ────────────────────────────────────────────────────────
    final = mpe.concatenate_videoclips(clips, method="compose")

    # ── 5. Background music (optional) ────────────────────────────────────────
    if os.path.exists(BG_MUSIC_PATH):
        try:
            music = (
                mpe.AudioFileClip(BG_MUSIC_PATH)
                .with_volume_scaled(BG_MUSIC_VOLUME)
            )
            music = _loop_audio(music, final.duration)

            existing = final.audio
            mixed = (
                mpe.CompositeAudioClip([existing, music])
                if existing
                else music
            )
            final = final.with_audio(mixed)
        except Exception as e:
            log.warning("Background music skipped: %s", e)

    # ── 6. Render ─────────────────────────────────────────────────────────────
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Use a unique per-video temp file to avoid Windows file-lock conflicts
    temp_audio = str(out_path.parent / "temp_audio.mp4")
    log.info("Rendering video → %s", output_path)
    try:
        final.write_videofile(
            output_path,
            fps=VIDEO_FPS,
            codec="libx264",
            audio_codec="aac",
            bitrate=VIDEO_BITRATE,
            preset="fast",
            logger=None,
            threads=4,
            temp_audiofile=temp_audio,
            remove_temp=False,   # we delete manually to avoid WinError 32
        )
    finally:
        # Close clips first to release all Windows file handles
        final.close()
        for c in clips:
            c.close()
        # Now safely delete all temp audio files (ours + MoviePy's default)
        import time as _time
        default_temp = str(out_path.parent / "finalTEMP_MPY_wvf_snd.mp4")
        for tmp in [temp_audio, default_temp]:
            for _ in range(5):
                try:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                    break
                except OSError:
                    _time.sleep(1)

    log.info("Video render complete: %s", output_path)
    return output_path
