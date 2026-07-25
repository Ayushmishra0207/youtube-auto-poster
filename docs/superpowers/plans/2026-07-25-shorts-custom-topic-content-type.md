# Shorts Custom Topic + Content Type Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a custom-topic input and a 16-option content-type dropdown to the Shorts Generator dashboard panel, threaded through the API and script generator so the chosen content type actually changes the tone of the generated script.

**Architecture:** One new `content_type` string flows end-to-end: dashboard state → `api.ts` → `POST /api/shorts/generate` payload → `generate_short_now.py` CLI arg → `generate_shorts_script_from_topic()` → a tone-instruction lookup dict injected into the existing shared system prompt. The same string is reused as `create_short()`'s existing `category` param, so background-music/thumbnail-badge selection benefit for free via their existing fallback logic — no new files there.

**Tech Stack:** Next.js/React + TypeScript (dashboard), FastAPI + Pydantic (api/main.py), Python subprocess CLI (generate_short_now.py, pipeline/script_generator.py).

## Global Constraints

- This repository has no automated test suite (per CLAUDE.md: "There is no test suite. The `--now` flag is the standard way to test pipeline changes end-to-end."). Every task below substitutes a concrete **manual verification step** (direct script run, curl, or UI click-through) for the usual automated test step. Do not add a new test framework as part of this work.
- Content type keys (exact strings, used identically in frontend and backend): `news`, `funny`, `story`, `short_story`, `motivational`, `entertainment`, `bollywood`, `history`, `imagination`, `devotional`, `sports`, `tech`, `comedy_skit`, `horror_mystery`, `books`, `poetry`.
- Default content type everywhere it's optional: `"news"` (preserves current behavior for existing feed-based generation).
- Follow existing code style: this codebase's Python has no type-checker/linter run in CI beyond what's already there; TypeScript files use the existing inline-style / lucide-icon conventions already present in `ShortsPanel.tsx` and `TopicsPanel.tsx`.

---

### Task 1: Content-type tone instructions in the script generator

**Files:**
- Modify: `pipeline/script_generator.py:541-615`

**Interfaces:**
- Produces: `_build_shorts_topic_system_prompt(locale: Locale, content_type: str = "news") -> str` (signature change, existing callers must pass `content_type` or rely on default)
- Produces: `generate_shorts_script_from_topic(topic: str, locale: Locale | None = None, content_type: str = "news") -> dict` (signature change)
- Produces: `_CONTENT_TYPE_TONE: dict[str, str]` — module-level lookup used only inside this file

- [ ] **Step 1: Add the tone-instruction lookup dict**

Insert immediately above `_build_shorts_topic_system_prompt` (currently at `pipeline/script_generator.py:541`):

```python
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
```

- [ ] **Step 2: Thread `content_type` through the topic system prompt**

Change the signature at `pipeline/script_generator.py:541` from:
```python
def _build_shorts_topic_system_prompt(locale: Locale) -> str:
    lang = locale.language_name
    return f"""\
You are a {lang} content creator writing scripts for 60-second YouTube Shorts for @bitnomad1. The current year is 2026.

You will be given a TOPIC chosen by the creator (not breaking-news headlines). Your job: break this topic into the MAXIMUM number of interesting, fact-based points for one fast-paced 60-second short, each with a very short brief. Use your own knowledge of the topic — this is not a news bulletin, so don't claim anything happened "today" unless the topic itself is a recent event.
```
to:
```python
def _build_shorts_topic_system_prompt(locale: Locale, content_type: str = "news") -> str:
    lang = locale.language_name
    tone = _CONTENT_TYPE_TONE.get(content_type, _CONTENT_TYPE_TONE["news"])
    return f"""\
You are a {lang} content creator writing scripts for 60-second YouTube Shorts for @bitnomad1. The current year is 2026.

You will be given a TOPIC chosen by the creator (not breaking-news headlines). Your job: break this topic into the MAXIMUM number of interesting, fact-based points for one fast-paced 60-second short, each with a very short brief. Use your own knowledge of the topic — this is not a news bulletin, so don't claim anything happened "today" unless the topic itself is a recent event.

CONTENT TYPE / TONE: {tone}
```

(Everything else in the returned string — JSON schema, TITLE RULES, etc. — is unchanged.)

- [ ] **Step 3: Thread `content_type` through `generate_shorts_script_from_topic`**

