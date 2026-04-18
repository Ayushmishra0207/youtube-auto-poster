"""
Generate a full Hindi YouTube video script using Claude.

Output schema
─────────────
{
  "title":           str   — Hindi title (≤ 100 chars, SEO-ready)
  "title_english":   str   — English translation of title
  "description":     str   — Hindi YouTube description (~200 words)
  "tags":            list  — mix of Hindi + English tags
  "thumbnail_text":  str   — ≤ 6 punchy Hindi words for thumbnail
  "sections": [
    {
      "id":           int,
      "heading":      str   — section title (Hindi),
      "narration":    str   — full spoken text (60-90 s worth),
      "key_points":   list  — 3 bullet highlights,
      "image_search": str   — English query for stock photo
    },
    ...
  ]
}

Prompt caching: the system prompt is marked cache_control=ephemeral so it is
cached after the first call. Subsequent calls in the same session skip re-encoding
~600 tokens, cutting Claude API costs by ~80 %.
"""
import json
import re

import anthropic
from json_repair import repair_json

from config import ANTHROPIC_API_KEY
from pipeline.logger import log
from pipeline.retry import with_retry

_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ── System prompt (cached) ────────────────────────────────────────────────────
_SYSTEM_PROMPT = """\
You are a professional Hindi YouTube content creator for the channel @bitnomad1.

Your output must be a single valid JSON object — no markdown, no extra text.

JSON schema:
{
  "title":           "<Hindi title, max 100 chars, SEO-optimised>",
  "title_english":   "<English translation>",
  "description":     "<Hindi YouTube description, ~200 words, include hashtags>",
  "tags":            ["<tag1>", "<tag2>", ...],
  "thumbnail_text":  "<6 punchy Hindi words for thumbnail>",
  "sections": [
    {
      "id":           1,
      "heading":      "<section heading in Hindi>",
      "narration":    "<full narration in Hindi — aim for 70-90 seconds of speech>",
      "key_points":   ["<point 1>", "<point 2>", "<point 3>"],
      "image_search": "<English search term for background stock image>"
    }
  ]
}

Rules:
- Script must be entirely in Hindi (Devanagari script).
- Write 5 to 7 sections. Section 1 = hook, last section = call to action.
- Tone: engaging, conversational, like a friendly news anchor.
- End the last narration with: "चैनल को like और subscribe करें, घंटी दबाना न भूलें!"
- Total narration ≈ 6–8 minutes of speech.
- CRITICAL: Output must be valid JSON. Do NOT include literal newline characters inside string values. Write each narration as a single continuous string with no line breaks.\
"""


def _sanitize_json(text: str) -> str:
    """
    Replace literal (unescaped) newlines and carriage returns inside JSON
    string values with a single space.  Claude occasionally writes long Hindi
    narrations with real newlines, which makes json.loads raise a parse error.
    """
    result = []
    in_string = False
    escape_next = False
    for ch in text:
        if escape_next:
            result.append(ch)
            escape_next = False
        elif ch == "\\":
            result.append(ch)
            escape_next = True
        elif ch == '"':
            result.append(ch)
            in_string = not in_string
        elif in_string and ch in ("\n", "\r"):
            result.append(" ")   # replace bare newline with space
        else:
            result.append(ch)
    return "".join(result)


@with_retry(max_attempts=3, base_delay=5.0, exceptions=(anthropic.APIError, anthropic.APIConnectionError, ValueError))
def generate_script(topic: str, category_style: str = "") -> dict:
    """Call Claude with a cached system prompt and return the parsed script dict."""
    log.info("Generating script for topic: %s", topic)

    user_content = f'Create a complete video script about: "{topic}"'
    if category_style:
        user_content += f"\n\nContent style: {category_style}"

    msg = _client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4096,
        system=[
            {
                "type": "text",
                "text": _SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},  # cache ~600-token prompt
            }
        ],
        messages=[
            {
                "role": "user",
                "content": user_content,
            }
        ],
    )

    raw = msg.content[0].text.strip()

    # Strip any accidental markdown code fences
    raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\n?```$", "", raw, flags=re.MULTILINE)

    # Fix literal newlines inside JSON string values (common with long Hindi narrations)
    clean = _sanitize_json(raw)

    try:
        script = json.loads(clean)
    except json.JSONDecodeError:
        # json_repair handles missing commas, trailing commas, unescaped quotes, etc.
        try:
            repaired = repair_json(clean, return_objects=True)
            if isinstance(repaired, dict) and "sections" in repaired:
                script = repaired
            else:
                raise ValueError("repaired JSON missing expected keys")
        except Exception as repair_exc:
            raise ValueError(
                f"Could not parse Claude response for topic '{topic}' "
                f"(repair also failed: {repair_exc}):\n{raw[:400]}"
            )

    log.info("Script ready: %s", script.get("title", "—"))
    return script
