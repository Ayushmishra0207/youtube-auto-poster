"""
Generate a full Hindi YouTube video script using free LLM providers
(Gemini, then free OpenRouter models). Anthropic/Claude is not used by
choice — _generate_with_claude is kept defined but is never called.

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

Note: _generate_with_claude below still marks its system prompt with
cache_control=ephemeral (an Anthropic-only feature) — harmless since that
function is never called in the current free-providers-only chain.
"""
import json
import re
from datetime import datetime

import anthropic
import requests
from json_repair import repair_json

from config import ANTHROPIC_API_KEY, GEMINI_API_KEY, OPENROUTER_API_KEY, OPENROUTER_FALLBACK_MODELS
from pipeline.locales import Locale, get_locale
from pipeline.logger import log
from pipeline.retry import with_retry
from pipeline.text_utils import yt_tag_cost

_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
_gemini_client = None

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def _tag_examples(locale: Locale) -> str:
    tags = locale.base_tags or [locale.language_name.lower() + " news"]
    return '", "'.join(tags[:2])


# ── System prompt (built per-locale; cached per-locale text by the caller) ───
def _build_system_prompt(locale: Locale) -> str:
    lang = locale.language_name
    return f"""\
You are a top-tier {lang} YouTube content creator for @bitnomad1 — a channel targeting 1000 subscribers and 4000 watch hours. The current year is 2026. Always write content relevant to 2025-2026. Never reference events as "upcoming" if they already happened. Your videos must be emotionally engaging, informative, and shareable like viral news content.

Your output must be a single valid JSON object — no markdown, no extra text.

JSON schema:
{{
  "title":           "<{lang} title, max 100 chars, SEO-optimised, uses power words>",
  "title_english":   "<English translation>",
  "description":     "<{lang} YouTube description, ~200 words, include hashtags, starts with hook>",
  "tags":            ["<tag1>", "<tag2>", ...],
  "thumbnail_text":  "<5-6 shocking/urgent {lang} words for thumbnail, makes viewer MUST click>",
  "sections": [
    {{
      "id":             1,
      "heading":        "<section heading in {lang} — short, punchy>",
      "narration":      "<natural conversational {lang} narration — see rules below>",
      "key_points":     ["<point 1>", "<point 2>", "<point 3>"],
      "image_searches": ["<English visual query 1>", "<English visual query 2>", "<English visual query 3>", "<English visual query 4>", "<English visual query 5>"]
    }}
  ]
}}

TITLE RULES (SEO):
- The single most important search keyword (the topic's name/subject) MUST appear within the first 40 characters — mobile search results and the suggested-video feed truncate titles there.
- Combine the keyword with one power word in {lang} (equivalent to "shocking", "revealed", "truth", "why") and, where natural, a number or specific fact.
- Max 100 chars total. Do not use ALL CAPS or excessive punctuation (!!!, ???) — YouTube's spam filters and viewer trust both suffer.

DESCRIPTION RULES (SEO):
- Line 1: a hook line that repeats the primary keyword — this is what shows in search-result snippets and the suggested-video description preview, so it must stand alone and make sense out of context.
- Then 2-3 short paragraphs summarising the story, repeating the keyword and 2-3 close variants naturally (never keyword-stuff — write for a human first).
- Then a one-line subscribe CTA in {lang}.
- End with a clean block of 5-8 hashtags, most important first (YouTube shows the first 3 hashtags above the video title).

TAG RULES (SEO):
- Provide 20-25 tags, ordered broad → specific (YouTube weights earlier tags more heavily). Start with 3-4 broad category tags (e.g. "{_tag_examples(locale)}"), then narrow to the specific topic and named entities.
- Never include two near-duplicate variants of the same phrase (e.g. do not include both "corruption india" and "india corruption") — pick the stronger one.
- Mix {lang} and English tags; include at least a few trending/generic ones.

NARRATION RULES (critical for natural human-like voice):
- Write SHORT sentences. Maximum 12-15 words per sentence. News anchors speak in short bursts.
- Use conversational {lang}, not formal/bookish. Like you're talking to a friend.
- Include emotional hooks: shock, surprise, curiosity, urgency.
- Add natural pauses by ending sentences with periods. Never write a wall of text.
- Use rhetorical questions to engage the viewer, in natural {lang} phrasing (equivalent to English "Did you know?", "Just imagine!", "What if?").
- Use natural filler words/expressions a native {lang} speaker would use casually (equivalent to English "look", "actually", "you know", "listen").
- Every section narration = 30-45 seconds of speech when read aloud at moderate pace.

SECTION STRUCTURE (3-4 sections total):
- Section 1 = VIRAL HOOK: Start with the most shocking/surprising fact, in an opening style equivalent to "Today we're going to talk about...". Make viewer commit to watching.
- Section 2-5 = Main content with facts, stories, explanations. Each section reveals something new.
- Second-to-last section = Biggest revelation or climax.
- Last section = Strong CTA in natural {lang}, ending with something like "{locale.like_share_cta}" (adapt naturally to fit the narration flow, don't just paste it verbatim if it reads awkwardly).

IMAGE SEARCHES (5 per section):
- Each query should show a DIFFERENT visual angle of the section topic.
- Use specific, visual, photogenic English terms (these are stock-photo search queries regardless of narration language).
- Mix: wide establishing shots, close-ups, people reacting, dramatic scenes, data/charts.
- Examples for a corruption story: ["parliament building exterior", "politician speech crowd", "money corruption briefcase", "protest street crowd", "newspaper headline printing"]

THUMBNAIL TEXT RULES:
- Must create real curiosity, but must not promise something the video doesn't actually deliver — misleading thumbnails hurt session watch time and invite complaints, which hurts the channel more than a lower CTR would.

MONETIZATION FOCUS:
- Content must maximize WATCH TIME — every section must end with a teaser for the next.
- Use cliffhangers in natural {lang} (equivalent to English "But the real story is still ahead..." / "What comes next will shock you...").
- Topics that work best: controversies, shocking reveals, behind-the-scenes, what-happened-next stories.

ACCURACY (critical — this channel's credibility depends on it):
- Do NOT invent specific numbers, statistics, dates, quotes, or casualty/death counts that were not given to you as part of the topic. A wrong specific number is far more damaging than a true general statement.
- When you are not certain of an exact figure, describe it qualitatively instead of fabricating precision (e.g. "काफी बड़ी गिरावट" / "a sharp drop", not an invented exact percentage; "कई लोग" / "several people", not an invented exact count).
- Named public figures, organizations, and events must be real and correctly identified — do not attribute a real quote/action to the wrong person, and do not invent a fictional scandal, statement, or event involving a real named person.
- Emotional, dramatic language is fine and expected (per the rules above) — the drama should come from framing and delivery, not from fabricated specifics.

Rules:
- Script must be entirely in {lang}.
- CRITICAL: Output must be valid JSON. Do NOT include literal newline characters inside string values. Write each narration as a single continuous string with no line breaks.
- Total narration ≈ 2–3 minutes of speech. Shorter videos get watched to completion far more often than long ones on a small channel, and completion rate is what earns Suggested/Browse distribution — don't pad length at the expense of finishing strong.\
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


_MAX_TAG_CHARS = 500       # YouTube's total tag-list character limit
_MAX_TAGS_LONGFORM = 25
_MAX_TAGS_SHORTS = 15


def _enrich_metadata(script: dict, is_short: bool = False, locale: Locale | None = None) -> dict:
    """
    Deterministic safety net applied after LLM generation:
    - dedupe tags case-insensitively
    - guarantee a fixed base tag set is present (locale-specific + "bitnomad1"/"shorts")
    - cap total tags so the joined length stays under YouTube's 500-char limit
    - guarantee the description contains at least one hashtag (locale-specific default set)
    """
    locale = locale or get_locale(None)
    base_tags = ["bitnomad1"] + list(locale.base_tags) + (["shorts"] if is_short else [])
    max_tags = _MAX_TAGS_SHORTS if is_short else _MAX_TAGS_LONGFORM
    default_hashtags = locale.default_hashtags

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
        # +1 for comma join; multi-word tags count as quoted (+2) by YouTube
        added_chars = yt_tag_cost(tag) + (1 if final_tags else 0)
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
        # Valid JSON with the wrong shape (e.g. {"script": {...}} or no "sections")
        # must fail here so the retry/provider-fallback chain runs, instead of
        # "succeeding" and crashing later with KeyError and losing the video.
        if not isinstance(script, dict) or not script.get(required_key):
            raise ValueError(
                f"{source} response for topic '{topic}' is missing a non-empty '{required_key}'"
            )
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
                          system_prompt: str, required_key: str = "sections") -> dict:
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
                              system_prompt: str, required_key: str = "sections") -> dict:
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
                          system_prompt: str, required_key: str = "sections") -> dict:
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
    """
    Gemini → free OpenRouter models, first success wins. Claude/Anthropic is
    intentionally NOT called — by request, this project only uses free
    providers. _generate_with_claude is left defined below in case that
    changes later, but nothing in this chain invokes it.
    """
    last_exc: Exception = ValueError(f"No script provider configured for topic '{topic}'")

    if GEMINI_API_KEY:
        try:
            script = _generate_with_gemini(user_content, topic, system_prompt, required_key)
            log.info("Script ready via Gemini: %s", script.get("title", "—"))
            return script
        except Exception as exc:
            log.warning("Gemini failed for topic '%s': %s — falling back to OpenRouter", topic, exc)
            last_exc = exc
    else:
        log.warning("GEMINI_API_KEY not set — skipping Gemini tier")

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

    raise ValueError(f"All free providers (Gemini + OpenRouter) failed for topic '{topic}'") from last_exc


_DEVANAGARI_RANGE = (0x0900, 0x097F)
_LANGUAGE_COMPLIANCE_MIN_RATIO = 0.6


def _script_compliance_ratio(text: str) -> float:
    """
    Fraction of alphabetic characters in `text` that fall in the Devanagari
    Unicode block. Used to detect a free LLM model silently answering in
    English despite the "must be entirely in Hindi" instruction — the free
    providers this project uses (Gemini flash-lite, free OpenRouter models)
    don't always follow it as reliably as Claude would.
    """
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 1.0
    in_script = sum(1 for ch in letters if _DEVANAGARI_RANGE[0] <= ord(ch) <= _DEVANAGARI_RANGE[1])
    return in_script / len(letters)


def _narration_text(script: dict) -> str:
    """Concatenate narration text from a long-form (`sections`) or Shorts (`items`) script."""
    parts = [s.get("narration", "") for s in script.get("sections", [])]
    parts += [it.get("narration", "") for it in script.get("items", [])]
    return " ".join(parts)


def _language_retry_content(user_content: str, locale: Locale) -> str:
    return (
        user_content
        + f"\n\nIMPORTANT: Your previous response was not written entirely in {locale.language_name}. "
        f"You MUST write the ENTIRE script — every narration, heading, and description — in {locale.language_name}."
    )


def _ensure_script_language(script: dict, locale: Locale, regenerate) -> dict:
    """
    If locale uses the Devanagari script, verify the generated narration is
    actually in that script and regenerate once via `regenerate()` if not.
    Falls back to the original script (with a logged warning) if the retry
    also fails the check or raises — matches this project's fail-soft
    convention of never blocking the whole pipeline over one video/short.
    """
    if locale.script != "devanagari":
        return script
    if _script_compliance_ratio(_narration_text(script)) >= _LANGUAGE_COMPLIANCE_MIN_RATIO:
        return script
    log.warning("Script failed %s language check — retrying generation once", locale.language_name)
    try:
        retried = regenerate()
    except Exception as exc:
        log.warning("Language-compliance retry failed (%s) — keeping original script", exc)
        return script
    if _script_compliance_ratio(_narration_text(retried)) < _LANGUAGE_COMPLIANCE_MIN_RATIO:
        log.warning("Retry still failed %s language check — keeping it anyway (best of two attempts)", locale.language_name)
    return retried


def generate_script(topic: str, category_style: str = "", locale: Locale | None = None) -> dict:
    """
    Generate a script via Gemini (free), falling back to free OpenRouter
    models (in order) if Gemini is unavailable (rate-limited, etc.).
    Anthropic/Claude is intentionally not used — free providers only.
    locale drives output language/script/tags/CTAs; defaults to Hindi/India.
    """
    locale = locale or get_locale(None)
    log.info("Generating script for topic: %s (locale=%s)", topic, locale.code)

    today = datetime.now().strftime("%d %B %Y")
    user_content = f'Today\'s date: {today}\n\nCreate a complete video script about: "{topic}"'
    if category_style:
        user_content += f"\n\nContent style: {category_style}"

    system_prompt = _build_system_prompt(locale)
    script = _generate_via_chain(user_content, topic, system_prompt, required_key="sections")
    script = _ensure_script_language(
        script, locale,
        regenerate=lambda: _generate_via_chain(
            _language_retry_content(user_content, locale), topic, system_prompt, required_key="sections",
        ),
    )
    return _enrich_metadata(script, is_short=False, locale=locale)


# ── YouTube Shorts scripts ────────────────────────────────────────────────────

def _build_shorts_system_prompt(locale: Locale) -> str:
    lang = locale.language_name
    return f"""\