Change (at `pipeline/script_generator.py:589-615`) from:
```python
def generate_shorts_script_from_topic(topic: str, locale: Locale | None = None) -> dict:
    """
    Generate a 60-second Shorts script about an arbitrary creator-chosen
    topic, instead of real breaking-news headlines. Uses the same
    Gemini → OpenRouter free-provider chain as generate_script.
    locale drives output language/script/tags; defaults to Hindi/India.
    """
    locale = locale or get_locale(None)
    log.info("Generating Shorts script from topic: %s (locale=%s)", topic, locale.code)

    today = datetime.now().strftime("%d %B %Y")
    user_content = (
        f"Today's date: {today}\n\n"
        f"Topic: {topic}\n\n"
        f"Create the Shorts script now."
    )

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
to:
```python
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
    cache_key = f"shorts-topic:{topic}:{content_type}"
    script = _generate_via_chain(user_content, cache_key, system_prompt, required_key="items")
    script = _ensure_script_language(
        script, locale,
        regenerate=lambda: _generate_via_chain(
            _language_retry_content(user_content, locale), cache_key, system_prompt, required_key="items",
        ),
    )
    return _enrich_metadata(script, is_short=True, locale=locale)
```

- [ ] **Step 4: Manual verification**

Run:
```bash
python -c "
from pipeline.script_generator import _build_shorts_topic_system_prompt
from pipeline.locales import get_locale
p = _build_shorts_topic_system_prompt(get_locale('hi'), 'funny')
assert 'CONTENT TYPE / TONE: Make it genuinely funny' in p, p
p2 = _build_shorts_topic_system_prompt(get_locale('hi'))
assert 'CONTENT TYPE / TONE: Keep a factual, breaking-news tone' in p2, p2
print('OK')
"
```
Expected output: `OK` (confirms the prompt branches correctly and the default is unchanged).

- [ ] **Step 5: Commit**

```bash
git add pipeline/script_generator.py
git commit -m "feat: add content-type tone injection to Shorts topic script prompt"
```

---

### Task 2: Thread `content_type` through `generate_short_now.py`

**Files:**
- Modify: `generate_short_now.py:43-79, 140-157, 160-195`

**Interfaces:**
- Consumes: `generate_shorts_script_from_topic(topic, locale=None, content_type="news")` from Task 1
- Produces: `build_short_script(feed="india", topic="", locale=None, content_type="news") -> dict` (signature change)
- Produces: `generate_one_short(base_dir, feed, topic, index, locale, content_type="news") -> Path` (signature change)
- Produces: new CLI flag `--content-type` (default `"news"`)

- [ ] **Step 1: Add `content_type` parameter to `build_short_script`**

Change (at `generate_short_now.py:43-60`) from:
```python
def build_short_script(feed: str = "india", topic: str = "", locale: Locale | None = None) -> dict:
    """
    Generate a Shorts script from either a custom topic (creator's own
    choice of subject) or a real breaking-news feed. Shared by the
    "generate new" and "regenerate existing" flows.

    Filters out headlines that closely match a recently-generated Short's
    topic (pipeline.topic_history) so back-to-back generations don't keep
    leading with the same dominant headline (e.g. the top business story
    barely changes within a few hours) — falls back to the full headline
    list only if filtering would leave too few to work with.
    """
    locale = locale or get_locale(None)
    topic = (topic or "").strip()
    if topic:
        script = generate_shorts_script_from_topic(topic, locale=locale)
        record_topic(script.get("title", ""))
        return script
```
to:
```python
def build_short_script(feed: str = "india", topic: str = "", locale: Locale | None = None,
                        content_type: str = "news") -> dict:
    """
    Generate a Shorts script from either a custom topic (creator's own
    choice of subject) or a real breaking-news feed. Shared by the
    "generate new" and "regenerate existing" flows.

    content_type only affects the custom-topic path — it selects the
    tone/style of the generated script (see pipeline.script_generator's
    _CONTENT_TYPE_TONE). Feed-based (breaking-news) generation ignores it.

    Filters out headlines that closely match a recently-generated Short's
    topic (pipeline.topic_history) so back-to-back generations don't keep
    leading with the same dominant headline (e.g. the top business story
    barely changes within a few hours) — falls back to the full headline
    list only if filtering would leave too few to work with.
    """
    locale = locale or get_locale(None)
    topic = (topic or "").strip()
    if topic:
        script = generate_shorts_script_from_topic(topic, locale=locale, content_type=content_type)
        record_topic(script.get("title", ""))
        return script
