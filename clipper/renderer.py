"""
ffmpeg render of one vertical (1080×1920) clip.

Edits applied (all are creative/transformative edits — they make the clip a new
piece of work, but they do NOT by themselves grant rights to someone else's video):
  • 9:16 reframe: blurred-background "fit" or full-screen centre crop
  • punch-in zoom, colour grade, sharpening, optional vignette
  • word-by-word animated captions, hook banner, channel watermark
  • progress bar, audio loudness normalisation, optional music bed
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from clipper.common import FONTS_DIR, MediaInfo, even, log, run_ffmpeg
from clipper.modes import CaptionStyle, Mode
from clipper.subtitles import build_ass

W, H, FPS = 1080, 1920, 30


@dataclass
class RenderOptions:
    layout: str = "blur_fit"          # blur_fit | center_crop
    caption_style: CaptionStyle | None = None
    hook_text: str = ""
    watermark: str = ""
    audio_mode: str = "original"      # original | original_music | music_only
    music_path: Path | None = None
    progress_bar: bool = True
    part_label: str = ""              # series mode: "PART 3" under the video


def _layout(info: MediaInfo, mode: Mode, layout: str) -> tuple[list[str], int, int]:
    """Video filter chain parts → returns (filters, caption_margin_v, hook_margin_v)."""
    grade = (f"eq=contrast={mode.contrast}:saturation={mode.saturation}:brightness={mode.brightness},"
             f"unsharp=5:5:0.45")
    src_vertical = info.height > info.width

    if layout == "center_crop" or src_vertical:
        f = max(W / info.width, H / info.height) * mode.zoom
        sw, sh = max(W, even(info.width * f)), max(H, even(info.height * f))
        chain = [f"[0:v]fps={FPS},scale={sw}:{sh},crop={W}:{H},{grade}[base]"]
        return chain, 430, 200

    fg_w = even(W * mode.zoom)
    fg_h = even(info.height * fg_w / info.width)
    crop_h = min(fg_h, 1500)
    top = int(H * 0.44 - crop_h / 2)
    chain = [
        f"[0:v]fps={FPS},split=2[bgs][fgs]",
        f"[bgs]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
        f"gblur=sigma=38,eq=brightness=-0.18:saturation=1.2[bg]",
        f"[fgs]scale={fg_w}:{fg_h},crop={W}:{crop_h},{grade}[fg]",
        f"[bg][fg]overlay=x=0:y={top}[base]",
    ]
    fg_bottom = top + crop_h
    caption_margin_v = max(260, min(820, H - fg_bottom - 60 - 130))
    hook_margin_v = max(110, min(420, top - 250))
    return chain, caption_margin_v, hook_margin_v


def render_clip(src: Path, info: MediaInfo, start: float, end: float, out_dir: Path,
                mode: Mode, words_rel: list[dict], opts: RenderOptions) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    dur = round(end - start, 3)
    out = out_dir / "clip.mp4"

    chain, cap_mv, hook_mv = _layout(info, mode, opts.layout)
    part_mv = cap_mv
    if opts.part_label:
        fullscreen = opts.layout == "center_crop" or info.height > info.width
        if fullscreen:          # video fills the frame: label in the lower third, captions under it
            part_mv = cap_mv + 190
        else:                   # label right under the video, captions move down a row
            cap_mv = max(200, cap_mv - 160)
    ass = build_ass(words_rel, dur, opts.caption_style, cap_mv, opts.hook_text, hook_mv, opts.watermark,
                    part_label=opts.part_label, part_margin_v=part_mv)
    (out_dir / "subs.ass").write_text(ass, encoding="utf-8")

    # ffmpeg filter args treat ':' and '\' specially — run inside out_dir and use
    # relative, forward-slash paths so Windows drive letters never reach the filter.
    fonts_rel = os.path.relpath(FONTS_DIR, out_dir).replace("\\", "/")
    post = []
    if mode.vignette:
        post.append("vignette=angle=PI/5")
    post.append(f"ass=subs.ass:fontsdir='{fonts_rel}'")
    post.append("fade=t=in:st=0:d=0.2")
    chain.append(f"[base]{','.join(post)}[cap]")
    if opts.progress_bar:
        chain.append(f"color=c=0xFFD400:s={W}x12:r={FPS}:d={dur}[bar]")
        chain.append(f"[cap][bar]overlay=x='-w+w*t/{dur}':y=H-h:eval=frame[vout]")
    else:
        chain.append("[cap]null[vout]")

    inputs = ["-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(src)]
    use_music = opts.audio_mode in ("original_music", "music_only") and opts.music_path is not None
    if use_music:
        inputs += ["-stream_loop", "-1", "-i", str(opts.music_path)]

    loud = "loudnorm=I=-14:TP=-1.5:LRA=11"
    fade = f"afade=t=in:st=0:d=0.15,afade=t=out:st={max(0.0, dur - 0.35):.2f}:d=0.35"
    audio_map: list[str] = []
    if opts.audio_mode == "music_only" and use_music:
        chain.append(f"[1:a]atrim=0:{dur},asetpts=N/SR/TB,{loud},{fade}[aout]")
        audio_map = ["-map", "[aout]"]
    elif use_music and info.has_audio:
        chain.append(f"[0:a]volume=1.0[oa];[1:a]atrim=0:{dur},asetpts=N/SR/TB,volume=0.14[ma];"
                     f"[oa][ma]amix=inputs=2:duration=first:normalize=0,{loud},{fade}[aout]")
        audio_map = ["-map", "[aout]"]
    elif info.has_audio:
        chain.append(f"[0:a]{loud},{fade}[aout]")
        audio_map = ["-map", "[aout]"]

    args = [
        "-y", *inputs,
        "-filter_complex", ";".join(chain),
        "-map", "[vout]", *audio_map,
        "-t", f"{dur:.3f}",
        # veryfast ≈ 2-3x quicker than medium; at CRF 20 the size grows a little but
        # quality stays well above what Shorts/Reels re-encode to anyway
        "-c:v", "libx264", "-preset", os.getenv("CLIPPER_X264_PRESET", "veryfast"), "-crf", "20",
        "-pix_fmt", "yuv420p", "-profile:v", "high", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        "clip.mp4",
    ]
    if not audio_map:
        args.insert(args.index("-c:a"), "-an")
    log.info("Rendering %s (%.1fs → %.1fs)", out_dir.name, start, end)
    run_ffmpeg(args, cwd=out_dir)

    # Thumbnail: a frame ~1 s in (hook banner already visible)
    run_ffmpeg(["-y", "-ss", f"{min(1.0, dur / 3):.2f}", "-i", "clip.mp4", "-frames:v", "1",
                "-q:v", "3", "-update", "1", "thumb.jpg"], cwd=out_dir)
    return out
