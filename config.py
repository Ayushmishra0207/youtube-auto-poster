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
# Free-tier limits as of 2026 (check the linked pages — these change over time):
#   Pollinations.ai (AI images, no key) — no published limit, genuinely unlimited free.
#   Pexels (photos + videos)            — 200 req/hour, 20,000/month. Pexels will lift
#                                          this for free on request if you give attribution:
#                                          https://help.pexels.com/hc/en-us/articles/900005852323
#   Jamendo (background music)          — 35,000 req/month. Not unlimited, but irrelevant
#                                          here since tracks are cached one-per-category.
#   HuggingFace / Gemini (AI images)    — provider-specific quotas, not unlimited.
ANTHROPIC_API_KEY       = os.getenv("ANTHROPIC_API_KEY", "")
PEXELS_API_KEY          = os.getenv("PEXELS_API_KEY", "")
GEMINI_API_KEY          = os.getenv("GEMINI_API_KEY", "")
HUGGINGFACE_API_KEY     = os.getenv("HUGGINGFACE_API_KEY", "")
OPENROUTER_API_KEY      = os.getenv("OPENROUTER_API_KEY", "")
# Free royalty-free music search — https://developer.jamendo.com (free client_id signup)
JAMENDO_CLIENT_ID       = os.getenv("JAMENDO_CLIENT_ID", "")

# Free OpenRouter models tried in order if Claude fails (out of credits, rate-limited, etc.)
# NOTE: OpenRouter's free catalog changes over time — if all of these start failing with
# 404 ("model unavailable for free"), refresh this list from https://openrouter.ai/models?max_price=0
OPENROUTER_FALLBACK_MODELS = [
    "google/gemma-4-31b-it:free",
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    # "openai/gpt-oss-120b:free" removed 2026-07-19 — OpenRouter discontinued
    # the free tier for this model (404s "unavailable for free"); the ":free"
    # suffix now maps to nothing, only a paid slug exists. Don't add it back
    # without ":free" — that would silently start incurring real cost.
]
YOUTUBE_CLIENT_SECRETS  = str(BASE_DIR / "client_secrets.json")
YOUTUBE_TOKEN_FILE      = str(BASE_DIR / "youtube_token.pickle")

# ─── Video specs ───────────────────────────────────────────────────────────────
VIDEO_WIDTH  = 1920
VIDEO_HEIGHT = 1080
VIDEO_FPS    = 24
VIDEO_BITRATE = "4000k"

# ─── Upload schedule (IST) ─────────────────────────────────────────────────────
# 8 slots: 18:30 → 19:40 IST (evening prime time — peak Hindi audience)
UPLOAD_SLOTS_IST = [
    "18:30", "18:40", "18:50",
    "19:00", "19:10", "19:20", "19:30", "19:40",
]

# Generate at 14:30 IST so all 8 videos are ready before 18:30 upload
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
# Adjustable via the dashboard Settings panel — the lever for shifting content
# mix toward whichever YouTube Partner Program path (standard watch-hours vs
# Shorts views) is closer to its threshold.
SHORTS_PER_DAY      = int(os.getenv("SHORTS_PER_DAY", "5"))
SHORTS_WIDTH        = 1080
SHORTS_HEIGHT       = 1920
SHORTS_MAX_SECONDS  = 59      # hard YouTube Shorts limit is 60 s
# Spread across the day's engagement windows for Indian mobile audiences
# instead of one back-to-back batch: late morning, lunch, pre-evening ramp,
# evening prime time, and the second night peak. Slots earlier than the
# 14:30 IST generation run roll to the next day automatically
# (_ist_slot_to_utc), which is fine — it just means today's batch fills a
# rolling ~24h content calendar rather than only "later today."
SHORTS_UPLOAD_SLOTS = ["11:00", "13:30", "17:30", "19:15", "21:00"]

# ─── Background music ──────────────────────────────────────────────────────────
BG_MUSIC_DIR    = ASSETS_DIR / "music"
BG_MUSIC_PATH   = str(BG_MUSIC_DIR / "background.mp3")   # legacy fixed fallback track
BG_MUSIC_VOLUME = 0.12    # 12 % of original track volume

# Vibe-matched background music: maps a content category to Jamendo search
# tags. music_fetcher.py downloads and caches one track per category under
# BG_MUSIC_DIR/<category>.mp3 the first time it's needed.
CATEGORY_MUSIC_TAGS = {
    "news_india":   "news,corporate,tense",
    "news_world":   "news,corporate,tense",
    "finance":      "corporate,motivational",
    "motivational": "motivational,uplifting",
    "story":        "cinematic,emotional",
    "entertainment": "upbeat,energetic",
    "movie_explained": "cinematic,dramatic",
    "news":         "news,corporate,tense",   # used by Shorts (breaking news)
}
DEFAULT_MUSIC_TAGS = "cinematic,background"   # fallback vibe for unrecognised categories

# ─── YouTube metadata defaults ─────────────────────────────────────────────────
YT_CATEGORY_ID        = "25"    # News & Politics  (change to "28" for Science)
YT_DEFAULT_LANGUAGE   = "hi"
YT_MADE_FOR_KIDS      = False

# ─── Post-upload engagement automation ─────────────────────────────────────────
# YouTube's Community-post tab has no public API, so this only covers what's
# actually supported: auto-posting a CTA comment on new uploads, plus keeping
# a queue of draft Community-post captions for you to paste in manually.
ENGAGEMENT_AUTO_COMMENT   = os.getenv("ENGAGEMENT_AUTO_COMMENT", "true").lower() == "true"
ENGAGEMENT_POLL_SECONDS   = int(os.getenv("ENGAGEMENT_POLL_SECONDS", str(15 * 60)))
ENGAGEMENT_MAX_DRAFTS     = int(os.getenv("ENGAGEMENT_MAX_DRAFTS", "20"))

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
