# Shorts Generator: Custom Topic + Content Type — Design

## Problem

The Shorts Generator panel (`dashboard/components/ShortsPanel.tsx`) only offers three preset feeds (India/World/Business) as generation triggers. The backend (`generate_short_now.py`, `api/main.py`) already half-supports a free-text `topic` override, but:

- The dashboard never sends it — `dashboard/lib/api.ts`'s `generateShort()` only sends `feed`.
- There is no UI for entering a custom topic at all.
- There is no concept of "content type" (tone/genre) for Shorts — every script is generated with one generic, news-flavored prompt (`_build_shorts_topic_system_prompt` in `pipeline/script_generator.py`), regardless of topic.

The user wants to generate a Short about any topic they type in, in a chosen style (news, funny, story, motivational, etc.), rather than only trending-news-style shorts.

## Goals

- Add a "Custom Topic" input box to the Shorts Generator panel.
- Add a content-type dropdown next to it, styled like the existing category pill dropdown in `TopicsPanel.tsx`.
- Thread the selected content type through the API and script generator so it actually changes the tone/style of the generated script — not just a cosmetic label.

## Non-goals

- No changes to the trending-feed (India/World/Business) generation path's default behavior — it still defaults to `content_type="news"`.
- No changes to long-form video category system (`TopicsPanel.tsx`'s existing `CategoryDropdown`) — Shorts gets its own dropdown instance/config, reusing the same visual pattern, not the same component instance (different category lists).
- No new background music assets are recorded in this pass; new content types that don't have a matching category-music mapping fall back to the existing generic/default music.

## Content Types

16 total, each with emoji + color for the pill dropdown (mirroring `CATEGORY_EMOJI` in `TopicsPanel.tsx`):

News, Funny, Story, Motivational, Entertainment, Bollywood, History, Imagination, Devotional, Sports, Tech, Comedy Skit, Horror/Mystery, Books, Poetry, Short Story.

## Design

### Frontend

**`dashboard/components/ShortsPanel.tsx`**
- In `GeneratePanel` (lines ~174–245), add a new "Custom Topic" box above/alongside the existing `FEEDS` button row:
  - A text `<input>` for the topic.
  - A new `ContentTypeDropdown` component (new, in the same file or a small new file), following the visual pattern of `CategoryDropdown` in `TopicsPanel.tsx` (button + `createPortal` menu, emoji + color per item) — a separate component/instance since the item list and colors differ from the long-form category list.
  - A "Generate" button that calls the API with `{ topic, content_type }` when a topic is entered (feed presets still work independently with `content_type` defaulting to `"news"`).
- Local component state: `customTopic: string`, `contentType: string` (default `"news"`).

**`dashboard/lib/api.ts`**
- Update `generateShort` to accept and send `topic` and `content_type`:
  ```ts
  generateShort: (feed: string, topic?: string, contentType?: string) =>
    post("/api/shorts/generate", { feed, topic, content_type: contentType })
  ```

### Backend API (`api/main.py`)

- `GenerateShortPayload` (currently `feed`, `topic`, `locale`, `count`): add `content_type: str = "news"`.
- `RegenerateShortPayload`: add `content_type: str = "news"` too, for consistency (regenerate can also pick a content type).
- Both handlers pass `--content-type <value>` to the `generate_short_now.py` subprocess invocation.

### CLI / orchestration (`generate_short_now.py`)

- Add `--content-type` CLI argument (default `"news"`).
- `build_short_script(...)` (lines ~43–79) gains a `content_type` parameter, forwarded to `generate_shorts_script_from_topic`.
- The `category` value passed to `create_short` (currently `"news"` if no topic else `"custom_topic"`, line ~155) becomes: use `content_type` directly as the category when a topic is set, so music/thumbnail-badge selection reflects the chosen type instead of a generic `"custom_topic"` bucket.

### Script generation (`pipeline/script_generator.py`)

- `generate_shorts_script_from_topic(topic, locale=None, content_type="news")` — new parameter, forwarded to the prompt builder.
- `_build_shorts_topic_system_prompt(locale, content_type="news")` — branches on `content_type` to inject one extra tone/style instruction sentence into the existing generic prompt, e.g.:
  - `news` — factual, breaking-news tone (current default, unchanged)
  - `funny` — witty, meme-friendly, punchy humor
  - `story` — narrative arc with a hook, middle, and payoff
  - `short_story` — literary micro-fiction with a twist ending
  - `motivational` — uplifting, second-person encouragement
  - `entertainment` — pop-culture, buzzy, casual tone
  - `bollywood` — Bollywood movie/celebrity gossip framing
  - `history` — storytelling framed around a historical event/figure
  - `imagination` — speculative "what if" framing
  - `devotional` — reverent, spiritual/devotional tone
  - `sports` — high-energy sports commentary framing
  - `tech` — tech-explainer, gadget/innovation framing
  - `comedy_skit` — scripted skit/scene format with a punchline
  - `horror_mystery` — suspenseful, eerie, cliffhanger framing
  - `books` — book recommendation/summary framing
  - `poetry` — verse-like rhythm and imagery
  - One shared prompt function with a lookup dict of tone instructions, not 16 separate prompt functions.

### Video assembly (`pipeline/shorts_creator.py`)

- No signature change needed: `create_short(..., category: str = "news", ...)` already accepts an arbitrary string; passing the new content-type values through means `get_music_for_category` and `category_badge_text` will simply see new category strings and use their existing fallback logic for unmapped ones. If desired later, category-specific music can be added incrementally — out of scope here.

## Data flow

```
ShortsPanel (topic + content_type)
  → api.ts generateShort(feed, topic, contentType)
    → POST /api/shorts/generate { feed, topic, content_type }
      → api/main.py spawns generate_short_now.py --topic ... --content-type ...
        → build_short_script(topic, content_type=...)
          → generate_shorts_script_from_topic(topic, content_type=...)
            → _build_shorts_topic_system_prompt(content_type=...) [tone injected]
        → create_short(..., category=content_type)
          → get_music_for_category(content_type) [existing fallback]
          → category_badge_text(content_type) [existing fallback]
```

## Error handling

- If `content_type` is missing/unrecognized anywhere in the chain, default to `"news"` behavior (current behavior), never error out.
- Frontend: "Generate" button for the custom topic box is disabled while `customTopic` is empty/whitespace.

## Testing

- No test suite exists in this repo (per CLAUDE.md). Verification is manual: `python scheduler.py`-adjacent manual run of `generate_short_now.py --topic "..." --content-type funny` to confirm script tone changes, and a dashboard click-through to confirm the request payload reaches the API correctly.
