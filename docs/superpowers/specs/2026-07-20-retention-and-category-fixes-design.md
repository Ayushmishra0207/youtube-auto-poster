# Retention, Category-ID, and Language Fixes for Videos and Shorts

## Problem

Channel Analytics (last 28 days) shows: 9.7% impressions CTR (fine) but only
53s average view duration, ~0% Suggested/Browse traffic (75% is YouTube
search), and +4 subscribers. CTR being healthy while retention is very low
against the current ~7-9 min long-form target points at **retention/format**,
not thumbnails, as the highest-leverage fix — a viewer who drops off in the
first minute never generates the watch-time/completion signal YouTube uses to
push a video into Suggested/Browse for a small channel.

Investigation of the actual pipeline code (not just the metrics) also
surfaced three concrete defects contributing to this and to poor
discoverability, verified by reading the code (not assumed):

1. **`yt_category_id` is computed correctly per topic category in
   `topic_config.json` but never reaches the YouTube upload call.**
   `scheduler.py::_load_slot_plan` builds the correct mapping
   (news→25, famous_story/historical_story→27, science_tech→28, sports→17,
   entertainment→24) and `run_pipeline()` even stores it on
   `meta["yt_category_id"]` (line 383), but the `upload_video(...)` call
   right after (lines 396-403) never passes `category_id=`, so every
   long-form video uploads under category 25 (News & Politics) regardless of
   topic. Non-news content (literature, history, sports, entertainment)
   likely gets recommended into the wrong audience.
2. **The "must be entirely in {lang}" instruction has no enforcement.**
   This project deliberately uses only free LLM providers (Gemini
   flash-lite, free OpenRouter models — Claude/Anthropic is intentionally
   unused, see `script_generator.py` module docstring), and weaker free
   models sometimes ignore instructions. This is how an English-language
   Short ("5,000 dead in Venezuela...") got published despite locale
   defaulting to Hindi everywhere and the prompt explicitly demanding Hindi.
3. **The thumbnail "breaking news" badge is unconditional.**
   `video_creator.py::create_thumbnail` and
   `shorts_creator.py::create_short_thumbnail` always stamp
   `locale.breaking_badge` ("बड़ी खबर"), including on Premchand literary
   stories, historical stories, science content, and sports — a misleading
   thumbnail that trains viewers to expect breaking news and then delivers a
   story narration, hurting trust and session retention.

Also noted, out of scope for this pass: legacy pirated-movie-titled videos
sitting in the channel's upload history (e.g. "RRR full movie hd") predate
this pipeline and are a manual YouTube Studio cleanup, not a code change —
flagged to the user separately, not addressed here.

## A. Fix category ID passthrough at upload

File: [scheduler.py](../../../scheduler.py), `run_pipeline()`, the
`upload_video(...)` call (~line 396).

- Pass `category_id=v["yt_category_id"]` through to `upload_video()`.
- No other logic changes — `topic_config.json`'s mapping and
  `uploader.py::upload_video`'s existing `category_id` parameter are both
  already correct; only the call site was dropping the value.

## B. Hindi-language enforcement safety net

Files: [pipeline/script_generator.py](../../../pipeline/script_generator.py)
— `generate_script`, `generate_shorts_script`,
`generate_shorts_script_from_topic`.

- After a script is generated (and parsed via `_parse_script_response`),
  check the narration text for a minimum ratio of Devanagari-range
  characters when `locale.script == "devanagari"`.
- If the check fails, retry generation once via `_generate_via_chain`
  (same provider chain) with an added user-message instruction emphasizing
  the language requirement. If the retry also fails the check, proceed with
  a logged warning rather than blocking the pipeline (matches existing
  fail-soft conventions elsewhere in this codebase — a failed script still
  aborts that one video per the retry table in CLAUDE.md, this just adds one
  extra attempt specifically for language compliance).
- This check is locale-generic (keys off `locale.script`), so it applies
  correctly regardless of which locale a slot uses, not just Hindi.

## C. Category-aware thumbnail badge

Files: [pipeline/video_creator.py](../../../pipeline/video_creator.py)
`create_thumbnail`, [pipeline/shorts_creator.py](../../../pipeline/shorts_creator.py)
`create_short_thumbnail`.

- Add a small category→badge-text mapping (e.g. news categories keep
  `locale.breaking_badge`; `famous_story`/`historical_story` get a "story"
  label; `science_tech` gets a "facts/did-you-know" label; `sports` gets a
  "sports update" label; `entertainment` gets an "entertainment" label),
  each per-locale where practical (fall back to the existing
  `breaking_badge` string for any category not explicitly mapped, so
  behavior is unchanged for news content and for any category we don't
  have a translated label for yet).
