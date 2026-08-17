"""
Real OpenType text shaping (HarfBuzz + FreeType) for scripts PIL can't
render correctly on its own.

Devanagari conjunct consonants (a consonant + halant + consonant cluster,
e.g. the "स्ट्र" in "इन्फ्रास्ट्रक्चर") only exist as font-internal GSUB
ligature substitutions — there is no separate Unicode codepoint for the
joined form. PIL's text drawing has no OpenType shaping support unless
linked against the optional `raqm` library, and the official Pillow wheels
for Windows don't bundle it (confirmed via `PIL.features.check("raqm")`
== False on this machine, both Pillow 11.3.0 and 12.3.0) — so without
shaping, PIL draws each half-form and consonant as separate glyphs instead
of the joined ligature, which is exactly the broken/unreadable text this
module fixes.

uharfbuzz + freetype-py ship prebuilt Windows wheels and do what raqm would
otherwise provide: shape text into the correct sequence of glyph IDs +
positions (real GSUB/GPOS), which we then rasterize glyph-by-glyph via
FreeType and composite onto the PIL canvas ourselves.

Scope: used for Devanagari specifically (see locale.script in callers).
Other scripts (Latin, Arabic via arabic_reshaper, Hebrew, CJK, Thai) keep
using PIL's normal draw.text() — they aren't reported as broken, and this
avoids touching working code for scripts with different shaping/bidi needs.
"""
from typing import Optional

import freetype
import uharfbuzz as hb
from PIL import Image, ImageFont

_hb_font_cache: dict[str, "hb.Font"] = {}
_ft_face_cache: dict[str, "freetype.Face"] = {}


def _get_hb_font(font_path: str) -> "hb.Font":
    if font_path not in _hb_font_cache:
        blob = hb.Blob.from_file_path(font_path)
        face = hb.Face(blob)
        font = hb.Font(face)
        font.scale = (face.upem, face.upem)  # shape in raw font units; we convert to px ourselves
        _hb_font_cache[font_path] = font
    return _hb_font_cache[font_path]


def _get_ft_face(font_path: str) -> "freetype.Face":
    if font_path not in _ft_face_cache:
        _ft_face_cache[font_path] = freetype.Face(font_path)
    return _ft_face_cache[font_path]


def _shape_run(text: str, font_path: str):
    """Shape text with HarfBuzz; returns (glyph_infos, glyph_positions) in raw font units."""
    hb_font = _get_hb_font(font_path)
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(hb_font, buf)
    return buf.glyph_infos, buf.glyph_positions


def _font_path_size(font: ImageFont.FreeTypeFont) -> tuple[str, int]:
    return font.path, font.size


def measure_text_width(text: str, font: ImageFont.FreeTypeFont) -> float:
    """Real shaped advance width in pixels — use this instead of
    font.getbbox()[2] for wrap/centering decisions on shaped text, since a
    ligature's shaped width can differ from the sum of its parts' widths."""
    if not text:
        return 0.0
    font_path, size_px = _font_path_size(font)
    face = _get_ft_face(font_path)
    upem = face.units_per_EM
    _, positions = _shape_run(text, font_path)
    total_units = sum(p.x_advance for p in positions)
    return total_units * size_px / upem


def draw_shaped_text(image: Image.Image, xy: tuple[float, float], text: str,
                     font: ImageFont.FreeTypeFont, fill: tuple,
                     stroke_width: int = 0, stroke_fill: Optional[tuple] = None) -> None:
    """
    Draw `text` shaped via HarfBuzz + rasterized via FreeType, composited
    onto `image` (must be RGBA — every call site in this codebase already
    draws onto RGBA canvases). xy is the top-left anchor, matching PIL's
    default "la" (left-ascender) text anchor: x = left edge, y = top of the
    font's ascent line — i.e. a drop-in replacement for
    `draw.text(xy, text, font=font, fill=fill, stroke_width=W, stroke_fill=F)`.
    """
    if not text:
        return
    font_path, size_px = _font_path_size(font)
    face = _get_ft_face(font_path)
    upem = face.units_per_EM
    face.set_pixel_sizes(0, size_px)
    infos, positions = _shape_run(text, font_path)

    ascender_px = face.size.ascender / 64.0
    x0, y0 = xy
    pen_x0, pen_y0 = float(x0), float(y0) + ascender_px

    # Stroke first (a ring of offset copies in stroke_fill, same technique
    # PIL's own stroke_width uses), then the real fill on top — so the
    # outline never shows through gaps between adjacent glyphs.
    passes: list[tuple[int, int, tuple]] = []
    if stroke_width > 0 and stroke_fill is not None:
        offsets = {
            (dx, dy)
            for dx in range(-stroke_width, stroke_width + 1)
            for dy in range(-stroke_width, stroke_width + 1)
            if dx * dx + dy * dy <= stroke_width * stroke_width and (dx, dy) != (0, 0)
        }
        for dx, dy in sorted(offsets):
            passes.append((dx, dy, stroke_fill))
    passes.append((0, 0, fill))

    for dx, dy, color in passes:
        r, g, b = color[:3]
        a = color[3] if len(color) == 4 else 255
        px, py = pen_x0, pen_y0
        for info, pos in zip(infos, positions):
            face.load_glyph(info.codepoint, freetype.FT_LOAD_RENDER | freetype.FT_LOAD_TARGET_NORMAL)
            bitmap = face.glyph.bitmap
            if bitmap.width > 0 and bitmap.rows > 0:
                cov = bytes(bitmap.buffer)
                if a != 255:
                    cov = bytes((c * a) // 255 for c in cov)
                glyph_alpha = Image.frombuffer("L", (bitmap.width, bitmap.rows), cov, "raw", "L", 0, 1)
                gx = int(px + pos.x_offset * size_px / upem) + face.glyph.bitmap_left + dx
                gy = int(py - pos.y_offset * size_px / upem) - face.glyph.bitmap_top + dy
                patch = Image.new("RGBA", glyph_alpha.size, (r, g, b, 0))
                patch.putalpha(glyph_alpha)
                image.alpha_composite(patch, dest=(gx, gy))
            px += pos.x_advance * size_px / upem
            py -= pos.y_advance * size_px / upem
