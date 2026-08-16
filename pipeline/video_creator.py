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
import math
import os
import re
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import moviepy as mpe

from config import (
    BG_MUSIC_PATH, BG_MUSIC_VOLUME,
    SLIDE_COLORS, VIDEO_FPS, VIDEO_HEIGHT, VIDEO_WIDTH, VIDEO_BITRATE,
)
from pipeline.locales import Locale, category_badge_text, get_locale
from pipeline.logger import log
from pipeline.music_fetcher import get_music_for_category
from pipeline.text_shaping import draw_shaped_text, measure_text_width

VIDEO_CLIP_EXTS = (".mp4", ".mov", ".webm", ".m4v")  # public: also used by scheduler.py to filter thumbnail picks


def _draw_text(image: Image.Image, xy: tuple, text: str, font: ImageFont.FreeTypeFont,
               locale: Locale, fill: tuple, stroke_width: int = 0, stroke_fill: Optional[tuple] = None) -> None:
    """
    Draw on-screen text, routing Devanagari through real OpenType shaping
    (pipeline/text_shaping.py) instead of PIL's naive one-glyph-per-codepoint
    drawing — PIL alone renders Devanagari conjunct consonants as broken
    separate half-forms instead of joined ligatures. Other scripts are
    unaffected and keep using plain PIL drawing. `image` must be RGBA.
    """
    if locale.script == "devanagari":
        draw_shaped_text(image, xy, text, font, fill, stroke_width=stroke_width, stroke_fill=stroke_fill)
    else:
        ImageDraw.Draw(image, "RGBA").text(xy, text, font=font, fill=fill,
                                           stroke_width=stroke_width, stroke_fill=stroke_fill)


def _text_width(text: str, font: ImageFont.FreeTypeFont, locale: Locale) -> float:
    """Real shaped width for Devanagari (see _draw_text); PIL's naive glyph-sum width otherwise."""
    if locale.script == "devanagari":
        return measure_text_width(text, font)
    return font.getbbox(text)[2]


def _resolve_music_path(category: str) -> Optional[str]:
    """Vibe-matched track for this category, falling back to the fixed track."""
    path = get_music_for_category(category)
    if path:
        return path
    return BG_MUSIC_PATH if os.path.exists(BG_MUSIC_PATH) else None

# ─── Multi-script text shaping/wrapping ───────────────────────────────────────
# PIL draws every codepoint left-to-right in logical order with no OpenType
# shaping of its own. Devanagari is handled by real HarfBuzz+FreeType shaping
# at draw time instead (see _draw_text/_text_width above and
# pipeline/text_shaping.py) — PIL can't form conjunct-consonant ligatures on
# its own at all (an older regex-based reordering hack lived here, but it
# could only fix vowel-sign ordering, not ligature formation, so it's gone
# now that real shaping covers both). Arabic needs letter-joining reshaping
# (verified via arabic_reshaper), and Arabic/Hebrew both need their word order
# reversed for correct RTL display (verified via python-bidi's get_display —
# the standard technique for RTL text in non-BiDi-aware renderers); those two
# still go through PIL's plain drawing, unaffected by the Devanagari change.
# CJK/Thai have no spaces between words, so they wrap by character instead.

def _shape_text(text: str, locale: Locale) -> str:
    """
    Prepare one line of already-wrapped text for drawing. Must be called
    per-line, AFTER wrapping — BiDi reordering is only correct within a
    single line/paragraph scope. Devanagari passes through unchanged: real
    shaping (ligatures AND vowel-sign reordering) happens later at draw time
    via _draw_text, which needs the original logical-order text, not a
    pre-reordered string.
    """
    script = locale.script
    if script == "arabic":
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(text))
    if script == "hebrew":
        from bidi.algorithm import get_display
        return get_display(text)
    return text


def _wrap_chars(text: str, font: ImageFont.FreeTypeFont, max_px: int, locale: Optional[Locale] = None) -> list[str]:
    """Character-based wrapping for scripts without spaces (CJK, Thai)."""
    lines, cur = [], ""
    for ch in text:
        test = cur + ch
        width = _text_width(test, font, locale) if locale else font.getbbox(test)[2]
        if width <= max_px:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines


def _wrap_localized(text: str, font: ImageFont.FreeTypeFont, max_px: int, locale: Locale) -> list[str]:
    """Word-wrap (most scripts) or character-wrap (CJK/Thai), by locale."""
    if locale.script_profile.wrap_mode == "char":
        return _wrap_chars(text, font, max_px, locale)
    return _wrap(text, font, max_px, locale)


def _shaped_lines(text: str, font: ImageFont.FreeTypeFont, max_px: int, locale: Locale) -> list[str]:
    """Wrap (locale-aware width) then apply per-line BiDi shaping (Arabic/Hebrew);
    Devanagari's real ligature/reordering shaping happens later, at draw time."""
    return [_shape_text(line, locale) for line in _wrap_localized(text, font, max_px, locale)]


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


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_px: int, locale: Optional[Locale] = None) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for word in words:
        test = f"{cur} {word}".strip()
        width = _text_width(test, font, locale) if locale else font.getbbox(test)[2]
        if width <= max_px:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


# ─── Ken Burns motion ─────────────────────────────────────────────────────────

_KB_OVERSCAN = 1.18   # source frames are rendered this much larger than 1080p
_KB_ZOOM     = 1.12   # maximum zoom travel within the oversized frame
_XFADE       = 0.6    # crossfade duration between slides/sections (seconds)

# Cycled deterministically so consecutive slides never repeat the same move
_KB_MOVES = ["zoom_in", "pan_lr", "zoom_out", "diag_dr", "pan_rl", "diag_ul"]