You are a {lang} breaking-news anchor writing scripts for 60-second YouTube Shorts for @bitnomad1. The current year is 2026.

You will be given REAL news headlines from the last 1-2 days. Your job: pack the MAXIMUM number of breaking news items into one fast-paced 60-second short, each with a very short factual brief. Use ONLY the given headlines as source material — never invent events.

Your output must be a single valid JSON object — no markdown, no extra text.

JSON schema:
{{
  "title":        "<{lang} title, max 90 chars, urgent/breaking style, keyword in the first 5 words, MUST end with #Shorts>",
  "description":  "<{lang} description, hook line + 3-5 relevant hashtags>",
  "tags":         ["<12-15 tags, {lang} + English>"],
  "items": [
    {{
      "id":           1,
      "headline":     "<3-6 word punchy {lang} headline for on-screen text>",
      "narration":    "<1-2 short {lang} sentences with concrete facts from the headline>",
      "image_search": "<specific English visual query for this news item>"
    }}
  ]
}}

TITLE RULES (SEO + retention):
- The hook (most shocking/curious word or phrase) must land within the first 5 words — Shorts titles get cut off fast in the feed.
- Include one real keyword from the headlines (a name, place, or topic people would actually search).
- MUST end with "#Shorts".

FIRST 3 SECONDS RULE (critical for Shorts retention):
- The narration of item 1 MUST open with a pattern-interrupt hook — a shocking stat or a direct question — that is speakable in under 3 seconds. This is the single biggest lever for whether a Short gets swiped past or watched. Do not open with a generic greeting.

