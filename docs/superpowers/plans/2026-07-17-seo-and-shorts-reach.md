# SEO & Reach Improvements for Videos and Shorts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve SEO metadata (titles, descriptions, tags, chapter timestamps) and retention-relevant prompt rules for both the 7 daily long-form videos and the 3 daily YouTube Shorts, so uploads are more discoverable and better packaged for CTR/watch-time.

**Architecture:** All changes live in three existing files — `pipeline/script_generator.py` (LLM prompt rules + a deterministic metadata post-processing safety net), `pipeline/video_creator.py` (pure chapter-offset math + a real-audio-duration chapter builder), and `scheduler.py` (wiring the chapter builder into the existing per-video pipeline). No new files are created except test scripts.

**Tech Stack:** Python 3, no test framework (project has none — see Global Constraints). `moviepy` (already a real dependency, used for video/audio elsewhere in the pipeline) generates silent-audio fixtures for chapter tests. `unittest.mock.patch` (stdlib) stubs the LLM call for wiring tests.

## Global Constraints

- No test suite or pytest exists in this project. Tests are plain Python scripts under `tests/` using bare `assert` statements, with an `if __name__ == "__main__":` block that calls every test function and prints `All tests passed.` on success. Run with `python tests/test_x.py`; a failed assert raises `AssertionError` and a nonzero exit.
- YouTube's total tag-list character limit is 500 characters (joined length, used by `_enrich_metadata`).
- Video title limit stays ≤100 chars (already enforced in `uploader.py:93`, do not change).
- All LLM prompts must still produce a single valid JSON object — no markdown, no extra text — matching the existing schema keys. Prompt edits must not change the JSON schema shape.
- Timing constants that already exist and must be reused (not redefined) in chapter math: `_XFADE = 0.6` (crossfade seconds, `pipeline/video_creator.py`), the `0.8` second tail added to every section's audio duration (`pipeline/video_creator.py` `_build_section_clip`), and the `5` second title card duration (`pipeline/video_creator.py` `create_video`).
- Never run `python scheduler.py --now` or `python generate_short_now.py` during implementation or verification — both upload real videos to a live YouTube channel. Verification calls `generate_script()`, `generate_shorts_script()`, `build_chapters()`, or the new helper functions directly, never the full pipeline entry points.
- Chapters are a long-form-only feature. YouTube Shorts do not support chapters — do not wire `build_chapters()` into `generate_short_now.py` or the Shorts branch of `scheduler.py`.
- `pydub` (declared in `requirements.txt` but unused anywhere in production code) is broken under this project's Python 3.13 environment — it imports the removed stdlib `audioop` module and no backport is installed. Do not use `pydub` for anything, including test fixtures. Use `moviepy`'s `mpe.AudioClip` (confirmed working) to generate silent-audio test fixtures instead — see the exact helper in Tasks 6 and 7.

---

### Task 1: Deterministic tag/hashtag safety net (`_enrich_metadata`)

**Files:**
- Modify: `pipeline/script_generator.py` (add constants + function after `_normalize_image_searches`, around line 148)
- Test: `tests/test_enrich_metadata.py` (new)

**Interfaces:**
- Produces: `_enrich_metadata(script: dict, is_short: bool = False) -> dict` — mutates and returns `script` with `script["tags"]` deduped/capped/base-tagged and `script["description"]` guaranteed to contain at least one `#` hashtag. Later tasks (Task 2) call this directly.

- [ ] **Step 1: Write the failing test**

Create the `tests/` directory and the test file:

```bash
mkdir -p tests
```

