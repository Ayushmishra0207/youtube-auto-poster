"""
Text-to-Speech — Microsoft Edge TTS (primary) with gTTS fallback.

Voice/language is locale-driven (pipeline/locales.py) — defaults to Hindi
(hi-IN-MadhurNeural) when no locale is given, matching the original
single-language behavior.

Tune the Hindi default in config.py / .env:
  TTS_VOICE  = hi-IN-MadhurNeural
  TTS_RATE   = +0%      (natural conversational pace; negative = slower, positive = faster)
  TTS_PITCH  = -4Hz     (negative = deeper / heavier voice)
"""
import asyncio
import os
from pathlib import Path

import edge_tts
from gtts import gTTS, gTTSError

from config import EMOTION_PROSODY, TTS_PITCH, TTS_RATE
from pipeline.locales import Locale, get_locale
from pipeline.logger import log
from pipeline.retry import with_retry


# ── Emotion-driven prosody ────────────────────────────────────────────────────

def _apply_emotion(rate: str, pitch: str, emotion: str | None) -> tuple[str, str]:
    """
    Combine a base rate ("+15%"/"-12%") and pitch ("-4Hz") with the
    (rate_delta_pct, pitch_delta_hz) for `emotion` from config.EMOTION_PROSODY.
    Unknown/missing emotion is a no-op (returns rate/pitch unchanged).
    """
    if not emotion or emotion not in EMOTION_PROSODY:
        return rate, pitch
    rate_delta, pitch_delta = EMOTION_PROSODY[emotion]
    if rate_delta == 0 and pitch_delta == 0:
        return rate, pitch

    rate_pct = int(rate.rstrip("%")) + rate_delta
    pitch_hz = int(pitch.rstrip("Hz")) + pitch_delta
    combined_rate = f"{'+' if rate_pct >= 0 else ''}{rate_pct}%"
    combined_pitch = f"{'+' if pitch_hz >= 0 else ''}{pitch_hz}Hz"
    return combined_rate, combined_pitch


# ── Edge TTS (primary) ────────────────────────────────────────────────────────

async def _edge_tts_async(text: str, output_path: str, voice: str, rate: str, pitch: str) -> str:
    """Async core for Edge TTS."""
    comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await comm.save(output_path)
    return output_path


@with_retry(max_attempts=3, base_delay=3.0, exceptions=(Exception,))
def _edge_tts(text: str, output_path: str, voice: str, rate: str, pitch: str) -> str:
    """Synchronous wrapper around the async Edge TTS call."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(_edge_tts_async(text, output_path, voice, rate, pitch))
    return output_path


# ── gTTS fallback ─────────────────────────────────────────────────────────────

@with_retry(max_attempts=3, base_delay=3.0, exceptions=(gTTSError, OSError))
def _gtts(text: str, output_path: str, gtts_lang: str) -> str:
    """gTTS fallback — free Google voice (less natural)."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    gTTS(text=text, lang=gtts_lang, slow=False).save(output_path)
    return output_path


# ── Public API ────────────────────────────────────────────────────────────────

def text_to_speech(text: str, output_path: str, rate: str | None = None,
                   locale: Locale | None = None, emotion: str | None = None) -> str:
    """
    Convert text to MP3 using Edge TTS (locale.tts_voice).
    Falls back to gTTS (locale.gtts_lang) if Edge TTS fails after retries,
    or raises if the locale has no gTTS fallback (e.g. Persian).

    rate: Edge TTS rate string (e.g. "+15%" for a brisk pace). None → config
          default (only meaningful for the Hindi default voice's pacing;
          other locales' voices use Edge TTS's own natural default rate).
    emotion: one of config.EMOTION_PROSODY's keys (e.g. "excited", "serious")
             — nudges rate/pitch per line so narration isn't monotone. The
             Hindi voice has no named "style" list, so this is done via
             prosody deltas rather than an express-as style tag.
    """
    locale = locale or get_locale(None)
    default_rate = TTS_RATE if locale.code == "hi" else "+0%"
    final_rate, final_pitch = _apply_emotion(rate or default_rate, TTS_PITCH, emotion)
    try:
        _edge_tts(text, output_path, locale.tts_voice, final_rate, final_pitch)
        log.info("Edge TTS (%s, emotion=%s) → %s", locale.tts_voice, emotion or "neutral", Path(output_path).name)
        return output_path
    except Exception as e:
        log.warning("Edge TTS failed (%s), falling back to gTTS: %s", locale.tts_voice, e)
        if not locale.gtts_lang:
            raise RuntimeError(f"Edge TTS failed and locale '{locale.code}' has no gTTS fallback") from e
        _gtts(text, output_path, locale.gtts_lang)
        log.info("gTTS (fallback, %s) → %s", locale.gtts_lang, Path(output_path).name)
        return output_path


def generate_section_voices(sections: list, output_dir: str, rate: str | None = None,
                            locale: Locale | None = None) -> list[str]:
    """
    Generate one MP3 per section.
    Returns list of file paths (empty string for any section that fails).
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    paths = []

    for section in sections:
        sid = section["id"]
        path = os.path.join(output_dir, f"voice_{sid:02d}.mp3")
        try:
            text_to_speech(section["narration"], path, rate=rate, locale=locale,
                           emotion=section.get("emotion"))
            paths.append(path)
            log.info("Voice %02d saved → %s", sid, Path(path).name)
        except Exception as exc:
            log.error("Voice %02d failed permanently: %s", sid, exc)
            paths.append("")

    return paths
