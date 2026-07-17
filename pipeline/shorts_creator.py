"""
YouTube Shorts renderer — vertical 1080×1920, ≤59 s.

One short = fast-paced breaking-news flash: each news item gets a portrait
background image with Ken Burns motion, a bold Hindi headline overlay, and
1.5x-speed narration. Items crossfade into each other.

Script shape (from script_generator.generate_shorts_script):
  {title, description, tags, items: [{id, headline, narration, image_search}]}
"""
import os
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw
import moviepy as mpe

from config import (
    BG_MUSIC_PATH, BG_MUSIC_VOLUME,
    HINDI_FONT_BOLD,
    SHORTS_HEIGHT, SHORTS_MAX_SECONDS, SHORTS_TTS_RATE, SHORTS_WIDTH,
    SLIDE_COLORS, VIDEO_FPS,
    PEXELS_API_KEY,
)
from pipeline.image_fetcher import fetch_image_pexels
from pipeline.logger import log
from pipeline.video_creator import (
    _XFADE, _KB_OVERSCAN, _fix_devanagari, _gradient, _ken_burns_clip, _load_font, _wrap,
)
from pipeline.voice_generator import text_to_speech


def _item_frame(headline: str, bg_path: Optional[str], colors: tuple) -> np.ndarray:
    """Render one oversized vertical frame: portrait image + headline band."""
    ow = int(SHORTS_WIDTH * _KB_OVERSCAN)
    oh = int(SHORTS_HEIGHT * _KB_OVERSCAN)

    if bg_path and os.path.exists(bg_path):
        img = Image.open(bg_path).convert("RGB")
        scale = max(ow / img.width, oh / img.height)
        nw, nh = int(img.width * scale + 0.5), int(img.height * scale + 0.5)
        img = img.resize((nw, nh), Image.LANCZOS)
        left, top = (nw - ow) // 2, (nh - oh) // 2
        bg = img.crop((left, top, left + ow, top + oh))
    else:
        bg = Image.fromarray(_gradient(*colors, ow, oh)).convert("RGB")

    draw = ImageDraw.Draw(bg, "RGBA")

    # Headline band in the upper part (kept inside the Ken Burns safe area)
    font = _load_font(HINDI_FONT_BOLD, 74)
    lines = [_fix_devanagari(l) for l in _wrap(headline, font, ow - 220)]
    line_h = int(font.size * 1.35)
    band_h = line_h * len(lines) + 70
    band_top = int(oh * 0.14)

    draw.rectangle([(0, band_top), (ow, band_top + band_h)], fill=(0, 0, 0, 150))
    draw.rectangle([(0, band_top), (18, band_top + band_h)], fill=(220, 30, 30))

    y = band_top + 35
    for line in lines:
        w = font.getbbox(line)[2]
        draw.text(((ow - w) // 2, y), line, font=font,
                  fill=(255, 214, 0), stroke_width=3, stroke_fill=(0, 0, 0))
        y += line_h

    return np.array(bg)


def create_short(script: dict, work_dir: str) -> str:
    """
    Render one vertical Short from a shorts script.
    Returns the path of the written MP4 (work_dir/short.mp4).
    """
    work = Path(work_dir)
    (work / "voices").mkdir(parents=True, exist_ok=True)
    (work / "images").mkdir(parents=True, exist_ok=True)

    items = script.get("items", [])
    if not items:
        raise ValueError("Shorts script has no items")

    # ── Voice (1.5x) + portrait image per item ────────────────────────────────
    prepared = []
    for i, item in enumerate(items):
        voice_path = str(work / "voices" / f"item_{i:02d}.mp3")
        try:
            text_to_speech(item["narration"], voice_path, rate=SHORTS_TTS_RATE)
        except Exception as exc:
            log.warning("Short item %d voice failed, skipping: %s", i + 1, exc)
            continue

        img_path = str(work / "images" / f"item_{i:02d}.jpg")
        img = fetch_image_pexels(
            item.get("image_search", "breaking news background"),
            PEXELS_API_KEY, img_path, result_index=i % 3, orientation="portrait",
        )
        prepared.append({"item": item, "voice": voice_path, "image": img})

    if not prepared:
        raise ValueError("No shorts items could be prepared (all voices failed)")

    # ── Build item clips, enforcing the 59 s cap ──────────────────────────────
    clips: list[mpe.VideoClip] = []
    total = 0.0
    for k, p in enumerate(prepared):
        audio = mpe.AudioFileClip(p["voice"])
        dur = audio.duration + 0.3
        # Account for crossfade overlap when projecting the running total
        projected = total + dur - (_XFADE if clips else 0)
        if projected > SHORTS_MAX_SECONDS:
            audio.close()
            log.info("Short: stopping at item %d/%d to stay under %ds",
                     k, len(prepared), SHORTS_MAX_SECONDS)
            break

        frame = _item_frame(
            p["item"].get("headline", ""),
            p["image"],
            SLIDE_COLORS[k % len(SLIDE_COLORS)],
        )
        clip = _ken_burns_clip(frame, dur, move_index=k,
                               out_size=(SHORTS_WIDTH, SHORTS_HEIGHT)).with_audio(audio)
        if clips:
            clip = clip.with_effects([mpe.vfx.CrossFadeIn(_XFADE)])
        clips.append(clip)
        total = projected

    final = (clips[0] if len(clips) == 1
             else mpe.concatenate_videoclips(clips, method="compose", padding=-_XFADE))

    # ── Background music (low volume) ─────────────────────────────────────────
    if os.path.exists(BG_MUSIC_PATH):
        try:
            music = mpe.AudioFileClip(BG_MUSIC_PATH).with_volume_scaled(BG_MUSIC_VOLUME)
            if music.duration < final.duration:
                music = mpe.concatenate_audioclips(
                    [music] * (int(final.duration / music.duration) + 1))
            music = music.subclipped(0, final.duration)
            final = final.with_audio(mpe.CompositeAudioClip([final.audio, music]))
        except Exception as e:
            log.warning("Short background music skipped: %s", e)

    # ── Render ────────────────────────────────────────────────────────────────
    out_path = str(work / "short.mp4")
    temp_audio = str(work / "temp_short_audio.mp4")
    log.info("Rendering Short (%.1fs, %d items) -> %s", final.duration, len(clips), out_path)
    try:
        final.write_videofile(
            out_path,
            fps=VIDEO_FPS,
            codec="libx264",
            audio_codec="aac",
            bitrate="5000k",
            preset="fast",
            logger=None,
            threads=4,
            temp_audiofile=temp_audio,
            remove_temp=False,
        )
    finally:
        final.close()
        for c in clips:
            c.close()
        import time as _time
        for _ in range(5):
            try:
                if os.path.exists(temp_audio):
                    os.remove(temp_audio)
                break
            except OSError:
                _time.sleep(1)

    log.info("Short render complete: %s", out_path)

    # ── Thumbnail (first-frame capture — dashboard/upload use this) ───────────
    thumb_path = str(work / "thumbnail.jpg")
    try:
        frame_clip = mpe.VideoFileClip(out_path)
        Image.fromarray(frame_clip.get_frame(0.5)).save(thumb_path, "JPEG", quality=90)
        frame_clip.close()
    except Exception as e:
        log.warning("Short thumbnail extraction failed: %s", e)

    return out_path