```python
# tests/test_enrich_metadata.py
from pipeline.script_generator import _enrich_metadata


def test_dedupes_case_insensitive_tags():
    script = {"tags": ["Hindi News", "HINDI news", "corruption"], "description": "hook"}
    result = _enrich_metadata(script, is_short=False)
    lowered = [t.lower() for t in result["tags"]]
    assert lowered.count("hindi news") == 1


def test_base_tags_always_present():
    script = {"tags": [], "description": "hook"}
    result = _enrich_metadata(script, is_short=False)
    assert "bitnomad1" in [t.lower() for t in result["tags"]]


def test_caps_tag_count():
    script = {"tags": [f"tag{i}" for i in range(50)], "description": "hook"}
    result = _enrich_metadata(script, is_short=False)
    assert len(result["tags"]) <= 25


def test_caps_total_char_length():
    script = {"tags": ["x" * 100 for _ in range(10)], "description": "hook"}
    result = _enrich_metadata(script, is_short=False)
    joined_len = sum(len(t) for t in result["tags"]) + max(0, len(result["tags"]) - 1)
    assert joined_len <= 500


def test_appends_default_hashtags_when_missing():
    script = {"tags": [], "description": "no hashtags here"}
    result = _enrich_metadata(script, is_short=False)
    assert "#" in result["description"]


def test_keeps_existing_hashtags_untouched():
    script = {"tags": [], "description": "hook #MyOwnTag"}
    result = _enrich_metadata(script, is_short=False)
    assert result["description"] == "hook #MyOwnTag"


def test_shorts_uses_shorts_base_tags():
    script = {"tags": [], "description": "hook"}
    result = _enrich_metadata(script, is_short=True)
    assert "shorts" in [t.lower() for t in result["tags"]]


if __name__ == "__main__":
    test_dedupes_case_insensitive_tags()
    test_base_tags_always_present()
    test_caps_tag_count()
    test_caps_total_char_length()
    test_appends_default_hashtags_when_missing()
    test_keeps_existing_hashtags_untouched()
    test_shorts_uses_shorts_base_tags()
    print("All tests passed.")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python tests/test_enrich_metadata.py`
Expected: `ImportError: cannot import name '_enrich_metadata' from 'pipeline.script_generator'`

- [ ] **Step 3: Implement `_enrich_metadata`**

In `pipeline/script_generator.py`, insert after `_normalize_image_searches` (after the line `return script` that closes it, currently line 147):

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python tests/test_enrich_metadata.py`
Expected: `All tests passed.`

- [ ] **Step 5: Commit**

```bash
git add pipeline/script_generator.py tests/test_enrich_metadata.py
git commit -m "feat: add deterministic tag/hashtag safety net for video metadata"
```

---

### Task 2: Wire `_enrich_metadata` into `generate_script` and `generate_shorts_script`

**Files:**
- Modify: `pipeline/script_generator.py:287-300` (`generate_script`) and `:337-353` (`generate_shorts_script`)
- Test: `tests/test_generate_script_wiring.py` (new)

**Interfaces:**
- Consumes: `_enrich_metadata(script: dict, is_short: bool = False) -> dict` from Task 1.
- Produces: `generate_script(...)` and `generate_shorts_script(...)` now always return enriched dicts. No signature changes — callers in `scheduler.py` and `generate_short_now.py` are unaffected.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_generate_script_wiring.py
from unittest.mock import patch
from pipeline import script_generator


def test_generate_script_applies_enrichment():
    fake_script = {"title": "t", "description": "hook", "tags": [], "sections": []}
    with patch.object(script_generator, "_generate_via_chain", return_value=fake_script):
        result = script_generator.generate_script("some topic")
    assert "bitnomad1" in [t.lower() for t in result["tags"]]
    assert "#" in result["description"]


def test_generate_shorts_script_applies_enrichment():
    fake_script = {"title": "t", "description": "hook", "tags": [], "items": []}
    with patch.object(script_generator, "_generate_via_chain", return_value=fake_script):
        result = script_generator.generate_shorts_script(["headline 1", "headline 2", "headline 3"])
    assert "shorts" in [t.lower() for t in result["tags"]]
    assert "#" in result["description"]


if __name__ == "__main__":
    test_generate_script_applies_enrichment()
    test_generate_shorts_script_applies_enrichment()
    print("All tests passed.")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python tests/test_generate_script_wiring.py`
Expected: `AssertionError` (tags list is empty — `_enrich_metadata` is not yet called, so no base tags were injected)

- [ ] **Step 3: Wire enrichment into both generators**

In `pipeline/script_generator.py`, change the end of `generate_script` (currently):

```python
    return _generate_via_chain(user_content, topic, _SYSTEM_PROMPT, required_key="sections")
```

to:

```python
    script = _generate_via_chain(user_content, topic, _SYSTEM_PROMPT, required_key="sections")
    return _enrich_metadata(script, is_short=False)
```

