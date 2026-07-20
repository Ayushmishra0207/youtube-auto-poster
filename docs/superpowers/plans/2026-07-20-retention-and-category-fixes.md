# Retention, Category-ID, and Language Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the concrete pipeline defects behind the channel's low retention/reach — a dropped category-ID at upload, an unenforced Hindi-language rule, an always-on "breaking news" thumbnail badge, an oversized video-length target, and low Shorts feed variety — per the approved spec.

**Architecture:** Five independent, self-contained fixes to the existing pipeline. No new modules or abstractions — each fix edits the specific function(s) already responsible for that behavior, matching the codebase's existing conventions (fail-soft retries, locale-driven text, per-category config in `topic_config.json`).

**Tech Stack:** Python 3, no test framework in this repo (per CLAUDE.md — `--now` end-to-end runs are the normal verification path). Verification in this plan uses small standalone `python -c` scripts exercising the pure-function pieces of each change directly, without hitting the network (no real Pexels/YouTube/LLM calls), consistent with how the codebase itself has no test suite to extend.

## Global Constraints

- No new dependencies — everything uses stdlib + libraries already imported in the touched files (PIL, `pipeline.locales.Locale`, etc.).
- Every fix must degrade gracefully (fail-soft), matching the existing pattern in `pipeline/script_generator.py`/`scheduler.py` where a failure in one video never aborts the whole run.
- All Hindi text added must be UTF-8 in the source file (already the norm throughout this repo — `topic_config.json` and `pipeline/locales.py` already contain Hindi/Bengali/Arabic literals).
- Run all verification commands from the repository root (`c:\Users\kalki\My_workspace\Py_projects\Py-Projects\youtube-auto-poster`).

---

## File Structure

| File | Change |
|---|---|
| `scheduler.py` | Task 1: pass `category_id` to `upload_video()`. Task 3: pass `category=` to `create_thumbnail()`. Task 5: expand `_SHORTS_PLAN` to 5 feeds. |
| `pipeline/script_generator.py` | Task 2: add language-compliance helpers + wire into all 3 `generate_*` functions. Task 4: shorten system-prompt length target. |
| `pipeline/locales.py` | Task 3: add `category_badge_text()` helper + `_CATEGORY_BADGE_HI` mapping. |
| `pipeline/video_creator.py` | Task 3: `create_thumbnail()` gains a `category` param, uses the new badge helper. |
| `pipeline/shorts_creator.py` | Task 3: `create_short_thumbnail()` gains a `category` param; `create_short()` passes its own `category` through. |
| `generate_short_now.py` | Task 3: pass a real `category` to `create_short()`. Task 5: add `entertainment`/`sports` to `_FOCUS_BY_FEED`. |
| `pipeline/news_fetcher.py` | Task 5: add `entertainment`/`sports` to `_FEED_PATHS`. |
| `topic_config.json` | Task 4: rewrite `famous_story.prompt_style` to a 2-3 minute target. |

---

### Task 1: Fix dropped category_id at long-form upload

**Files:**
- Modify: `scheduler.py:396-403`

**Interfaces:**
- Consumes: `v["yt_category_id"]` (already set at `scheduler.py:383`, no change needed there), `uploader.py::upload_video(..., category_id: str = YT_CATEGORY_ID, ...)` (existing parameter, unused until now).
- Produces: nothing new — this is a call-site fix only.

- [ ] **Step 1: Confirm the current (buggy) call site**

Read `scheduler.py:390-407` and confirm the `upload_video(...)` call has no `category_id=` argument even though `v["yt_category_id"]` exists on the same dict.

- [ ] **Step 2: Add the missing argument**

In `scheduler.py`, change:

```python
            vid_id = upload_video(
                video_path=v["path"],
                title=v["title"],
                description=v["description"],
                tags=v["tags"],
                publish_at_utc=publish_utc,
                yt_language=v.get("yt_language", "hi"),
            )
```

to:

