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
    # ctranslate2 defaults to 4 threads; use every core (12 on this PC → ~2-3x faster)
    threads = int(os.getenv("CLIPPER_WHISPER_THREADS", "0")) or (os.cpu_count() or 4)
    log.info("Loading Whisper model '%s' on %s, %d threads (first run downloads it)", size, device, threads)
    _MODEL = WhisperModel(size, device=device, compute_type=compute, cpu_threads=threads)
    return _MODEL


SAMPLE_RATE = 16000


def _read_wav(wav: Path, start: float = 0.0, end: float | None = None):
    """Read only [start, end) — a 10-hour 16 kHz file is ~2.3 GB as float32."""
    import wave

    import numpy as np
    with wave.open(str(wav), "rb") as wf:
        n = wf.getnframes()
        a = min(n, int(start * SAMPLE_RATE))
        b = n if end is None else min(n, int(end * SAMPLE_RATE))
        wf.setpos(a)
        raw = wf.readframes(max(0, b - a))
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def extract_audio(src: Path, wav: Path) -> Path:
    """16 kHz mono WAV — the format Whisper and the energy analyser both want."""
    run_ffmpeg(["-y", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)])
    return wav


_BATCHED = None


def _run_whisper(model, audio, lang, prompt):
    """
    Batched + greedy decoding. Measured on this PC (12-core CPU, 2 min of Hindi
    gameplay commentary): sequential beam-5 took 792 s, batched beam-1 took 42 s.
    Sequential mode keeps re-decoding low-confidence Hindi segments at higher
    temperatures; batched mode doesn't. CLIPPER_WHISPER_BATCHED=0 restores the old mode.
    """
    global _BATCHED
    if os.getenv("CLIPPER_WHISPER_BATCHED", "1") != "0":
        try:
            if _BATCHED is None:
                from faster_whisper import BatchedInferencePipeline
                _BATCHED = BatchedInferencePipeline(model=model)
            kwargs = dict(language=lang, word_timestamps=True, beam_size=1,
                          batch_size=int(os.getenv("CLIPPER_WHISPER_BATCH", "8")))
            if prompt:
                kwargs["initial_prompt"] = prompt
            return _BATCHED.transcribe(audio, **kwargs)
        except Exception as e:   # older faster-whisper / unexpected kwarg → sequential
            log.warning("Batched Whisper unavailable (%s) — using sequential decoding", e)
    return model.transcribe(
        audio, language=lang, word_timestamps=True, vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 400}, initial_prompt=prompt or None,
        condition_on_previous_text=False, beam_size=1, temperature=0.0,
    )


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

    for a, b in spans:
        if ranges:
            audio = _read_wav(wav, a, b)
            offset = a
        else:
            audio, offset = _read_wav(wav), 0.0
        if audio.size < SAMPLE_RATE // 2:
            continue

        # Passing samples (not a path) skips faster-whisper's PyAV decoder,
        # which breaks on some PyAV versions.
        seg_iter, info = _run_whisper(model, audio, lang, prompt)
        detected = detected or info.language
        for seg in seg_iter:
            text = seg.text.strip()
            if not text:
                continue
            segments.append({"start": seg.start + offset, "end": seg.end + offset, "text": text})
            for w in seg.words or []:
                t = w.word.strip()
                if not t:
                    continue
                # Noisy gameplay audio makes greedy decoding loop ("आप आप आप आप …")
                # and invent words under music — drop the 3rd+ identical word in a
                # row and words Whisper itself gives almost no confidence.
                if len(words) >= 2 and words[-1]["text"] == words[-2]["text"] == t:
                    continue
                if getattr(w, "probability", 1.0) < 0.15:
                    continue
                words.append({"start": w.start + offset, "end": w.end + offset, "text": t})
            if on_progress:
                on_progress(min(0.99, (done + seg.end) / total))
        done += max(0.0, b - a) if ranges else total

    if on_progress:
        on_progress(1.0)
    log.info("Transcribed %d words (language=%s)", len(words), detected)
    return {"language": detected, "words": words, "segments": segments}
