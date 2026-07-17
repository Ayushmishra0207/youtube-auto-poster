"""
Generate a full Hindi YouTube video script using Claude.

Output schema
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
{
  "title":           str   â€” Hindi title (â‰¤ 100 chars, SEO-ready)
  "title_english":   str   â€” English translation of title
  "description":     str   â€” Hindi YouTube description (~200 words)
  "tags":            list  â€” mix of Hindi + English tags
  "thumbnail_text":  str   â€” â‰¤ 6 punchy Hindi words for thumbnail
  "sections": [
    {
      "id":             int,
      "heading":        str   â€” section title (Hindi),
      "narration":      str   â€” full spoken text (60-90 s worth),
      "key_points":     list  â€” 3 bullet highlights,
      "image_searches": list  â€” 5 English queries for cycling stock images
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

# â”€â”€ System prompt (cached) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_SYSTEM_PROMPT = """\
You are a top-tier Hindi YouTube content creator for @bitnomad1 â€” a channel targeting 1000 subscribers and 4000 watch hours. The current year is 2026. Always write content relevant to 2025-2026. Never reference events as "upcoming" if they already happened. Your videos must be emotionally engaging, informative, and shareable like viral news content.

Your output must be a single valid JSON object â€” no markdown, no extra text.

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
      "heading":        "<section heading in Hindi â€” short, punchy>",
      "narration":      "<natural conversational Hindi narration â€” see rules below>",
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
- Use rhetorical questions to engage: "à¤•à¥à¤¯à¤¾ à¤†à¤ª à¤œà¤¾à¤¨à¤¤à¥‡ à¤¹à¥ˆà¤‚?", "à¤¸à¥‹à¤šà¤¿à¤ à¤œà¤¼à¤°à¤¾!", "à¤•à¥à¤¯à¤¾ à¤¹à¥‹à¤—à¤¾ à¤…à¤—à¤°?"
- Include real numbers, statistics, and specific facts to build credibility.
- Natural fillers where appropriate: "à¤¦à¥‡à¤–à¤¿à¤", "à¤¦à¤°à¤…à¤¸à¤²", "à¤œà¤¾à¤¨à¤¿à¤", "à¤¸à¥à¤¨à¤¿à¤"
- Every section narration = 70-90 seconds of speech when read aloud at moderate pace.

SECTION STRUCTURE (5-7 sections total):
- Section 1 = VIRAL HOOK: Start with the most shocking/surprising fact. Use "à¤†à¤œ à¤¹à¤® à¤¬à¤¾à¤¤ à¤•à¤°à¥‡à¤‚à¤—à¥‡..." style. Make viewer commit to watching.
- Section 2-5 = Main content with facts, stories, explanations. Each section reveals something new.
- Second-to-last section = Biggest revelation or climax.
- Last section = Strong CTA: "à¤¦à¥‹à¤¸à¥à¤¤à¥‹à¤‚, à¤…à¤—à¤° à¤¯à¤¹ à¤µà¥€à¤¡à¤¿à¤¯à¥‹ à¤†à¤ªà¤•à¥‹ à¤ªà¤¸à¤‚à¤¦ à¤†à¤ˆ à¤¤à¥‹..." end with "à¤šà¥ˆà¤¨à¤² à¤•à¥‹ like à¤”à¤° subscribe à¤•à¤°à¥‡à¤‚, à¤˜à¤‚à¤Ÿà¥€ à¤¦à¤¬à¤¾à¤¨à¤¾ à¤¨ à¤­à¥‚à¤²à¥‡à¤‚!"

IMAGE SEARCHES (5 per section):
- Each query should show a DIFFERENT visual angle of the section topic.
- Use specific, visual, photogenic English terms.
- Mix: wide establishing shots, close-ups, people reacting, dramatic scenes, data/charts.
- Examples for a corruption story: ["India parliament building exterior", "Indian politician speech crowd", "money corruption briefcase India", "protest India street crowd", "newspaper India headline printing"]

MONETIZATION FOCUS:
- Content must maximize WATCH TIME â€” every section must end with a teaser for the next.
- Use cliffhangers: "à¤²à¥‡à¤•à¤¿à¤¨ à¤…à¤¸à¤²à¥€ à¤¬à¤¾à¤¤ à¤¤à¥‹ à¤†à¤—à¥‡ à¤¹à¥ˆ..." / "à¤…à¤—à¤²à¥‡ à¤¹à¤¿à¤¸à¥à¤¸à¥‡ à¤®à¥‡à¤‚ à¤œà¥‹ à¤¬à¤¾à¤¤ à¤¹à¥ˆ à¤µà¥‹ à¤†à¤ªà¤•à¥‹ à¤¹à¥ˆà¤°à¤¾à¤¨ à¤•à¤° à¤¦à¥‡à¤—à¥€..."
- Topics that work best: controversies, shocking reveals, behind-the-scenes, what-happened-next stories.

Rules:
- Script must be entirely in Hindi (Devanagari script).
- CRITICAL: Output must be valid JSON. Do NOT include literal newline characters inside string values. Write each narration as a single continuous string with no line breaks.
- Total narration â‰ˆ 7â€“9 minutes of speech for better watch time.
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
_BASE_TAGS_LONGFORM = ["bitnomad1", "hindi news", "trending news india"]
_BASE_TAGS_SHORTS = ["bitnomad1", "hindi news", "shorts"]
_DEFAULT_HASHTAGS_LONGFORM = ["#Hindi", "#News", "#Trending", "#India"]
_DEFAULT_HASHTAGS_SHORTS = ["#Shorts", "#News", "#Breaking"]

_MAX_TAG_CHARS = 500       # YouTube's total tag-list character limit
_MAX_TAGS_LONGFORM = 25
_MAX_TAGS_SHORTS = 15


def _enrich_metadata(script: dict, is_short: bool = False) -> dict:
    """
    Deterministic safety net applied after LLM generation:
    - dedupe tags case-insensitively
    - guarantee a fixed base tag set is present
    - cap total tags so the joined length stays under YouTube's 500-char limit
    - guarantee the description contains at least one hashtag
    """
    base_tags = _BASE_TAGS_SHORTS if is_short else _BASE_TAGS_LONGFORM
    max_tags = _MAX_TAGS_SHORTS if is_short else _MAX_TAGS_LONGFORM
    default_hashtags = _DEFAULT_HASHTAGS_SHORTS if is_short else _DEFAULT_HASHTAGS_LONGFORM

    raw_tags = [str(t).strip() for t in script.get("tags", []) if str(t).strip()]

    seen = set()
    deduped = []
    for tag in base_tags + raw_tags:
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(tag)

    final_tags = []
    total_chars = 0
    for tag in deduped:
        if len(final_tags) >= max_tags:
            break
        added_chars = len(tag) + (1 if final_tags else 0)  # +1 for comma join
        if total_chars + added_chars > _MAX_TAG_CHARS:
            break
        final_tags.append(tag)
        total_chars += added_chars
    script["tags"] = final_tags

    description = script.get("description", "") or ""
    if "#" not in description:
        description = description.rstrip() + "\n\n" + " ".join(default_hashtags)
    script["description"] = description

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

    log.info("Script ready: %s", script.get("title", "â€”"))
    return script