And change the end of `generate_shorts_script` (currently):

```python
    return _generate_via_chain(user_content, f"shorts:{focus}", _SHORTS_SYSTEM_PROMPT, required_key="items")
```

to:

```python
    script = _generate_via_chain(user_content, f"shorts:{focus}", _SHORTS_SYSTEM_PROMPT, required_key="items")
    return _enrich_metadata(script, is_short=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python tests/test_generate_script_wiring.py`
Expected: `All tests passed.`

- [ ] **Step 5: Commit**

```bash
git add pipeline/script_generator.py tests/test_generate_script_wiring.py
git commit -m "feat: apply metadata safety net to generate_script and generate_shorts_script"
```

---

### Task 3: Rewrite the long-form system prompt for SEO/retention

**Files:**
- Modify: `pipeline/script_generator.py:46-101` (`_SYSTEM_PROMPT`)
- Test: `tests/test_longform_prompt_rules.py` (new)

**Interfaces:**
- Consumes: nothing new.
- Produces: `_SYSTEM_PROMPT` (module-level string) still contains the exact same JSON schema keys (`title`, `title_english`, `description`, `tags`, `thumbnail_text`, `sections`) — Task 3 only changes the prose rules, not the schema, so `video_creator.py` and `voice_generator.py` consumers are unaffected.

- [ ] **Step 1: Write the failing test**

This is a regression guard: it asserts the new rule phrases exist in the prompt, so a future edit can't silently drop them. It cannot test actual LLM output quality (that requires a real API call — see the manual verification note in Step 5).

```python
# tests/test_longform_prompt_rules.py
from pipeline.script_generator import _SYSTEM_PROMPT


def test_title_keyword_placement_rule_present():
    assert "first 40 characters" in _SYSTEM_PROMPT or "first 40 chars" in _SYSTEM_PROMPT


def test_description_structure_rules_present():
    assert "hook line" in _SYSTEM_PROMPT.lower()
    assert "hashtag" in _SYSTEM_PROMPT.lower()


def test_tag_count_and_ordering_rule_present():
    assert "20-25" in _SYSTEM_PROMPT
    assert "broad" in _SYSTEM_PROMPT.lower()


def test_schema_keys_unchanged():
    for key in ("title", "title_english", "description", "tags", "thumbnail_text", "sections"):
        assert f'"{key}"' in _SYSTEM_PROMPT


if __name__ == "__main__":
    test_title_keyword_placement_rule_present()
    test_description_structure_rules_present()
    test_tag_count_and_ordering_rule_present()
    test_schema_keys_unchanged()
    print("All tests passed.")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python tests/test_longform_prompt_rules.py`
Expected: `AssertionError` on `test_title_keyword_placement_rule_present` (current prompt has no "first 40 characters" rule)

- [ ] **Step 3: Rewrite `_SYSTEM_PROMPT`**

In `pipeline/script_generator.py`, replace the whole `_SYSTEM_PROMPT` string (lines 46-101) with:

```python
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

TITLE RULES (SEO):
- The single most important search keyword (the topic's name/subject) MUST appear within the first 40 characters — mobile search results and the suggested-video feed truncate titles there.
- Combine the keyword with one power word (शॉकिंग, खुलासा, सच्चाई, वजह) and, where natural, a number or specific fact.
- Max 100 chars total. Do not use ALL CAPS or excessive punctuation (!!!, ???) — YouTube's spam filters and viewer trust both suffer.

DESCRIPTION RULES (SEO):
- Line 1: a hook line that repeats the primary keyword — this is what shows in search-result snippets and the suggested-video description preview, so it must stand alone and make sense out of context.
- Then 2-3 short paragraphs summarising the story, repeating the keyword and 2-3 close variants naturally (never keyword-stuff — write for a human first).
- Then a one-line subscribe CTA.
- End with a clean block of 5-8 hashtags, most important first (YouTube shows the first 3 hashtags above the video title).

TAG RULES (SEO):
- Provide 20-25 tags, ordered broad → specific (YouTube weights earlier tags more heavily). Start with 3-4 broad category tags (e.g. "hindi news", "india news"), then narrow to the specific topic and named entities.
- Never include two near-duplicate variants of the same phrase (e.g. do not include both "corruption india" and "india corruption") — pick the stronger one.
- Mix Hindi and English tags; include at least a few trending/generic ones.

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

THUMBNAIL TEXT RULES:
- Must create real curiosity, but must not promise something the video doesn't actually deliver — misleading thumbnails hurt session watch time and invite complaints, which hurts the channel more than a lower CTR would.

MONETIZATION FOCUS:
- Content must maximize WATCH TIME — every section must end with a teaser for the next.
- Use cliffhangers: "लेकिन असली बात तो आगे है..." / "अगले हिस्से में जो बात है वो आपको हैरान कर देगी..."
- Topics that work best: controversies, shocking reveals, behind-the-scenes, what-happened-next stories.

Rules:
- Script must be entirely in Hindi (Devanagari script).
- CRITICAL: Output must be valid JSON. Do NOT include literal newline characters inside string values. Write each narration as a single continuous string with no line breaks.
- Total narration ≈ 7–9 minutes of speech for better watch time.\
"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python tests/test_longform_prompt_rules.py`
Expected: `All tests passed.`