DESCRIPTION RULES (SEO):
- Start with a real hook line (not filler), then 3-5 hashtags that are specific to today's actual headlines/topics (avoid generic-only tags like just "#news" alone).

TAG RULES (SEO):
- Provide 12-15 tags: a fixed broad set ("shorts", "{_tag_examples(locale)}") plus terms specific to today's headlines (names, places, topics).

RULES:
- 5 to 7 items. Cover the most important and diverse stories from the given headlines.
- Total narration across ALL items: 190-220 words maximum. The voice plays at 1.5x speed and everything must fit in under 55 seconds.
- Narration: telegraphic news-flash style. Short punchy sentences. Real names, numbers, places from the headlines — never a number, name, or detail that isn't actually in the given headlines.
- End the LAST item's narration with either a direct question to the viewer or a tease for the "next short" — this nudges comments, which is a strong engagement signal.
- Everything in {lang} except proper nouns.
- CRITICAL: valid JSON only, no literal newlines inside string values.\
"""


def generate_shorts_script(headlines: list[str], focus: str = "India and world breaking news",
                          locale: Locale | None = None, avoid_titles: list[str] | None = None) -> dict:
    """
    Generate a 60-second Shorts script covering real headlines from the last 1-2 days.
    Uses the same Gemini → OpenRouter free-provider chain as generate_script.
    locale drives output language/script/tags; defaults to Hindi/India.
    avoid_titles: titles of recently-generated Shorts (pipeline.topic_history) —
    steers the LLM away from re-leading with the same dominant headline every time.
    """
    locale = locale or get_locale(None)
    log.info("Generating Shorts script (%d headlines, focus: %s, locale=%s)", len(headlines), focus, locale.code)

    today = datetime.now().strftime("%d %B %Y")
    headline_block = "\n".join(f"- {h}" for h in headlines)
    avoid_block = (
        f"\n\nAlready covered in recent Shorts — do NOT lead with these stories again, "
        f"pick a different angle or headline instead:\n" + "\n".join(f"- {t}" for t in avoid_titles)
        if avoid_titles else ""
    )
    user_content = (
        f"Today's date: {today}\n\n"
        f"Focus: {focus}\n\n"
        f"Real headlines from the last 1-2 days:\n{headline_block}"
        f"{avoid_block}\n\n"
        f"Create the Shorts script now."
    )

    system_prompt = _build_shorts_system_prompt(locale)
    script = _generate_via_chain(user_content, f"shorts:{focus}", system_prompt, required_key="items")
    script = _ensure_script_language(
        script, locale,
        regenerate=lambda: _generate_via_chain(
            _language_retry_content(user_content, locale), f"shorts:{focus}", system_prompt, required_key="items",
        ),
    )
    return _enrich_metadata(script, is_short=True, locale=locale)


# ── YouTube Shorts — custom topic (not breaking news) ─────────────────────────

_CONTENT_TYPE_TONE: dict[str, str] = {
    "news": "Keep a factual, breaking-news tone — real, well-known facts framed like a news bulletin.",
    "funny": "Make it genuinely funny — witty, meme-friendly, punchy comedic framing on every point.",
    "story": "Frame the whole thing as a narrative with a hook, a rising middle, and a payoff at the end.",
    "short_story": "Frame this as literary micro-fiction — build toward a twist or surprising final beat.",
    "motivational": "Use an uplifting, second-person voice that pushes the viewer to feel inspired and take action.",
    "entertainment": "Use a buzzy, casual, pop-culture tone, like gossiping about the latest trend.",
    "bollywood": "Frame everything around Bollywood movies, actors, or industry gossip, in a fan-magazine tone.",
    "history": "Tell it like a compelling historical story centered on a real event or figure.",
    "imagination": "Use speculative 'what if' framing — explore hypothetical or imaginative angles on the topic.",
    "devotional": "Use a reverent, spiritual, devotional tone appropriate for religious/spiritual content.",
    "sports": "Use high-energy sports-commentary framing, like a hype reel.",
    "tech": "Use a tech-explainer tone — gadgets, innovation, and 'how it works' framing.",
    "comedy_skit": "Write it like a scripted comedy skit/scene building to a punchline, not a bulletin.",
    "horror_mystery": "Use a suspenseful, eerie tone with an unresolved hook or cliffhanger.",
    "books": "Frame it like a book recommendation/summary — enticing readers to pick it up.",
    "poetry": "Give the narration a verse-like rhythm and vivid imagery, more poetic than bulletin-style.",
}

def _build_shorts_topic_system_prompt(locale: Locale, content_type: str = "news") -> str:
    lang = locale.language_name
    if content_type not in _CONTENT_TYPE_TONE:
        log.warning(
            "Unknown content_type '%s' — falling back to 'news' tone. Valid keys: %s",
            content_type, ", ".join(_CONTENT_TYPE_TONE.keys()),
        )
    tone = _CONTENT_TYPE_TONE.get(content_type, _CONTENT_TYPE_TONE["news"])
    return f"""\