```

- [ ] **Step 2: Add `content_type` parameter to `generate_one_short` and use it as `category`**

Change (at `generate_short_now.py:140-157`) from:
```python
def generate_one_short(base_dir: Path, feed: str, topic: str, index: int, locale: Locale) -> Path:
    """Build, render, and save one Short into base_dir/short_NN. Returns work_dir."""
    work_dir = base_dir / f"short_{index:02d}"
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    source = f"topic='{topic}'" if topic.strip() else f"feed={feed}"
    log.info("[manual-short %d] Generating (%s, locale=%s)...", index, source, locale.code)

    script = build_short_script(feed=feed, topic=topic, locale=locale)
    script["_locale"] = locale.code
    with open(work_dir / "script.json", "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)

    create_short(script, str(work_dir), category=("news" if not topic.strip() else "custom_topic"), locale=locale)
    log.info("[manual-short %d] Done: %s", index, work_dir)
    return work_dir
```
to:
```python
def generate_one_short(base_dir: Path, feed: str, topic: str, index: int, locale: Locale,
                        content_type: str = "news") -> Path:
    """Build, render, and save one Short into base_dir/short_NN. Returns work_dir."""
    work_dir = base_dir / f"short_{index:02d}"
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    source = f"topic='{topic}' (content_type={content_type})" if topic.strip() else f"feed={feed}"
    log.info("[manual-short %d] Generating (%s, locale=%s)...", index, source, locale.code)

    script = build_short_script(feed=feed, topic=topic, locale=locale, content_type=content_type)
    script["_locale"] = locale.code
    with open(work_dir / "script.json", "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)

    category = content_type if topic.strip() else "news"
    create_short(script, str(work_dir), category=category, locale=locale)
    log.info("[manual-short %d] Done: %s", index, work_dir)
    return work_dir
```

- [ ] **Step 3: Add the `--content-type` CLI flag and pass it through `main()`**

Change (at `generate_short_now.py:160-195`) from:
```python
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--feed", choices=["india", "world", "business", "entertainment", "sports"], default="india")
    parser.add_argument("--topic", default="", help="Custom topic — overrides --feed when set")
    parser.add_argument("--index", type=int, default=0,
                        help="Regenerate this existing short_NN in place instead of creating a new one")
    parser.add_argument("--date", default="", help="Output date folder (YYYY-MM-DD); defaults to today")
    parser.add_argument("--locale", default=DEFAULT_LOCALE,
                        help="Locale code for language/tags/TTS/rendering (pipeline/locales.py); default hi")
    parser.add_argument("--count", type=int, default=1,
                        help="Number of Shorts to generate in this run (ignored when --index is set)")
    args = parser.parse_args()

    locale = get_locale(args.locale)

    if not _acquire_lock():
        log.warning("[manual-short] Another Short generation is already in progress — aborting this run.")
        sys.exit(1)
    try:
        base_dir = (Path(OUTPUT_DIR) / args.date) if args.date else _today_output_dir()
        base_dir.mkdir(parents=True, exist_ok=True)

        if args.index > 0:
            generate_one_short(base_dir, args.feed, args.topic, args.index, locale)
        else:
            count = max(1, args.count)
            failures = 0
            for _ in range(count):
                index = _next_short_index(base_dir)
                try:
                    generate_one_short(base_dir, args.feed, args.topic, index, locale)
                except Exception as exc:
                    failures += 1
                    log.error("[manual-short %d] Failed: %s", index, exc, exc_info=True)
            if failures == count:
                sys.exit(1)
```
to:
```python
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--feed", choices=["india", "world", "business", "entertainment", "sports"], default="india")
    parser.add_argument("--topic", default="", help="Custom topic — overrides --feed when set")
    parser.add_argument("--content-type", default="news", dest="content_type",
                        help="Tone/style for a custom-topic script (e.g. news, funny, story, devotional); ignored for feed-based generation")
    parser.add_argument("--index", type=int, default=0,
                        help="Regenerate this existing short_NN in place instead of creating a new one")
    parser.add_argument("--date", default="", help="Output date folder (YYYY-MM-DD); defaults to today")
    parser.add_argument("--locale", default=DEFAULT_LOCALE,
                        help="Locale code for language/tags/TTS/rendering (pipeline/locales.py); default hi")
    parser.add_argument("--count", type=int, default=1,
                        help="Number of Shorts to generate in this run (ignored when --index is set)")
    args = parser.parse_args()

    locale = get_locale(args.locale)

    if not _acquire_lock():
        log.warning("[manual-short] Another Short generation is already in progress — aborting this run.")
        sys.exit(1)
    try:
        base_dir = (Path(OUTPUT_DIR) / args.date) if args.date else _today_output_dir()
        base_dir.mkdir(parents=True, exist_ok=True)

        if args.index > 0:
            generate_one_short(base_dir, args.feed, args.topic, args.index, locale, content_type=args.content_type)
        else:
            count = max(1, args.count)
            failures = 0
            for _ in range(count):
                index = _next_short_index(base_dir)
                try:
                    generate_one_short(base_dir, args.feed, args.topic, index, locale, content_type=args.content_type)
                except Exception as exc:
                    failures += 1
                    log.error("[manual-short %d] Failed: %s", index, exc, exc_info=True)
            if failures == count:
                sys.exit(1)
```

Also update the module docstring at the top of the file (lines 6-10) to add an example:
```python
  python generate_short_now.py --topic "IPL 2026 auction shockers" --content-type funny
```

- [ ] **Step 4: Manual verification**

Run (requires a working API key / network — this hits the real script-generation chain, so only run if you want to actually verify against Task 1's live behavior; otherwise skip to the `--help` check):
```bash
python generate_short_now.py --help
```
Expected: `--content-type` appears in the printed usage/options.

If you want a full live check:
```bash
python generate_short_now.py --topic "sundar pichai success story" --content-type motivational --count 1
```
Expected: exits 0, creates `output/<today>/short_NN/script.json` whose narration reads as uplifting/second-person rather than a news bulletin.

- [ ] **Step 5: Commit**

```bash
git add generate_short_now.py
git commit -m "feat: add --content-type CLI flag threaded to custom-topic Shorts generation"
```

---

### Task 3: Add `content_type` to the FastAPI payloads

**Files:**
- Modify: `api/main.py:966-1031`

**Interfaces:**
- Consumes: `--content-type` CLI flag from Task 2
- Produces: `GenerateShortPayload.content_type: str` and `RegenerateShortPayload.content_type: str`, both accepted by their respective endpoints and forwarded as `--content-type <value>` to the subprocess

- [ ] **Step 1: Add the field to `GenerateShortPayload` and forward it in `generate_short`**

Change (at `api/main.py:966-999`) from:
```python
class GenerateShortPayload(BaseModel):
    feed: str = "india"           # "india" | "world" | "business" | "entertainment" | "sports" — ignored if topic is set
    topic: str = ""               # custom topic; overrides feed when non-empty
    locale: str = DEFAULT_LOCALE  # region/language target (pipeline/locales.py)
    count: int = 1                # how many Shorts to generate in this run (batch mode)

@app.post("/api/shorts/generate")
async def generate_short(payload: GenerateShortPayload):
    global _short_proc

    topic = payload.topic.strip()
    if not topic and payload.feed not in ("india", "world", "business", "entertainment", "sports"):
        raise HTTPException(400, "feed must be one of: india, world, business, entertainment, sports")
    if payload.locale not in LOCALES:
        raise HTTPException(400, f"Unknown locale '{payload.locale}'")
    count = max(1, min(payload.count, 10))

    if _short_proc_running() or _short_lock_pid_alive():
        return {"ok": False, "message": "A Short is already being generated"}

    args = [PYTHON, str(BASE_DIR / "generate_short_now.py"), "--locale", payload.locale, "--count", str(count)]
    if topic:
        args += ["--topic", topic]
    else:
        args += ["--feed", payload.feed]
```
to:
```python
class GenerateShortPayload(BaseModel):
    feed: str = "india"           # "india" | "world" | "business" | "entertainment" | "sports" — ignored if topic is set
    topic: str = ""               # custom topic; overrides feed when non-empty
    content_type: str = "news"    # tone/style for a custom topic (news, funny, story, devotional, ...); ignored if topic is empty
    locale: str = DEFAULT_LOCALE  # region/language target (pipeline/locales.py)
    count: int = 1                # how many Shorts to generate in this run (batch mode)

@app.post("/api/shorts/generate")
async def generate_short(payload: GenerateShortPayload):
    global _short_proc

    topic = payload.topic.strip()
    if not topic and payload.feed not in ("india", "world", "business", "entertainment", "sports"):
        raise HTTPException(400, "feed must be one of: india, world, business, entertainment, sports")
    if payload.locale not in LOCALES:
        raise HTTPException(400, f"Unknown locale '{payload.locale}'")
    count = max(1, min(payload.count, 10))

    if _short_proc_running() or _short_lock_pid_alive():
        return {"ok": False, "message": "A Short is already being generated"}

    args = [PYTHON, str(BASE_DIR / "generate_short_now.py"), "--locale", payload.locale, "--count", str(count),
            "--content-type", payload.content_type or "news"]
    if topic:
        args += ["--topic", topic]
    else:
        args += ["--feed", payload.feed]
```

- [ ] **Step 2: Add the field to `RegenerateShortPayload` and forward it in `regenerate_short`**

Change (at `api/main.py:1002-1031`) from:
```python
class RegenerateShortPayload(BaseModel):
    feed: str = "india"
    topic: str = ""
    locale: str = DEFAULT_LOCALE

@app.post("/api/shorts/{date}/{index}/regenerate")
async def regenerate_short(date: str, index: int, payload: RegenerateShortPayload):
    """Regenerate an existing Short in place (new script + render, no auto-upload)."""
    key = _regen_key("short", date, index)
    if _regen_running(key) or _short_proc_running() or _short_lock_pid_alive():
        return {"ok": False, "message": "A Short generation/regeneration is already in progress"}

    topic = payload.topic.strip()
    if not topic and payload.feed not in ("india", "world", "business", "entertainment", "sports"):
        raise HTTPException(400, "feed must be one of: india, world, business, entertainment, sports")
    if payload.locale not in LOCALES:
        raise HTTPException(400, f"Unknown locale '{payload.locale}'")

    args = [PYTHON, str(BASE_DIR / "generate_short_now.py"), "--date", date, "--index", str(index),
            "--locale", payload.locale]
    args += ["--topic", topic] if topic else ["--feed", payload.feed]
```
to:
```python
class RegenerateShortPayload(BaseModel):
    feed: str = "india"
    topic: str = ""
    content_type: str = "news"
    locale: str = DEFAULT_LOCALE

@app.post("/api/shorts/{date}/{index}/regenerate")
async def regenerate_short(date: str, index: int, payload: RegenerateShortPayload):
    """Regenerate an existing Short in place (new script + render, no auto-upload)."""
    key = _regen_key("short", date, index)
    if _regen_running(key) or _short_proc_running() or _short_lock_pid_alive():
        return {"ok": False, "message": "A Short generation/regeneration is already in progress"}

    topic = payload.topic.strip()
    if not topic and payload.feed not in ("india", "world", "business", "entertainment", "sports"):
        raise HTTPException(400, "feed must be one of: india, world, business, entertainment, sports")
    if payload.locale not in LOCALES:
        raise HTTPException(400, f"Unknown locale '{payload.locale}'")

    args = [PYTHON, str(BASE_DIR / "generate_short_now.py"), "--date", date, "--index", str(index),
            "--locale", payload.locale, "--content-type", payload.content_type or "news"]
    args += ["--topic", topic] if topic else ["--feed", payload.feed]
```

- [ ] **Step 3: Manual verification**

Start the API (`python run_api.py` or the project's existing launcher) and run:
```bash
curl -s -X POST http://localhost:8000/api/shorts/generate \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <your session token>" \
  -d '{"topic": "test topic", "content_type": "funny"}'
```
Expected: `{"ok": true, ...}` response, and the spawned process's command line (visible via Task Manager or `tasklist`) includes `--content-type funny --topic "test topic"`.

- [ ] **Step 4: Commit**

```bash
git add api/main.py
git commit -m "feat: accept content_type in Shorts generate/regenerate API payloads"
```

---

### Task 4: Update the dashboard API client

**Files:**
- Modify: `dashboard/lib/api.ts:121`

**Interfaces:**
- Consumes: `POST /api/shorts/generate` body shape `{ feed, topic, content_type }` from Task 3
- Produces: `api.generateShort(feed, topic?, contentType?) => Promise<unknown>` — new optional params, backward compatible with existing call sites that only pass `feed`

- [ ] **Step 1: Update `generateShort`'s signature**

Change (at `dashboard/lib/api.ts:121`) from:
```ts
  generateShort:   (feed: "india" | "world" | "business") => post("/api/shorts/generate", { feed }),
```
to:
```ts
  generateShort:   (feed: "india" | "world" | "business", topic: string = "", contentType: string = "news") =>
    post("/api/shorts/generate", { feed, topic, content_type: contentType }),
```

- [ ] **Step 2: Manual verification**

Run the dashboard's TypeScript build check:
```bash
cd dashboard && npx tsc --noEmit
```
Expected: no new type errors (existing single-arg call site in `ShortsPanel.tsx` still compiles because the new params are optional — this will be updated to pass all three in Task 5, but the build must not break in between).

- [ ] **Step 3: Commit**

```bash
git add dashboard/lib/api.ts
git commit -m "feat: thread topic/content_type through the dashboard's generateShort client"
```

---

### Task 5: Custom Topic box + content-type dropdown in `ShortsPanel.tsx`

**Files:**
- Modify: `dashboard/components/ShortsPanel.tsx:1-245` (imports, new `CONTENT_TYPES` map, new `ContentTypeDropdown` component, `GeneratePanel` rewrite)

**Interfaces:**
- Consumes: `api.generateShort(feed, topic, contentType)` from Task 4
- Produces: no new exports — `GeneratePanel` remains a private component used only by the default-exported `ShortsPanel`

- [ ] **Step 1: Add the `createPortal` import and the `CONTENT_TYPES` map**

Change the import block (at `dashboard/components/ShortsPanel.tsx:1-8`) from:
```tsx
"use client";

import { useEffect, useState } from "react";
import { api, authedMediaUrl, authHeaders } from "@/lib/api";
import type { ShortMeta } from "@/lib/types";
import { Play, X, Upload, ExternalLink, CheckCircle, Sparkles, Newspaper, Globe2, TrendingUp } from "lucide-react";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
```
to:
```tsx
"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, authedMediaUrl, authHeaders } from "@/lib/api";
import type { ShortMeta } from "@/lib/types";
import { Play, X, Upload, ExternalLink, CheckCircle, Sparkles, Newspaper, Globe2, TrendingUp, ChevronDown, Check } from "lucide-react";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface ContentType {
  label: string;
  emoji: string;
  color: string;
}

const CONTENT_TYPES: Record<string, ContentType> = {
  news:           { label: "News",           emoji: "📰", color: "#4FC3F7" },
  funny:          { label: "Funny",          emoji: "😂", color: "#facc15" },
  story:          { label: "Story",          emoji: "📖", color: "#a78bfa" },
  short_story:    { label: "Short Story",    emoji: "✍️", color: "#c084fc" },
  motivational:   { label: "Motivational",   emoji: "🔥", color: "#fb923c" },
  entertainment:  { label: "Entertainment",  emoji: "🎭", color: "#f472b6" },
  bollywood:      { label: "Bollywood",      emoji: "🎬", color: "#e879f9" },
  history:        { label: "History",        emoji: "🏛️", color: "#94a3b8" },
  imagination:    { label: "Imagination",    emoji: "💭", color: "#818cf8" },
  devotional:     { label: "Devotional",     emoji: "🕉️", color: "#fbbf24" },
  sports:         { label: "Sports",         emoji: "🏆", color: "#4ade80" },
  tech:           { label: "Tech",           emoji: "🔬", color: "#22d3ee" },
  comedy_skit:    { label: "Comedy Skit",    emoji: "🎪", color: "#f59e0b" },
  horror_mystery: { label: "Horror/Mystery", emoji: "👻", color: "#64748b" },
  books:          { label: "Books",          emoji: "📚", color: "#60a5fa" },
  poetry:         { label: "Poetry",         emoji: "🪶", color: "#f0abfc" },
};
```

- [ ] **Step 2: Add the `ContentTypeDropdown` component**

Insert a new component right after the `CONTENT_TYPES` map and before the existing `FEEDS` array (currently at `dashboard/components/ShortsPanel.tsx:10-14`):

```tsx
function ContentTypeDropdown({ value, onSelect }: { value: string; onSelect: (key: string) => void }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState({ top: 0, left: 0, width: 200 });
  const btnRef = useRef<HTMLButtonElement>(null);
  const current = CONTENT_TYPES[value] ?? CONTENT_TYPES.news;

  const handleOpen = () => {
    if (btnRef.current) {
      const r = btnRef.current.getBoundingClientRect();
      setPos({ top: r.bottom + 4, left: r.left, width: Math.max(r.width, 200) });
    }
    setOpen((o) => !o);
  };

  return (
    <div>
      <button
        ref={btnRef}
        onClick={handleOpen}
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-all"
        style={{
          background: `${current.color}18`,
          border: `1px solid ${current.color}40`,
          color: current.color,
        }}
      >
        <span>{current.emoji}</span>
        <span>{current.label}</span>
        <ChevronDown size={12} className={`transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && createPortal(
        <>
          <div style={{ position: "fixed", inset: 0, zIndex: 9998 }} onClick={() => setOpen(false)} />
          <div
            style={{
              position: "fixed",
              top: pos.top,
              left: pos.left,
              width: pos.width,
              maxHeight: "50vh",
              overflowY: "auto",
              zIndex: 9999,
              background: "#080c18",
              border: "1px solid rgba(79,195,247,0.25)",
              borderRadius: "12px",
              boxShadow: "0 20px 60px rgba(0,0,0,0.9)",
            }}
          >
            {Object.entries(CONTENT_TYPES).map(([key, ct]) => (
              <button
                key={key}
                onClick={() => { onSelect(key); setOpen(false); }}
                style={{
                  width: "100%",
                  display: "flex",
                  alignItems: "center",
                  gap: "10px",
                  padding: "8px 12px",
                  fontSize: "13px",
                  textAlign: "left",
                  background: key === value ? "rgba(255,255,255,0.05)" : "transparent",
                  border: "none",
                  cursor: "pointer",
                  color: key === value ? ct.color : "#e2e8f0",
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.06)")}
                onMouseLeave={(e) => (e.currentTarget.style.background = key === value ? "rgba(255,255,255,0.05)" : "transparent")}
              >
                <span>{ct.emoji}</span>
                <span style={{ flex: 1 }}>{ct.label}</span>
                {key === value && <Check size={12} style={{ color: ct.color }} />}
              </button>
            ))}
          </div>
        </>,
        document.body
      )}
    </div>
  );
}

```

- [ ] **Step 3: Rewrite `GeneratePanel` to add the Custom Topic box**

Change (at `dashboard/components/ShortsPanel.tsx:174-245`) from:
```tsx
function GeneratePanel({ onGenerated }: { onGenerated: () => void }) {
  const [feed, setFeed]           = useState<"india" | "world" | "business">("india");
  const [generating, setGenerating] = useState(false);
  const [msg, setMsg]             = useState<{ text: string; ok: boolean } | null>(null);

  const handle = async () => {
    setGenerating(true);
    setMsg(null);
    try {
      const res: any = await api.generateShort(feed);
      if (res?.ok === false) {
        setMsg({ text: res.message ?? "Could not start generation", ok: false });
      } else {
        setMsg({ text: "Generating… this takes a few minutes.", ok: true });
        onGenerated();
      }
    } catch {
      setMsg({ text: "Failed to reach API", ok: false });
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="glass rounded-2xl p-5 space-y-3">
      <div className="flex items-center gap-2">
        <Sparkles size={16} style={{ color: "#4FC3F7" }} />
        <h2 className="text-sm font-semibold text-white">Generate a Short now</h2>
      </div>
      <p className="text-xs" style={{ color: "var(--muted)" }}>
        Pulls real breaking headlines from the last 48 hours, writes a 60-second Hindi script at 1.5x voice speed, and renders a vertical video.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {FEEDS.map((f) => (
          <button
            key={f.id}
            onClick={() => setFeed(f.id)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all"
            style={{
              background: feed === f.id ? "rgba(79,195,247,0.15)" : "rgba(255,255,255,0.04)",
              border: `1px solid ${feed === f.id ? "rgba(79,195,247,0.4)" : "var(--border)"}`,
              color: feed === f.id ? "#4FC3F7" : "#94a3b8",
            }}
          >
            {f.icon}
            {f.label}
          </button>
        ))}
        <button
          onClick={handle}
          disabled={generating}
          className="ml-auto flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-semibold transition-all disabled:opacity-50"
          style={{
            background: "linear-gradient(135deg, rgba(79,195,247,0.2) 0%, rgba(124,58,237,0.2) 100%)",
            border: "1px solid var(--border-strong)",
            color: "#4FC3F7",
          }}
        >
          {generating ? (
            <div className="w-3 h-3 border border-cyan-400 border-t-transparent rounded-full animate-spin" />
          ) : (
            <Sparkles size={13} />
          )}
          {generating ? "Starting…" : "Generate Short"}
        </button>
      </div>
      {msg && (
        <p className="text-xs" style={{ color: msg.ok ? "#4ade80" : "#f87171" }}>{msg.text}</p>
      )}
    </div>
  );
}
```
to:
```tsx
function GeneratePanel({ onGenerated }: { onGenerated: () => void }) {
  const [feed, setFeed]           = useState<"india" | "world" | "business">("india");
  const [customTopic, setCustomTopic] = useState("");
  const [contentType, setContentType] = useState("news");
  const [generating, setGenerating] = useState(false);
  const [msg, setMsg]             = useState<{ text: string; ok: boolean } | null>(null);

  const usingCustomTopic = customTopic.trim().length > 0;

  const handle = async () => {
    setGenerating(true);
    setMsg(null);
    try {
      const res: any = await api.generateShort(feed, customTopic.trim(), contentType);
      if (res?.ok === false) {
        setMsg({ text: res.message ?? "Could not start generation", ok: false });
      } else {
        setMsg({ text: "Generating… this takes a few minutes.", ok: true });
        onGenerated();
      }
    } catch {
      setMsg({ text: "Failed to reach API", ok: false });
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="glass rounded-2xl p-5 space-y-3">
      <div className="flex items-center gap-2">
        <Sparkles size={16} style={{ color: "#4FC3F7" }} />
        <h2 className="text-sm font-semibold text-white">Generate a Short now</h2>
      </div>
      <p className="text-xs" style={{ color: "var(--muted)" }}>
        Pulls real breaking headlines from the last 48 hours, writes a 60-second Hindi script at 1.5x voice speed, and renders a vertical video.
      </p>

      <div className="flex flex-wrap items-center gap-2">
        {FEEDS.map((f) => (
          <button
            key={f.id}
            onClick={() => setFeed(f.id)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all"
            style={{
              background: feed === f.id ? "rgba(79,195,247,0.15)" : "rgba(255,255,255,0.04)",
              border: `1px solid ${feed === f.id ? "rgba(79,195,247,0.4)" : "var(--border)"}`,
              color: feed === f.id ? "#4FC3F7" : "#94a3b8",
              opacity: usingCustomTopic ? 0.4 : 1,
            }}
          >
            {f.icon}
            {f.label}
          </button>
        ))}
      </div>

      <div
        className="rounded-xl p-3 space-y-2"
        style={{ background: "rgba(255,255,255,0.03)", border: "1px solid var(--border)" }}
      >
        <p className="text-xs font-semibold" style={{ color: "#64748b" }}>OR — CUSTOM TOPIC</p>
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={customTopic}
            onChange={(e) => setCustomTopic(e.target.value)}
            placeholder="Type any topic, e.g. 'IPL 2026 auction shockers'…"
            className="flex-1 min-w-[200px] bg-transparent text-sm text-white outline-none border-b pb-1"
            style={{ borderColor: usingCustomTopic ? "#4FC3F7" : "var(--border)" }}
          />
          <ContentTypeDropdown value={contentType} onSelect={setContentType} />
        </div>
      </div>

      <div className="flex justify-end">
        <button
          onClick={handle}
          disabled={generating}
          className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-semibold transition-all disabled:opacity-50"
          style={{
            background: "linear-gradient(135deg, rgba(79,195,247,0.2) 0%, rgba(124,58,237,0.2) 100%)",
            border: "1px solid var(--border-strong)",
            color: "#4FC3F7",
          }}
        >
          {generating ? (
            <div className="w-3 h-3 border border-cyan-400 border-t-transparent rounded-full animate-spin" />
          ) : (
            <Sparkles size={13} />
          )}
          {generating ? "Starting…" : "Generate Short"}
        </button>
      </div>
      {msg && (
        <p className="text-xs" style={{ color: msg.ok ? "#4ade80" : "#f87171" }}>{msg.text}</p>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Manual verification**

Run:
```bash
cd dashboard && npx tsc --noEmit
```
Expected: no type errors.

Then start the dashboard dev server (`npm run dev` in `dashboard/`) and the API, navigate to the Shorts tab, and confirm:
1. The feed buttons (India/World/Business) still work as before when the Custom Topic input is empty.
2. Typing into the Custom Topic input visually dims the feed buttons and highlights the input's underline.
3. The content-type dropdown opens, lists all 16 types with emoji, and selecting one updates the pill's label/color.
4. Clicking "Generate Short" with a custom topic + non-default content type starts a generation (network tab shows `POST /api/shorts/generate` with `{ feed, topic, content_type }` all populated).

- [ ] **Step 5: Commit**

```bash
git add dashboard/components/ShortsPanel.tsx
git commit -m "feat: add custom topic box and content-type dropdown to Shorts Generator"
```

---

## Post-plan follow-up (not in scope here)

- New content-type → background-music mappings in `pipeline/music_fetcher.py`'s `CATEGORY_MUSIC_TAGS` are not added in this plan; unmapped types fall back to `DEFAULT_MUSIC_TAGS` automatically (existing behavior, see `pipeline/music_fetcher.py:65`).
- New content-type → thumbnail-badge text in `pipeline/locales.py`'s `_CATEGORY_BADGE_HI` is not added; unmapped types fall back to `locale.breaking_badge` automatically (existing behavior, see `pipeline/locales.py:417-426`).