- [ ] **Step 5: Optional manual quality check (not automated — costs API credit)**

This step is informational, not part of the automated test cycle. To eyeball real LLM output against the new rules without creating or uploading any video, run:

```bash
python -c "from pipeline.script_generator import generate_script; import json; print(json.dumps(generate_script('टेस्ट टॉपिक: भारत में महंगाई'), ensure_ascii=False, indent=2))"
```

This only calls the Claude/OpenRouter/Gemini text API (same cost as one normal script generation) — it does not touch voice, images, video rendering, or the YouTube API.

- [ ] **Step 6: Commit**

```bash
git add pipeline/script_generator.py tests/test_longform_prompt_rules.py
git commit -m "feat: rewrite long-form SEO prompt rules (title keyword placement, structured description, tag ordering)"
```

---

### Task 4: Rewrite the Shorts system prompt for SEO/retention

**Files:**
- Modify: `pipeline/script_generator.py:305-334` (`_SHORTS_SYSTEM_PROMPT`)
- Test: `tests/test_shorts_prompt_rules.py` (new)

**Interfaces:**
- Consumes: nothing new.
- Produces: `_SHORTS_SYSTEM_PROMPT` still contains the same JSON schema keys (`title`, `description`, `tags`, `items` with `id`/`headline`/`narration`/`image_search`) — schema unchanged, `shorts_creator.py` consumers unaffected.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_shorts_prompt_rules.py
from pipeline.script_generator import _SHORTS_SYSTEM_PROMPT


def test_first_line_hook_rule_present():
    assert "first 5 words" in _SHORTS_SYSTEM_PROMPT or "3 seconds" in _SHORTS_SYSTEM_PROMPT


def test_hashtag_count_rule_present():
    assert "3-5" in _SHORTS_SYSTEM_PROMPT


def test_tag_count_rule_present():
    assert "12-15" in _SHORTS_SYSTEM_PROMPT


def test_next_short_tease_rule_present():
    assert "next short" in _SHORTS_SYSTEM_PROMPT.lower()


def test_schema_keys_unchanged():
    for key in ("title", "description", "tags", "items", "headline", "narration", "image_search"):
        assert f'"{key}"' in _SHORTS_SYSTEM_PROMPT


