"""
Hindi Text-to-Speech — Microsoft Edge TTS (primary) with gTTS fallback.

Primary: edge-tts  →  hi-IN-MadhurNeural  (deep Hindi male, Natural quality)
Fallback: gTTS     →  hi (standard Google voice, used if Edge TTS fails)

Tune in config.py / .env:
  TTS_VOICE  = hi-IN-MadhurNeural
  TTS_RATE   = -5%      (negative = slower, more deliberate delivery)
  TTS_PITCH  = -8Hz     (negative = deeper / heavier voice)
"""
import asyncio
import os
from pathlib import Path

import edge_tts
from gtts import gTTS, gTTSError

from config import TTS_LANG, TTS_PITCH, TTS_RATE, TTS_VOICE
from pipeline.logger import log
from pipeline.retry import with_retry


# ── Edge TTS (primary) ────────────────────────────────────────────────────────

async def _edge_tts_async(text: str, output_path: str) -> str:
    """Async core for Edge TTS."""
    comm = edge_tts.Communicate(text, TTS_VOICE, rate=TTS_RATE, pitch=TTS_PITCH)
    await comm.save(output_path)
    return output_path


@with_retry(max_attempts=3, base_delay=3.0, exceptions=(Exception,))
def _edge_tts(text: str, output_path: str) -> str:
    """Synchronous wrapper around the async Edge TTS call."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(_edge_tts_async(text, output_path))
    return output_path


# ── gTTS fallback ─────────────────────────────────────────────────────────────

@with_retry(max_attempts=3, base_delay=3.0, exceptions=(gTTSError, OSError))
def _gtts(text: str, output_path: str) -> str:
    """gTTS fallback — free Google voice (less natural)."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    gTTS(text=text, lang=TTS_LANG, slow=False).save(output_path)
    return output_path


# ── Public API ────────────────────────────────────────────────────────────────

def text_to_speech(text: str, output_path: str) -> str:
    """
    Convert text to MP3 using Edge TTS (MadhurNeural male voice).
    Falls back to gTTS if Edge TTS fails after retries.
    """
    try:
        _edge_tts(text, output_path)
        log.info("Edge TTS  → %s", Path(output_path).name)
        return output_path
    except Exception as e:
        log.warning("Edge TTS failed (%s), falling back to gTTS: %s", TTS_VOICE, e)
        _gtts(text, output_path)
        log.info("gTTS (fallback) → %s", Path(output_path).name)
        return output_path


def generate_section_voices(sections: list, output_dir: str) -> list[str]:
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
            text_to_speech(section["narration"], path)
            paths.append(path)
            log.info("Voice %02d saved → %s", sid, Path(path).name)
        except Exception as exc:
            log.error("Voice %02d failed permanently: %s", sid, exc)
            paths.append("")

    return paths