```python
            vid_id = upload_video(
                video_path=v["path"],
                title=v["title"],
                description=v["description"],
                tags=v["tags"],
                publish_at_utc=publish_utc,
                category_id=v.get("yt_category_id", "25"),
                yt_language=v.get("yt_language", "hi"),
            )
```

- [ ] **Step 3: Verify with a static check (no network)**

Run:

```bash
python -c "
import re
src = open('scheduler.py', encoding='utf-8').read()
m = re.search(r'vid_id = upload_video\((.*?)\n            \)', src, re.S)
assert m, 'could not find the upload_video( ... ) call'
assert 'category_id' in m.group(1), 'category_id still missing from upload_video call'
print('OK: category_id is now passed to upload_video')
"
```

Expected: `OK: category_id is now passed to upload_video`

- [ ] **Step 4: Commit**

```bash
git add scheduler.py
git commit -m "fix: pass per-category yt_category_id through to upload_video"
```

---

### Task 2: Hindi-language enforcement safety net

**Files:**
- Modify: `pipeline/script_generator.py` (add helpers near the top-level functions; wire into `generate_script`, `generate_shorts_script`, `generate_shorts_script_from_topic`)

**Interfaces:**
- Consumes: `Locale.script` and `Locale.language_name` (already defined in `pipeline/locales.py`), `_generate_via_chain(user_content, topic, system_prompt, required_key)` (existing, unchanged signature).
- Produces: `_script_compliance_ratio(text: str) -> float`, `_narration_text(script: dict) -> str`, `_language_retry_content(user_content: str, locale: Locale) -> str`, `_ensure_script_language(script: dict, locale: Locale, regenerate: Callable[[], dict]) -> dict` — all module-private in `pipeline/script_generator.py`, used by later steps in this task and available if Task 4 or future work needs them.

- [ ] **Step 1: Add the language-compliance helpers**

In `pipeline/script_generator.py`, add this block directly above `def generate_script(`:

```python
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
```

- [ ] **Step 2: Verify the helpers with a standalone check (no network)**

Run:

```bash
python -c "
from pipeline.script_generator import _script_compliance_ratio, _ensure_script_language
from pipeline.locales import get_locale

hi = get_locale('hi')
assert _script_compliance_ratio('यह एक हिंदी वाक्य है') > 0.9
assert _script_compliance_ratio('This is an English sentence') < 0.1

calls = {'n': 0}
def regen():
    calls['n'] += 1
    return {'sections': [{'narration': 'यह सही स्क्रिप्ट है'}]}

bad_script = {'sections': [{'narration': 'This is fully English narration text'}]}
fixed = _ensure_script_language(bad_script, hi, regen)
assert calls['n'] == 1, 'regenerate should be called exactly once'
assert _script_compliance_ratio(fixed['sections'][0]['narration']) > 0.6

good_script = {'sections': [{'narration': 'यह पहले से ही सही भाषा में है'}]}
untouched = _ensure_script_language(good_script, hi, regen)
assert calls['n'] == 1, 'regenerate must NOT be called when the script already passes'
print('OK: language safety net works')
"
```

Expected: `OK: language safety net works`

- [ ] **Step 3: Wire the safety net into `generate_script`**

Change:

```python
    script = _generate_via_chain(user_content, topic, _build_system_prompt(locale), required_key="sections")
    return _enrich_metadata(script, is_short=False, locale=locale)
```

to:

```python
    system_prompt = _build_system_prompt(locale)
    script = _generate_via_chain(user_content, topic, system_prompt, required_key="sections")
    script = _ensure_script_language(
        script, locale,
        regenerate=lambda: _generate_via_chain(
            _language_retry_content(user_content, locale), topic, system_prompt, required_key="sections",
        ),
    )
    return _enrich_metadata(script, is_short=False, locale=locale)
```

- [ ] **Step 4: Wire the safety net into `generate_shorts_script`**

Change:

