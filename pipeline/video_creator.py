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
import re
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

# ─── Devanagari rendering fix ─────────────────────────────────────────────────
# Pillow only fully shapes complex scripts (Devanagari, Arabic, ...) when the
# optional `raqm` library is available; without it (the case on this machine —
# see PIL.features.check("raqm")), PIL draws every codepoint in strict logical
# order. Empirically (tested against this font), Pillow already positions े and
# ै correctly, but NOT ि (U+093F): it's stored AFTER its consonant(cluster) in
# Unicode but must be drawn BEFORE it, so naive rendering garbles any word
# containing it (e.g. "मिडल" -> "मडिल"). Swapping it into visual order here
# (only for rendering, never for stored script text) fixes this without an
# external library. Do NOT add े/ै here — they already render correctly and
# swapping them breaks them.
_DEVANAGARI_CONSONANT = r"[क-हक़-य़]"
_PREBASE_MATRA_RE = re.compile(
    rf"((?:{_DEVANAGARI_CONSONANT}्)*{_DEVANAGARI_CONSONANT})(ि)"
)


def _fix_devanagari(text: str) -> str:
    """Reorder Devanagari pre-base vowel signs for correct rendering without raqm."""
    return _PREBASE_MATRA_RE.sub(lambda m: m.group(2) + m.group(1), text)


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


def _card_motion_clip(card: np.ndarray, duration: float) -> mpe.VideoClip:
    """Gentle push-in for full-frame cards (title/outro): upscale once, zoom in."""
    ow = int(VIDEO_WIDTH * _KB_OVERSCAN)
    oh = int(VIDEO_HEIGHT * _KB_OVERSCAN)
    oversized = np.array(Image.fromarray(card).resize((ow, oh), Image.LANCZOS))
    return _ken_burns_clip(oversized, duration, move_index=0)  # zoom_in


# ─── Slide renderers ──────────────────────────────────────────────────────────