- Both functions already receive `locale`; thread the video's `category`
  string through as well (already available at both call sites in
  `scheduler.py` and `generate_short_now.py`) so the badge choice can be
  made without new plumbing beyond one extra parameter.

## D. Shorten long-form target length

Files: [pipeline/script_generator.py](../../../pipeline/script_generator.py)
`_build_system_prompt`, [topic_config.json](../../../topic_config.json).

- Change the system prompt's length target from "≈7-9 minutes" / "5-7
  sections" / "70-90s each" to ≈2-3 minutes total, 3-4 sections, 30-45s
  narration each. Keep the existing section-structure rules (viral hook
  first, climax second-to-last, CTA last) — only the count/duration changes.
- Update `famous_story` and `historical_story` entries in
  `topic_config.json` — their `prompt_style` text currently says "Total
  narration 8-10 minutes," which would directly contradict the new system
  prompt target. Rewrite to fit the shorter format while keeping their
  distinct narrative/dramatic framing.

## E. Shorts: same badge + language fixes, plus feed variety

Files: [pipeline/shorts_creator.py](../../../pipeline/shorts_creator.py),
[generate_short_now.py](../../../generate_short_now.py), `scheduler.py`
`_SHORTS_PLAN`.

- Badge fix (C) and language safety net (B) apply here too — most relevant
  to `generate_short_now.py`'s custom-topic path
  (`generate_shorts_script_from_topic`), where a non-news Short would
  otherwise still get stamped "breaking news."
- `_SHORTS_PLAN` in `scheduler.py` currently rotates only 3 feeds
  (india/world/business) across the 5 daily Shorts slots, so 2 feeds repeat
  same-day. Existing headline-level dedup (`filter_fresh`/`avoid_titles` via
  `pipeline/topic_history.py`, already wired in `generate_short_now.py`)
  prevents identical headlines but not identical feed/framing. Expand
  `_SHORTS_PLAN` to 5 distinct feeds/focuses so no feed repeats within a
  single day.

## F. New "movie explained" category (8th daily slot)

Files: [config.py](../../../config.py) `UPLOAD_SLOTS_IST`,
[topic_config.json](../../../topic_config.json).

YouTube Studio's Trends tab shows this channel's audience heavily searching
for "movie explained in Hindi" / dubbed-movie content. That search intent
overlaps with the same audience segment behind the legacy pirated-movie
uploads already flagged as a monetization risk (see Problem section) —
actual dubbed/clip-heavy movie redistribution is copyright infringement and
must not be built. A narration-only "movie explainer" format is the legal
way to capture this demand:

- Add an 8th daily upload slot (`"19:40"`, 10 minutes after the existing
  last slot) to `UPLOAD_SLOTS_IST` in `config.py`. Total long-form videos
  per day goes from 7 to 8.
- Add a `movie_explained` category to `topic_config.json` (slot entry +
  category block), reusing the existing `generate_script` pipeline exactly
  like `famous_story`/`historical_story` do — category-specific instructions
  flow entirely through `prompt_style`, no new Python code needed.
- `prompt_style` must explicitly frame this as commentary/review, not a
  retelling: discuss plot, themes, performances, and audience reception in
  the narrator's own words; no verbatim extended dialogue or lyrics; treat
  it like a film critic's video essay, not a scene-by-scene substitute for
  watching the movie.
- `yt_category_id: "1"` (Film & Animation — a more accurate YouTube
  classification for movie-focused content than the existing `entertainment`
  category's "24").
- No new image-safety mechanism needed: `image_searches` already only query
  Pexels stock photography (cinema halls, red carpets, audiences), which
  cannot return actual copyrighted movie stills/posters regardless of
  category.
- Optionally add a `"movie_explained": "cinematic,dramatic"` entry to
  `CATEGORY_MUSIC_TAGS` in `config.py` (falls back to
  `DEFAULT_MUSIC_TAGS = "cinematic,background"` if omitted, which already
  fits reasonably well).

## Out of scope (explicit follow-ups, not dropped silently)

- Finishing `pipeline/engagement.py`/`pipeline/community_post.py`
  (auto-comment + Community-post draft automation) — deferred to a
  separate pass per user decision.
- Manual cleanup of legacy pirated-movie-titled uploads in YouTube Studio —
  flagged to the user as a monetization-eligibility risk, not a code change.
- Thumbnail visual redesign beyond the badge-text fix (e.g. adding a
  channel logo/watermark, testing face-driven thumbnails).