```python
    script = _generate_via_chain(
        user_content, f"shorts:{focus}", _build_shorts_system_prompt(locale), required_key="items"
    )
    return _enrich_metadata(script, is_short=True, locale=locale)
```

to:

```python
    system_prompt = _build_shorts_system_prompt(locale)
    script = _generate_via_chain(user_content, f"shorts:{focus}", system_prompt, required_key="items")
    script = _ensure_script_language(
        script, locale,
        regenerate=lambda: _generate_via_chain(
            _language_retry_content(user_content, locale), f"shorts:{focus}", system_prompt, required_key="items",
        ),
    )
    return _enrich_metadata(script, is_short=True, locale=locale)
```

- [ ] **Step 5: Wire the safety net into `generate_shorts_script_from_topic`**

Change:

```python
    script = _generate_via_chain(
        user_content, f"shorts-topic:{topic}", _build_shorts_topic_system_prompt(locale), required_key="items"
    )
    return _enrich_metadata(script, is_short=True, locale=locale)
```

to:

```python
    system_prompt = _build_shorts_topic_system_prompt(locale)
    script = _generate_via_chain(user_content, f"shorts-topic:{topic}", system_prompt, required_key="items")
    script = _ensure_script_language(
        script, locale,
        regenerate=lambda: _generate_via_chain(
            _language_retry_content(user_content, locale), f"shorts-topic:{topic}", system_prompt, required_key="items",
        ),
    )
    return _enrich_metadata(script, is_short=True, locale=locale)
```

- [ ] **Step 6: Verify the three call sites compile and import cleanly**

Run:

```bash
python -c "
import pipeline.script_generator as sg
import inspect
for name in ('generate_script', 'generate_shorts_script', 'generate_shorts_script_from_topic'):
    src = inspect.getsource(getattr(sg, name))
    assert '_ensure_script_language(' in src, f'{name} missing language safety net'
print('OK: all three generators call _ensure_script_language')
"
```

Expected: `OK: all three generators call _ensure_script_language`

- [ ] **Step 7: Commit**

```bash
git add pipeline/script_generator.py
git commit -m "feat: retry script generation once when Hindi-language rule is ignored"
```

---

### Task 3: Category-aware thumbnail badge

**Files:**
- Modify: `pipeline/locales.py` (add `category_badge_text()` + `_CATEGORY_BADGE_HI`)
- Modify: `pipeline/video_creator.py:518-595` (`create_thumbnail` gains `category` param)
- Modify: `pipeline/shorts_creator.py:98-177,211-347` (`create_short_thumbnail` gains `category` param; `create_short` passes its own `category` through)
- Modify: `scheduler.py:323` (pass `category=category` into `create_thumbnail`)
- Modify: `generate_short_now.py:153` (pass a real `category` into `create_short`)

**Interfaces:**
- Consumes: `Locale.breaking_badge` (existing field).
- Produces: `pipeline.locales.category_badge_text(category: str, locale: Locale) -> str`, used by both thumbnail functions.

- [ ] **Step 1: Add the badge-mapping helper to `pipeline/locales.py`**

Insert this block between `def get_locale(...)` and `def locales_by_continent(...)`:

```python
# Category → thumbnail-badge text override. Hindi-only for now since every
# configured slot in topic_config.json uses the Hindi locale in practice —
# any category not listed here (including all actual news categories) keeps
# the locale's default `breaking_badge` ("बड़ी खबर" style), which is correct
# for real news content. Falls back to breaking_badge for every other locale
# too, since we have no translated labels for those yet.
_CATEGORY_BADGE_HI: dict[str, str] = {
    "famous_story":     "कहानी",
    "historical_story": "कहानी",
    "science_tech":      "जानिए",
    "sports":            "स्पोर्ट्स अपडेट",
    "entertainment":     "एंटरटेनमेंट",
    "custom_topic":      "जानिए",
}


def category_badge_text(category: str, locale: Locale) -> str:
    """
    Thumbnail badge text for a given topic category, in the given locale.
    Prevents stamping "breaking news" on non-news content (stories, science,
    sports, entertainment), which was previously unconditional and misled
    viewers about what the video actually delivers.
    """
    if locale.code == "hi" and category in _CATEGORY_BADGE_HI:
        return _CATEGORY_BADGE_HI[category]
    return locale.breaking_badge
```

