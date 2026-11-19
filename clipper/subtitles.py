"""Word-by-word animated captions + hook banner + watermark, as an ASS subtitle file."""
from __future__ import annotations

import re

from clipper.modes import CaptionStyle

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_NON_BMP = re.compile(r"[^\u0000-￿]")           # emojis — fonts here can't draw them
HINDI_FONT = "Noto Sans Devanagari"


def ass_color(hex_rgb: str, alpha: int = 0) -> str:
    h = hex_rgb.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _ts(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _clean(text: str) -> str:
    text = _NON_BMP.sub("", text)
    return text.replace("\\", "").replace("{", "(").replace("}", ")").strip()


def _chunks(words: list[dict], per_chunk: int, max_chars: int) -> list[list[dict]]:
    out: list[list[dict]] = []
    cur: list[dict] = []
    for i, w in enumerate(words):
        gap = w["start"] - words[i - 1]["end"] if i else 0
        cur_len = sum(len(x["text"]) + 1 for x in cur)
        if cur and (len(cur) >= per_chunk or gap > 0.6 or cur_len + len(w["text"]) > max_chars):
            out.append(cur)
            cur = []
        cur.append(w)
        if re.search(r"[.!?।]$", w["text"]):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def build_ass(
    words: list[dict], duration: float, style: CaptionStyle | None, caption_margin_v: int,
    hook_text: str = "", hook_margin_v: int = 260, watermark: str = "",
    width: int = 1080, height: int = 1920,
) -> str:
    """`words` are clip-relative: [{"start","end","text"}]."""
    st = style
    font = st.font if st else "Impact"
    size = st.size if st else 90
    primary = ass_color(st.primary if st else "#FFFFFF")
    outline = ass_color(st.outline if st else "#000000")
    back = ass_color("#000000", 0x60 if (st and st.box) else 0x80)
    border_style = 3 if (st and st.box) else 1
    outline_w = (12 if (st and st.box) else st.outline_w) if st else 6
    shadow = st.shadow if st else 2

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{size},{primary},&H000000FF,{outline},{back},-1,0,0,0,100,100,1,0,{border_style},{outline_w},{shadow},2,70,70,{caption_margin_v},1
Style: Hook,Impact,78,&H00FFFFFF,&H000000FF,&H00000000,&H00101010,-1,0,0,0,100,100,1,0,3,18,0,8,80,80,{hook_margin_v},1
Style: Mark,Segoe UI Semibold,38,&H70FFFFFF,&H000000FF,&H90000000,&H00000000,-1,0,0,0,100,100,1,0,1,2,0,3,40,40,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []

    hook = _clean(hook_text)
    if hook:
        hfont = f"{{\\fn{HINDI_FONT}}}" if _DEVANAGARI.search(hook) else ""
        events.append(f"Dialogue: 2,{_ts(0)},{_ts(duration)},Hook,,0,0,0,,{{\\fad(250,0)}}{hfont}{hook}")

    mark = _clean(watermark)
    if mark:
        events.append(f"Dialogue: 1,{_ts(0)},{_ts(duration)},Mark,,0,0,0,,{mark}")

    if st and words:
        hl = ass_color(st.highlight)
        base = ass_color(st.primary)
        max_chars = 18 if st.uppercase else 30
        chunks = _chunks(words, st.words_per_chunk, max_chars)
        for ci, chunk in enumerate(chunks):
            texts = [_clean(w["text"]) for w in chunk]
            if st.uppercase:
                texts = [t if _DEVANAGARI.search(t) else t.upper() for t in texts]
            hindi = any(_DEVANAGARI.search(t) for t in texts)
            fn = f"\\fn{HINDI_FONT}" if hindi else ""
            chunk_end = chunk[-1]["end"] + 0.25
            if ci + 1 < len(chunks):
                chunk_end = min(chunk_end, chunks[ci + 1][0]["start"])
            for wi, w in enumerate(chunk):
                start = w["start"]
                end = chunk[wi + 1]["start"] if wi + 1 < len(chunk) else chunk_end
                if end - start < 0.04:
                    continue
                parts = []
                for j, t in enumerate(texts):
                    if j == wi:
                        pop = "\\fscx112\\fscy112\\t(0,90,\\fscx100\\fscy100)" if st.pop else ""
                        parts.append(f"{{\\c{hl}{pop}}}{t}{{\\c{base}\\fscx100\\fscy100}}")
                    else:
                        parts.append(t)
                intro = "\\fad(60,0)" if wi == 0 else ""
                events.append(
                    f"Dialogue: 3,{_ts(start)},{_ts(end)},Cap,,0,0,0,,{{{intro}{fn}}}{' '.join(parts)}"
                )

    return header + "\n".join(events) + "\n"