def _title_card(title: str, thumbnail_text: str, colors: tuple) -> np.ndarray:
    bg = Image.fromarray(_gradient(*colors)).convert("RGB")
    draw = ImageDraw.Draw(bg)
    f_title = _load_font(HINDI_FONT_BOLD, 88)
    f_sub   = _load_font(HINDI_FONT_REGULAR, 50)

    lines   = [_fix_devanagari(l) for l in _wrap(title, f_title, VIDEO_WIDTH - 200)]
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
        thumbnail_text = _fix_devanagari(thumbnail_text)
        tw = f_sub.getbbox(thumbnail_text)[2]
        draw.text(((VIDEO_WIDTH - tw) // 2, bar_y + 20), thumbnail_text,
                  font=f_sub, fill=(79, 195, 247))

    return np.array(bg)


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


def _outro_card() -> np.ndarray:
    bg   = Image.fromarray(_gradient("#000428", "#004e92")).convert("RGB")
    draw = ImageDraw.Draw(bg)
    f1   = _load_font(HINDI_FONT_BOLD, 78)
    f2   = _load_font(HINDI_FONT_REGULAR, 48)

    msg1 = _fix_devanagari("चैनल को Subscribe करें")
    msg2 = _fix_devanagari("Like, Share और घंटी दबाना न भूलें!")

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


def create_thumbnail(script: dict, output_path: str,
                     image_paths: Optional[list[str]] = None) -> str:
    """
    Render a dramatic news-style composite thumbnail (1280×720):
    2-3 of the video's own images side by side, dark bottom gradient,
    bold two-line Hindi text (white + yellow) with red accents.
    Falls back to the plain title card when no images are available.
    """
    W, H = 1280, 720
    images = [p for p in (image_paths or []) if p and os.path.exists(p)]

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    if not images:
        # Fallback: old gradient title card
        arr = _title_card(script["title"], script.get("thumbnail_text", ""), SLIDE_COLORS[0])
        Image.fromarray(arr).resize((W, H), Image.LANCZOS).save(
            output_path, "JPEG", quality=92, optimize=True)
        log.info("Thumbnail saved (gradient fallback) → %s", output_path)
        return output_path

    canvas = Image.new("RGB", (W, H), (10, 10, 14))

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
        draw.rectangle([(split - 3, 0), (split + 3, H)], fill=(220, 30, 30))
        if len(images) >= 3:
            draw.rectangle([(split, H // 2 - 3), (W, H // 2 + 3)], fill=(220, 30, 30))

    # Dark gradient over the bottom half for text legibility
    grad = Image.new("L", (1, H), 0)
    for y in range(H):
        p = max(0.0, (y / H - 0.42) / 0.58)
        grad.putpixel((0, y), int(210 * p))
    alpha = grad.resize((W, H))
    black = Image.new("RGB", (W, H), (0, 0, 0))
    canvas = Image.composite(black, canvas, alpha)
    draw = ImageDraw.Draw(canvas, "RGBA")

    # "BREAKING" style badge top-left
    f_badge = _load_font(HINDI_FONT_BOLD, 34)
    badge_txt = _fix_devanagari("बड़ी खबर")
    bw = f_badge.getbbox(badge_txt)[2]
    draw.rectangle([(28, 26), (28 + bw + 36, 84)], fill=(210, 20, 20))
    draw.text((46, 32), badge_txt, font=f_badge, fill=(255, 255, 255))

    # Two-line headline: line 1 white, line 2 yellow — split thumbnail_text
    text = (script.get("thumbnail_text") or script.get("title", "")).strip()
    words = text.split()
    mid = max(1, (len(words) + 1) // 2)
    line1 = _fix_devanagari(" ".join(words[:mid]))
    line2 = _fix_devanagari(" ".join(words[mid:]))

    f_head = _load_font(HINDI_FONT_BOLD, 82)
    # Shrink until both lines fit
    for size in range(82, 44, -4):
        f_head = _load_font(HINDI_FONT_BOLD, size)
        if max(f_head.getbbox(line1)[2], f_head.getbbox(line2 or " ")[2]) <= W - 90:
            break

    line_h = int(f_head.size * 1.42)
    y = H - 60 - line_h * (2 if line2 else 1)
    for line, color in ((line1, (255, 255, 255)), (line2, (255, 214, 0))):
        if not line:
            continue
        draw.text((46, y), line, font=f_head, fill=color,
                  stroke_width=5, stroke_fill=(0, 0, 0))
        y += line_h

    canvas.save(output_path, "JPEG", quality=92, optimize=True)
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


def build_chapters(script: dict, voices: list, title_card_seconds: float = 5.0) -> str:
    """
    Read each section's real voice-clip duration and format YouTube chapter
    markers as a plain text block ("M:SS heading" per line). Long-form only
    — YouTube Shorts do not support chapters.
    """
    sections = script.get("sections", [])
    headings = [s.get("heading", "") for s in sections]

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

    offsets = _compute_chapter_offsets(headings, durations, title_card_seconds=title_card_seconds)
    return "\n".join(f"{_format_timestamp(t)} {h}" for t, h in offsets)


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

    # ── 1. Title card (5 s, no voice, gentle push-in) ─────────────────────────
    title_arr = _title_card(
        script["title"],
        script.get("thumbnail_text", ""),
        SLIDE_COLORS[0],
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

    # ── 3. Outro (5 s, no voice, gentle push-in) ──────────────────────────────
    clips.append(_card_motion_clip(_outro_card(), 5))

    # ── 4. Concatenate with crossfades between all top-level clips ───────────
    # Sections carry a 0.8 s silent tail, so the 0.6 s overlap never clips voice.
    clips = [
        c if k == 0 else c.with_effects([mpe.vfx.CrossFadeIn(_XFADE)])
        for k, c in enumerate(clips)
    ]
    final = mpe.concatenate_videoclips(clips, method="compose", padding=-_XFADE)

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