- [ ] **Step 2: Verify the helper standalone (no network)**

Run:

```bash
python -c "
from pipeline.locales import category_badge_text, get_locale
hi = get_locale('hi')
assert category_badge_text('news_india', hi) == hi.breaking_badge
assert category_badge_text('famous_story', hi) == 'कहानी'
assert category_badge_text('science_tech', hi) == 'जानिए'
assert category_badge_text('sports', hi) == 'स्पोर्ट्स अपडेट'
assert category_badge_text('entertainment', hi) == 'एंटरटेनमेंट'
assert category_badge_text('custom_topic', hi) == 'जानिए'
assert category_badge_text('unknown_category', hi) == hi.breaking_badge
en = get_locale('en-US')
assert category_badge_text('famous_story', en) == en.breaking_badge
print('OK: category_badge_text mapping works')
"
```

Expected: `OK: category_badge_text mapping works`

- [ ] **Step 3: Use the helper in `create_thumbnail`**

In `pipeline/video_creator.py`, change the import line:

```python
from pipeline.locales import Locale, get_locale
```

to:

```python
from pipeline.locales import Locale, category_badge_text, get_locale
```

Change the function signature at `pipeline/video_creator.py:518`:

```python
def create_thumbnail(script: dict, output_path: str,
                     image_paths: Optional[list[str]] = None,
                     locale: Optional[Locale] = None,
                     category_color: str = "") -> str:
```

to:

```python
def create_thumbnail(script: dict, output_path: str,
                     image_paths: Optional[list[str]] = None,
                     locale: Optional[Locale] = None,
                     category_color: str = "",
                     category: str = "") -> str:
```

Change the badge line at `pipeline/video_creator.py:591`:

```python
    badge_txt = _shape_text(locale.breaking_badge, locale)
```

to:

```python
    badge_txt = _shape_text(category_badge_text(category, locale), locale)
```

- [ ] **Step 4: Use the helper in `create_short_thumbnail`, and thread `category` through `create_short`**

In `pipeline/shorts_creator.py`, change the import line:

```python
from pipeline.locales import Locale, get_locale
```

to:

```python
from pipeline.locales import Locale, category_badge_text, get_locale
```

Change the function signature at `pipeline/shorts_creator.py:98`:

```python
def create_short_thumbnail(script: dict, output_path: str, image_paths: list,
                           locale: Locale) -> str:
```

to:

```python
def create_short_thumbnail(script: dict, output_path: str, image_paths: list,
                           locale: Locale, category: str = "") -> str:
```

Change the badge line at `pipeline/shorts_creator.py:146`:

```python
    badge_txt = _shape_text(locale.breaking_badge, locale)
```

to:

```python
    badge_txt = _shape_text(category_badge_text(category, locale), locale)
```

Change the call site inside `create_short` at `pipeline/shorts_creator.py:347`:

```python
        create_short_thumbnail(script, thumb_path, thumb_images, locale)
```

to:

```python
        create_short_thumbnail(script, thumb_path, thumb_images, locale, category=category)
```

