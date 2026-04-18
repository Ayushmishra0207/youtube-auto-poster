"""
Download Noto Sans Devanagari fonts (required for Hindi text rendering).

Usage:
  python setup_fonts.py
"""
import re
from pathlib import Path

import requests

FONTS_DIR = Path(__file__).parent / "assets" / "fonts"
FONTS_DIR.mkdir(parents=True, exist_ok=True)

# Old user-agent tricks Google Fonts API into returning plain .ttf URLs in CSS
_OLD_UA = "Mozilla/4.0 (compatible; MSIE 6.0; Windows NT 5.0)"

GFONTS_CSS = {
    "NotoSansDevanagari-Regular.ttf":
        "https://fonts.googleapis.com/css?family=Noto+Sans+Devanagari:400",
    "NotoSansDevanagari-Bold.ttf":
        "https://fonts.googleapis.com/css?family=Noto+Sans+Devanagari:700",
}

# jsDelivr mirrors the Google Fonts GitHub repo — used when CSS approach fails
JSDELIVR = {
    "NotoSansDevanagari-Regular.ttf":
        "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/notosansdevanagari/"
        "NotoSansDevanagari%5Bwdth%2Cwght%5D.ttf",
    "NotoSansDevanagari-Bold.ttf":
        "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/notosansdevanagari/"
        "NotoSansDevanagari%5Bwdth%2Cwght%5D.ttf",
}


def _download_bytes(url: str, ua: str = "Mozilla/5.0") -> bytes:
    r = requests.get(url, timeout=60, headers={"User-Agent": ua})
    r.raise_for_status()
    return r.content


def download_font(name: str) -> bool:
    dest = FONTS_DIR / name
    if dest.exists() and dest.stat().st_size > 10_000:
        print(f"  [OK] Already exists: {name}")
        return True

    print(f"  Downloading {name} ...", end="", flush=True)

    # ── Strategy 1: Google Fonts CSS → extract TTF URL ───────────────────────
    try:
        css = _download_bytes(GFONTS_CSS[name], ua=_OLD_UA).decode()
        match = re.search(r"url\((https://[^\)]+\.ttf)\)", css)
        if match:
            font_url = match.group(1)
            data = _download_bytes(font_url)
            dest.write_bytes(data)
            print(f" done via Google Fonts ({len(data)//1024} KB)")
            return True
    except Exception as e:
        print(f"\n    [warn] Google Fonts strategy failed: {e}")

    # ── Strategy 2: jsDelivr CDN ─────────────────────────────────────────────
    try:
        data = _download_bytes(JSDELIVR[name])
        dest.write_bytes(data)
        print(f" done via jsDelivr ({len(data)//1024} KB)")
        return True
    except Exception as e:
        print(f" FAILED: {e}")
        return False


if __name__ == "__main__":
    print("Setting up Hindi fonts ...\n")
    ok = all(download_font(n) for n in GFONTS_CSS)
    print("\nAll fonts ready." if ok else "\nSome fonts failed — check your internet connection.")
    print(f"Saved to: {FONTS_DIR}")