You are a {lang} content creator writing scripts for 60-second YouTube Shorts for @bitnomad1. The current year is 2026.

You will be given a TOPIC chosen by the creator (not breaking-news headlines). Your job: break this topic into the MAXIMUM number of interesting, fact-based points for one fast-paced 60-second short, each with a very short brief. Use your own knowledge of the topic — this is not a news bulletin, so don't claim anything happened "today" unless the topic itself is a recent event.

CONTENT TYPE / TONE: {tone}

Your output must be a single valid JSON object — no markdown, no extra text.

JSON schema:
{{
  "title":        "<{lang} title, max 90 chars, curiosity-driven, keyword in the first 5 words, MUST end with #Shorts>",
  "description":  "<{lang} description, hook line + 3-5 relevant hashtags>",
  "tags":         ["<12-15 tags, {lang} + English>"],
  "items": [
    {{
      "id":           1,
      "headline":     "<3-6 word punchy {lang} headline for on-screen text>",
      "narration":    "<1-2 short {lang} sentences with a concrete fact/angle about the topic>",
      "image_search": "<specific English visual query for this point>"
    }}
  ]
}}

TITLE RULES (SEO + retention):
- The hook (most shocking/curious word or phrase) must land within the first 5 words — Shorts titles get cut off fast in the feed.
- Include one real keyword from the topic.
- MUST end with "#Shorts".

