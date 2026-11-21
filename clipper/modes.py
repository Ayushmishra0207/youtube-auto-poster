"""
Clip modes (what counts as a "viral moment") and caption styles (how it looks).

A mode tunes three things:
  • moment detection — how much loud action / fast cuts / talking matter
  • the look         — zoom punch-in, colour grade, default caption style
  • the AI brief     — what Claude should hunt for in the transcript
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

GTA_VOCAB = (
    "GTA 6, GTA VI, Grand Theft Auto VI, Rockstar Games, Vice City, Leonida, "
    "Lucia, Jason, Port Gellhorn, Grassrivers, Ambrosia, Mount Kalaga, Keys"
)


@dataclass(frozen=True)
class Mode:
    key: str
    label: str
    description: str
    ai_brief: str                 # what Claude looks for
    w_energy: float               # weight: loud audio peaks (gunfire, crashes, hype)
    w_scene: float                # weight: fast cutting / visual change
    w_speech: float               # weight: dense talking (commentary, dialogue)
    min_len: int                  # default clip length range, seconds
    max_len: int
    zoom: float                   # foreground punch-in (1.0 = none)
    contrast: float
    saturation: float
    brightness: float
    vignette: bool
    caption_style: str
    whisper_prompt: str = GTA_VOCAB
    fallback_hooks: tuple[str, ...] = field(default_factory=tuple)
    hashtags: tuple[str, ...] = field(default_factory=tuple)
    yt_category: str = "20"       # Gaming


MODES: dict[str, Mode] = {m.key: m for m in [
    Mode(
        key="gta6_action", label="GTA 6 · Action",
        description="Chases, shootouts, explosions, stunts and police escapes.",
        ai_brief=("high-adrenaline GTA 6 moments: police chases, shootouts, explosions, crashes, "
                  "stunt jumps, heists going wrong, narrow escapes, wanted-level spikes, hype reactions"),
        w_energy=0.6, w_scene=0.3, w_speech=0.1, min_len=20, max_len=40,
        zoom=1.12, contrast=1.12, saturation=1.28, brightness=0.0, vignette=True,
        caption_style="impact",
        # Used only when AI is off/unavailable, so they must fit any action clip
        fallback_hooks=("GTA 6 ACTION IS NEXT LEVEL", "WAIT FOR IT...", "THIS GOT CRAZY FAST",
                        "WATCH TILL THE END", "GTA 6 IS INSANE"),
        hashtags=("#GTA6", "#GTAVI", "#GTA6Gameplay", "#Gaming", "#Shorts"),
    ),
    Mode(
        key="gta6_funny", label="GTA 6 · Funny",
        description="Fails, glitches, wild NPCs, ragdolls and streamer reactions.",
        ai_brief=("funny GTA 6 moments: fails, glitches, ragdoll physics, wild NPC behaviour, "
                  "unexpected outcomes, laughing or shocked reactions, punchlines, roasts"),
        w_energy=0.35, w_scene=0.15, w_speech=0.5, min_len=15, max_len=35,
        zoom=1.08, contrast=1.08, saturation=1.2, brightness=0.02, vignette=False,
        caption_style="pop",
        fallback_hooks=("WAIT FOR THE END", "GTA 6 NPCs ARE WILD", "I WAS NOT READY",
                        "BRO WHAT JUST HAPPENED", "ONLY IN VICE CITY"),
        hashtags=("#GTA6", "#GTA6Funny", "#GamingFunny", "#Shorts"),
    ),
    Mode(
        key="gta6_trailer", label="GTA 6 · Trailer / News",
        description="Trailer breakdowns, leaks, release news and hidden details.",
        ai_brief=("informative GTA 6 news or trailer-breakdown moments: release dates, price, map size, "
                  "hidden details, easter eggs, leaks, comparisons with GTA 5, surprising facts"),
        w_energy=0.2, w_scene=0.25, w_speech=0.55, min_len=25, max_len=55,
        zoom=1.05, contrast=1.06, saturation=1.12, brightness=0.0, vignette=False,
        caption_style="clean",
        fallback_hooks=("DID YOU NOTICE THIS?", "GTA 6 HIDDEN DETAIL", "ROCKSTAR CONFIRMED THIS",
                        "GTA 6 NEWS YOU MISSED", "THIS CHANGES EVERYTHING"),
        hashtags=("#GTA6", "#GTA6Trailer", "#GTA6News", "#RockstarGames", "#Shorts"),
    ),
    Mode(
        key="gta6_cinematic", label="GTA 6 · Cinematic",
        description="Scenic Vice City shots, sunset drives and beautiful moments.",
        ai_brief=("visually stunning GTA 6 moments: scenic Vice City and Leonida views, sunset or night "
                  "drives, beaches, weather, cinematic camera shots, graphics showcases"),
        w_energy=0.25, w_scene=0.55, w_speech=0.2, min_len=15, max_len=30,
        zoom=1.04, contrast=1.1, saturation=1.32, brightness=0.01, vignette=True,
        caption_style="minimal",
        fallback_hooks=("VICE CITY LOOKS UNREAL", "GTA 6 GRAPHICS ARE INSANE", "THIS IS A GAME?!",
                        "LEONIDA AT SUNSET"),
        hashtags=("#GTA6", "#ViceCity", "#GTA6Graphics", "#Cinematic", "#Shorts"),
    ),
    Mode(
        key="gta6_story", label="GTA 6 · Story",
        description="Missions, dialogue, Lucia & Jason moments and plot twists.",
        ai_brief=("GTA 6 story moments: memorable dialogue, Lucia and Jason scenes, mission setups and "
                  "payoffs, betrayals, plot twists, emotional or quotable lines"),
        w_energy=0.25, w_scene=0.15, w_speech=0.6, min_len=25, max_len=55,
        zoom=1.04, contrast=1.08, saturation=1.1, brightness=0.0, vignette=True,
        caption_style="clean",
        fallback_hooks=("THIS SCENE HITS DIFFERENT", "LUCIA & JASON", "NOBODY SAW THIS COMING",
                        "GTA 6 STORY MOMENT"),
        hashtags=("#GTA6", "#GTA6Story", "#LuciaAndJason", "#Shorts"),
    ),
    Mode(
        key="general", label="Any video",
        description="Podcasts, vlogs, other games — balanced moment detection.",
        ai_brief=("the most engaging self-contained moments: strong opinions, surprising facts, "
                  "funny or emotional peaks, punchlines, quotable lines, high-energy action"),
        w_energy=0.35, w_scene=0.2, w_speech=0.45, min_len=20, max_len=45,
        zoom=1.06, contrast=1.06, saturation=1.12, brightness=0.0, vignette=False,
        caption_style="impact", whisper_prompt="",
        fallback_hooks=("WATCH TILL THE END", "THIS IS CRAZY", "YOU NEED TO SEE THIS"),
        hashtags=("#Shorts", "#Viral", "#Trending"),
        yt_category="24",  # Entertainment
    ),
]}

DEFAULT_MODE = "gta6_action"

# "Split into parts" (series) look: whole frame kept (no punch-in), light grade.
# Not in MODES, so it never shows up as a viral-moment mode card.
SERIES_MODE = Mode(
    key="series", label="Series", description="Whole video split into numbered parts.",
    ai_brief="", w_energy=0.0, w_scene=0.0, w_speech=0.0, min_len=30, max_len=60,
    zoom=1.0, contrast=1.04, saturation=1.06, brightness=0.0, vignette=False,
    caption_style="clean", whisper_prompt="", yt_category="24",
)


# ── Caption styles ──────────────────────────────────────────────────────────────
# Colours are #RRGGBB. `highlight` colours the word currently being spoken.

@dataclass(frozen=True)
class CaptionStyle:
    key: str
    label: str
    font: str
    size: int
    primary: str
    highlight: str
    outline: str
    outline_w: float
    shadow: float
    uppercase: bool
    words_per_chunk: int
    pop: bool            # scale "pop" on the active word
    box: bool            # opaque box behind the text instead of an outline


CAPTION_STYLES: dict[str, CaptionStyle] = {s.key: s for s in [
    CaptionStyle("impact",  "Impact",  "Impact",            104, "#FFFFFF", "#FFD400", "#000000", 7, 3, True,  3, True,  False),
    CaptionStyle("pop",     "Pop",     "Impact",            100, "#FFFFFF", "#3CFF6B", "#000000", 7, 3, True,  2, True,  False),
    CaptionStyle("neon",    "Neon",    "Segoe UI Black",     92, "#FFFFFF", "#FF3CAC", "#2B0A3D", 6, 0, True,  3, True,  False),
    CaptionStyle("clean",   "Clean",   "Segoe UI Semibold",  74, "#FFFFFF", "#4FC3F7", "#000000", 0, 0, False, 5, False, True),
    CaptionStyle("minimal", "Minimal", "Segoe UI Semibold",  62, "#FFFFFF", "#FFE08A", "#000000", 3, 1, False, 6, False, False),
]}

NO_CAPTIONS = "none"

# Length presets offered in the UI (min, max seconds). "auto" uses the mode's range.
LENGTH_PRESETS: dict[str, tuple[int, int] | None] = {
    "auto": None,
    "short": (15, 30),
    "medium": (30, 45),
    "long": (45, 58),
}


def get_mode(key: str) -> Mode:
    return MODES.get(key) or MODES[DEFAULT_MODE]


def options_payload() -> dict:
    """Everything the dashboard needs to render the clip form."""
    return {
        "modes": [
            {"key": m.key, "label": m.label, "description": m.description,
             "caption_style": m.caption_style, "min_len": m.min_len, "max_len": m.max_len}
            for m in MODES.values()
        ],
        "caption_styles": [{"key": s.key, "label": s.label, "highlight": s.highlight} for s in CAPTION_STYLES.values()]
                          + [{"key": NO_CAPTIONS, "label": "Off", "highlight": ""}],
        "lengths": [{"key": k, "range": list(v) if v else None} for k, v in LENGTH_PRESETS.items()],
        "default_mode": DEFAULT_MODE,
    }


def mode_dict(m: Mode) -> dict:
    return asdict(m)