(`create_short`'s own `category: str = "news"` parameter already exists at `pipeline/shorts_creator.py:211` — no signature change needed there.)

- [ ] **Step 5: Verify both thumbnail functions render with a category (no network — synthetic local image)**

Run:

```bash
python -c "
import os
from PIL import Image
from pipeline.video_creator import create_thumbnail
from pipeline.shorts_creator import create_short_thumbnail
from pipeline.locales import get_locale

hi = get_locale('hi')
tmp_img = 'scratch_test_img.jpg'
Image.new('RGB', (800, 600), (50, 50, 50)).save(tmp_img)

script = {'title': 'Test Title', 'thumbnail_text': 'Test', 'items': [{'headline': 'Test Headline'}]}

out1 = create_thumbnail(script, 'scratch_thumb_long.jpg', image_paths=[tmp_img], locale=hi, category='famous_story')
assert os.path.exists(out1)

out2 = create_short_thumbnail(script, 'scratch_thumb_short.jpg', [tmp_img], hi, category='sports')
assert os.path.exists(out2)

os.remove(tmp_img); os.remove(out1); os.remove(out2)
print('OK: both thumbnail functions accept and use category')
"
```

Expected: `OK: both thumbnail functions accept and use category`

- [ ] **Step 6: Pass real category values at the two call sites**

In `scheduler.py`, change the `create_thumbnail(...)` call at line 323:

```python
        create_thumbnail(script, thumbnail_path, image_paths=picks, locale=locale, category_color=category_color)
```

to:

```python
        create_thumbnail(script, thumbnail_path, image_paths=picks, locale=locale, category_color=category_color, category=category)
```

(`category` is already an existing parameter of `_run_single_video`, in scope at this line — no new plumbing needed.)

In `generate_short_now.py`, change line 153:

```python
    create_short(script, str(work_dir), locale=locale)
```

to:

```python
    create_short(script, str(work_dir), category=("news" if not topic.strip() else "custom_topic"), locale=locale)
```

(`topic` is the function parameter already in scope in `generate_one_short` — feed-based Shorts are real news, custom-topic Shorts are not.)

- [ ] **Step 7: Verify the call sites were updated**

Run:

```bash
python -c "
import re
sched = open('scheduler.py', encoding='utf-8').read()
assert 'create_thumbnail(script, thumbnail_path, image_paths=picks, locale=locale, category_color=category_color, category=category)' in sched
gsn = open('generate_short_now.py', encoding='utf-8').read()
assert 'category=(\"news\" if not topic.strip() else \"custom_topic\")' in gsn
print('OK: call sites pass category through')
"
```

Expected: `OK: call sites pass category through`

- [ ] **Step 8: Commit**

```bash
git add pipeline/locales.py pipeline/video_creator.py pipeline/shorts_creator.py scheduler.py generate_short_now.py
git commit -m "feat: category-aware thumbnail badge instead of always-on breaking news"
```

---

### Task 4: Shorten long-form target length

**Files:**
- Modify: `pipeline/script_generator.py:96-129` (`_build_system_prompt`)
- Modify: `topic_config.json` (`categories.famous_story.prompt_style`)

**Interfaces:**
- Consumes/produces: none — text-only changes, no signatures affected.

- [ ] **Step 1: Shorten the narration/section/total-length rules in the system prompt**

In `pipeline/script_generator.py`, inside `_build_system_prompt`, change:

```python
- Every section narration = 70-90 seconds of speech when read aloud at moderate pace.

SECTION STRUCTURE (5-7 sections total):
```

to:

```python
- Every section narration = 30-45 seconds of speech when read aloud at moderate pace.

SECTION STRUCTURE (3-4 sections total):
```

Then change:

```python
Rules:
- Script must be entirely in {lang}.
- CRITICAL: Output must be valid JSON. Do NOT include literal newline characters inside string values. Write each narration as a single continuous string with no line breaks.
- Total narration ≈ 7–9 minutes of speech for better watch time.\
```

to:

```python
Rules:
- Script must be entirely in {lang}.
- CRITICAL: Output must be valid JSON. Do NOT include literal newline characters inside string values. Write each narration as a single continuous string with no line breaks.
- Total narration ≈ 2–3 minutes of speech. Shorter videos get watched to completion far more often than long ones on a small channel, and completion rate is what earns Suggested/Browse distribution — don't pad length at the expense of finishing strong.\
```

- [ ] **Step 2: Rewrite `famous_story`'s prompt_style in `topic_config.json` to match**

Change:

```json
      "prompt_style": "cinematic literary storytelling — narrate this famous Hindi story dramatically in engaging conversational Hindi. Include: the author's background (1-2 sentences), the full story retold with vivid scenes and dialogue, the deeper moral and why this story is immortal in Indian literature. Make listeners feel the emotions. Total narration 8-10 minutes.",
```

to:

```json
      "prompt_style": "cinematic literary storytelling — narrate this famous Hindi story dramatically in engaging conversational Hindi. Include: the author's background (1 short sentence), the story's core scene and turning point retold with vivid emotion, and the deeper moral in one closing line. Keep the dramatic arc but tell it tight — total narration 2-3 minutes, matching the video's overall length target.",
```

- [ ] **Step 3: Verify both changes**

Run:

```bash
python -c "
from pipeline.script_generator import _build_system_prompt
from pipeline.locales import get_locale
p = _build_system_prompt(get_locale('hi'))
assert '7-9' not in p and '7–9' not in p, 'old 7-9 minute target still present'
assert '2-3' in p or '2–3' in p, 'new 2-3 minute target missing'
assert '5-7 sections' not in p, 'old section count still present'
assert '3-4 sections' in p, 'new section count missing'

import json
cfg = json.load(open('topic_config.json', encoding='utf-8'))
style = cfg['categories']['famous_story']['prompt_style']
assert '8-10 minutes' not in style, 'famous_story still targets 8-10 minutes'
assert '2-3 minutes' in style, 'famous_story missing new 2-3 minute target'
print('OK: long-form length target shortened consistently')
"
```

Expected: `OK: long-form length target shortened consistently`

- [ ] **Step 4: Commit**

```bash
git add pipeline/script_generator.py topic_config.json
git commit -m "feat: shorten long-form video target from 7-9min to 2-3min for retention"
```

---

### Task 5: Widen daily Shorts feed variety

**Files:**
- Modify: `pipeline/news_fetcher.py:21-25` (`_FEED_PATHS`)
- Modify: `generate_short_now.py:32-36` (`_FOCUS_BY_FEED`)
- Modify: `scheduler.py` (`_SHORTS_PLAN`)

**Interfaces:**
- Consumes: `get_breaking_headlines(feed: str, ...)` (existing, unchanged signature — just gains two more valid `feed` values).
- Produces: no new interfaces — same dict/list shapes, more entries.

- [ ] **Step 1: Add two more real Google News RSS topic feeds**

In `pipeline/news_fetcher.py`, change:

```python
_FEED_PATHS = {
    "india": "https://news.google.com/rss",
    "world": "https://news.google.com/rss/headlines/section/topic/WORLD",
    "business": "https://news.google.com/rss/headlines/section/topic/BUSINESS",
}
```

to:

```python
_FEED_PATHS = {
    "india": "https://news.google.com/rss",
    "world": "https://news.google.com/rss/headlines/section/topic/WORLD",
    "business": "https://news.google.com/rss/headlines/section/topic/BUSINESS",
    "entertainment": "https://news.google.com/rss/headlines/section/topic/ENTERTAINMENT",
    "sports": "https://news.google.com/rss/headlines/section/topic/SPORTS",
}
```

- [ ] **Step 2: Add matching focus strings**

In `generate_short_now.py`, change:

```python
_FOCUS_BY_FEED = {
    "india": "India breaking news",
    "world": "World breaking news",
    "business": "Business and economy breaking news",
}
```

to:

```python
_FOCUS_BY_FEED = {
    "india": "India breaking news",
    "world": "World breaking news",
    "business": "Business and economy breaking news",
    "entertainment": "Entertainment and Bollywood breaking news",
    "sports": "Sports breaking news",
}
```

- [ ] **Step 3: Expand the daily Shorts plan to 5 distinct feeds**

In `scheduler.py`, change:

```python
_SHORTS_PLAN = [
    {"feed": "india",    "focus": "India breaking news"},
    {"feed": "world",    "focus": "World breaking news"},
    {"feed": "business", "focus": "Business and economy breaking news"},
]
```

to:

```python
_SHORTS_PLAN = [
    {"feed": "india",         "focus": "India breaking news"},
    {"feed": "world",         "focus": "World breaking news"},
    {"feed": "business",      "focus": "Business and economy breaking news"},
    {"feed": "entertainment", "focus": "Entertainment and Bollywood breaking news"},
    {"feed": "sports",        "focus": "Sports breaking news"},
]
```

- [ ] **Step 4: Verify all three changes together**

Run:

```bash
python -c "
from pipeline.news_fetcher import _FEED_PATHS
assert 'entertainment' in _FEED_PATHS and 'sports' in _FEED_PATHS

from generate_short_now import _FOCUS_BY_FEED
assert 'entertainment' in _FOCUS_BY_FEED and 'sports' in _FOCUS_BY_FEED

import scheduler
feeds = [p['feed'] for p in scheduler._SHORTS_PLAN]
assert len(feeds) == 5, f'expected 5 shorts slots, got {len(feeds)}'
assert len(set(feeds)) == 5, f'feeds are not all distinct: {feeds}'
print('OK: 5 distinct Shorts feeds configured end to end')
"
```

Expected: `OK: 5 distinct Shorts feeds configured end to end`

- [ ] **Step 5: Commit**

```bash
git add pipeline/news_fetcher.py generate_short_now.py scheduler.py
git commit -m "feat: expand daily Shorts to 5 distinct feeds instead of repeating 3"
```

---

### Task 6: New "movie explained" category (8th daily slot)

**Files:**
- Modify: `config.py` (`UPLOAD_SLOTS_IST`, optionally `CATEGORY_MUSIC_TAGS`)
- Modify: `topic_config.json` (`slots`, `categories.movie_explained`)

**Interfaces:**
- Consumes: the existing `generate_script(topic, category_style, locale)` pipeline and `scheduler.py::_load_slot_plan()` — both already generic over any category key in `topic_config.json`, no code changes needed.
- Produces: nothing new — config-only change.

- [ ] **Step 1: Add the 8th upload slot**

In `config.py`, change:

```python
UPLOAD_SLOTS_IST = [
    "18:30", "18:40", "18:50",
    "19:00", "19:10", "19:20", "19:30",
]
```

to:

```python
UPLOAD_SLOTS_IST = [
    "18:30", "18:40", "18:50",
    "19:00", "19:10", "19:20", "19:30", "19:40",
]
```

- [ ] **Step 2: (Optional) Add a music vibe for the new category**

In `config.py`, change:

```python
CATEGORY_MUSIC_TAGS = {
    "news_india":   "news,corporate,tense",
    "news_world":   "news,corporate,tense",
    "finance":      "corporate,motivational",
    "motivational": "motivational,uplifting",
    "story":        "cinematic,emotional",
    "entertainment": "upbeat,energetic",
    "news":         "news,corporate,tense",   # used by Shorts (breaking news)
}
```

to:

```python
CATEGORY_MUSIC_TAGS = {
    "news_india":   "news,corporate,tense",
    "news_world":   "news,corporate,tense",
    "finance":      "corporate,motivational",
    "motivational": "motivational,uplifting",
    "story":        "cinematic,emotional",
    "entertainment": "upbeat,energetic",
    "movie_explained": "cinematic,dramatic",
    "news":         "news,corporate,tense",   # used by Shorts (breaking news)
}
```

- [ ] **Step 3: Add the slot entry and category block to `topic_config.json`**

Add this entry to the `"slots"` array (after the `entertainment` entry):

```json
    {"slot": "19:40", "category": "movie_explained",   "custom_topic": null}
```

Add this block to the `"categories"` object (after `"entertainment"`):

```json
    "movie_explained": {
      "label": "Movie Explained",
      "color": "#EF4444",
      "description": "Narrator's own commentary/review of a current movie — plot, themes, performances, reception. Not a retelling or dubbed reproduction.",
      "search_query": "new movie release 2026 explained hindi review",
      "prompt_style": "movie-explainer commentary in Hindi, in the style of a film critic's video essay. Discuss the plot setup, key themes, character arcs, standout performances, and audience/critical reception of a real, current or recently released movie — entirely in your own words. This is spoken analysis and review, NOT a scene-by-scene retelling: do not reproduce extended dialogue or song lyrics verbatim, and do not present it as a substitute for watching the film. Give an honest take (what works, what doesn't) to build viewer trust.",
      "yt_category_id": "1",
      "fallback_topics": [
        "2026 ki trending Bollywood movie ka explanation aur review",
        "Hollywood ki naye release movie ka Hindi mein explanation",
        "South Indian dubbed movie 2026 ka review aur explanation",
        "OTT par trending movie ka explanation Hindi mein",
        "Naye release movie ka honest review Hindi mein"
      ]
    }
```

- [ ] **Step 4: Verify the new slot and category are wired correctly (no network)**

Run:

```bash
python -c "
import json
cfg = json.load(open('topic_config.json', encoding='utf-8'))
slots = cfg['slots']
assert len(slots) == 8, f'expected 8 slots, got {len(slots)}'
assert slots[7]['category'] == 'movie_explained'

cat = cfg['categories']['movie_explained']
assert cat['yt_category_id'] == '1'
assert 'do not reproduce extended dialogue' in cat['prompt_style']
assert len(cat['fallback_topics']) >= 5

import config
assert len(config.UPLOAD_SLOTS_IST) == 8
assert config.UPLOAD_SLOTS_IST[7] == '19:40'
print('OK: movie_explained category and 8th slot wired correctly')
"
```

Expected: `OK: movie_explained category and 8th slot wired correctly`

- [ ] **Step 5: Verify the slot plan builder actually resolves the new category (no network)**

This calls `scheduler._load_slot_plan()`, which normally triggers a live pytrends fetch for slots without a fixed topic — to keep this check network-free, temporarily monkeypatch the trends call:

```bash
python -c "
import scheduler
import pipeline.trends as trends

# Avoid a real network call; force fallback_topics to be used for this check only.
trends.get_trending_topics = lambda *a, **k: []

import builtins
_orig_import = None

plan = scheduler._load_slot_plan()
assert len(plan) == 8, f'expected 8 planned slots, got {len(plan)}'
movie_slot = plan[7]
assert movie_slot['category'] == 'movie_explained'
assert movie_slot['yt_category_id'] == '1'
assert movie_slot['topic'], 'movie_explained slot got no topic (fallback_topics or trends should have filled it)'
print('OK: slot plan resolves the movie_explained slot end to end:', movie_slot['topic'])
"
```

Expected: `OK: slot plan resolves the movie_explained slot end to end: <some topic string>`

(If this fails because `pytrends` still attempts a real request despite the monkeypatch — `_load_slot_plan` calls `TrendReq(...).trending_searches(...)` directly rather than through `get_trending_topics` for the primary fetch path — that's fine to observe once, live, since it's read-only and doesn't touch YouTube/upload; don't treat a slow/flaky pytrends response as a code defect.)

- [ ] **Step 6: Commit**

```bash
git add config.py topic_config.json
git commit -m "feat: add movie_explained category as 8th daily slot (commentary, not retelling)"
```

---

## Final End-to-End Smoke Check

- [ ] **Run the full pipeline once for real, per CLAUDE.md's standard test path**

```bash
python scheduler.py --now
```

Expected: pipeline completes (or fails per normal transient-API reasons, e.g. rate limits — check `logs/pipeline.log`), and spot-check `output/<today>/video_01/script.json` through `video_07/script.json`:
- Narration total is noticeably shorter than before (2-3 min worth of text, not 7-9 min).
- `output/<today>/video_XX/thumbnail.jpg` for a non-news category (e.g. whichever slot is `famous_story`) does not show "बड़ी खबर".
- Uploaded videos (check YouTube Studio or dashboard) show the correct category per topic, not all "News & Politics".