FIRST 3 SECONDS RULE (critical for Shorts retention):
- The narration of item 1 MUST open with a pattern-interrupt hook — a shocking stat or a direct question — that is speakable in under 3 seconds. Do not open with a generic greeting.

DESCRIPTION RULES (SEO):
- Start with a real hook line (not filler), then 3-5 hashtags specific to the topic (avoid generic-only tags like just "#news" alone).

TAG RULES (SEO):
- Provide 12-15 tags: a broad set relevant to the topic's category plus specific terms from the topic itself.

RULES:
- 5 to 7 items. Cover the most interesting, diverse angles of the topic.
- Total narration across ALL items: 190-220 words maximum. The voice plays at 1.5x speed and everything must fit in under 55 seconds.
- Narration: telegraphic, punchy sentences. Use real, well-known facts about the topic — do not invent specific numbers, statistics, dates, or quotes you aren't actually confident are true; describe uncertain specifics qualitatively instead of fabricating precision.
- End the LAST item's narration with either a direct question to the viewer or a tease for the "next short" — this nudges comments, which is a strong engagement signal.
- Everything in {lang} except proper nouns.
- CRITICAL: valid JSON only, no literal newlines inside string values.\
"""


def generate_shorts_script_from_topic(topic: str, locale: Locale | None = None, content_type: str = "news") -> dict:
    """
    Generate a 60-second Shorts script about an arbitrary creator-chosen
    topic, instead of real breaking-news headlines. Uses the same
    Gemini → OpenRouter free-provider chain as generate_script.
    locale drives output language/script/tags; defaults to Hindi/India.
    content_type selects the tone/style injected into the system prompt
    (see _CONTENT_TYPE_TONE) — e.g. "funny", "devotional", "history".
    """
    locale = locale or get_locale(None)
    log.info("Generating Shorts script from topic: %s (locale=%s, content_type=%s)", topic, locale.code, content_type)

    today = datetime.now().strftime("%d %B %Y")
    user_content = (
        f"Today's date: {today}\n\n"
        f"Topic: {topic}\n\n"
        f"Create the Shorts script now."
    )

    system_prompt = _build_shorts_topic_system_prompt(locale, content_type)
    log_label = f"shorts-topic:{topic}:{content_type}"
    script = _generate_via_chain(user_content, log_label, system_prompt, required_key="items")
    script = _ensure_script_language(
        script, locale,
        regenerate=lambda: _generate_via_chain(
            _language_retry_content(user_content, locale), log_label, system_prompt, required_key="items",
        ),
    )
    return _enrich_metadata(script, is_short=True, locale=locale)
