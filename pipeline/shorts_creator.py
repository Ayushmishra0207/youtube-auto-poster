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
    SHORTS_HEIGHT, SHORTS_MAX_SECONDS, SHORTS_TTS_RATE, SHORTS_WIDTH,
    SLIDE_COLORS, VIDEO_FPS,
    PEXELS_API_KEY,
)
from pipeline.image_fetcher import fetch_image_pexels, fetch_video_pexels
from pipeline.locales import Locale, category_badge_text, get_locale
from pipeline.logger import log
from pipeline.music_fetcher import get_music_for_category
from pipeline.video_creator import (
    _XFADE, _KB_OVERSCAN, _cover_crop, _gradient, _ken_burns_clip, _load_font,
    _shape_text, _shaped_lines, _video_cover_clip, draw_engagement_row,
)
from pipeline.voice_generator import text_to_speech


def _headline_overlay_rgba(headline: str, size: tuple[int, int], locale: Locale) -> np.ndarray:
    """Transparent RGBA frame with just the headline band + text (no background)."""
    w, h = size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")

    font = _load_font(locale.font_bold, 74)
    lines = _shaped_lines(headline, font, w - 220, locale)
    line_h = int(font.size * 1.35)
    band_h = line_h * len(lines) + 70
    band_top = int(h * 0.14)

    draw.rectangle([(0, band_top), (w, band_top + band_h)], fill=(0, 0, 0, 150))
    draw.rectangle([(0, band_top), (18, band_top + band_h)], fill=(220, 30, 30, 255))

    y = band_top + 35
    for line in lines:
        lw = font.getbbox(line)[2]
        draw.text(((w - lw) // 2, y), line, font=font,
                  fill=(255, 214, 0, 255), stroke_width=3, stroke_fill=(0, 0, 0, 255))
        y += line_h

    return np.array(overlay)


def _item_frame(headline: str, bg_path: Optional[str], colors: tuple, locale: Locale) -> np.ndarray:
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
    font = _load_font(locale.font_bold, 74)
    lines = _shaped_lines(headline, font, ow - 220, locale)
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


def create_short_thumbnail(script: dict, output_path: str, image_paths: list,
                           locale: Locale, category: str = "") -> str:
    """
    Render a punchy vertical (9:16) thumbnail composited from the Short's own
    fetched background images — same tabloid-news look (badge, bold headline
    banner, topic-colored accent rule) as the long-form video thumbnail
    (pipeline.video_creator.create_thumbnail), adapted to portrait. Falls
    back to a plain gradient card if no real still images were fetched for
    this Short (e.g. every item used a Pexels video background instead).
    """
    W, H = SHORTS_WIDTH, SHORTS_HEIGHT
    images = [p for p in (image_paths or []) if p and os.path.exists(p)]
    RED = (214, 24, 24)
    ACCENT = (255, 214, 0)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    if not images:
        canvas = Image.fromarray(_gradient("#1a1a2e", "#16213e", W, H)).convert("RGB")
    else:
        canvas = Image.new("RGB", (W, H), (10, 10, 14))
        if len(images) == 1:
            canvas.paste(_cover_crop(Image.open(images[0]).convert("RGB"), W, H), (0, 0))
        else:
            main_h = int(H * 0.72)
            canvas.paste(_cover_crop(Image.open(images[0]).convert("RGB"), W, main_h), (0, 0))
            rest = images[1:3]
            bw = W // len(rest)
            for i, p in enumerate(rest):
                canvas.paste(_cover_crop(Image.open(p).convert("RGB"), bw, H - main_h), (i * bw, main_h))
            if len(rest) >= 2:
                draw = ImageDraw.Draw(canvas)
                draw.rectangle([(bw - 2, main_h), (bw + 2, H)], fill=RED)

    draw = ImageDraw.Draw(canvas, "RGBA")

    # Dark gradient (top badge strip + bottom headline shelf) for legibility
    grad = Image.new("L", (1, H), 0)
    for y in range(H):
        bottom_p = max(0.0, (y / H - 0.55) / 0.45)
        top_p = max(0.0, 1 - y / 110) if y < 110 else 0.0
        grad.putpixel((0, y), int(220 * max(bottom_p, top_p * 0.8)))
    alpha = grad.resize((W, H))
    canvas = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), canvas, alpha)
    draw = ImageDraw.Draw(canvas, "RGBA")

    # "BREAKING" style badge, top-left
    f_badge = _load_font(locale.font_bold, 40)
    badge_txt = _shape_text(category_badge_text(category, locale), locale)
    bw_ = f_badge.getbbox(badge_txt)[2]
    draw.rectangle([(24, 24), (24 + bw_ + 36, 90)], fill=RED)
    draw.text((42, 34), badge_txt, font=f_badge, fill=(255, 255, 255))

    # Headline: first item's headline (the actual hook), falling back to title
    items = script.get("items") or []
    text = ((items[0].get("headline") if items else "") or script.get("title", "")).strip()

    max_w = W - 80
    f_head = _load_font(locale.font_bold, 68)
    lines = _shaped_lines(text, f_head, max_w, locale)
    for size in range(68, 34, -4):
        f_head = _load_font(locale.font_bold, size)
        lines = _shaped_lines(text, f_head, max_w, locale)
        if len(lines) <= 3:
            break
    lines = lines[:3]

    line_h = int(f_head.size * 1.35)
    y = H - 56 - line_h * len(lines)
    draw.rectangle([(0, y - 22), (W, y - 18)], fill=ACCENT)
    for i, line in enumerate(lines):
        color = (255, 255, 255) if i % 2 == 0 else ACCENT
        lw = f_head.getbbox(line)[2]
        draw.text(((W - lw) // 2, y), line, font=f_head, fill=color,
                  stroke_width=5, stroke_fill=(0, 0, 0))
        y += line_h

    canvas.save(output_path, "JPEG", quality=92, optimize=True)
    log.info("Short thumbnail saved (composite, %d images) -> %s", len(images), output_path)
    return output_path


OUTRO_SECONDS = 2.6  # Shorts are time-tight — keep the engagement CTA brief


def _outro_frame(locale: Locale) -> np.ndarray:
    """Oversized (Ken-Burns-ready) vertical outro frame: LIKE + SUBSCRIBE engagement CTA."""
    ow = int(SHORTS_WIDTH * _KB_OVERSCAN)
    oh = int(SHORTS_HEIGHT * _KB_OVERSCAN)
    bg = Image.fromarray(_gradient("#000428", "#004e92", ow, oh)).convert("RGB")
    draw = ImageDraw.Draw(bg)

    f1 = _load_font(locale.font_bold, 56)
    y = int(oh * 0.30)
    for line in _shaped_lines(locale.subscribe_cta, f1, ow - 100, locale):
        w = f1.getbbox(line)[2]
        draw.text(((ow - w) // 2, y), line, font=f1, fill=(255, 68, 68),
                  stroke_width=2, stroke_fill=(0, 0, 0))
        y += int(f1.size * 1.35)

    draw_engagement_row(bg, locale, int(oh * 0.52), scale=1.35)

    draw = ImageDraw.Draw(bg)
    f2 = _load_font(locale.font_regular, 36)
    y2 = int(oh * 0.66)
    for line in _shaped_lines(locale.like_share_cta, f2, ow - 100, locale):
        w = f2.getbbox(line)[2]
        draw.text(((ow - w) // 2, y2), line, font=f2, fill=(255, 255, 255))
        y2 += int(f2.size * 1.3)

    return np.array(bg)


def create_short(script: dict, work_dir: str, category: str = "news",
                 locale: Optional[Locale] = None) -> str:
    """
    Render one vertical Short from a shorts script.
    Returns the path of the written MP4 (work_dir/short.mp4).
    """
    locale = locale or get_locale(None)
    work = Path(work_dir)
    (work / "voices").mkdir(parents=True, exist_ok=True)
    (work / "images").mkdir(parents=True, exist_ok=True)

    items = script.get("items", [])
    if not items:
        raise ValueError("Shorts script has no items")

    # ── Voice (1.5x) + portrait background (video clip, else still image) ────
    prepared = []
    for i, item in enumerate(items):
        voice_path = str(work / "voices" / f"item_{i:02d}.mp3")
        try:
            text_to_speech(item["narration"], voice_path, rate=SHORTS_TTS_RATE, locale=locale)
        except Exception as exc:
            log.warning("Short item %d voice failed, skipping: %s", i + 1, exc)
            continue

        query = item.get("image_search", "breaking news background")

        video_path = str(work / "images" / f"item_{i:02d}.mp4")
        bg_video = fetch_video_pexels(query, PEXELS_API_KEY, video_path,
                                      result_index=i % 3, orientation="portrait")

        bg_image = None
        if not bg_video:
            img_path = str(work / "images" / f"item_{i:02d}.jpg")
            bg_image = fetch_image_pexels(
                query, PEXELS_API_KEY, img_path, result_index=i % 3, orientation="portrait",
            )
            if not bg_image:
                # Pexels has no portrait match for niche/topical Hindi queries far
                # more often than it does for the broader English search terms
                # long-form videos use — Pollinations (free, unlimited AI-generated)
                # is what keeps those reliable, so fall back to it here too instead
                # of leaving the item with zero background media.
                from pipeline.image_generator_pollinations import generate_image as pollinations_img
                bg_image = pollinations_img(query, img_path, width=SHORTS_WIDTH, height=SHORTS_HEIGHT)
                if bg_image:
                    log.info("Short item %d [pollinations] %s", i + 1, query[:45])

        prepared.append({"item": item, "voice": voice_path, "video": bg_video, "image": bg_image})

    if not prepared:
        raise ValueError("No shorts items could be prepared (all voices failed)")

    # ── Build item clips, enforcing the 59 s cap ──────────────────────────────
    clips: list[mpe.VideoClip] = []
    total = 0.0
    for k, p in enumerate(prepared):
        audio = mpe.AudioFileClip(p["voice"])
        dur = audio.duration + 0.3
        # Account for crossfade overlap when projecting the running total.
        # Reserve OUTRO_SECONDS so the LIKE/SUBSCRIBE card always fits under the cap.
        projected = total + dur - (_XFADE if clips else 0)
        if projected > SHORTS_MAX_SECONDS - OUTRO_SECONDS:
            audio.close()
            log.info("Short: stopping at item %d/%d to leave room for the outro (cap %ds)",
                     k, len(prepared), SHORTS_MAX_SECONDS)
            break

        headline = p["item"].get("headline", "")
        bg_clip = None
        if p.get("video"):
            bg_clip = _video_cover_clip(p["video"], dur, (SHORTS_WIDTH, SHORTS_HEIGHT))
            if bg_clip is not None:
                overlay_rgba = _headline_overlay_rgba(headline, (SHORTS_WIDTH, SHORTS_HEIGHT), locale)
                overlay_clip = mpe.ImageClip(overlay_rgba).with_duration(dur)
                bg_clip = mpe.CompositeVideoClip([bg_clip, overlay_clip])

        if bg_clip is None:
            frame = _item_frame(headline, p["image"], SLIDE_COLORS[k % len(SLIDE_COLORS)], locale)
            bg_clip = _ken_burns_clip(frame, dur, move_index=k,
                                      out_size=(SHORTS_WIDTH, SHORTS_HEIGHT))

        clip = bg_clip.with_audio(audio)
        if clips:
            clip = clip.with_effects([mpe.vfx.CrossFadeIn(_XFADE)])
        clips.append(clip)
        total = projected

    final = (clips[0] if len(clips) == 1
             else mpe.concatenate_videoclips(clips, method="compose", padding=-_XFADE))

    # ── Outro: LIKE + SUBSCRIBE engagement card ───────────────────────────────
    outro_clip = _ken_burns_clip(_outro_frame(locale), OUTRO_SECONDS, move_index=0,
                                 out_size=(SHORTS_WIDTH, SHORTS_HEIGHT))
    outro_clip = outro_clip.with_effects([mpe.vfx.CrossFadeIn(_XFADE)])
    final = mpe.concatenate_videoclips([final, outro_clip], method="compose", padding=-_XFADE)

    # ── Background music (vibe-matched to category, low volume) ──────────────
    music_path = get_music_for_category(category) or (BG_MUSIC_PATH if os.path.exists(BG_MUSIC_PATH) else None)
    if music_path:
        try:
            music = mpe.AudioFileClip(music_path).with_volume_scaled(BG_MUSIC_VOLUME)
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

    # ── Thumbnail: designed composite from this Short's own images ───────────
    thumb_path = str(work / "thumbnail.jpg")
    thumb_images = [p["image"] for p in prepared if p.get("image")][:3]
    try:
        create_short_thumbnail(script, thumb_path, thumb_images, locale, category=category)
    except Exception as e:
        log.warning("Short thumbnail composite failed, falling back to frame capture: %s", e)
        try:
            frame_clip = mpe.VideoFileClip(out_path)
            Image.fromarray(frame_clip.get_frame(0.5)).save(thumb_path, "JPEG", quality=90)
            frame_clip.close()
        except Exception as e2:
            log.warning("Short thumbnail extraction failed: %s", e2)

    return out_path