def _ken_burns_clip(oversized: np.ndarray, duration: float, move_index: int,
                    out_size: tuple[int, int] = (VIDEO_WIDTH, VIDEO_HEIGHT)) -> mpe.VideoClip:
    """
    Animate a slow zoom/pan over an oversized frame, cropping a moving
    out_size window per frame. PIL's resize(box=...) gives subpixel-accurate
    crops, so the motion stays smooth at 24 fps.
    """
    out_w, out_h = out_size
    h2, w2 = oversized.shape[:2]
    move = _KB_MOVES[move_index % len(_KB_MOVES)]
    img = Image.fromarray(oversized)

    max_cw, max_ch = float(w2), float(h2)                 # fully zoomed out
    min_cw, min_ch = w2 / _KB_ZOOM, h2 / _KB_ZOOM         # fully zoomed in

    def _window(p: float) -> tuple[float, float, float, float]:
        if move == "zoom_in":
            cw = max_cw + (min_cw - max_cw) * p
            ch = max_ch + (min_ch - max_ch) * p
            cx, cy = w2 / 2, h2 / 2
        elif move == "zoom_out":
            cw = min_cw + (max_cw - min_cw) * p
            ch = min_ch + (max_ch - min_ch) * p
            cx, cy = w2 / 2, h2 / 2
        else:
            cw, ch = min_cw, min_ch   # fixed slight zoom while traveling
            if move == "pan_lr":
                cx, cy = cw / 2 + (w2 - cw) * p, h2 / 2
            elif move == "pan_rl":
                cx, cy = w2 - cw / 2 - (w2 - cw) * p, h2 / 2
            elif move == "diag_dr":
                cx, cy = cw / 2 + (w2 - cw) * p, ch / 2 + (h2 - ch) * p
            else:  # diag_ul
                cx, cy = w2 - cw / 2 - (w2 - cw) * p, h2 - ch / 2 - (h2 - ch) * p
        left = min(max(cx - cw / 2, 0.0), w2 - cw)
        top  = min(max(cy - ch / 2, 0.0), h2 - ch)
        return (left, top, left + cw, top + ch)

    def _frame(t: float) -> np.ndarray:
        p = min(max(t / duration, 0.0), 1.0) if duration > 0 else 0.0
        p = p * p * (3 - 2 * p)   # smoothstep ease in-out
        out = img.resize((out_w, out_h), Image.BILINEAR, box=_window(p))
        return np.array(out)

    return mpe.VideoClip(_frame, duration=duration).with_fps(VIDEO_FPS)


def _video_cover_clip(path: str, duration: float, size: tuple[int, int]) -> Optional[mpe.VideoClip]:
    """
    Load a stock video clip, mute it, loop/trim to duration, and scale +
    center-crop it to exactly fill size (cover-fit, same idea as _cover_crop
    for still images). Returns None if the file can't be used as video.
    """
    w, h = size
    try:
        clip = mpe.VideoFileClip(path).without_audio()
        if clip.duration <= 0:
            clip.close()
            return None
        if clip.duration < duration:
            loops = int(duration / clip.duration) + 1
            clip = mpe.concatenate_videoclips([clip] * loops)
        clip = clip.subclipped(0, duration)

        scale = max(w / clip.w, h / clip.h)
        clip = clip.resized(scale)
        x1 = (clip.w - w) / 2
        y1 = (clip.h - h) / 2
        clip = clip.cropped(x1=x1, y1=y1, x2=x1 + w, y2=y1 + h)
        return clip.with_fps(VIDEO_FPS)
    except Exception as exc:
        log.warning("Video clip background failed (%s): %s", path, exc)
        return None


def _card_motion_clip(card: np.ndarray, duration: float) -> mpe.VideoClip:
    """Gentle push-in for full-frame cards (title/outro): upscale once, zoom in."""
    ow = int(VIDEO_WIDTH * _KB_OVERSCAN)
    oh = int(VIDEO_HEIGHT * _KB_OVERSCAN)
    oversized = np.array(Image.fromarray(card).resize((ow, oh), Image.LANCZOS))
    return _ken_burns_clip(oversized, duration, move_index=0)  # zoom_in


# ─── Engagement icons (subscribe/like/bell) ───────────────────────────────────
# Public: also used by shorts_creator.py to draw a matching outro on Shorts.

def draw_bell_icon(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int,
                   color: tuple = (255, 255, 255)) -> None:
    """Simple bell silhouette centered at (cx, cy) with 'radius' r."""
    draw.pieslice([cx - r, cy - r, cx + r, cy + int(r * 0.25)], 180, 360, fill=color)
    draw.rectangle([cx - r, cy - int(r * 0.05), cx + r, cy + int(r * 0.55)], fill=color)
    draw.polygon([
        (cx - r, cy + int(r * 0.55)), (cx + r, cy + int(r * 0.55)),
        (cx + int(r * 1.3), cy + int(r * 0.9)), (cx - int(r * 1.3), cy + int(r * 0.9)),
    ], fill=color)
    draw.rectangle([cx - int(r * 0.22), cy + int(r * 0.9), cx + int(r * 0.22), cy + int(r * 1.15)], fill=color)
    draw.ellipse([cx - int(r * 0.22), cy + int(r * 1.08), cx + int(r * 0.22), cy + int(r * 1.5)], fill=color)


