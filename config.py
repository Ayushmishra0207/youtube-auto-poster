"""
Central configuration for the YouTube Auto-Poster pipeline.
All values can be overridden via environment variables (.env file).
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ─── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
ASSETS_DIR = BASE_DIR / "assets"

OUTPUT_DIR.mkdir(exist_ok=True)
(ASSETS_DIR / "fonts").mkdir(parents=True, exist_ok=True)
(ASSETS_DIR / "music").mkdir(parents=True, exist_ok=True)

# ─── API Keys ──────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY       = os.getenv("ANTHROPIC_API_KEY", "")
PEXELS_API_KEY          = os.getenv("PEXELS_API_KEY", "")
YOUTUBE_CLIENT_SECRETS  = str(BASE_DIR / "client_secrets.json")
YOUTUBE_TOKEN_FILE      = str(BASE_DIR / "youtube_token.pickle")

# ─── Video specs ───────────────────────────────────────────────────────────────
VIDEO_WIDTH  = 1920
VIDEO_HEIGHT = 1080
VIDEO_FPS    = 24
VIDEO_BITRATE = "4000k"

# ─── Upload schedule (IST) ─────────────────────────────────────────────────────
# 7 slots: 6:30 → 7:30, every 10 minutes
UPLOAD_SLOTS_IST = [
    "06:30", "06:40", "06:50",
    "07:00", "07:10", "07:20", "07:30",
]

# How many hours before first slot to start generation (so videos are ready)
GENERATION_LEAD_HOURS = 4   # generates at ~2:30 AM for 6:30 upload

# ─── Fonts (downloaded by setup_fonts.py) ─────────────────────────────────────
HINDI_FONT_BOLD    = str(ASSETS_DIR / "fonts" / "NotoSansDevanagari-Bold.ttf")
HINDI_FONT_REGULAR = str(ASSETS_DIR / "fonts" / "NotoSansDevanagari-Regular.ttf")

# ─── TTS ───────────────────────────────────────────────────────────────────────
# Edge TTS (primary) — Microsoft Madhur Neural, deep Hindi male voice
TTS_VOICE  = os.getenv("TTS_VOICE", "hi-IN-MadhurNeural")
TTS_RATE   = os.getenv("TTS_RATE",  "-5%")    # slightly slower = clearer delivery
TTS_PITCH  = os.getenv("TTS_PITCH", "-8Hz")   # lower pitch = heavier/deeper voice
# gTTS fallback (used only if Edge TTS fails)
TTS_LANG   = "hi"

# ─── Background music ──────────────────────────────────────────────────────────
BG_MUSIC_PATH   = str(ASSETS_DIR / "music" / "background.mp3")
BG_MUSIC_VOLUME = 0.12    # 12 % of original track volume

# ─── YouTube metadata defaults ─────────────────────────────────────────────────
YT_CATEGORY_ID        = "25"    # News & Politics  (change to "28" for Science)
YT_DEFAULT_LANGUAGE   = "hi"
YT_MADE_FOR_KIDS      = False

# ─── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

# ─── Output retention ──────────────────────────────────────────────────────────
KEEP_OUTPUT_DAYS = int(os.getenv("KEEP_OUTPUT_DAYS", "3"))   # delete output older than N days

# ─── Slide colour pairs (hex dark-to-darker gradient) ─────────────────────────
SLIDE_COLORS = [
    ("#1a1a2e", "#16213e"),
    ("#0f3460", "#533483"),
    ("#1B262C", "#0F4C75"),
    ("#16213e", "#0f3460"),
    ("#2D132C", "#1A1A2E"),
    ("#1B1B2F", "#2C3333"),
    ("#000428", "#004e92"),
]
