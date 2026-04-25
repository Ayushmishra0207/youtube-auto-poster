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
      "id":             int,
      "heading":        str   — section title (Hindi),
      "narration":      str   — full spoken text (60-90 s worth),
      "key_points":     list  — 3 bullet highlights,
      "image_searches": list  — 5 English queries for cycling stock images
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
from datetime import datetime

import anthropic
from json_repair import repair_json

from config import ANTHROPIC_API_KEY
from pipeline.logger import log
from pipeline.retry import with_retry

_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ── System prompt (cached) ────────────────────────────────────────────────────
_SYSTEM_PROMPT = """\
You are a top-tier Hindi YouTube content creator for @bitnomad1 — a channel targeting 1000 subscribers and 4000 watch hours. The current year is 2026. Always write content relevant to 2025-2026. Never reference events as "upcoming" if they already happened. Your videos must be emotionally engaging, informative, and shareable like viral news content.

Your output must be a single valid JSON object — no markdown, no extra text.

JSON schema:
{
  "title":           "<Hindi title, max 100 chars, SEO-optimised, uses power words>",
  "title_english":   "<English translation>",
  "description":     "<Hindi YouTube description, ~200 words, include hashtags, starts with hook>",
  "tags":            ["<tag1>", "<tag2>", ...],
  "thumbnail_text":  "<5-6 shocking/urgent Hindi words for thumbnail, makes viewer MUST click>",
  "sections": [
    {
      "id":             1,
      "heading":        "<section heading in Hindi — short, punchy>",
      "narration":      "<natural conversational Hindi narration — see rules below>",
      "key_points":     ["<point 1>", "<point 2>", "<point 3>"],
      "image_searches": ["<English visual query 1>", "<English visual query 2>", "<English visual query 3>", "<English visual query 4>", "<English visual query 5>"]
    }
  ]
}

NARRATION RULES (critical for natural human-like voice):
- Write SHORT sentences. Maximum 12-15 words per sentence. News anchors speak in short bursts.
- Use conversational Hindi, not formal/bookish. Like you're talking to a friend.
- Include emotional hooks: shock, surprise, curiosity, urgency.
- Add natural pauses by ending sentences with periods. Never write a wall of text.
- Use rhetorical questions to engage: "क्या आप जानते हैं?", "सोचिए ज़रा!", "क्या होगा अगर?"
- Include real numbers, statistics, and specific facts to build credibility.
- Natural fillers where appropriate: "देखिए", "दरअसल", "जानिए", "सुनिए"
- Every section narration = 70-90 seconds of speech when read aloud at moderate pace.

SECTION STRUCTURE (5-7 sections total):
- Section 1 = VIRAL HOOK: Start with the most shocking/surprising fact. Use "आज हम बात करेंगे..." style. Make viewer commit to watching.
- Section 2-5 = Main content with facts, stories, explanations. Each section reveals something new.
- Second-to-last section = Biggest revelation or climax.
- Last section = Strong CTA: "दोस्तों, अगर यह वीडियो आपको पसंद आई तो..." end with "चैनल को like और subscribe करें, घंटी दबाना न भूलें!"

IMAGE SEARCHES (5 per section):
- Each query should show a DIFFERENT visual angle of the section topic.
- Use specific, visual, photogenic English terms.
- Mix: wide establishing shots, close-ups, people reacting, dramatic scenes, data/charts.
- Examples for a corruption story: ["India parliament building exterior", "Indian politician speech crowd", "money corruption briefcase India", "protest India street crowd", "newspaper India headline printing"]

MONETIZATION FOCUS:
- Content must maximize WATCH TIME — every section must end with a teaser for the next.
- Use cliffhangers: "लेकिन असली बात तो आगे है..." / "अगले हिस्से में जो बात है वो आपको हैरान कर देगी..."
- Topics that work best: controversies, shocking reveals, behind-the-scenes, what-happened-next stories.

Rules:
- Script must be entirely in Hindi (Devanagari script).
- CRITICAL: Output must be valid JSON. Do NOT include literal newline characters inside string values. Write each narration as a single continuous string with no line breaks.
- Total narration ≈ 7–9 minutes of speech for better watch time.
- Tags: 15-20 mix of Hindi + English, include trending ones.\
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


def _normalize_image_searches(script: dict) -> dict:
    """
    Ensure every section has `image_searches` as a list of strings.
    Handles backward-compat if Claude returns the old `image_search` string field.
    """
    for section in script.get("sections", []):
        if "image_searches" not in section:
            # Upgrade old single-string field
            old = section.pop("image_search", None) or "india news background"
            section["image_searches"] = [old, f"{old} crowd", f"{old} closeup", "india news studio", "india flag background"]
        elif isinstance(section["image_searches"], str):
            # Claude returned a string instead of list
            s = section["image_searches"]
            section["image_searches"] = [s]
        # Ensure at least 1 entry
        if not section["image_searches"]:
            section["image_searches"] = ["india news background"]
    return script


@with_retry(max_attempts=3, base_delay=5.0, exceptions=(anthropic.APIError, anthropic.APIConnectionError, ValueError))
def generate_script(topic: str, category_style: str = "") -> dict:
    """Call Claude with a cached system prompt and return the parsed script dict."""
    log.info("Generating script for topic: %s", topic)

    today = datetime.now().strftime("%d %B %Y")
    user_content = f'Today\'s date: {today}\n\nCreate a complete video script about: "{topic}"'
    if category_style:
        user_content += f"\n\nContent style: {category_style}"

    msg = _client.messages.create(
        model="claude-opus-4-6",
        max_tokens=6000,
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

    # Normalize image_searches field (handles old single-string format)
    script = _normalize_image_searches(script)

    log.info("Script ready: %s", script.get("title", "—"))
    return script