def draw_thumbsup_icon(canvas: Image.Image, cx: int, cy: int, r: int,
                       color: tuple = (255, 255, 255)) -> None:
    """Simplified thumbs-up glyph (fist + rotated thumb) composited onto canvas (RGB or RGBA)."""
    fw, fh = int(r * 1.5), int(r * 1.15)
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    fx0, fy0 = cx - fw // 2, cy - int(r * 0.1)
    ld.rounded_rectangle([fx0, fy0, fx0 + fw, fy0 + fh], radius=int(fh * 0.3), fill=color)

    tw, th = int(r * 0.55), int(r * 1.3)
    thumb = Image.new("RGBA", (tw * 3, th * 2), (0, 0, 0, 0))
    td = ImageDraw.Draw(thumb)
    td.rounded_rectangle([tw, 0, tw * 2, th], radius=tw // 2, fill=color)
    thumb = thumb.rotate(-24, resample=Image.BICUBIC, expand=True)
    layer.paste(thumb, (fx0 - thumb.width // 4, fy0 - int(th * 0.55)), thumb)

    if canvas.mode == "RGBA":
        canvas.alpha_composite(layer)
    else:
        canvas.paste(layer, (0, 0), layer)


def draw_bell_icon_rotated(canvas: Image.Image, cx: int, cy: int, r: int, angle_deg: float,
                           color: tuple = (255, 255, 255)) -> None:
    """
    Same silhouette as draw_bell_icon, rotated angle_deg around its own
    center — used for the outro's periodic 'ring' animation. canvas must be
    RGBA (drawn via alpha_composite onto it).
    """
    if abs(angle_deg) < 0.05:
        draw_bell_icon(ImageDraw.Draw(canvas, "RGBA"), cx, cy, r, color)
        return
    half = int(r * 2.2)
    layer = Image.new("RGBA", (half * 2, half * 2), (0, 0, 0, 0))
    draw_bell_icon(ImageDraw.Draw(layer, "RGBA"), half, half, r, color)
    rotated = layer.rotate(-angle_deg, resample=Image.BICUBIC, center=(half, half))
    canvas.alpha_composite(rotated, (cx - half, cy - half))


# ─── Outro: glassmorphic engagement row ───────────────────────────────────────
# Frosted-glass LIKE/SUBSCRIBE cards (blurred-background panel + translucent
# tint + soft colored glow + thin bright border) instead of flat solid-fill
# shapes, plus small independent motions on top: an entrance fade, a
# continuous glow pulse behind SUBSCRIBE, a periodic bell ring, and a
# periodic thumbs-up bump (phase-offset from the bell so nothing moves in
# lockstep). The glass panels themselves are static (baked into the
# background once — re-blurring per frame at 24fps would be far too slow),
# only the icons/text/glow-pulse animate frame to frame.

def _ease_out_cubic(p: float) -> float:
    p = min(max(p, 0.0), 1.0)
    return 1 - (1 - p) ** 3


def _bell_ring_angle(t: float) -> float:
    """Rings (rapid decaying wiggle) for 0.6s every 2.2s, resting otherwise."""
    cycle, burst = 2.2, 0.6
    local_t = t % cycle
    if local_t >= burst:
        return 0.0
    envelope = 1.0 - local_t / burst
    return 16.0 * math.sin(local_t * 2 * math.pi * 5) * envelope


def _thumb_bump_scale(t: float) -> float:
    """Quick 'punch' pulse, phase-offset from the bell ring above."""
    cycle, bump_dur = 2.4, 0.35
    local_t = (t + 1.1) % cycle
    if local_t >= bump_dur:
        return 1.0
    p = local_t / bump_dur
    return 1.0 + 0.22 * math.sin(p * math.pi)


def _glow_pulse_alpha(t: float) -> float:
    """Slow continuous glow-ring pulse around SUBSCRIBE — the 'breathing' cue,
    done as a cheap per-frame alpha ring instead of re-blurring the panel."""
    return 0.4 + 0.4 * (0.5 + 0.5 * math.sin(2 * math.pi * t / 1.8))


def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], radius=radius, fill=255)
    return m


def _glass_panel(
    bg_rgba: Image.Image, box: tuple, radius: int, blur: int = 22,
    tint: tuple = (255, 255, 255, 46), border: tuple = (255, 255, 255, 150),
    glow_color: tuple = (130, 170, 255), glow_alpha: int = 85,
) -> Image.Image:
    """
    One frosted-glass panel: a blurred crop of bg_rgba shows through a
    translucent rounded shape, with a bright thin border and a soft colored
    glow bleeding outward behind it. Returns an RGBA layer the same size as
    bg_rgba with only this panel drawn (transparent elsewhere) — composite
    it onto the scene with alpha_composite.
    """
    x0, y0, x1, y1 = box
    size = bg_rgba.size
    pad = blur * 2

    glow = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).rounded_rectangle(
        [x0 - pad // 2, y0 - pad // 2, x1 + pad // 2, y1 + pad // 2],
        radius=radius + pad // 2, fill=(*glow_color, glow_alpha),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(pad))

    crop_box = (max(0, x0 - pad), max(0, y0 - pad), min(size[0], x1 + pad), min(size[1], y1 + pad))
    blurred_crop = bg_rgba.crop(crop_box).filter(ImageFilter.GaussianBlur(blur))
    blurred_full = Image.new("RGBA", size, (0, 0, 0, 0))
    blurred_full.paste(blurred_crop, (crop_box[0], crop_box[1]))

    mask_full = Image.new("L", size, 0)
    mask_full.paste(_rounded_mask((x1 - x0, y1 - y0), radius), (x0, y0))

    transparent = Image.new("RGBA", size, (0, 0, 0, 0))
    panel = Image.composite(blurred_full, transparent, mask_full)
    tint_layer = Image.composite(Image.new("RGBA", size, tint), transparent, mask_full)
    panel.alpha_composite(tint_layer)
    ImageDraw.Draw(panel).rounded_rectangle([x0, y0, x1, y1], radius=radius, outline=border, width=3)

    glow.alpha_composite(panel)
    return glow


def draw_engagement_row_animated(canvas: Image.Image, locale: Locale, cy: int, t: float,
                                 f_label: ImageFont.FreeTypeFont, f_sub: ImageFont.FreeTypeFont,
                                 scale: float = 1.0) -> None:
    """
    Animated LIKE + SUBSCRIBE row content (icons + labels only — the glass
    panels behind them are baked into the background separately, see
    _outro_clip_animated). Bell rings on a beat, thumb bumps on its own
    offset beat, SUBSCRIBE gets a pulsing glow ring. canvas must already be
    RGBA (a fresh transparent per-frame layer); f_label/f_sub are pre-loaded
    fonts (loading a font is too slow to redo every frame at 24fps).
    """
    W = canvas.width
    draw = ImageDraw.Draw(canvas, "RGBA")

    fade = _ease_out_cubic(min(1.0, t / 0.4))
    bump = _thumb_bump_scale(t)
    ring_angle = _bell_ring_angle(t)
    glow_a = _glow_pulse_alpha(t) * fade

    def _fa(rgb: tuple, a: int = 255) -> tuple:
        return (*rgb, int(a * fade))

    # LIKE — glass panel already drawn; just the thumb glyph (bumping) + label.
    like_r = int(58 * scale)
    like_cx = W // 2 - int(190 * scale)
    icon_r = int(26 * scale * bump)
    draw_thumbsup_icon(canvas, like_cx, cy - int(6 * scale), icon_r, color=_fa((255, 255, 255)))
    like_label = "LIKE"
    lw = f_label.getbbox(like_label)[2]
    draw.text((like_cx - lw // 2, cy + like_r + 10), like_label, font=f_label,
               fill=_fa((255, 255, 255)), stroke_width=3, stroke_fill=_fa((0, 0, 0)))

    # SUBSCRIBE — glass panel already drawn; pulsing glow ring + bell + label.
    sub_cx = W // 2 + int(60 * scale)
    pill_w, pill_h = int(260 * scale), int(84 * scale)
    px0, py0 = sub_cx - pill_w // 2, cy - pill_h // 2
    draw.rounded_rectangle([px0 - 4, py0 - 4, px0 + pill_w + 4, py0 + pill_h + 4], radius=pill_h // 2 + 4,
                           outline=(255, 90, 90, int(220 * glow_a)), width=3)
    draw_bell_icon_rotated(canvas, px0 + int(46 * scale), cy, int(15 * scale),
                           ring_angle, color=_fa((255, 90, 90)))
    sub_label = "SUBSCRIBE"
    draw.text((px0 + int(78 * scale), cy - f_sub.size // 2 - 4), sub_label, font=f_sub, fill=_fa((255, 255, 255)))


def _outro_clip_animated(
    locale: Locale,
    duration: float,
    size: tuple[int, int],
    title_font_size: int = 66,
    body_font_size: int = 40,
    row_scale: float = 1.5,
    title_y: Optional[int] = None,
    row_cy: Optional[int] = None,
    body_y: Optional[int] = None,
    gradient_colors: tuple = ("#1e1b4b", "#5b21b6"),
) -> mpe.VideoClip:
    """
    Glassmorphic LIKE+SUBSCRIBE outro clip: a vivid gradient background with
    two frosted-glass cards baked in once (blur is too slow to redo at
    24fps), then a fresh transparent foreground redrawn every frame — the
    CTA text fades/slides in, and the engagement row keeps moving (glow
    pulse, ringing bell, bumping thumb) for the rest of the clip. Shared by
    the long-form and Shorts outros — they only differ in canvas
    size/positions/scale, passed in by the caller.
    """
    w, h = size
    title_y = h // 2 - 210 if title_y is None else title_y
    row_cy  = h // 2 - 40  if row_cy  is None else row_cy
    body_y  = h // 2 + 140 if body_y  is None else body_y

    bg = Image.fromarray(_gradient(*gradient_colors, w, h)).convert("RGBA")
    f1 = _load_font(locale.font_bold, title_font_size)
    f2 = _load_font(locale.font_regular, body_font_size)
    f_label = _load_font(locale.font_bold, int(34 * row_scale))
    f_sub = _load_font(locale.font_bold, int(30 * row_scale))
    title_lines = _shaped_lines(locale.subscribe_cta, f1, w - 160, locale)
    body_lines = _shaped_lines(locale.like_share_cta, f2, w - 160, locale)

    # Bake the two frosted-glass cards into the background once.
    like_r = int(58 * row_scale)
    like_cx = w // 2 - int(190 * row_scale)
    like_box = (like_cx - like_r - 16, row_cy - like_r - 16,
               like_cx + like_r + 16, row_cy + like_r + int(46 * row_scale))
    bg.alpha_composite(_glass_panel(bg, like_box, radius=int(34 * row_scale),
                                    tint=(255, 255, 255, 40), glow_color=(160, 180, 255), glow_alpha=70))

    sub_cx = w // 2 + int(60 * row_scale)
    pill_w, pill_h = int(260 * row_scale), int(84 * row_scale)
    sub_box = (sub_cx - pill_w // 2, row_cy - pill_h // 2, sub_cx + pill_w // 2, row_cy + pill_h // 2)
    bg.alpha_composite(_glass_panel(bg, sub_box, radius=pill_h // 2,
                                    tint=(255, 70, 70, 55), glow_color=(255, 90, 90), glow_alpha=90))

    def _frame(t: float) -> np.ndarray:
        fg = Image.new("RGBA", (w, h), (0, 0, 0, 0))

        text_p = _ease_out_cubic(min(1.0, t / 0.4))
        alpha = int(255 * text_p)
        slide = int((1 - text_p) * 30)

        y = title_y + slide
        for line in title_lines:
            lw = _text_width(line, f1, locale)
            _draw_text(fg, ((w - lw) // 2, y), line, f1, locale,
                      fill=(255, 100, 100, alpha), stroke_width=2, stroke_fill=(0, 0, 0, alpha))
            y += int(f1.size * 1.25)

        draw_engagement_row_animated(fg, locale, row_cy, t, f_label, f_sub, scale=row_scale)

        y2 = body_y + slide
        for line in body_lines:
            lw = _text_width(line, f2, locale)
            _draw_text(fg, ((w - lw) // 2, y2), line, f2, locale, fill=(255, 255, 255, alpha))
            y2 += int(f2.size * 1.25)

        composed = bg.copy()
        composed.alpha_composite(fg)
        return np.array(composed.convert("RGB"))

    return mpe.VideoClip(_frame, duration=duration).with_fps(VIDEO_FPS)


# ─── Slide renderers ──────────────────────────────────────────────────────────

def _title_card(title: str, thumbnail_text: str, colors: tuple, locale: Locale) -> np.ndarray:
    bg = Image.fromarray(_gradient(*colors)).convert("RGBA")
    draw = ImageDraw.Draw(bg)
    f_title = _load_font(locale.font_bold, 88)
    f_sub   = _load_font(locale.font_regular, 50)

    lines   = _shaped_lines(title, f_title, VIDEO_WIDTH - 200, locale)
    total_h = len(lines) * 108
    y       = (VIDEO_HEIGHT - total_h) // 2 - 60

    for line in lines:
        w = _text_width(line, f_title, locale)
        _draw_text(bg, ((VIDEO_WIDTH - w) // 2, y), line, f_title, locale,
                  fill=(255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0))
        y += 108

    bar_y = y + 18
    draw.rectangle([(VIDEO_WIDTH // 2 - 220, bar_y),
                    (VIDEO_WIDTH // 2 + 220, bar_y + 4)], fill=(79, 195, 247))

    if thumbnail_text:
        thumbnail_text = _shape_text(thumbnail_text, locale)
        tw = _text_width(thumbnail_text, f_sub, locale)
        _draw_text(bg, ((VIDEO_WIDTH - tw) // 2, bar_y + 20), thumbnail_text, f_sub, locale,
                  fill=(79, 195, 247))

    return np.array(bg.convert("RGB"))


def _section_slide(
    heading: str,
    narration: str,
    bg_path: Optional[str],
    colors: tuple,
    size: tuple[int, int] = (VIDEO_WIDTH, VIDEO_HEIGHT),
) -> np.ndarray:
    """Render one slide frame — clean full-screen image, no text overlay."""
    w, h = size
    if bg_path and os.path.exists(bg_path):
        bg = (Image.open(bg_path).convert("RGBA")
                   .resize((w, h), Image.LANCZOS))
        # Very subtle vignette-only overlay so image stays vibrant
        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 40))
        bg = Image.alpha_composite(bg, overlay).convert("RGB")
    else:
        bg = Image.fromarray(_gradient(*colors, w, h)).convert("RGB")

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
    move_offset: int = 0,
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
    # Crossfades overlap adjacent sub-clips, so stretch each one to compensate
    # and keep the total exactly equal to voice duration + tail.
    sub_dur = (total_dur + _XFADE * (n - 1)) / n

    ow = int(VIDEO_WIDTH * _KB_OVERSCAN)
    oh = int(VIDEO_HEIGHT * _KB_OVERSCAN)

    sub_clips: list[mpe.VideoClip] = []
    for j, img_path in enumerate(images):
        clip = None
        if img_path and img_path.lower().endswith(VIDEO_CLIP_EXTS):
            clip = _video_cover_clip(img_path, sub_dur, (VIDEO_WIDTH, VIDEO_HEIGHT))

        if clip is None:
            frame = _section_slide(
                section["heading"],
                section["narration"],
                img_path,
                color_pair,
                size=(ow, oh),
            )
            clip = _ken_burns_clip(frame, sub_dur, move_index=move_offset + j)

        if j > 0:
            clip = clip.with_effects([mpe.vfx.CrossFadeIn(_XFADE)])
        sub_clips.append(clip)

    # Concatenate sub-clips (overlapping by the crossfade), then attach audio
    if len(sub_clips) == 1:
        section_video = sub_clips[0]
    else:
        section_video = mpe.concatenate_videoclips(
            sub_clips, method="compose", padding=-_XFADE
        )

    return section_video.with_audio(audio)


# ─── Public API ───────────────────────────────────────────────────────────────

def _cover_crop(img: Image.Image, w: int, h: int) -> Image.Image:
    """Scale + center-crop an image to exactly fill (w, h)."""
    scale = max(w / img.width, h / img.height)
    nw, nh = int(img.width * scale + 0.5), int(img.height * scale + 0.5)
    img = img.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - w) // 2, (nh - h) // 2
    return img.crop((left, top, left + w, top + h))


def _diagonal_stamp(canvas: Image.Image, text: str, font: ImageFont.FreeTypeFont,
                    color: tuple, cx: int, cy: int, locale: Locale, angle: float = -14) -> None:
    """Paste a rotated 'impact stamp' ribbon (colored bg + white bold text) onto canvas."""
    pad_x, pad_y = 34, 16
    tb = font.getbbox(text)
    tw, th = int(_text_width(text, font, locale)), tb[3] - tb[1]
    ribbon = Image.new("RGBA", (tw + pad_x * 2, th + pad_y * 2), (0, 0, 0, 0))
    rd = ImageDraw.Draw(ribbon)
    rd.rectangle([(0, 0), (ribbon.width, ribbon.height)], fill=(*color, 235))
    rd.rectangle([(0, 0), (ribbon.width, ribbon.height)], outline=(255, 255, 255, 220), width=3)
    _draw_text(ribbon, (pad_x - tb[0], pad_y - tb[1]), text, font, locale, fill=(255, 255, 255, 255))
    ribbon = ribbon.rotate(angle, expand=True, resample=Image.BICUBIC)

    # Drop shadow
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow.paste(Image.new("RGBA", ribbon.size, (0, 0, 0, 110)), (cx - ribbon.width // 2 + 6, cy - ribbon.height // 2 + 6), ribbon)
    canvas.alpha_composite(shadow) if canvas.mode == "RGBA" else canvas.paste(shadow, (0, 0), shadow)

    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    layer.paste(ribbon, (cx - ribbon.width // 2, cy - ribbon.height // 2), ribbon)
    if canvas.mode == "RGBA":
        canvas.alpha_composite(layer)
    else:
        canvas.paste(layer, (0, 0), layer)


def _paste_presenter(canvas: Image.Image, cutout_path: str, w: int, h: int) -> int:
    """
    Composite the cached AI-presenter cutout bottom-right, scaled to fit the
    frame height, arms-crossed waist-up. Returns the x-coordinate where the
    presenter's silhouette starts (so callers can keep text clear of it) —
    or `w` (no reserved space) if the cutout can't be loaded.
    """
    try:
        person = Image.open(cutout_path).convert("RGBA")
    except Exception:
        return w
    target_h = int(h * 0.92)
    scale = target_h / person.height
    person = person.resize((int(person.width * scale), target_h), Image.LANCZOS)
    px = w - person.width + int(person.width * 0.08)  # bleed slightly off the right edge
    py = h - person.height
    canvas.alpha_composite(person, (px, py))
    return px


def _banner_text(canvas: Image.Image, xy: tuple, text: str, font: ImageFont.FreeTypeFont,
                 locale: Locale, text_color: tuple, banner_color: Optional[tuple] = None,
                 max_width: Optional[int] = None, pad_x: int = 18, pad_y: int = 10) -> None:
    """
    One headline line, styled like a real news thumbnail: either a solid
    color banner block behind bold text, or bold text with a heavy black
    stroke directly on the image — matching the two treatments professional
    thumbnails mix (a colored "chip" behind the key phrase, plain punchy
    text elsewhere).
    """
    x, y = xy
    w = int(_text_width(text, font, locale))
    if max_width:
        w = min(w, max_width)
    if banner_color is not None:
        ImageDraw.Draw(canvas, "RGBA").rectangle(
            [x - pad_x, y - pad_y, x + w + pad_x, y + font.size + pad_y], fill=banner_color
        )
        _draw_text(canvas, (x, y), text, font, locale, fill=text_color)
    else:
        _draw_text(canvas, (x, y), text, font, locale, fill=text_color, stroke_width=6, stroke_fill=(0, 0, 0))


def create_thumbnail(script: dict, output_path: str,
                     image_paths: Optional[list[str]] = None,
                     locale: Optional[Locale] = None,
                     category_color: str = "",
                     category: str = "") -> str:
    """
    Render a punchy, tabloid-news-style composite thumbnail (1280×720):
    2-3 of the video's own images side by side, a top badge banner, a
    rotated "impact stamp", the AI presenter cutout bottom-right, and a
    bold multi-line headline (a banner-block "chip" line + a plain
    heavy-stroke line) kept clear of the presenter, in the given locale's
    script/font. Falls back to the plain title card when no images are
    available. `category_color` (a hex string, e.g. from topic_config.json)
    tints the accent rule/chip so the design responds to the video's topic;
    the dominant red/black/yellow palette stays fixed for consistent punch.
    """
    locale = locale or get_locale(None)
    W, H = 1280, 720
    accent = _hex_to_rgb(category_color) if re.fullmatch(r"#?[0-9A-Fa-f]{6}", category_color or "") else (79, 195, 247)
    RED = (214, 24, 24)

    # Video clips can't be opened as still images — only real image files apply here.
    images = [
        p for p in (image_paths or [])
        if p and os.path.exists(p) and not p.lower().endswith(VIDEO_CLIP_EXTS)
    ]

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    if not images:
        # Fallback: old gradient title card
        arr = _title_card(script["title"], script.get("thumbnail_text", ""), SLIDE_COLORS[0], locale)
        Image.fromarray(arr).resize((W, H), Image.LANCZOS).save(
            output_path, "JPEG", quality=92, optimize=True)
        log.info("Thumbnail saved (gradient fallback) → %s", output_path)
        return output_path

    canvas = Image.new("RGBA", (W, H), (10, 10, 14, 255))

    # ── Photo composite: 1 image = full bleed; 2 = 60/40 split; 3+ = main + 2 stacked
    if len(images) == 1:
        canvas.paste(_cover_crop(Image.open(images[0]).convert("RGB"), W, H), (0, 0))
    elif len(images) == 2:
        split = int(W * 0.58)
        canvas.paste(_cover_crop(Image.open(images[0]).convert("RGB"), split, H), (0, 0))
        canvas.paste(_cover_crop(Image.open(images[1]).convert("RGB"), W - split, H), (split, 0))
    else:
        split = int(W * 0.58)
        canvas.paste(_cover_crop(Image.open(images[0]).convert("RGB"), split, H), (0, 0))
        half = H // 2
        canvas.paste(_cover_crop(Image.open(images[1]).convert("RGB"), W - split, half), (split, 0))
        canvas.paste(_cover_crop(Image.open(images[2]).convert("RGB"), W - split, H - half), (split, half))

    draw = ImageDraw.Draw(canvas, "RGBA")

    # Red separator bars between panels
    if len(images) >= 2:
        split = int(W * 0.58)
        draw.rectangle([(split - 3, 0), (split + 3, H)], fill=RED)
        if len(images) >= 3:
            draw.rectangle([(split, H // 2 - 3), (W, H // 2 + 3)], fill=RED)

    # Dark gradient over the top strip and bottom half for banner legibility
    grad = Image.new("L", (1, H), 0)
    for y in range(H):
        bottom_p = max(0.0, (y / H - 0.42) / 0.58)
        top_p = max(0.0, 1 - y / 92) if y < 92 else 0.0
        grad.putpixel((0, y), int(210 * max(bottom_p, top_p * 0.85)))
    alpha = grad.resize((W, H))
    black = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    canvas = Image.composite(black, canvas, alpha)
    draw = ImageDraw.Draw(canvas, "RGBA")

    # ── Top banner: full-width badge strip with a topic-colored underline ────
    f_badge = _load_font(locale.font_bold, 34)
    badge_txt = _shape_text(category_badge_text(category, locale), locale)
    bw = _text_width(badge_txt, f_badge, locale)
    draw.rectangle([(0, 0), (W, 6)], fill=accent)
    draw.rectangle([(28, 20), (28 + int(bw) + 36, 78)], fill=RED)
    _draw_text(canvas, (46, 26), badge_txt, f_badge, locale, fill=(255, 255, 255))

    # ── AI presenter cutout, bottom-right — keeps the headline block clear
    # of it (matches how professional news-Shorts thumbnails reserve one
    # side for the anchor figure). Skipped gracefully if unavailable.
    presenter_x = W
    try:
        from pipeline.presenter import get_presenter_cutout
        cutout_path = get_presenter_cutout()
        if cutout_path:
            presenter_x = _paste_presenter(canvas, cutout_path, W, H)
    except Exception as exc:
        log.warning("Presenter cutout skipped: %s", exc)
    draw = ImageDraw.Draw(canvas, "RGBA")

    # Diagonal impact stamp (top-right corner) — only when there's no
    # presenter occupying that corner; the two visually collide otherwise.
    if presenter_x >= W:
        _diagonal_stamp(canvas, badge_txt, f_badge, RED, cx=W - 130, cy=140, locale=locale, angle=-16)

    # Headline block: up to 3 lines in the space left of the presenter, one
    # line rendered as a solid-color "chip" (the key/shocking phrase), the
    # rest as bold heavy-stroke text directly on the image.
    text = (script.get("thumbnail_text") or script.get("title", "")).strip()
    max_w = int(presenter_x * 0.94) - 46

    f_head = _load_font(locale.font_bold, 76)
    lines: list[str] = []
    for size in range(76, 38, -4):
        f_head = _load_font(locale.font_bold, size)
        lines = _shaped_lines(text, f_head, max_w, locale)[:3]
        if len(lines) <= 3 and all(_text_width(l, f_head, locale) <= max_w for l in lines):
            break

    line_h = int(f_head.size * 1.5)
    total_h = line_h * len(lines)
    y = max(150, (H - total_h) // 2)
    chip_line = len(lines) - 1  # the last line gets the color-chip treatment

    for i, line in enumerate(lines):
        if i == chip_line:
            _banner_text(canvas, (46, y), line, f_head, locale,
                        text_color=(255, 255, 255), banner_color=(*accent, 255), max_width=max_w)
        else:
            _banner_text(canvas, (46, y), line, f_head, locale, text_color=(255, 214, 0))
        y += line_h

    canvas.convert("RGB").save(output_path, "JPEG", quality=92, optimize=True)
    log.info("Thumbnail saved (news composite, %d images) → %s", len(images), output_path)
    return output_path


def _format_timestamp(total_seconds: float) -> str:
    """Format seconds as YouTube chapter-marker text: "M:SS"."""
    total_seconds = max(0, int(round(total_seconds)))
    m, s = divmod(total_seconds, 60)
    return f"{m}:{s:02d}"


def _compute_chapter_offsets(
    section_headings: list,
    section_durations: list,
    title_card_seconds: float = 5.0,
    xfade_seconds: float = _XFADE,
    tail_seconds: float = 0.8,
    min_chapter_seconds: float = 10.0,
) -> list:
    """
    Pure function: compute chapter (start_seconds, heading) pairs matching
    create_video's actual clip timeline (title card + non-skipped sections,
    each transition overlapped by xfade_seconds).

    The title card has no chapter of its own -- it is too short (5s) to ever
    satisfy min_chapter_seconds, so its time is folded into the first
    section's chapter, which is always forced to start at 0:00 (YouTube
    requires the first chapter marker at 0:00). Any later chapter that would
    start less than min_chapter_seconds after the previous kept chapter is
    dropped (merged into the previous chapter).
    """
    included = [title_card_seconds]
    kept_headings = []
    for heading, dur in zip(section_headings, section_durations):
        if dur:
            included.append(dur + tail_seconds)
            kept_headings.append(heading)

    if not kept_headings:
        return [(0.0, section_headings[0] if section_headings else "")]

    starts = []
    cum = 0.0
    for k in range(len(included)):
        starts.append(cum - k * xfade_seconds)
        cum += included[k]
    section_starts = starts[1:]  # one per kept section, in order

    chapters = [(0.0, kept_headings[0])]
    for heading, start in zip(kept_headings[1:], section_starts[1:]):
        if start - chapters[-1][0] >= min_chapter_seconds:
            chapters.append((start, heading))
    return chapters


def _voice_durations(voices: list) -> list:
    """Real clip duration (seconds) per voice file, None where missing/unreadable."""
    durations = []
    for v in voices:
        if v and os.path.exists(v):
            try:
                clip = mpe.AudioFileClip(v)
                durations.append(clip.duration)
                clip.close()
            except Exception:
                durations.append(None)
        else:
            durations.append(None)
    return durations


def build_chapters(script: dict, voices: list, title_card_seconds: float = 5.0) -> str:
    """
    Read each section's real voice-clip duration and format YouTube chapter
    markers as a plain text block ("M:SS heading" per line). Long-form only
    — YouTube Shorts do not support chapters.
    """
    sections = script.get("sections", [])
    headings = [s.get("heading", "") for s in sections]
    durations = _voice_durations(voices)
    offsets = _compute_chapter_offsets(headings, durations, title_card_seconds=title_card_seconds)
    return "\n".join(f"{_format_timestamp(t)} {h}" for t, h in offsets)


def _compute_section_windows(
    section_texts: list, section_durations: list,
    title_card_seconds: float = 5.0, xfade_seconds: float = _XFADE, tail_seconds: float = 0.8,
) -> list:
    """
    Pure function: (start_seconds, end_seconds, text) for every section that
    has a real voice duration, using the exact same timeline math as
    _compute_chapter_offsets — but WITHOUT merging short sections together,
    since captions must line up with the real spoken audio rather than being
    simplified for display the way chapter markers are.
    """
    included = [title_card_seconds]
    kept = []
    for text, dur in zip(section_texts, section_durations):
        if dur:
            included.append(dur + tail_seconds)
            kept.append((text, dur))
    if not kept:
        return []

    starts = []
    cum = 0.0
    for k in range(len(included)):
        starts.append(cum - k * xfade_seconds)
        cum += included[k]
    section_starts = starts[1:]

    return [(start, start + dur, text) for (text, dur), start in zip(kept, section_starts)]


def _format_srt_timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    whole = int(seconds)
    h, rem = divmod(whole, 3600)
    m, s = divmod(rem, 60)
    ms = int(round((seconds - whole) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_captions_srt(script: dict, voices: list, title_card_seconds: float = 5.0) -> str:
    """
    Real timed captions (SRT) built from each section's actual voice-clip
    duration and narration text — reuses the same timeline math as
    build_chapters, so captions line up with the rendered video exactly.
    Long-form only. Coarse-grained (one cue per section, not per sentence) —
    still real, accurate timing, without needing a separate forced-alignment
    tool. Returns "" if no section has a usable voice duration.
    """
    sections = script.get("sections", [])
    texts = [s.get("narration", "") for s in sections]
    durations = _voice_durations(voices)

    windows = _compute_section_windows(texts, durations, title_card_seconds=title_card_seconds)
    if not windows:
        return ""

    lines = []
    for i, (start, end, text) in enumerate(windows, start=1):
        lines.append(str(i))
        lines.append(f"{_format_srt_timestamp(start)} --> {_format_srt_timestamp(end)}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def create_video(
    script: dict,
    voice_files: list[str],
    bg_images: list[list[Optional[str]]],
    output_path: str,
    category: str = "",
    locale: Optional[Locale] = None,
) -> str:
    """
    Render the complete video and write to output_path.

    bg_images: list[list[str|None]] — one inner list per section,
               each inner list contains paths to multiple background images
               that will be cycled through during that section.
               (Backward-compat: a flat list[str|None] is also accepted and
               wrapped automatically so old callers don't break.)
    locale: drives on-screen text font/script/wrap + outro CTA text.
            Defaults to Hindi/India if not given.
    """
    locale = locale or get_locale(None)
    sections = script["sections"]

    # Backward-compat: if caller passes flat list[str|None], wrap each item
    if bg_images and not isinstance(bg_images[0], list):
        bg_images = [[img] for img in bg_images]  # type: ignore[assignment]

    clips: list[mpe.VideoClip] = []

    # ── 1. Title card (5 s, no voice, gentle push-in) ─────────────────────────
    title_arr = _title_card(
        script["title"],
        script.get("thumbnail_text", ""),
        SLIDE_COLORS[0],
        locale,
    )
    clips.append(_card_motion_clip(title_arr, 5))

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

        section_clip = _build_section_clip(
            section, vpath, img_list, color_pair, move_offset=i
        )
        clips.append(section_clip)

    # ── 3. Outro (5 s, no voice, animated engagement row) ─────────────────────
    clips.append(_outro_clip_animated(locale, 5, (VIDEO_WIDTH, VIDEO_HEIGHT)))

    # ── 4. Concatenate with crossfades between all top-level clips ───────────
    # Sections carry a 0.8 s silent tail, so the 0.6 s overlap never clips voice.
    clips = [
        c if k == 0 else c.with_effects([mpe.vfx.CrossFadeIn(_XFADE)])
        for k, c in enumerate(clips)
    ]
    final = mpe.concatenate_videoclips(clips, method="compose", padding=-_XFADE)

    # ── 5. Background music (vibe-matched to category, optional) ─────────────
    music_path = _resolve_music_path(category)
    if music_path:
        try:
            music = (
                mpe.AudioFileClip(music_path)
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
