# SEO & Reach Improvements for Videos and Shorts

## Problem

Uploaded videos and Shorts get near-zero views/likes. The channel is small
but growing (hundreds of subscribers), so the fix that pays off fastest is
better packaging (title/first-3-seconds hook, since CTR/retention decide
whether YouTube's algorithm keeps testing a video to wider audiences) plus
genuinely searchable metadata (description/tags, since search and suggested-
video traffic depend on them). Topic/headline selection already pulls real
trending topics ([pipeline/trends.py](../../../pipeline/trends.py)) and real
recent headlines ([pipeline/news_fetcher.py](../../../pipeline/news_fetcher.py)),
so this pass leaves topic selection alone and focuses on metadata and
retention-relevant prompt rules.

Out of scope for this pass (explicit follow-ups, not dropped silently):
- Pinned engagement-question comments (needs new YouTube comments API calls)
- Thumbnail visual redesign
- Topic/trend-selection logic changes

## A. Long-form script prompt rewrite

File: [pipeline/script_generator.py](../../../pipeline/script_generator.py), `_SYSTEM_PROMPT`.

- **Title**: primary keyword must appear within the first ~40 characters
  (visible on mobile search/suggested-feed before truncation). Keep existing
  power-word/emotion requirement, ≤100 chars.
- **Description**: restructured into:
  1. Hook line containing the primary keyword (this is what shows in search
     result snippets and the suggested-video description preview).
  2. 2-3 short paragraphs summarizing the story with natural keyword
     repetition (topic name + close variants, not stuffed).
  3. Subscribe CTA.
  4. A clean block of 5-8 hashtags at the very end (YouTube shows the first
     3 above the video title, so the most important ones go first).
- **Tags**: instruction changes from vague "15-20 mixed" to 20-25 tags,
  ordered broad → specific (YouTube weights earlier tags more), no
  near-duplicate variants (e.g. not both "corruption india" and "india
  corruption").
- **thumbnail_text**: keep curiosity-driven but explicitly rule out
  misleading claims not backed by the actual content (clickbait that doesn't
  pay off hurts session retention and can trigger complaints).

## B. Shorts script prompt rewrite

File: [pipeline/script_generator.py](../../../pipeline/script_generator.py), `_SHORTS_SYSTEM_PROMPT`.

- **Title**: hook must land in the first 5 words, includes a keyword, still
  ends with `#Shorts`.
- **First narration line**: mandated pattern-interrupt hook (shocking
  stat/question) deliverable in under 3 seconds of speech — this is the
  single biggest lever for Shorts retention/algorithm distribution.
- **Description**: real hook line + 3-5 relevant hashtags (topic-specific,
  not generic filler like just "#news").
- **Tags**: 12-15 — a fixed broad set (e.g. "shorts", "hindi news",
  "breaking news") plus headline-specific terms, instead of unstructured.
- **Last item**: instructed to tease "next short" or ask a direct question,
  nudging comments as a cheap engagement signal (no comment-API automation
  needed for this).

## C. Deterministic metadata post-processing

New function `_enrich_metadata(script: dict, is_short: bool) -> dict` in
[pipeline/script_generator.py](../../../pipeline/script_generator.py),
called at the end of both `generate_script()` and `generate_shorts_script()`
(after `_generate_via_chain` returns, before returning to caller).

- Dedupe tags case-insensitively (strip whitespace, compare lowercase).
- Prepend a fixed base tag set if missing: channel handle ("bitnomad1"),
  "hindi news", plus one category tag (e.g. "trending news india" for
  long-form, "shorts" for Shorts). Base tags always survive dedup/cap.
- Cap total tags so the joined length stays under YouTube's 500-character
  tag-list limit — drop lowest-priority (last) LLM tags first if over.
- If the LLM's description contains no `#` hashtag, append a small default
  set based on category so no upload ever ships without hashtags.

This is a safety net for LLM inconsistency, not a replacement for the
prompt rules in A/B — the prompt should already produce good output most of
the time.

## D. Real chapters/timestamps for long-form descriptions

New helper `build_chapters(script: dict, voices: list[str], title_card_seconds: float = 5.0) -> str`
in [pipeline/video_creator.py](../../../pipeline/video_creator.py).

- Computes cumulative mm:ss by walking the title card duration, then each
  section's real voice-clip duration + 0.8s tail (mirroring the timing logic
  `create_video` already uses), pairing each timestamp with the section's
  Hindi `heading`.
- YouTube requires the first chapter at 0:00 and each chapter to be at least
  ~10 seconds, or it silently ignores the whole chapter list. Any section
  whose slide would produce a chapter shorter than 10s is merged into the
  previous chapter (its heading is dropped, not shown as its own marker)
  rather than emitting an invalid list.
- Returns a plain text block, e.g.:
  ```
  0:00 शुरुआत
  0:05 पहला बड़ा खुलासा
  1:32 दूसरा मोड़
  ...
  ```

In [scheduler.py](../../../scheduler.py) `_run_single_video`, immediately
after `voices = generate_section_voices(...)`, call `build_chapters(script,
voices)` and append the result to `script["description"]` before the
script.json is persisted and before the metadata dict is returned — so the
dashboard and the actual YouTube upload both see the same final
description with real timestamps.

## Data flow summary

```
generate_script() / generate_shorts_script()
    → Claude/OpenRouter/Gemini (prompt rules A/B)
    → _enrich_metadata() (rule C: tags + hashtag safety net)
    → returned script dict

scheduler._run_single_video()
    → generate_section_voices()  (real per-section durations now exist)
    → build_chapters(script, voices)  (rule D)
    → script["description"] += chapters block
    → script.json persisted, meta returned for upload
```

Shorts do not get chapters (YouTube doesn't support chapters on Shorts).

## Testing

No existing test suite (per CLAUDE.md). Verification is via
`python scheduler.py --now` for long-form and
`python generate_short_now.py --feed india` for Shorts, inspecting the
generated `script.json` for: keyword-forward title, structured description
with real timestamps (long-form) or hook+hashtags (Shorts), deduped/capped
tag list starting with the base tags.
