"""
Download Noto Sans font variants for every script family this project
renders on-screen text in (Latin/Cyrillic/Greek, Devanagari, Bengali,
Arabic, Hebrew, Simplified Chinese, Japanese, Korean, Thai) — see
pipeline/locales.py SCRIPT_PROFILES for which locale uses which family.

Usage:
  python setup_fonts.py
  python setup_fonts.py --family NotoSansArabic   # just one family
"""
import argparse
import re
from pathlib import Path

import requests

FONTS_DIR = Path(__file__).parent / "assets" / "fonts"
FONTS_DIR.mkdir(parents=True, exist_ok=True)

# Old user-agent tricks Google Fonts API into returning plain .ttf URLs in CSS
_OLD_UA = "Mozilla/4.0 (compatible; MSIE 6.0; Windows NT 5.0)"

# font_family -> (Google Fonts family name, jsDelivr repo dir, variable-axis suffix)
# Axis suffix verified against the actual filenames in github.com/google/fonts —
# most Noto Sans variants ship [wdth,wght], but the CJK families only have [wght].
FAMILIES = {
    "NotoSans":           ("Noto Sans",           "notosans",           "wdth,wght"),
    "NotoSansDevanagari": ("Noto Sans Devanagari", "notosansdevanagari", "wdth,wght"),
    "NotoSansBengali":    ("Noto Sans Bengali",    "notosansbengali",    "wdth,wght"),
    "NotoSansArabic":     ("Noto Sans Arabic",     "notosansarabic",     "wdth,wght"),
    "NotoSansHebrew":     ("Noto Sans Hebrew",     "notosanshebrew",     "wdth,wght"),
    "NotoSansSC":         ("Noto Sans SC",         "notosanssc",         "wght"),
    "NotoSansJP":         ("Noto Sans JP",          "notosansjp",         "wght"),
    "NotoSansKR":         ("Noto Sans KR",          "notosanskr",         "wght"),
    "NotoSansThai":       ("Noto Sans Thai",        "notosansthai",       "wdth,wght"),
}


def _download_bytes(url: str, ua: str = "Mozilla/5.0") -> bytes:
    r = requests.get(url, timeout=60, headers={"User-Agent": ua})
    r.raise_for_status()
    return r.content


def _gfonts_css_url(gfonts_name: str, weight: int) -> str:
    family = gfonts_name.replace(" ", "+")
    return f"https://fonts.googleapis.com/css?family={family}:{weight}"


def _jsdelivr_url(repo_dir: str, gfonts_name: str, axes: str) -> str:
    slug = gfonts_name.replace(" ", "")
    axes_encoded = axes.replace(",", "%2C")
    return (
        f"https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/{repo_dir}/"
        f"{slug}%5B{axes_encoded}%5D.ttf"
    )


def download_font(family_key: str, weight_name: str, weight: int) -> bool:
    gfonts_name, repo_dir, axes = FAMILIES[family_key]
    name = f"{family_key}-{weight_name}.ttf"
    dest = FONTS_DIR / name
    if dest.exists() and dest.stat().st_size > 10_000:
        print(f"  [OK] Already exists: {name}")
        return True

    print(f"  Downloading {name} ...", end="", flush=True)

    # ── Strategy 1: Google Fonts CSS -> extract TTF URL ──────────────────────
    try:
        css = _download_bytes(_gfonts_css_url(gfonts_name, weight), ua=_OLD_UA).decode()
        match = re.search(r"url\((https://[^\)]+\.ttf)\)", css)
        if match:
            data = _download_bytes(match.group(1))
            dest.write_bytes(data)
            print(f" done via Google Fonts ({len(data)//1024} KB)")
            return True
    except Exception as e:
        print(f"\n    [warn] Google Fonts strategy failed: {e}")

    # ── Strategy 2: jsDelivr CDN (variable font, single file for all weights) ─
    try:
        data = _download_bytes(_jsdelivr_url(repo_dir, gfonts_name, axes))
        dest.write_bytes(data)
        print(f" done via jsDelivr ({len(data)//1024} KB)")
        return True
    except Exception as e:
        print(f" FAILED: {e}")
        return False


def download_family(family_key: str) -> bool:
    ok_regular = download_font(family_key, "Regular", 400)
    ok_bold = download_font(family_key, "Bold", 700)
    return ok_regular and ok_bold


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--family", choices=list(FAMILIES), default=None,
                        help="Download just one font family instead of all of them")
    args = parser.parse_args()

    targets = [args.family] if args.family else list(FAMILIES)
    print(f"Setting up fonts for {len(targets)} script famil{'y' if len(targets)==1 else 'ies'} ...\n")

    results = {}
    for family_key in targets:
        print(f"{family_key} ({FAMILIES[family_key][0]}):")
        results[family_key] = download_family(family_key)
        print()

    failed = [k for k, ok in results.items() if not ok]
    if failed:
        print(f"Some fonts failed: {', '.join(failed)} — check your internet connection.")
    else:
        print("All fonts ready.")
    print(f"Saved to: {FONTS_DIR}")
