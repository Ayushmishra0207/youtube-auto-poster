"""
Signal-based moment detection — works even with zero speech (pure gameplay).

Per-second features:
  energy  loudness (dB) — gunfire, explosions, engines, hype screams
  onset   sudden loudness jumps — impacts, crashes, punchlines
  cuts    scene changes — fast editing / chaotic action
  speech  words per second — commentary density
Each feature is robust-normalised, weighted by the mode, and scored over sliding windows.
"""
from __future__ import annotations

import re
import wave
from pathlib import Path

import numpy as np

from clipper.common import log, run_ffmpeg
from clipper.modes import Mode


def audio_energy(wav: Path) -> np.ndarray:
    """Loudness in dB for each 1-second bucket (plus onset strength from 0.25 s frames)."""
    with wave.open(str(wav), "rb") as wf:
        rate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if pcm.size == 0:
        return np.zeros((0, 2), dtype=np.float32)
    hop = rate // 4                                     # 0.25 s frames
    n = pcm.size // hop
    frames = pcm[: n * hop].reshape(n, hop)
    rms_db = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-6)
    onset = np.maximum(0.0, np.diff(rms_db, prepend=rms_db[:1]))
    secs = n // 4
    if secs == 0:
        return np.zeros((0, 2), dtype=np.float32)
    energy = rms_db[: secs * 4].reshape(secs, 4).mean(axis=1)
    onset_s = onset[: secs * 4].reshape(secs, 4).max(axis=1)
    return np.stack([energy, onset_s], axis=1)


def scene_cuts(src: Path, threshold: float = 0.32) -> list[float]:
    """Timestamps of hard cuts, from a cheap low-res decode."""
    try:
        err = run_ffmpeg([
            "-i", str(src), "-an", "-sn",
            "-vf", f"fps=4,scale=160:-2,select='gt(scene,{threshold})',showinfo",
            "-f", "null", "-",
        ])
    except RuntimeError as e:
        log.warning("Scene detection failed, continuing without it: %s", e)
        return []
    return [float(m) for m in re.findall(r"pts_time:([0-9.]+)", err)]


def _robust(x: np.ndarray) -> np.ndarray:
    if x.size == 0:
        return x
    med = np.median(x)
    spread = np.percentile(x, 90) - np.percentile(x, 10)
    if spread < 1e-6:
        return np.zeros_like(x)
    return np.clip((x - med) / spread, -1.5, 2.5)


def per_second_features(duration: float, energy: np.ndarray, cuts: list[float], words: list[dict]) -> dict:
    n = max(1, int(np.ceil(duration)))
    e = np.full(n, energy[:, 0].min() if energy.size else 0.0, dtype=np.float32)
    o = np.zeros(n, dtype=np.float32)
    k = min(n, len(energy))
    if k:
        e[:k] = energy[:k, 0]
        o[:k] = energy[:k, 1]
    c = np.zeros(n, dtype=np.float32)
    for t in cuts:
        if 0 <= t < n:
            c[int(t)] += 1
    s = np.zeros(n, dtype=np.float32)
    for w in words:
        i = int(w["start"])
        if 0 <= i < n:
            s[i] += 1
    return {"energy": _robust(e), "onset": _robust(o), "cuts": c, "speech": s, "raw_energy": e}


def _window_score(f: dict, a: int, b: int, mode: Mode) -> tuple[float, dict]:
    e = f["energy"][a:b]
    if e.size == 0:
        return -9.0, {}
    top = np.sort(e)[-max(1, int(e.size * 0.3)):].mean()           # loudest 30 %
    onset = np.sort(f["onset"][a:b])[-3:].mean()                    # biggest impacts
    cut_rate = f["cuts"][a:b].sum() / (b - a) * 10                  # cuts per 10 s
    speech = f["speech"][a:b].sum() / (b - a)                       # words per second
    hook = f["energy"][a:min(b, a + 3)].mean() + f["onset"][a:min(b, a + 3)].max(initial=0)
    energy_term = 0.65 * top + 0.35 * onset
    scene_term = min(cut_rate, 6.0) / 3.0
    speech_term = min(speech, 3.5) / 1.75
    score = (mode.w_energy * energy_term + mode.w_scene * scene_term +
             mode.w_speech * speech_term + 0.25 * hook)
    return float(score), {
        "energy": round(float(energy_term), 2), "cuts_per_10s": round(float(cut_rate), 1),
        "words_per_s": round(float(speech), 2), "hook": round(float(hook), 2),
    }


def find_candidates(duration: float, features: dict, mode: Mode, min_len: int, max_len: int,
                    count: int) -> list[dict]:
    """Greedy non-overlapping best windows. Tries a few lengths per start point."""
    n = int(duration)
    if n <= min_len:
        return [{"start": 0.0, "end": float(duration), "score": 0.0, "signals": {}}]
    lengths = sorted({min_len, (min_len + max_len) // 2, max_len})
    scored: list[tuple[float, int, int, dict]] = []
    for L in lengths:
        if L > n:
            continue
        for a in range(0, n - L + 1, 1):
            s, sig = _window_score(features, a, a + L, mode)
            # Slight preference for mid-length clips: best retention on Shorts
            s -= 0.04 * abs(L - (min_len + max_len) / 2) / max(1, max_len - min_len)
            scored.append((s, a, a + L, sig))
    scored.sort(key=lambda x: -x[0])
    picked: list[dict] = []
    for s, a, b, sig in scored:
        if all(b + 2 <= p["start"] or a >= p["end"] + 2 for p in picked):
            picked.append({"start": float(a), "end": float(b), "score": round(s, 3), "signals": sig})
            if len(picked) >= count:
                break
    return sorted(picked, key=lambda p: -p["score"])


def snap(start: float, end: float, words: list[dict], cuts: list[float], duration: float,
         min_len: int, max_len: int) -> tuple[float, float]:
    """Nudge boundaries so clips don't start/end mid-word, preferring sentence gaps or hard cuts."""
    def nearest(t: float, points: list[float], radius: float) -> float | None:
        best = None
        for p in points:
            if abs(p - t) <= radius and (best is None or abs(p - t) < abs(best - t)):
                best = p
        return best

    starts, ends = [], []
    for i, w in enumerate(words):
        prev_end = words[i - 1]["end"] if i else -9
        nxt_start = words[i + 1]["start"] if i + 1 < len(words) else 1e9
        if w["start"] - prev_end > 0.3:
            starts.append(max(0.0, w["start"] - 0.12))
        if nxt_start - w["end"] > 0.3:
            ends.append(min(duration, w["end"] + 0.25))

    s = nearest(start, starts, 2.5) or nearest(start, cuts, 1.5) or start
    e = nearest(end, ends, 3.0) or nearest(end, cuts, 1.5) or end
    # If a word straddles the start/end, extend to cover it fully
    for w in words:
        if w["start"] < s < w["end"]:
            s = max(0.0, w["start"] - 0.05)
        if w["start"] < e < w["end"]:
            e = min(duration, w["end"] + 0.15)
    if e - s < min_len:
        e = min(duration, s + min_len)
    if e - s > max_len:
        e = s + max_len
    return round(max(0.0, s), 2), round(min(duration, e), 2)
