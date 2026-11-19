"""
Claude picks the clip moments and writes hooks/titles/descriptions.

Optional: if no Anthropic credentials are available (or the call fails) the job
falls back to the signal-based candidates and template hooks, so clipping still works.
"""
from __future__ import annotations

import json
import os

from clipper.common import log
from clipper.modes import Mode

MODEL = os.getenv("CLIPPER_CLAUDE_MODEL", "claude-opus-5-5")

# Very long transcripts are sent only around the strongest signal windows
MAX_TRANSCRIPT_CHARS = 180_000

_SCHEMA = {
    "type": "object",
    "properties": {
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "hook_text": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "hashtags": {"type": "array", "items": {"type": "string"}},
                    "virality_score": {"type": "integer"},
                    "reason": {"type": "string"},
                },
                "required": ["start", "end", "hook_text", "title", "description",
                             "hashtags", "virality_score", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clips"],
    "additionalProperties": False,
}

_SYSTEM = """You are a short-form video editor who cuts long videos into viral YouTube Shorts / Instagram Reels for an Indian gaming audience.

You receive: source video metadata, a timestamped transcript (may be empty for pure gameplay), and signal-ranked candidate windows (loud audio peaks, fast cuts, dense speech).

Pick the best moments. Rules:
- Each clip must stand alone: a viewer with no context understands it and gets a payoff.
- The first 2 seconds must hook: start on action, a bold line, or a question — never on filler ("so", "anyway", "hello guys").
- End on a payoff, punchline, or cliffhanger line — never mid-sentence.
- Respect the requested length range exactly. Clips must not overlap.
- When the transcript is empty or thin, rely on the candidate windows' signals.
- hook_text: on-screen banner, max 6 words, ALL CAPS for English/Hinglish, no emojis, no hashtags.
- title: max 70 characters, curiosity-driven, includes the main keyword (e.g. "GTA 6"), 1 emoji allowed.
- description: 2-3 short lines describing the clip, then a call to comment/subscribe. Do not invent facts that are not in the source.
- hashtags: 4-6, each starting with #, always include #Shorts.
- virality_score: 1-100, your honest estimate relative to the other clips.
- reason: one sentence on why this moment works.
Return only the JSON object."""


def _fmt(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


def _transcript_text(segments: list[dict], focus: list[tuple[float, float]] | None) -> str:
    lines = [f"[{_fmt(s['start'])}-{_fmt(s['end'])}] {s['text']}" for s in segments
             if not focus or any(a - 20 <= s["start"] <= b + 20 for a, b in focus)]
    return "\n".join(lines)


def plan_with_claude(
    meta: dict, mode: Mode, segments: list[dict], candidates: list[dict], count: int,
    min_len: int, max_len: int, duration: float, title_language: str,
) -> list[dict] | None:
    try:
        import anthropic
    except ImportError:
        return None
    if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN") or os.getenv("CLIPPER_USE_CLAUDE") == "1"):
        log.info("No Anthropic credentials — using signal-based moment picking")
        return None

    transcript = _transcript_text(segments, None)
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        focus = [(c["start"], c["end"]) for c in candidates]
        transcript = _transcript_text(segments, focus)
        log.info("Transcript too long for one request — sending only the parts around %d candidate windows",
                 len(focus))

    lang_rule = {
        "hinglish": "Write title, hook_text and description in Hinglish (Hindi written in Roman/English letters, mixed with English) — the style Indian gaming creators use.",
        "hindi": "Write title and description in Hindi (Devanagari). hook_text may be Hindi (Devanagari) or short English.",
        "english": "Write title, hook_text and description in English.",
    }.get(title_language, "")

    cand_lines = "\n".join(
        f"- {_fmt(c['start'])} to {_fmt(c['end'])} (start={c['start']:.1f}, end={c['end']:.1f}) signals={json.dumps(c.get('signals', {}))}"
        for c in candidates
    )
    user = f"""SOURCE
title: {meta.get('title', '')}
channel: {meta.get('channel', '')}
duration_seconds: {duration:.1f}
description: {meta.get('description', '')[:600]}

MODE: {mode.label}
Look for: {mode.ai_brief}

REQUEST: exactly {count} clips, each between {min_len} and {max_len} seconds. Times in seconds from the start of the video.
{lang_rule}

CANDIDATE WINDOWS (signal-ranked, best first):
{cand_lines or '(none)'}

TRANSCRIPT:
{transcript or '(no speech detected — pure gameplay / music)'}"""

    try:
        client = anthropic.Anthropic()
        resp = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": _SCHEMA}},
            system=_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
    except Exception as e:  # network, auth, rate limits — clipping must still work
        log.warning("Claude planning failed (%s) — falling back to signal-based picks", e)
        return None

    if resp.stop_reason in ("refusal", "max_tokens"):
        log.warning("Claude planning stopped with %s — falling back", resp.stop_reason)
        return None
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        clips = json.loads(text)["clips"]
    except (ValueError, KeyError, TypeError):
        log.warning("Claude returned unparseable JSON — falling back")
        return None

    valid: list[dict] = []
    for c in sorted(clips, key=lambda c: -int(c.get("virality_score", 0))):
        s, e = float(c["start"]), float(c["end"])
        s, e = max(0.0, s), min(duration, e)
        if e - s < max(5.0, min_len * 0.6) or e - s > max_len + 8:
            continue
        if any(not (e <= v["start"] or s >= v["end"]) for v in valid):
            continue
        c["start"], c["end"] = s, e
        valid.append(c)
        if len(valid) >= count:
            break
    log.info("Claude picked %d clip(s)", len(valid))
    return valid or None