if __name__ == "__main__":
    test_first_line_hook_rule_present()
    test_hashtag_count_rule_present()
    test_tag_count_rule_present()
    test_next_short_tease_rule_present()
    test_schema_keys_unchanged()
    print("All tests passed.")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python tests/test_shorts_prompt_rules.py`
Expected: `AssertionError` on `test_first_line_hook_rule_present`

- [ ] **Step 3: Rewrite `_SHORTS_SYSTEM_PROMPT`**

In `pipeline/script_generator.py`, replace the whole `_SHORTS_SYSTEM_PROMPT` string (lines 305-334) with:

```python
_SHORTS_SYSTEM_PROMPT = """\
You are a Hindi breaking-news anchor writing scripts for 60-second YouTube Shorts for @bitnomad1. The current year is 2026.

You will be given REAL news headlines from the last 1-2 days. Your job: pack the MAXIMUM number of breaking news items into one fast-paced 60-second short, each with a very short factual brief. Use ONLY the given headlines as source material — never invent events.

Your output must be a single valid JSON object — no markdown, no extra text.

JSON schema:
{
  "title":        "<Hindi title, max 90 chars, urgent/breaking style, keyword in the first 5 words, MUST end with #Shorts>",
  "description":  "<Hindi description, hook line + 3-5 relevant hashtags>",
  "tags":         ["<12-15 tags, Hindi + English>"],
  "items": [
    {
      "id":           1,
      "headline":     "<3-6 word punchy Hindi headline for on-screen text>",
      "narration":    "<1-2 short Hindi sentences with concrete facts from the headline>",
      "image_search": "<specific English visual query for this news item>"
    }
  ]
}

TITLE RULES (SEO + retention):
- The hook (most shocking/curious word or phrase) must land within the first 5 words — Shorts titles get cut off fast in the feed.
- Include one real keyword from the headlines (a name, place, or topic people would actually search).
- MUST end with "#Shorts".

FIRST 3 SECONDS RULE (critical for Shorts retention):
- The narration of item 1 MUST open with a pattern-interrupt hook — a shocking stat or a direct question — that is speakable in under 3 seconds. This is the single biggest lever for whether a Short gets swiped past or watched. Do not open with a generic greeting.

DESCRIPTION RULES (SEO):
- Start with a real hook line (not filler), then 3-5 hashtags that are specific to today's actual headlines/topics (avoid generic-only tags like just "#news" alone).

TAG RULES (SEO):
- Provide 12-15 tags: a fixed broad set ("shorts", "hindi news", "breaking news") plus terms specific to today's headlines (names, places, topics).

RULES:
- 5 to 7 items. Cover the most important and diverse stories from the given headlines.
- Total narration across ALL items: 190-220 words maximum. The voice plays at 1.5x speed and everything must fit in under 55 seconds.
- Narration: telegraphic news-flash style. Short punchy sentences. Real names, numbers, places from the headlines.
- End the LAST item's narration with either a direct question to the viewer or a tease for the "next short" — this nudges comments, which is a strong engagement signal.
- Everything in Hindi (Devanagari) except proper nouns.
- CRITICAL: valid JSON only, no literal newlines inside string values.\
"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python tests/test_shorts_prompt_rules.py`
Expected: `All tests passed.`

- [ ] **Step 5: Optional manual quality check (not automated — costs API credit)**

```bash
python -c "from pipeline.script_generator import generate_shorts_script; import json; print(json.dumps(generate_shorts_script(['भारत में महंगाई बढ़ी', 'शेयर बाजार में उछाल', 'नई सरकारी योजना का ऐलान']), ensure_ascii=False, indent=2))"
```

Only calls the text API — creates no video, uploads nothing.

- [ ] **Step 6: Commit**

```bash
git add pipeline/script_generator.py tests/test_shorts_prompt_rules.py
git commit -m "feat: rewrite Shorts SEO prompt rules (first-3-seconds hook, hashtags, comment-nudge ending)"
```

---

### Task 5: Pure chapter-offset math (`_compute_chapter_offsets`, `_format_timestamp`)

**Files:**
- Modify: `pipeline/video_creator.py` (add functions near the bottom, after `create_thumbnail` and before `create_video`, i.e. after line 393)
- Test: `tests/test_chapter_offsets.py` (new)

**Interfaces:**
- Produces:
  - `_format_timestamp(total_seconds: float) -> str` — formats as `"M:SS"`.
  - `_compute_chapter_offsets(section_headings: list[str], section_durations: list[Optional[float]], title_card_seconds: float = 5.0, xfade_seconds: float = _XFADE, tail_seconds: float = 0.8, min_chapter_seconds: float = 10.0) -> list[tuple[float, str]]` — pure function, no file I/O. `section_durations[i]` is `None` (or any falsy value) if that section's voice failed and was skipped in `create_video`. Task 6 calls this with real durations read from disk.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_chapter_offsets.py
from pipeline.video_creator import _compute_chapter_offsets, _format_timestamp


def test_format_timestamp_basic():
    assert _format_timestamp(0) == "0:00"
    assert _format_timestamp(65) == "1:05"
    assert _format_timestamp(599.6) == "10:00"


def test_first_chapter_forced_to_zero():
    offsets = _compute_chapter_offsets(
        section_headings=["भाग 1", "भाग 2"],
        section_durations=[20.0, 15.0],
    )
    assert offsets[0][0] == 0.0
    assert offsets[0][1] == "भाग 1"


def test_skips_section_with_no_duration():
    offsets = _compute_chapter_offsets(
        section_headings=["भाग 1", "गायब"],
        section_durations=[20.0, None],
    )
    assert len(offsets) == 1
    assert offsets[0][1] == "भाग 1"


def test_merges_chapter_closer_than_minimum_gap():
    offsets = _compute_chapter_offsets(
        section_headings=["भाग 1", "भाग 2", "भाग 3"],
        section_durations=[20.0, 3.0, 20.0],
    )
    headings = [h for _, h in offsets]
    assert "भाग 3" not in headings
    assert "भाग 2" in headings


if __name__ == "__main__":
    test_format_timestamp_basic()
    test_first_chapter_forced_to_zero()
    test_skips_section_with_no_duration()
    test_merges_chapter_closer_than_minimum_gap()
    print("All tests passed.")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python tests/test_chapter_offsets.py`
Expected: `ImportError: cannot import name '_compute_chapter_offsets' from 'pipeline.video_creator'`

- [ ] **Step 3: Implement both functions**

In `pipeline/video_creator.py`, insert immediately after `create_thumbnail` (after its closing `return output_path` on line 393) and before `def create_video(`:

```python
def _format_timestamp(total_seconds: float) -> str:
    """Format seconds as YouTube chapter-marker text: "M:SS"."""
    total_seconds = max(0, int(round(total_seconds)))
    m, s = divmod(total_seconds, 60)
    return f"{m}:{s:02d}"


def _compute_chapter_offsets(
    section_headings: list,
    section_durations: list,
    title_card_seconds: float = 5.0,
    xfade_seconds: float = _XFADE,
    tail_seconds: float = 0.8,
    min_chapter_seconds: float = 10.0,
) -> list:
    """
    Pure function: compute chapter (start_seconds, heading) pairs matching
    create_video's actual clip timeline (title card + non-skipped sections,
    each transition overlapped by xfade_seconds).

    The title card has no chapter of its own — it is too short (5s) to ever
    satisfy min_chapter_seconds, so its time is folded into the first
    section's chapter, which is always forced to start at 0:00 (YouTube
    requires the first chapter marker at 0:00). Any later chapter that would
    start less than min_chapter_seconds after the previous kept chapter is
    dropped (merged into the previous chapter).
    """
    included = [title_card_seconds]
    kept_headings = []
    for heading, dur in zip(section_headings, section_durations):
        if dur:
            included.append(dur + tail_seconds)
            kept_headings.append(heading)

    if not kept_headings:
        return [(0.0, section_headings[0] if section_headings else "")]

    starts = []
    cum = 0.0
    for k in range(len(included)):
        starts.append(cum - k * xfade_seconds)
        cum += included[k]
    section_starts = starts[1:]  # one per kept section, in order

    chapters = [(0.0, kept_headings[0])]
    for heading, start in zip(kept_headings[1:], section_starts[1:]):
        if start - chapters[-1][0] >= min_chapter_seconds:
            chapters.append((start, heading))
    return chapters
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python tests/test_chapter_offsets.py`
Expected: `All tests passed.`

- [ ] **Step 5: Commit**

```bash
git add pipeline/video_creator.py tests/test_chapter_offsets.py
git commit -m "feat: add pure chapter-offset math matching create_video's crossfade timeline"
```

---

### Task 6: `build_chapters` — real audio-duration wrapper

**Files:**
- Modify: `pipeline/video_creator.py` (add function right after `_compute_chapter_offsets` from Task 5)
- Test: `tests/test_build_chapters.py` (new)

**Interfaces:**
- Consumes: `_compute_chapter_offsets`, `_format_timestamp` from Task 5.
- Produces: `build_chapters(script: dict, voices: list[str], title_card_seconds: float = 5.0) -> str` — a plain-text chapter block ("M:SS heading" per line). Task 7 calls this from `scheduler.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_build_chapters.py
import tempfile
from pathlib import Path

import moviepy as mpe
import numpy as np

from pipeline.video_creator import build_chapters


def _make_silent_mp3(path: str, seconds: float):
    def make_frame(t):
        if np.isscalar(t):
            return np.array([0.0, 0.0])
        return np.zeros((len(t), 2))
    clip = mpe.AudioClip(make_frame, duration=seconds, fps=44100)
    clip.write_audiofile(path, logger=None)
    clip.close()


def test_build_chapters_matches_pure_offsets():
    with tempfile.TemporaryDirectory() as tmp:
        v1 = str(Path(tmp) / "v1.mp3")
        v2 = str(Path(tmp) / "v2.mp3")
        _make_silent_mp3(v1, 20.0)
        _make_silent_mp3(v2, 15.0)
        script = {"sections": [{"heading": "पहला हिस्सा"}, {"heading": "दूसरा हिस्सा"}]}
        result = build_chapters(script, [v1, v2])
        lines = result.strip().split("\n")
        assert len(lines) == 2
        assert lines[0] == "0:00 पहला हिस्सा"
        assert "दूसरा हिस्सा" in lines[1]


def test_build_chapters_skips_missing_voice():
    with tempfile.TemporaryDirectory() as tmp:
        v1 = str(Path(tmp) / "v1.mp3")
        _make_silent_mp3(v1, 20.0)
        script = {"sections": [{"heading": "पहला हिस्सा"}, {"heading": "गायब हिस्सा"}]}
        result = build_chapters(script, [v1, ""])
        assert "गायब हिस्सा" not in result


def test_build_chapters_merges_short_gap():
    with tempfile.TemporaryDirectory() as tmp:
        v1 = str(Path(tmp) / "v1.mp3")
        v2 = str(Path(tmp) / "v2.mp3")
        v3 = str(Path(tmp) / "v3.mp3")
        _make_silent_mp3(v1, 20.0)
        _make_silent_mp3(v2, 3.0)
        _make_silent_mp3(v3, 20.0)
        script = {"sections": [
            {"heading": "भाग 1"}, {"heading": "भाग 2"}, {"heading": "भाग 3"},
        ]}
        result = build_chapters(script, [v1, v2, v3])
        assert "भाग 3" not in result
        assert "भाग 2" in result


if __name__ == "__main__":
    test_build_chapters_matches_pure_offsets()
    test_build_chapters_skips_missing_voice()
    test_build_chapters_merges_short_gap()
    print("All tests passed.")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python tests/test_build_chapters.py`
Expected: `ImportError: cannot import name 'build_chapters' from 'pipeline.video_creator'`

- [ ] **Step 3: Implement `build_chapters`**

In `pipeline/video_creator.py`, insert right after `_compute_chapter_offsets` (from Task 5):

```python
def build_chapters(script: dict, voices: list, title_card_seconds: float = 5.0) -> str:
    """
    Read each section's real voice-clip duration and format YouTube chapter
    markers as a plain text block ("M:SS heading" per line). Long-form only
    — YouTube Shorts do not support chapters.
    """
    sections = script.get("sections", [])
    headings = [s.get("heading", "") for s in sections]

    durations = []
    for v in voices:
        if v and os.path.exists(v):
            try:
                clip = mpe.AudioFileClip(v)
                durations.append(clip.duration)
                clip.close()
            except Exception:
                durations.append(None)
        else:
            durations.append(None)

    offsets = _compute_chapter_offsets(headings, durations, title_card_seconds=title_card_seconds)
    return "\n".join(f"{_format_timestamp(t)} {h}" for t, h in offsets)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python tests/test_build_chapters.py`
Expected: `All tests passed.`

- [ ] **Step 5: Commit**

```bash
git add pipeline/video_creator.py tests/test_build_chapters.py
git commit -m "feat: add build_chapters wrapper reading real voice-clip durations"
```

---

### Task 7: Wire chapters into the long-form pipeline

**Files:**
- Modify: `scheduler.py:43-51` (imports) and `:236-296` (`_run_single_video`)
- Test: `tests/test_scheduler_chapters.py` (new)

**Interfaces:**
- Consumes: `build_chapters(script: dict, voices: list, title_card_seconds: float = 5.0) -> str` from Task 6.
- Produces: `_append_chapters_to_description(script: dict, voices: list) -> dict` in `scheduler.py` — mutates and returns `script` with the chapters block appended to `script["description"]`. Used only inside `_run_single_video`; no other module needs to import it.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scheduler_chapters.py
import tempfile
from pathlib import Path

import moviepy as mpe
import numpy as np

from scheduler import _append_chapters_to_description


def _make_silent_mp3(path: str, seconds: float):
    def make_frame(t):
        if np.isscalar(t):
            return np.array([0.0, 0.0])
        return np.zeros((len(t), 2))
    clip = mpe.AudioClip(make_frame, duration=seconds, fps=44100)
    clip.write_audiofile(path, logger=None)
    clip.close()


def test_appends_chapters_to_existing_description():
    with tempfile.TemporaryDirectory() as tmp:
        v1 = str(Path(tmp) / "v1.mp3")
        _make_silent_mp3(v1, 20.0)
        script = {
            "description": "यह एक हुक लाइन है। #Hindi #News",
            "sections": [{"heading": "पहला हिस्सा"}],
        }
        result = _append_chapters_to_description(script, [v1])
        assert "यह एक हुक लाइन है" in result["description"]
        assert "0:00 पहला हिस्सा" in result["description"]


if __name__ == "__main__":
    test_appends_chapters_to_existing_description()
    print("All tests passed.")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python tests/test_scheduler_chapters.py`
Expected: `ImportError: cannot import name '_append_chapters_to_description' from 'scheduler'`

- [ ] **Step 3: Add the helper and wire it into `_run_single_video`**

In `scheduler.py`, change the import block (currently lines 43-51):

```python
from pipeline.image_fetcher import fetch_all_section_images
from pipeline.logger import log
from pipeline.news_fetcher import get_breaking_headlines
from pipeline.script_generator import generate_script, generate_shorts_script
from pipeline.shorts_creator import create_short
from pipeline.trends import get_trending_topics
from pipeline.uploader import upload_thumbnail, upload_video
from pipeline.video_creator import create_thumbnail, create_video
from pipeline.voice_generator import generate_section_voices
```

to:

```python
from pipeline.image_fetcher import fetch_all_section_images
from pipeline.logger import log
from pipeline.news_fetcher import get_breaking_headlines
from pipeline.script_generator import generate_script, generate_shorts_script
from pipeline.shorts_creator import create_short
from pipeline.trends import get_trending_topics
from pipeline.uploader import upload_thumbnail, upload_video
from pipeline.video_creator import build_chapters, create_thumbnail, create_video
from pipeline.voice_generator import generate_section_voices
```

Then add this helper function directly above `_run_single_video` (before the line `def _run_single_video(...` currently at line 236):

```python
def _append_chapters_to_description(script: dict, voices: list) -> dict:
    """Append real YouTube chapter markers to script['description'] in place."""
    chapters_text = build_chapters(script, voices)
    if chapters_text.strip():
        script["description"] = (script.get("description", "") or "").rstrip() + "\n\n" + chapters_text
    return script
```

Then inside `_run_single_video`, change:

```python
        # 2. Voice
        log.info("[%d] Generating voice-over...", index)
        voices = generate_section_voices(
            script["sections"],
            str(work_dir / "voices"),
            rate=voice_rate,
        )

        # 3. Images
```

to:

```python
        # 2. Voice
        log.info("[%d] Generating voice-over...", index)
        voices = generate_section_voices(
            script["sections"],
            str(work_dir / "voices"),
            rate=voice_rate,
        )
        script = _append_chapters_to_description(script, voices)

        # 3. Images
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python tests/test_scheduler_chapters.py`
Expected: `All tests passed.`

- [ ] **Step 5: Commit**

```bash
git add scheduler.py tests/test_scheduler_chapters.py
git commit -m "feat: append real chapter timestamps to long-form video descriptions"
```

---

## Spec coverage check

- Section A (long-form prompt) → Task 3.
- Section B (Shorts prompt) → Task 4.
- Section C (deterministic metadata post-processing) → Tasks 1-2.
- Section D (real chapters/timestamps) → Tasks 5-7.
- Out-of-scope items (pinned comments, thumbnail redesign, topic selection) → untouched, as intended.
