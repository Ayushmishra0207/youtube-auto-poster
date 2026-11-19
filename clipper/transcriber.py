"""Local speech-to-text with word timestamps (faster-whisper, free, no API key)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from clipper.common import log, run_ffmpeg

_MODEL = None


def _load_model():
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    from faster_whisper import WhisperModel

    size = os.getenv("CLIPPER_WHISPER_MODEL", "small")
    device, compute = "cpu", "int8"
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            device, compute = "cuda", "float16"
    except Exception:
        pass
    log.info("Loading Whisper model '%s' on %s (first run downloads it)", size, device)
    _MODEL = WhisperModel(size, device=device, compute_type=compute)
    return _MODEL


SAMPLE_RATE = 16000


def _read_wav(wav: Path):
    import wave

    import numpy as np
    with wave.open(str(wav), "rb") as wf:
        raw = wf.readframes(wf.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def extract_audio(src: Path, wav: Path) -> Path:
    """16 kHz mono WAV — the format Whisper and the energy analyser both want."""
    run_ffmpeg(["-y", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)])
    return wav


def transcribe(
    wav: Path,
    language: str = "auto",
    prompt: str = "",
    ranges: list[tuple[float, float]] | None = None,
    total_duration: float = 0.0,
    on_progress: Callable[[float], None] | None = None,
) -> dict:
    """
    Transcribe the whole file, or only `ranges` (absolute seconds) for long videos.
    Returns {"language": str, "words": [{"start","end","text"}], "segments": [{"start","end","text"}]}.
    """
    model = _load_model()
    lang = None if language in ("", "auto") else language
    spans = ranges or [(0.0, total_duration or 0.0)]
    total = sum(max(0.0, b - a) for a, b in spans) or 1.0
    done = 0.0
    words: list[dict] = []
    segments: list[dict] = []
    detected = lang or ""

    pcm = _read_wav(wav)
    for a, b in spans:
        if ranges:
            audio = pcm[int(a * SAMPLE_RATE): int(b * SAMPLE_RATE)]
            offset = a
        else:
            audio, offset = pcm, 0.0
        if audio.size < SAMPLE_RATE // 2:
            continue

        # Passing samples (not a path) skips faster-whisper's PyAV decoder,
        # which breaks on some PyAV versions.
        seg_iter, info = model.transcribe(
            audio,
            language=lang,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 400},
            initial_prompt=prompt or None,
            condition_on_previous_text=False,
            beam_size=5,
        )
        detected = detected or info.language
        for seg in seg_iter:
            text = seg.text.strip()
            if not text:
                continue
            segments.append({"start": seg.start + offset, "end": seg.end + offset, "text": text})
            for w in seg.words or []:
                t = w.word.strip()
                if t:
                    words.append({"start": w.start + offset, "end": w.end + offset, "text": t})
            if on_progress:
                on_progress(min(0.99, (done + seg.end) / total))
        done += max(0.0, b - a) if ranges else total

    if on_progress:
        on_progress(1.0)
    log.info("Transcribed %d words (language=%s)", len(words), detected)
    return {"language": detected, "words": words, "segments": segments}
