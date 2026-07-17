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
GEMINI_API_KEY          = os.getenv("GEMINI_API_KEY", "")
HUGGINGFACE_API_KEY     = os.getenv("HUGGINGFACE_API_KEY", "")
OPENROUTER_API_KEY      = os.getenv("OPENROUTER_API_KEY", "")

# Free OpenRouter models tried in order if Claude fails (out of credits, rate-limited, etc.)
# NOTE: OpenRouter's free catalog changes over time — if all of these start failing with
# 404 ("model unavailable for free"), refresh this list from https://openrouter.ai/models?max_price=0
OPENROUTER_FALLBACK_MODELS = [
    "google/gemma-4-31b-it:free",
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "openai/gpt-oss-120b:free",
]
YOUTUBE_CLIENT_SECRETS  = str(BASE_DIR / "client_secrets.json")
YOUTUBE_TOKEN_FILE      = str(BASE_DIR / "youtube_token.pickle")

# ─── Video specs ───────────────────────────────────────────────────────────────
VIDEO_WIDTH  = 1920
VIDEO_HEIGHT = 1080
VIDEO_FPS    = 24
VIDEO_BITRATE = "4000k"

# ─── Upload schedule (IST) ─────────────────────────────────────────────────────
# 7 slots: 18:30 → 19:30 IST (evening prime time — peak Hindi audience)
UPLOAD_SLOTS_IST = [
    "18:30", "18:40", "18:50",
    "19:00", "19:10", "19:20", "19:30",
]

# Generate at 14:30 IST so all 7 videos are ready before 18:30 upload
GENERATION_LEAD_HOURS = 4   # pipeline starts at 14:30 IST

# ─── Fonts (downloaded by setup_fonts.py) ─────────────────────────────────────
HINDI_FONT_BOLD    = str(ASSETS_DIR / "fonts" / "NotoSansDevanagari-Bold.ttf")
HINDI_FONT_REGULAR = str(ASSETS_DIR / "fonts" / "NotoSansDevanagari-Regular.ttf")

# ─── TTS ───────────────────────────────────────────────────────────────────────
# Edge TTS (primary) — Microsoft Madhur Neural, deep Hindi male voice
TTS_VOICE  = os.getenv("TTS_VOICE", "hi-IN-MadhurNeural")
TTS_RATE   = os.getenv("TTS_RATE",  "-12%")   # deliberate news-anchor pace
TTS_PITCH  = os.getenv("TTS_PITCH", "-4Hz")   # slight depth, stays natural
# gTTS fallback (used only if Edge TTS fails)
TTS_LANG   = "hi"

# Faster delivery for time-sensitive content
NEWS_TTS_RATE   = os.getenv("NEWS_TTS_RATE",   "+15%")  # news-category long videos
SHORTS_TTS_RATE = os.getenv("SHORTS_TTS_RATE", "+50%")  # YouTube Shorts (1.5x)

# Long-video categories that get the faster news voice
NEWS_CATEGORIES = {"news_india", "news_world", "finance"}

# ─── YouTube Shorts ────────────────────────────────────────────────────────────
SHORTS_PER_DAY      = 3
SHORTS_WIDTH        = 1080
SHORTS_HEIGHT       = 1920
SHORTS_MAX_SECONDS  = 59      # hard YouTube Shorts limit is 60 s
SHORTS_UPLOAD_SLOTS = ["19:40", "19:45", "19:50"]   # right after the 7 long slots

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
