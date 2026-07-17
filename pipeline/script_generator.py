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
import requests
from json_repair import repair_json

from config import ANTHROPIC_API_KEY, GEMINI_API_KEY, OPENROUTER_API_KEY, OPENROUTER_FALLBACK_MODELS
from pipeline.logger import log
from pipeline.retry import with_retry

_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
_gemini_client = None

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

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


def _parse_script_response(raw: str, topic: str, source: str, required_key: str = "sections") -> dict:
    """Parse a raw JSON-ish LLM response into the script dict, repairing minor errors."""
    raw = raw.strip()

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
            if isinstance(repaired, dict) and required_key in repaired:
                script = repaired
            else:
                raise ValueError("repaired JSON missing expected keys")
        except Exception as repair_exc:
            raise ValueError(
                f"Could not parse {source} response for topic '{topic}' "
                f"(repair also failed: {repair_exc}):\n{raw[:400]}"
            )

    return _normalize_image_searches(script)


@with_retry(max_attempts=3, base_delay=5.0, exceptions=(anthropic.APIError, anthropic.APIConnectionError, ValueError))
def _generate_with_claude(user_content: str, topic: str,
                          system_prompt: str = _SYSTEM_PROMPT, required_key: str = "sections") -> dict:
    msg = _client.messages.create(
        model="claude-opus-4-6",
        max_tokens=6000,
        system=[
            {
                "type": "text",
                "text": system_prompt,
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
    raw = msg.content[0].text
    return _parse_script_response(raw, topic, source="Claude", required_key=required_key)


@with_retry(max_attempts=2, base_delay=3.0, exceptions=(requests.exceptions.RequestException, ValueError))
def _generate_with_openrouter(model: str, user_content: str, topic: str,
                              system_prompt: str = _SYSTEM_PROMPT, required_key: str = "sections") -> dict:
    resp = requests.post(
        _OPENROUTER_URL,
        headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        },
        timeout=120,
    )
    if resp.status_code != 200:
        raise ValueError(f"OpenRouter {model} returned {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    raw = data["choices"][0]["message"]["content"]
    return _parse_script_response(raw, topic, source=f"OpenRouter/{model}", required_key=required_key)


def _get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        from google import genai
        _gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    return _gemini_client


@with_retry(max_attempts=2, base_delay=3.0, exceptions=(Exception,))
def _generate_with_gemini(user_content: str, topic: str,
                          system_prompt: str = _SYSTEM_PROMPT, required_key: str = "sections") -> dict:
    client = _get_gemini_client()
    response = client.models.generate_content(
        model="gemini-flash-lite-latest",
        contents=f"{system_prompt}\n\n{user_content}",
    )
    raw = response.text
    if not raw:
        raise ValueError("Gemini returned empty response")
    return _parse_script_response(raw, topic, source="Gemini", required_key=required_key)


def _generate_via_chain(user_content: str, topic: str,
                        system_prompt: str, required_key: str) -> dict:
    """Claude → free OpenRouter models → Gemini, first success wins."""
    last_exc: Exception
    try:
        script = _generate_with_claude(user_content, topic, system_prompt, required_key)
        log.info("Script ready via Claude: %s", script.get("title", "—"))
        return script
    except Exception as claude_exc:
        log.warning("Claude failed for topic '%s': %s — falling back to free models", topic, claude_exc)
        last_exc = claude_exc

    if OPENROUTER_API_KEY:
        for model in OPENROUTER_FALLBACK_MODELS:
            try:
                script = _generate_with_openrouter(model, user_content, topic, system_prompt, required_key)
                log.info("Script ready via OpenRouter/%s: %s", model, script.get("title", "—"))
                return script
            except Exception as exc:
                log.warning("OpenRouter model %s failed for topic '%s': %s", model, topic, exc)
                last_exc = exc
    else:
        log.warning("OPENROUTER_API_KEY not set — skipping OpenRouter fallback tier")

    if GEMINI_API_KEY:
        try:
            script = _generate_with_gemini(user_content, topic, system_prompt, required_key)
            log.info("Script ready via Gemini: %s", script.get("title", "—"))
            return script
        except Exception as exc:
            log.warning("Gemini fallback failed for topic '%s': %s", topic, exc)
            last_exc = exc
    else:
        log.warning("GEMINI_API_KEY not set — skipping Gemini fallback tier")

    raise ValueError(f"All providers (Claude + OpenRouter + Gemini fallbacks) failed for topic '{topic}'") from last_exc


def generate_script(topic: str, category_style: str = "") -> dict:
    """
    Generate a script via Claude, falling back to free OpenRouter models
    (in order), then direct Gemini, if earlier providers are unavailable
    (out of credits, rate-limited, etc.).
    """
    log.info("Generating script for topic: %s", topic)

    today = datetime.now().strftime("%d %B %Y")
    user_content = f'Today\'s date: {today}\n\nCreate a complete video script about: "{topic}"'
    if category_style:
        user_content += f"\n\nContent style: {category_style}"

    return _generate_via_chain(user_content, topic, _SYSTEM_PROMPT, required_key="sections")


# ── YouTube Shorts scripts ────────────────────────────────────────────────────

_SHORTS_SYSTEM_PROMPT = """\
You are a Hindi breaking-news anchor writing scripts for 60-second YouTube Shorts for @bitnomad1. The current year is 2026.

You will be given REAL news headlines from the last 1-2 days. Your job: pack the MAXIMUM number of breaking news items into one fast-paced 60-second short, each with a very short factual brief. Use ONLY the given headlines as source material — never invent events.

Your output must be a single valid JSON object — no markdown, no extra text.

JSON schema:
{
  "title":        "<Hindi title, max 90 chars, urgent/breaking style, MUST end with #Shorts>",
  "description":  "<Hindi description, 2-3 lines + hashtags #Shorts #News #Breaking>",
  "tags":         ["<10-15 tags, Hindi + English>"],
  "items": [
    {
      "id":           1,
      "headline":     "<3-6 word punchy Hindi headline for on-screen text>",
      "narration":    "<1-2 short Hindi sentences with concrete facts from the headline>",
      "image_search": "<specific English visual query for this news item>"
    }
  ]
}

RULES:
- 5 to 7 items. Cover the most important and diverse stories from the given headlines.
- Total narration across ALL items: 190-220 words maximum. The voice plays at 1.5x speed and everything must fit in under 55 seconds.
- Narration: telegraphic news-flash style. Short punchy sentences. Real names, numbers, places from the headlines.
- Start item 1 narration with a hook like "आज की बड़ी खबरें!" and end the last item with "पूरी खबरों के लिए चैनल को subscribe करें!"
- Everything in Hindi (Devanagari) except proper nouns.
- CRITICAL: valid JSON only, no literal newlines inside string values.\
"""


def generate_shorts_script(headlines: list[str], focus: str = "India and world breaking news") -> dict:
    """
    Generate a 60-second Shorts script covering real headlines from the last 1-2 days.
    Uses the same Claude → OpenRouter → Gemini fallback chain as generate_script.
    """
    log.info("Generating Shorts script (%d headlines, focus: %s)", len(headlines), focus)

    today = datetime.now().strftime("%d %B %Y")
    headline_block = "\n".join(f"- {h}" for h in headlines)
    user_content = (
        f"Today's date: {today}\n\n"
        f"Focus: {focus}\n\n"
        f"Real headlines from the last 1-2 days:\n{headline_block}\n\n"
        f"Create the Shorts script now."
    )

    return _generate_via_chain(user_content, f"shorts:{focus}", _SHORTS_SYSTEM_PROMPT, required_key="items")
