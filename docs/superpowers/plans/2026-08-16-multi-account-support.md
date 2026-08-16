# Multi-Account YouTube Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Support multiple connected YouTube channels, each with its own niche (categories, schedule, locale), plus on-demand generation (account + category + custom topic) for both long-form and Shorts.

**Architecture:** A new `pipeline/accounts.py` registry (`accounts.json` + one `accounts/<id>/` directory per account holding that account's `topic_config.json`, `shorts_config.json`, and state files) sits underneath the existing single-account scheduler/uploader/dashboard, which get threaded with an `account`/`token_file` parameter at each call site rather than rewritten. Onboarding a new account stays CLI-driven (`setup_auth.py --account`); the dashboard is read/manage-only for accounts.

**Tech Stack:** Python (existing pipeline), FastAPI (`api/main.py`), Next.js/TypeScript dashboard — no new frameworks. This repo has no test suite; every task's "test" step is a direct script run with printed/asserted output, matching the project's existing verification convention (see CLAUDE.md: "There is no test suite... `--now` is the standard way to test pipeline changes").

**Spec:** `docs/superpowers/specs/2026-08-16-multi-account-support-design.md`

## Global Constraints

- Every new function that takes an account-scoping parameter (`token_file`, `base_dir`, `cache_dir`) makes it **optional, defaulting to today's single-account behavior** — existing callers must keep working unmodified until the task that updates them.
- `client_secrets.json` stays shared across all accounts — never per-account.
- Account IDs are filesystem-safe slugs (`[a-z0-9_]+`) — used directly as directory names.
- All new/modified JSON files use `ensure_ascii=False, indent=2` (matches every existing state file in this repo).
- IST timezone constant (`timezone(timedelta(hours=5, minutes=30))`) is already defined in `scheduler.py` and `generate_short_now.py` — reuse it, don't redefine.

---

## Task 1: Account model, registry, and migration

**Files:**
- Create: `pipeline/accounts.py`
- Test: manual script run (see steps)

**Interfaces:**
- Produces: `Account` dataclass with fields `id: str, label: str, locale: str, token_file: str, enabled: bool = True, created_at: str = ""` and properties `token_path -> Path`, `dir -> Path`, `topic_config_path -> Path`, `shorts_config_path -> Path`, `output_dir -> Path`.
- Produces: `load_accounts() -> list[Account]`, `save_accounts(accounts: list[Account]) -> None`, `get_account(account_id: str) -> Account | None`, `enabled_accounts() -> list[Account]`, `add_account(account_id: str, label: str, locale: str, token_file: str) -> Account`, `set_account_enabled(account_id: str, enabled: bool) -> None`, `ensure_default_account() -> None`.
- Consumes: `config.BASE_DIR`, `config.OUTPUT_DIR`.

- [ ] **Step 1: Write `pipeline/accounts.py`**

```python
"""
Multi-account registry. Each connected YouTube channel is an Account with
its own OAuth token, topic/Shorts config, and output/state directory —
see docs/superpowers/specs/2026-08-16-multi-account-support-design.md.
"""
import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import BASE_DIR, OUTPUT_DIR

IST = timezone(timedelta(hours=5, minutes=30))

ACCOUNTS_FILE = BASE_DIR / "accounts.json"
ACCOUNTS_DIR = BASE_DIR / "accounts"

_DEFAULT_TOPIC_CONFIG = {"slots": [], "categories": {}}
_DEFAULT_SHORTS_CONFIG = {
    "shorts_per_day": 10,
    "feeds": ["india", "world", "business"],
    "content_types_enabled": [
        "news", "funny", "story", "short_story", "motivational", "entertainment",
        "bollywood", "history", "imagination", "devotional", "sports", "tech",
        "comedy_skit", "horror_mystery", "books", "poetry",
    ],
    "upload_slots": [
        "08:00", "09:30", "11:00", "12:30", "13:30",
        "15:30", "17:30", "19:15", "20:30", "21:45",
    ],
}


@dataclass
class Account:
    id: str
    label: str
    locale: str
    token_file: str
    enabled: bool = True
    created_at: str = ""

    @property
    def token_path(self) -> Path:
        return BASE_DIR / self.token_file

    @property
    def dir(self) -> Path:
        return ACCOUNTS_DIR / self.id

    @property
    def topic_config_path(self) -> Path:
        return self.dir / "topic_config.json"

    @property
    def shorts_config_path(self) -> Path:
        return self.dir / "shorts_config.json"

    @property
    def output_dir(self) -> Path:
        return Path(OUTPUT_DIR) / self.id


def ensure_default_account() -> None:
    """
    Idempotent first-run migration: if accounts.json doesn't exist yet,
    wrap today's single-account setup (root topic_config.json,
    youtube_token.pickle, output/<date>/...) into one account called
    "default", so the channel that's already running keeps working with
    zero manual steps.
    """
    if ACCOUNTS_FILE.exists():
        return

    ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
    default_dir = ACCOUNTS_DIR / "default"
    default_dir.mkdir(parents=True, exist_ok=True)

    root_topic_config = BASE_DIR / "topic_config.json"
    if root_topic_config.exists():
        shutil.copy(root_topic_config, default_dir / "topic_config.json")
    else:
        (default_dir / "topic_config.json").write_text(
            json.dumps(_DEFAULT_TOPIC_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    (default_dir / "shorts_config.json").write_text(
        json.dumps(_DEFAULT_SHORTS_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    for state_name in ("longform_topic_history.json", "shorts_topic_history.json", "youtube_playlists.json"):
        root_state = BASE_DIR / state_name
        if root_state.exists():
            shutil.copy(root_state, default_dir / state_name)

    old_output = Path(OUTPUT_DIR)
    new_output = Path(OUTPUT_DIR) / "default"
    if old_output.exists():
        new_output.mkdir(parents=True, exist_ok=True)
        for dated_dir in old_output.iterdir():
            if dated_dir.is_dir() and dated_dir.name != "default":
                shutil.move(str(dated_dir), str(new_output / dated_dir.name))

    account = Account(
        id="default", label="Default Channel", locale="hi",
        token_file="youtube_token.pickle", enabled=True,
        created_at=datetime.now(IST).strftime("%Y-%m-%d"),
    )
    save_accounts([account])


def load_accounts() -> list[Account]:
    ensure_default_account()
    data = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
    return [Account(**a) for a in data["accounts"]]


def save_accounts(accounts: list[Account]) -> None:
    ACCOUNTS_FILE.write_text(
        json.dumps({"accounts": [asdict(a) for a in accounts]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_account(account_id: str) -> "Account | None":
    for a in load_accounts():
        if a.id == account_id:
            return a
    return None


def enabled_accounts() -> list[Account]:
    return [a for a in load_accounts() if a.enabled]


def set_account_enabled(account_id: str, enabled: bool) -> None:
    accounts = load_accounts()
    for a in accounts:
        if a.id == account_id:
            a.enabled = enabled
            break
    else:
        raise ValueError(f"Unknown account '{account_id}'")
    save_accounts(accounts)


def add_account(account_id: str, label: str, locale: str, token_file: str) -> Account:
    accounts = load_accounts()
    if any(a.id == account_id for a in accounts):
        raise ValueError(f"Account '{account_id}' already exists")

    account = Account(
        id=account_id, label=label, locale=locale, token_file=token_file,
        enabled=True, created_at=datetime.now(IST).strftime("%Y-%m-%d"),
    )
    accounts.append(account)
    save_accounts(accounts)

    account.dir.mkdir(parents=True, exist_ok=True)
    account.topic_config_path.write_text(
        json.dumps(_DEFAULT_TOPIC_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    account.shorts_config_path.write_text(
        json.dumps(_DEFAULT_SHORTS_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return account
```

- [ ] **Step 2: Verify migration and CRUD manually**

Run:
```bash
python -c "
from pipeline.accounts import load_accounts, add_account, set_account_enabled, get_account

accs = load_accounts()
assert len(accs) == 1 and accs[0].id == 'default', accs
print('migration OK:', accs[0])

add_account('test_acct', 'Test Account', 'en', 'youtube_token_test_acct.pickle')
assert get_account('test_acct').label == 'Test Account'
set_account_enabled('test_acct', False)
assert get_account('test_acct').enabled is False
print('CRUD OK')
"
```
Expected: both `print` lines execute with no assertion errors. Then manually delete the `test_acct` entry from `accounts.json` and `accounts/test_acct/` (this was a throwaway verification account, not a real one).

- [ ] **Step 3: Commit**

```bash
git add pipeline/accounts.py
git commit -m "feat: add multi-account registry with default-account migration"
```

---

## Task 2: Per-account credentials and playlist cache in uploader.py

**Files:**
- Modify: `pipeline/uploader.py`

**Interfaces:**
- Consumes: nothing new (no dependency on Task 1 — this task only adds optional parameters).
- Produces: `_get_service(token_file: str | None = None)`, `upload_video(..., token_file: str | None = None)`, `upload_thumbnail(video_id, thumbnail_path, token_file: str | None = None)`, `add_video_to_playlist(video_id, category, label="", token_file: str | None = None, cache_dir: Path | None = None)`, `upload_captions(video_id, srt_text, language="hi", token_file: str | None = None)`, `post_engagement_comment(video_id, text, token_file: str | None = None)`.

- [ ] **Step 1: Make `_get_service` accept an optional token file**

In `pipeline/uploader.py`, change:
```python
def _get_service():
    creds = None

    if os.path.exists(YOUTUBE_TOKEN_FILE):
        with open(YOUTUBE_TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)
```
to:
```python
def _get_service(token_file: str | None = None):
    token_path = token_file or YOUTUBE_TOKEN_FILE
    creds = None

    if os.path.exists(token_path):
        with open(token_path, "rb") as f:
            creds = pickle.load(f)
```
and further down in the same function, change the two remaining bare `YOUTUBE_TOKEN_FILE` references (the browser-flow branch and the final `pickle.dump`) to `token_path`.

- [ ] **Step 2: Thread `token_file` through every public upload function**

Add `token_file: str | None = None` as the last parameter of `upload_video`, `post_engagement_comment`, and `upload_thumbnail`, and change their internal `svc = _get_service()` / `_get_service()` calls to `_get_service(token_file)`.

- [ ] **Step 3: Scope the playlist cache to a directory**

Change:
```python
PLAYLIST_CACHE_FILE = BASE_DIR / "youtube_playlists.json"
```
to a function instead of a constant:
```python
def _playlist_cache_file(cache_dir: Path | None = None) -> Path:
    return (cache_dir or BASE_DIR) / "youtube_playlists.json"
```
Update `_load_playlist_cache`, `_save_playlist_cache`, `_get_or_create_playlist`, and `add_video_to_playlist` to each accept `cache_dir: Path | None = None` and pass it to `_playlist_cache_file(cache_dir)` instead of referencing `PLAYLIST_CACHE_FILE` directly. `_get_or_create_playlist` and `add_video_to_playlist` also gain `token_file: str | None = None`, forwarded to `_get_service(token_file)`.

- [ ] **Step 4: Same for captions**

Add `token_file: str | None = None` to `upload_captions`, forwarded to `_get_service(token_file)`.

- [ ] **Step 5: Verify backward compatibility**

Run:
```bash
python -c "
import pipeline.uploader as up
import inspect
sig = inspect.signature(up.upload_video)
assert 'token_file' in sig.parameters and sig.parameters['token_file'].default is None
sig2 = inspect.signature(up.add_video_to_playlist)
assert 'token_file' in sig2.parameters and 'cache_dir' in sig2.parameters
print('signatures OK')
"
```
Expected: `signatures OK` printed, no import errors (confirms the module still loads cleanly and every call site elsewhere in the repo that calls these functions with the OLD argument list still works, since all new parameters are optional keyword-only-by-position-default).

- [ ] **Step 6: Commit**

```bash
git add pipeline/uploader.py
git commit -m "feat: thread optional token_file/cache_dir through uploader functions"
```

---

## Task 3: Per-account topic-history state

**Files:**
- Modify: `pipeline/topic_history.py`

**Interfaces:**
- Consumes: nothing (independent of Tasks 1-2; only adds an optional parameter).
- Produces: `_history_path(namespace: str = "shorts", base_dir: Path | None = None) -> Path`, and `base_dir: Path | None = None` added to `record_topic`, `recent_titles`, `is_duplicate`, `filter_fresh`.

- [ ] **Step 1: Add `base_dir` to every function**

In `pipeline/topic_history.py`, change:
```python
def _history_path(namespace: str) -> Path:
    return BASE_DIR / f"{namespace}_topic_history.json"
```
to:
```python
def _history_path(namespace: str = "shorts", base_dir: Path | None = None) -> Path:
    return (base_dir or BASE_DIR) / f"{namespace}_topic_history.json"
```
Then add `base_dir: Path | None = None` as the last parameter of `_load`, `_save`, `record_topic`, `recent_titles`, `is_duplicate`, and `filter_fresh`, forwarding it to `_history_path(namespace, base_dir)` wherever they currently call `_history_path(namespace)`.

- [ ] **Step 2: Verify old and new call styles both work**

Run:
```bash
python -c "
from pathlib import Path
import tempfile, os
from pipeline.topic_history import record_topic, recent_titles, is_duplicate

# old style (no base_dir) still writes to BASE_DIR/shorts_topic_history.json
record_topic('Old Style Test Topic 12345')
assert any('Old Style Test' in t for t in recent_titles())
print('backward-compat OK')

# new style scopes to a custom dir
with tempfile.TemporaryDirectory() as td:
    scoped = Path(td)
    record_topic('Scoped Topic ABC', namespace='longform', base_dir=scoped)
    assert (scoped / 'longform_topic_history.json').exists()
    assert is_duplicate('Scoped Topic ABC', namespace='longform', base_dir=scoped)
    print('scoped OK')
"
```
Expected: both `print` lines execute. (The 'Old Style Test Topic' entry lands in the real `shorts_topic_history.json` — harmless, it'll age out after 72h same as any real entry.)

- [ ] **Step 3: Commit**

```bash
git add pipeline/topic_history.py
git commit -m "feat: scope topic history to an optional per-account base_dir"
```

---

## Task 4: Per-account Shorts config

**Files:**
- Create: `pipeline/shorts_config.py`

**Interfaces:**
- Consumes: `pipeline.accounts.Account` (Task 1).
- Produces: `load_shorts_config(account: Account) -> dict`, `save_shorts_config(account: Account, cfg: dict) -> None`.

- [ ] **Step 1: Write `pipeline/shorts_config.py`**

```python
"""Per-account Shorts settings — feeds, enabled content-types, daily slots.
Mirrors topic_config.json's role for long-form, but for Shorts."""
import json

from pipeline.accounts import Account, _DEFAULT_SHORTS_CONFIG


def load_shorts_config(account: Account) -> dict:
    if not account.shorts_config_path.exists():
        save_shorts_config(account, dict(_DEFAULT_SHORTS_CONFIG))
    return json.loads(account.shorts_config_path.read_text(encoding="utf-8"))


def save_shorts_config(account: Account, cfg: dict) -> None:
    account.dir.mkdir(parents=True, exist_ok=True)
    account.shorts_config_path.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )
```

- [ ] **Step 2: Verify**

Run:
```bash
python -c "
from pipeline.accounts import get_account
from pipeline.shorts_config import load_shorts_config

acc = get_account('default')
cfg = load_shorts_config(acc)
assert cfg['shorts_per_day'] == 10
assert 'news' in cfg['content_types_enabled']
print('shorts config OK:', acc.shorts_config_path)
"
```
Expected: `shorts config OK: ...accounts\default\shorts_config.json` printed, and that file now exists on disk.

- [ ] **Step 3: Commit**

```bash
git add pipeline/shorts_config.py
git commit -m "feat: add per-account Shorts config load/save"
```

---

## Task 5: `setup_auth.py --account` for onboarding new channels

**Files:**
- Modify: `setup_auth.py`

**Interfaces:**
- Consumes: `pipeline.accounts.add_account` (Task 1), `pipeline.uploader._get_service(token_file)` (Task 2).

- [ ] **Step 1: Read the current file to see its exact structure**

Run: `cat setup_auth.py` (or open it) — confirm it currently deletes `YOUTUBE_TOKEN_FILE` unconditionally and calls `_get_service()` with no args (per the earlier project survey: "zero CLI args... always writes to the one fixed token file").

- [ ] **Step 2: Add argparse and account-aware token path**

Replace the script's body with:
```python
import argparse
import os

from config import BASE_DIR
from pipeline.uploader import YOUTUBE_TOKEN_FILE, _get_service
from pipeline.accounts import add_account


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", default="", help="Account id (slug) — omit to (re)authenticate the default single-account token")
    parser.add_argument("--label", default="", help="Display label for this account (required with --account)")
    parser.add_argument("--locale", default="hi", help="Default locale code for this account (see pipeline/locales.py)")
    args = parser.parse_args()

    if args.account:
        if not args.label:
            parser.error("--label is required when using --account")
        token_file = f"youtube_token_{args.account}.pickle"
        token_path = BASE_DIR / token_file
        if token_path.exists():
            os.remove(token_path)
        print(f"Starting OAuth flow for account '{args.account}'...")
        _get_service(token_file=str(token_path))
        add_account(args.account, args.label, args.locale, token_file)
        print(f"Account '{args.account}' connected -> {token_path}")
    else:
        if YOUTUBE_TOKEN_FILE.exists():
            os.remove(YOUTUBE_TOKEN_FILE)
        print("Starting OAuth flow for the default account...")
        _get_service()
        print(f"Token saved -> {YOUTUBE_TOKEN_FILE}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Verify the no-args path still matches old behavior**

Run: `python setup_auth.py --help`
Expected: argparse help text listing `--account`, `--label`, `--locale`, with no errors. (Do not actually run the OAuth flow in this verification step — that opens a real browser window and should only be run intentionally by the user for a real new account.)

- [ ] **Step 4: Commit**

```bash
git add setup_auth.py
git commit -m "feat: setup_auth.py --account for onboarding additional YouTube channels"
```

---

## Task 6: Extract a reusable "pick a fresh topic for one category" helper

**Files:**
- Modify: `scheduler.py`

**Interfaces:**
- Consumes: existing `get_youtube_trending_topics`, `filter_fresh`, `is_duplicate`, `get_trending_topics` imports already in `scheduler.py`.
- Produces: `_pick_topic_for_category(cat_info: dict, locale: Locale, assigned_topics: set, topic_history_base_dir: Path) -> str` — used by both the scheduled slot-planner (Task 7) and the new on-demand generator (Task 9), so the trending-fetch logic is written once.

- [ ] **Step 1: Extract the per-slot-group fetch logic in `_load_slot_plan` into a standalone function**

In `scheduler.py`, the body of the `for (query, locale_code), slots_needing in by_query.items():` loop (roughly lines 233-303 today) picks one topic for a *group* of slots sharing a category. Extract the single-topic-selection part (not the group-fan-out) into:

```python
def _pick_topic_for_category(cat_info: dict, locale: Locale, assigned_topics: set,
                             topic_history_base_dir: Path | None = None) -> str:
    """
    One fresh topic for a single category: real YouTube trending videos in
    that category first, then Google Trends keyword-matched to
    search_query, then the category's fallback_topics, then a generic
    trending topic — skipping anything in `assigned_topics` (case-
    insensitive) or already covered per topic_history within the given
    base_dir (None = the shared/default history file).
    """
    yt_category_id = cat_info.get("yt_category_id", "25")
    query = cat_info.get("search_query", "")
    fallback_topics = cat_info.get("fallback_topics", [])
    candidates: list[str] = []

    try:
        yt_trending = get_youtube_trending_topics(num=6, locale=locale, video_category_id=yt_category_id)
        candidates.extend(filter_fresh(yt_trending, namespace="longform", base_dir=topic_history_base_dir))
    except Exception as e:
        log.warning("YouTube trending fetch failed for category id '%s': %s", yt_category_id, e)

    if query and query != "general":
        try:
            from pytrends.request import TrendReq
            pt = TrendReq(hl=locale.news_hl, tz=330, timeout=(10, 30))
            df = pt.trending_searches(pn=locale.trends_pn)
            all_trends = [str(t).strip() for t in df[0].dropna().tolist() if t]
            keywords = query.lower().split()
            matched = [t for t in all_trends if any(k in t.lower() for k in keywords)]
            candidates.extend(filter_fresh(matched or all_trends, namespace="longform", base_dir=topic_history_base_dir))
        except Exception as e:
            log.warning("Trends fetch failed for query '%s': %s", query, e)

    for c in candidates:
        key = c.strip().lower()
        if key and key not in assigned_topics:
            return c

    fresh_fallbacks = [
        f for f in fallback_topics
        if not is_duplicate(f, namespace="longform", base_dir=topic_history_base_dir)
        and f.strip().lower() not in assigned_topics
    ]
    import random as _random
    chosen = fresh_fallbacks or fallback_topics
    if chosen:
        return _random.choice(chosen)

    general = get_trending_topics(1, locale=locale)
    return general[0] if general else f"{locale.label} news today"
```

- [ ] **Step 2: Rewrite `_load_slot_plan`'s fetch loop to call the new helper**

Replace the inner body of the `for (query, locale_code), slots_needing in by_query.items():` loop (the candidate-gathering + Google-Trends + fallback code) with one call per slot in the group:

```python
for p in slots_needing:
    p["topic"] = _pick_topic_for_category(
        {"yt_category_id": p["yt_category_id"], "search_query": p["search_query"], "fallback_topics": p["fallback_topics"]},
        p["locale"], assigned_topics,
    )
    assigned_topics.add(p["topic"].strip().lower())
```
(This keeps `_load_slot_plan`'s per-slot cross-run dedup exactly as before — the only change is that the actual topic-picking logic now lives in one shared function.)

- [ ] **Step 3: Verify `_load_slot_plan` still produces a full, deduplicated plan**

Run:
```bash
python -c "
from scheduler import _load_slot_plan
plan = _load_slot_plan()
topics = [p['topic'].strip().lower() for p in plan]
assert len(plan) == 8, len(plan)
assert len(set(topics)) == len(topics), 'duplicate topics found'
print('slot plan OK:', len(plan), 'unique topics')
"
```
Expected: `slot plan OK: 8 unique topics` (matches the behavior verified earlier this session — 8 slots, 8 unique topics).

- [ ] **Step 4: Commit**

```bash
git add scheduler.py
git commit -m "refactor: extract _pick_topic_for_category, shared by scheduled and on-demand generation"
```

---

## Task 7: Account-aware `_load_slot_plan` and `run_pipeline`

**Files:**
- Modify: `scheduler.py`

**Interfaces:**
- Consumes: `pipeline.accounts.{Account, enabled_accounts}` (Task 1), `_pick_topic_for_category` (Task 6).
- Produces: `_load_slot_plan(account: Account) -> list[dict]` (now **requires** an account — every call site updated in this same task), `run_pipeline_for_account(account: Account) -> None`, `run_pipeline() -> None` (loops over `enabled_accounts()`).

- [ ] **Step 1: Add the `account` parameter to `_load_slot_plan`**

Change the signature from `def _load_slot_plan() -> list[dict]:` to `def _load_slot_plan(account) -> list[dict]:`. Inside, change:
```python
if TOPIC_CONFIG_FILE.exists():
    try:
        cfg = json.loads(TOPIC_CONFIG_FILE.read_text(encoding="utf-8"))
```
to:
```python
if account.topic_config_path.exists():
    try:
        cfg = json.loads(account.topic_config_path.read_text(encoding="utf-8"))
```
and change the default locale fallback from `get_locale(slot_cfg.get("locale") or DEFAULT_LOCALE)` to `get_locale(slot_cfg.get("locale") or account.locale)` so an account's own locale is the per-slot default instead of the global `DEFAULT_LOCALE`.

Also update the `_pick_topic_for_category` call added in Task 6 to pass `topic_history_base_dir=account.dir`.

- [ ] **Step 2: Split `run_pipeline` into a per-account body plus an account loop**

Rename the existing `run_pipeline()` function to `run_pipeline_for_account(account)`, and inside it:
- Replace every `base_dir = _today_output_dir()` with `base_dir = _today_output_dir(account)` (Step 3 below updates `_today_output_dir` to take the account).
- Replace `slot_plan = _load_slot_plan()` with `slot_plan = _load_slot_plan(account)`.
- In the upload loop, add `token_file=account.token_file` to the `upload_video(...)` call, and `token_file=account.token_file` to `upload_thumbnail(...)`, `add_video_to_playlist(..., cache_dir=account.dir)`, and `upload_captions(...)`.
- Replace `record_topic(script["title"], namespace="longform")` inside `_run_single_video` — this one needs the account threaded in too; add an `account_dir: Path | None = None` parameter to `_run_single_video` and forward it as `record_topic(script["title"], namespace="longform", base_dir=account_dir)`. Update the call in `run_pipeline_for_account` to pass `account_dir=account.dir`.

Then add the new top-level `run_pipeline()`:
```python
def run_pipeline():
    from pipeline.accounts import enabled_accounts
    accounts = enabled_accounts()
    if not accounts:
        log.error("No enabled accounts configured — nothing to do.")
        return
    for account in accounts:
        log.info("=" * 60)
        log.info("Running pipeline for account '%s' (%s)", account.id, account.label)
        try:
            run_pipeline_for_account(account)
        except Exception as exc:
            log.error("Pipeline failed for account '%s': %s", account.id, exc, exc_info=True)
```

- [ ] **Step 3: Make `_today_output_dir` and `_cleanup_old_output` account-aware**

Change:
```python
def _today_output_dir() -> Path:
    date_str = datetime.now(IST).strftime("%Y-%m-%d")
    d = Path(OUTPUT_DIR) / date_str
    d.mkdir(parents=True, exist_ok=True)
    return d
```
to:
```python
def _today_output_dir(account) -> Path:
    date_str = datetime.now(IST).strftime("%Y-%m-%d")
    d = account.output_dir / date_str
    d.mkdir(parents=True, exist_ok=True)
    return d
```
Similarly add an `account` parameter to `_cleanup_old_output`, changing its base path from `Path(OUTPUT_DIR)` to `account.output_dir`, and call it once per account inside `run_pipeline_for_account` (or once per account at the end of the new top-level `run_pipeline()` loop — either is fine, keep it inside `run_pipeline_for_account` to match today's call position).

- [ ] **Step 4: Verify with `--now` against the migrated default account**

Run: `python scheduler.py --now`
Expected: log lines showing `Running pipeline for account 'default' (Default Channel)`, followed by the normal 8-slot generation + upload flow, writing into `output/default/<today>/video_NN` (confirm with `ls output/default/$(date +%Y-%m-%d)/` after it completes — this is a full real run, so only do this if you're OK with real API usage/uploads; otherwise inspect the code path with a dry run by temporarily commenting out the upload loop and checking the generated `videos` list length and `base_dir` path via an added `print(base_dir, len(videos))`).

- [ ] **Step 5: Commit**

```bash
git add scheduler.py
git commit -m "feat: make the daily pipeline loop over enabled accounts"
```

---

## Task 8: Account-aware `_run_shorts`

**Files:**
- Modify: `scheduler.py`

**Interfaces:**
- Consumes: `pipeline.shorts_config.load_shorts_config` (Task 4), `account.output_dir`, `account.dir`, `account.token_file`.
- Produces: `_run_shorts(base_dir: Path, account) -> None` (account now required).

- [ ] **Step 1: Thread `account` through `_run_shorts`**

Change the signature to `def _run_shorts(base_dir: Path, account) -> None:`. Replace the hardcoded `_SHORTS_PLAN` feed rotation and `SHORTS_PER_DAY` with values from `load_shorts_config(account)`:
```python
from pipeline.shorts_config import load_shorts_config
cfg = load_shorts_config(account)
shorts_per_day = cfg.get("shorts_per_day", SHORTS_PER_DAY)
feeds = cfg.get("feeds") or ["india", "world", "business"]
plan = [{"feed": f, "focus": f"{f.title()} breaking news"} for f in feeds]
```
and change the loop bound from `range(1, SHORTS_PER_DAY + 1)` to `range(1, shorts_per_day + 1)`, and `plan = _SHORTS_PLAN[(i - 1) % len(_SHORTS_PLAN)]` to `plan_entry = plan[(i - 1) % len(plan)]` (rename to avoid shadowing the outer `plan` variable name introduced above).

Update `build_short_script(feed=plan_entry["feed"], locale=locale)` to also pass through account-scoped topic history: this requires threading `account.dir` into `generate_short_now.build_short_script` (covered in Task 11) — for now, pass an explicit `account=account` argument here matching the new signature Task 11 will add, so this task and Task 11 agree on the interface: `build_short_script(feed=plan_entry["feed"], locale=locale, account=account)`.

Change the record_topic call after script generation from `record_topic(script.get("title", ""))` to `record_topic(script.get("title", ""), namespace="shorts", base_dir=account.dir)`.

Update the upload call at the end of `_run_shorts` (the `upload_video(...)` for shorts) to add `token_file=account.token_file`.

- [ ] **Step 2: Update the call site in `run_pipeline_for_account`**

Change `_run_shorts(base_dir)` to `_run_shorts(base_dir, account)` (this call is already inside `run_pipeline_for_account` from Task 7, where `base_dir` is `account.output_dir / today`).

- [ ] **Step 3: Verify shorts config drives the loop count**

Run:
```bash
python -c "
from pipeline.accounts import get_account
from pipeline.shorts_config import load_shorts_config, save_shorts_config

acc = get_account('default')
cfg = load_shorts_config(acc)
cfg['shorts_per_day'] = 3
save_shorts_config(acc, cfg)
print('shorts_per_day set to 3 for default account -- verify by reading it back')
cfg2 = load_shorts_config(acc)
assert cfg2['shorts_per_day'] == 3
print('OK')
"
```
Expected: `OK` printed. Afterwards, if you don't actually want the default account's real daily Shorts count changed, run the same snippet again with `cfg['shorts_per_day'] = 10` to restore it.

- [ ] **Step 4: Commit**

```bash
git add scheduler.py
git commit -m "feat: drive Shorts generation from each account's shorts_config.json"
```

---

## Task 9: On-demand long-form generation

**Files:**
- Modify: `scheduler.py`

**Interfaces:**
- Consumes: `pipeline.accounts.get_account` (Task 1), `_pick_topic_for_category` (Task 6), `_run_single_video` (existing, now with `account_dir` from Task 7), `_next_video_index` (new helper, this task).
- Produces: `generate_video_now(account_id: str, category: str, custom_topic: str = "", locale_override: str = "") -> dict` — raises `ValueError` for an unknown account or category; returns the same meta dict `_run_single_video` returns, plus `"youtube_id"` once uploaded.

- [ ] **Step 1: Add a `_next_video_index` helper**

Mirror the existing `_next_short_index` pattern from `generate_short_now.py`:
```python
def _next_video_index(base_dir: Path) -> int:
    existing = [int(p.name.split("_")[1]) for p in base_dir.glob("video_*") if p.name.split("_")[1].isdigit()]
    return (max(existing) + 1) if existing else 1
```

- [ ] **Step 2: Write `generate_video_now`**

```python
def generate_video_now(account_id: str, category: str, custom_topic: str = "", locale_override: str = "") -> dict:
    """
    Generate and upload ONE long-form video immediately for account_id —
    used by the dashboard's on-demand "Generate video now" panel. Raises
    ValueError for an unknown account or category.
    """
    from pipeline.accounts import get_account

    account = get_account(account_id)
    if not account:
        raise ValueError(f"Unknown account '{account_id}'")

    cfg = json.loads(account.topic_config_path.read_text(encoding="utf-8")) if account.topic_config_path.exists() else {}
    cat_info = cfg.get("categories", {}).get(category, {})
    if not cat_info:
        raise ValueError(f"Unknown category '{category}' for account '{account_id}'")

    locale = get_locale(locale_override) if locale_override.strip() else get_locale(account.locale)
    assigned: set = set()
    topic = custom_topic.strip() or _pick_topic_for_category(cat_info, locale, assigned, topic_history_base_dir=account.dir)

    base_dir = account.output_dir / datetime.now(IST).strftime("%Y-%m-%d")
    base_dir.mkdir(parents=True, exist_ok=True)
    index = _next_video_index(base_dir)

    meta = _run_single_video(
        topic=topic, slot_str="on-demand", index=index, base_dir=base_dir,
        category_style=cat_info.get("prompt_style", ""),
        category=category, category_color=cat_info.get("color", ""),
        category_label=cat_info.get("label", category),
        locale=locale, account_dir=account.dir,
    )
    if not meta:
        raise RuntimeError(f"Video generation failed for account '{account_id}', category '{category}'")

    meta["yt_category_id"] = cat_info.get("yt_category_id", "25")
    vid_id = upload_video(
        video_path=meta["path"], title=meta["title"], description=meta["description"],
        tags=meta["tags"], publish_at_utc=datetime.now(timezone.utc),
        category_id=meta["yt_category_id"], yt_language=meta["yt_language"],
        token_file=account.token_file,
    )
    upload_thumbnail(vid_id, meta["thumbnail_path"], token_file=account.token_file)
    add_video_to_playlist(vid_id, category, meta.get("category_label", category),
                          token_file=account.token_file, cache_dir=account.dir)
    upload_captions(vid_id, meta.get("captions_srt", ""), language=meta["yt_language"], token_file=account.token_file)
    meta["youtube_id"] = vid_id
    return meta
```

- [ ] **Step 3: Verify against the default account (real generation + upload — confirm you're OK with this before running)**

Run:
```bash
python -c "
from scheduler import generate_video_now
meta = generate_video_now('default', category='news_india', custom_topic='India digital payments UPI growth 2026')
print('generated + uploaded:', meta['title'], '->', meta['youtube_id'])
"
```
Expected: prints a real title and a real YouTube video ID. This performs a real upload — only run it when you intend to publish a real video.

- [ ] **Step 4: Commit**

```bash
git add scheduler.py
git commit -m "feat: add generate_video_now for on-demand long-form generation"
```

---

## Task 10: Account-scope `regenerate_video.py`

**Files:**
- Modify: `regenerate_video.py`

**Interfaces:**
- Consumes: `pipeline.accounts.get_account` (Task 1), account-aware `_load_slot_plan`/`_run_single_video` (Task 7).

- [ ] **Step 1: Add `--account` and resolve paths through it**

Add `parser.add_argument("--account", default="default", help="Account id")`. After parsing args, resolve:
```python
from pipeline.accounts import get_account
account = get_account(args.account)
if not account:
    log.error("Unknown account '%s'", args.account)
    sys.exit(1)
base_dir = account.output_dir / args.date if args.date else account.output_dir / datetime.now(IST).strftime("%Y-%m-%d")
```
replacing the current `base_dir = Path(OUTPUT_DIR) / args.date`. Update `slot_plan = _load_slot_plan()` to `slot_plan = _load_slot_plan(account)`, and pass `account_dir=account.dir` to the `_run_single_video(...)` call (alongside the existing `category_label=plan.get("category_label", "")` added earlier this session).

- [ ] **Step 2: Verify**

Run: `python regenerate_video.py --help`
Expected: `--account` appears in the help output alongside `--date` and `--index`.

- [ ] **Step 3: Commit**

```bash
git add regenerate_video.py
git commit -m "feat: account-scope regenerate_video.py"
```

---

## Task 11: Account-scope `generate_short_now.py`

**Files:**
- Modify: `generate_short_now.py`

**Interfaces:**
- Consumes: `pipeline.accounts.get_account` (Task 1), `pipeline.shorts_config.load_shorts_config` (Task 4).
- Produces: `build_short_script(feed="india", topic="", locale=None, content_type="news", account=None) -> dict` (adds the `account` parameter referenced in Task 8).

- [ ] **Step 1: Add `--account` and thread it through `build_short_script`/`generate_one_short`**

Add `parser.add_argument("--account", default="default", help="Account id")`. Add `account: "Account | None" = None` as the last parameter of `build_short_script`, and change its two `record_topic(script.get("title", ""))` calls to `record_topic(script.get("title", ""), namespace="shorts", base_dir=account.dir if account else None)`. Change `fresh = filter_fresh(headlines)` to `fresh = filter_fresh(headlines, namespace="shorts", base_dir=account.dir if account else None)`, and `avoid_titles=recent_titles()` to `avoid_titles=recent_titles(namespace="shorts", base_dir=account.dir if account else None)`.

Add the same `account` parameter to `generate_one_short`, forwarding it to `build_short_script(..., account=account)`, and use `account.output_dir` instead of `OUTPUT_DIR` for `base_dir` resolution in `main()` when `--account` is given (resolve via `pipeline.accounts.get_account(args.account)`, erroring out same as Task 10 if unknown). Add `token_file=account.token_file if account else None` to whatever upload call exists in this script's flow (check whether `generate_short_now.py` itself uploads or only generates — if it only generates without uploading, skip this sub-step; if it does upload, thread it through).

- [ ] **Step 2: Verify**

Run: `python generate_short_now.py --help`
Expected: `--account` appears alongside `--feed`, `--topic`, `--content-type`, `--index`, `--date`, `--locale`, `--count`.

- [ ] **Step 3: Commit**

```bash
git add generate_short_now.py
git commit -m "feat: account-scope generate_short_now.py"
```

---

## Task 12: Accounts CRUD API endpoints

**Files:**
- Modify: `api/main.py`

**Interfaces:**
- Produces: `GET /api/accounts`, `POST /api/accounts/{account_id}/toggle`, `GET /api/accounts/{account_id}/topic-config`, `POST /api/accounts/{account_id}/topic-config`, `GET /api/accounts/{account_id}/shorts-config`, `POST /api/accounts/{account_id}/shorts-config`.

- [ ] **Step 1: Add the routes**

```python
from pipeline.accounts import load_accounts, get_account, set_account_enabled, add_account
from pipeline.shorts_config import load_shorts_config, save_shorts_config

@app.get("/api/accounts")
async def list_accounts():
    accounts = load_accounts()
    return {
        "accounts": [
            {
                "id": a.id, "label": a.label, "locale": a.locale,
                "enabled": a.enabled, "created_at": a.created_at,
                "token_exists": a.token_path.exists(),
            }
            for a in accounts
        ]
    }

@app.post("/api/accounts/{account_id}/toggle")
async def toggle_account(account_id: str, body: dict):
    enabled = bool(body.get("enabled", True))
    try:
        set_account_enabled(account_id, enabled)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"ok": True, "id": account_id, "enabled": enabled}

@app.get("/api/accounts/{account_id}/topic-config")
async def get_account_topic_config(account_id: str):
    account = get_account(account_id)
    if not account:
        raise HTTPException(404, f"Unknown account '{account_id}'")
    if not account.topic_config_path.exists():
        return {"slots": [], "categories": {}}
    return json.loads(account.topic_config_path.read_text(encoding="utf-8"))

@app.post("/api/accounts/{account_id}/topic-config")
async def save_account_topic_config(account_id: str, body: dict):
    account = get_account(account_id)
    if not account:
        raise HTTPException(404, f"Unknown account '{account_id}'")
    account.dir.mkdir(parents=True, exist_ok=True)
    account.topic_config_path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True}

@app.get("/api/accounts/{account_id}/shorts-config")
async def get_account_shorts_config(account_id: str):
    account = get_account(account_id)
    if not account:
        raise HTTPException(404, f"Unknown account '{account_id}'")
    return load_shorts_config(account)

@app.post("/api/accounts/{account_id}/shorts-config")
async def save_account_shorts_config(account_id: str, body: dict):
    account = get_account(account_id)
    if not account:
        raise HTTPException(404, f"Unknown account '{account_id}'")
    save_shorts_config(account, body)
    return {"ok": True}
```
(Place these near the existing `/api/settings` routes; confirm `json` and `HTTPException` are already imported at the top of `api/main.py` — both are, per the existing file.)

- [ ] **Step 2: Verify with the running dev server**

With the API dev server running (`python run_api.py`), run:
```bash
curl -s http://127.0.0.1:8000/api/accounts | python -m json.tool
```
Expected: JSON with one account, `"id": "default"`, `"enabled": true`, `"token_exists": true` (this route has no auth guard in this snippet — check whether other `/api/*` routes in this file require a login cookie/header via a dependency; if so, add the same dependency to these new routes for consistency before testing with curl).

- [ ] **Step 3: Commit**

```bash
git add api/main.py
git commit -m "feat: add accounts CRUD API endpoints"
```

---

## Task 13: On-demand long-form generation endpoint + account_id on existing routes

**Files:**
- Modify: `api/main.py`

**Interfaces:**
- Consumes: `scheduler.generate_video_now` (Task 9).
- Produces: `POST /api/videos/generate`. Existing video/short/log/upload/regenerate routes gain an `account_id: str = "default"` query parameter, defaulting to `"default"` so today's dashboard (not yet updated for accounts) keeps working against the migrated default account without changes until Task 17.

- [ ] **Step 1: Add the generation endpoint**

```python
class GenerateVideoRequest(BaseModel):
    account_id: str
    category: str
    custom_topic: str = ""
    locale: str = ""

@app.post("/api/videos/generate")
async def generate_video(req: GenerateVideoRequest):
    from scheduler import generate_video_now

    def _do_generate():
        return generate_video_now(req.account_id, req.category, req.custom_topic, req.locale)

    try:
        meta = await asyncio.to_thread(_do_generate)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"ok": True, "title": meta["title"], "youtube_id": meta.get("youtube_id")}
```
(Confirm `BaseModel` is already imported from `pydantic` in `api/main.py` — it is, used by other request models in this file; confirm `asyncio` is imported — it is, used by the existing upload endpoints.)

- [ ] **Step 2: Add `account_id` to the existing video-serving/listing routes**

For each of `_video_dir`, `_today` (or equivalent path-building helpers used by `/api/videos`, `/api/videos/{date}/{index}/...`, `/api/shorts`, `/api/logs`, `upload_generated_video`, `upload_generated_short`), add an `account_id: str = "default"` query parameter and resolve the base output path via `get_account(account_id).output_dir` instead of the bare `OUTPUT_DIR` constant, falling back to `OUTPUT_DIR` directly if `get_account(account_id)` is `None` (defensive default so a stale/unknown account_id in an old dashboard tab doesn't 500).

- [ ] **Step 3: Verify the new endpoint against the default account**

With the dev server running:
```bash
curl -s -X POST http://127.0.0.1:8000/api/videos/generate \
  -H "Content-Type: application/json" \
  -d '{"account_id":"default","category":"news_india","custom_topic":"India digital payments UPI growth 2026"}'
```
Expected: `{"ok":true,"title":"...","youtube_id":"..."}` (this is a real generation + upload — confirm you want to run it before doing so; if you just want to check the route wires up correctly without a real upload, pass an intentionally-unknown `category` like `"not_a_real_category"` and expect a 400 with the `ValueError` message instead).

- [ ] **Step 4: Commit**

```bash
git add api/main.py
git commit -m "feat: on-demand long-form generation endpoint + account_id on existing routes"
```

---

## Task 14: Dashboard API client + account context

**Files:**
- Modify: `dashboard/lib/api.ts`
- Create: `dashboard/lib/accountContext.tsx`

**Interfaces:**
- Produces (in `api.ts`): `api.listAccounts()`, `api.toggleAccount(id, enabled)`, `api.getAccountTopicConfig(id)`, `api.saveAccountTopicConfig(id, cfg)`, `api.getAccountShortsConfig(id)`, `api.saveAccountShortsConfig(id, cfg)`, `api.generateVideo(accountId, category, customTopic, locale)`.
- Produces (in `accountContext.tsx`): `AccountProvider`, `useAccount()` returning `{ accountId: string, setAccountId: (id: string) => void, accounts: Account[] }`.

- [ ] **Step 1: Add the API client functions**

Open `dashboard/lib/api.ts` and find how existing functions like `api.generateShort` are structured (per this session's earlier work: `api.generateShort(feed, topic, contentType)`, calling `POST ${BASE}/api/shorts/generate`). Add, following the exact same `fetch`/`authHeaders()` pattern:
```typescript
listAccounts: async () => {
  const res = await fetch(`${BASE}/api/accounts`, { headers: authHeaders() });
  return res.json();
},
toggleAccount: async (id: string, enabled: boolean) => {
  const res = await fetch(`${BASE}/api/accounts/${id}/toggle`, {
    method: "POST", headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  return res.json();
},
getAccountTopicConfig: async (id: string) => {
  const res = await fetch(`${BASE}/api/accounts/${id}/topic-config`, { headers: authHeaders() });
  return res.json();
},
saveAccountTopicConfig: async (id: string, cfg: unknown) => {
  const res = await fetch(`${BASE}/api/accounts/${id}/topic-config`, {
    method: "POST", headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify(cfg),
  });
  return res.json();
},
getAccountShortsConfig: async (id: string) => {
  const res = await fetch(`${BASE}/api/accounts/${id}/shorts-config`, { headers: authHeaders() });
  return res.json();
},
saveAccountShortsConfig: async (id: string, cfg: unknown) => {
  const res = await fetch(`${BASE}/api/accounts/${id}/shorts-config`, {
    method: "POST", headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify(cfg),
  });
  return res.json();
},
generateVideo: async (accountId: string, category: string, customTopic: string, locale: string) => {
  const res = await fetch(`${BASE}/api/videos/generate`, {
    method: "POST", headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify({ account_id: accountId, category, custom_topic: customTopic, locale }),
  });
  return res.json();
},
```
placed inside the existing exported `api` object, matching the surrounding style exactly (check whether the file uses `export const api = { ... }` as one object literal — add these as more entries in that same literal).

- [ ] **Step 2: Write the account context**

```tsx
"use client";
import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { api } from "./api";

interface AccountInfo {
  id: string;
  label: string;
  locale: string;
  enabled: boolean;
}

interface AccountContextValue {
  accountId: string;
  setAccountId: (id: string) => void;
  accounts: AccountInfo[];
}

const AccountContext = createContext<AccountContextValue | null>(null);

export function AccountProvider({ children }: { children: ReactNode }) {
  const [accounts, setAccounts] = useState<AccountInfo[]>([]);
  const [accountId, setAccountIdState] = useState<string>(
    () => (typeof window !== "undefined" && localStorage.getItem("currentAccountId")) || "default"
  );

  useEffect(() => {
    api.listAccounts().then((data) => setAccounts(data.accounts || []));
  }, []);

  const setAccountId = (id: string) => {
    setAccountIdState(id);
    if (typeof window !== "undefined") localStorage.setItem("currentAccountId", id);
  };

  return (
    <AccountContext.Provider value={{ accountId, setAccountId, accounts }}>
      {children}
    </AccountContext.Provider>
  );
}

export function useAccount(): AccountContextValue {
  const ctx = useContext(AccountContext);
  if (!ctx) throw new Error("useAccount must be used within an AccountProvider");
  return ctx;
}
```

- [ ] **Step 3: Wrap the dashboard layout in `AccountProvider`**

Find `dashboard/app/layout.tsx` (Next.js App Router root layout). Import `AccountProvider` from `@/lib/accountContext` and wrap the existing `{children}` (and whatever provider(s) already wrap it, e.g. an auth provider) with `<AccountProvider>{children}</AccountProvider>`, innermost-or-outermost matching how the existing provider nesting is structured (check the current file's JSX before deciding placement — it should wrap everything that renders dashboard panels, but can sit inside an existing auth-check wrapper).

- [ ] **Step 4: Verify it compiles**

Run:
```bash
cd dashboard && npx tsc --noEmit -p tsconfig.json
```
Expected: no new errors introduced in `api.ts`, `accountContext.tsx`, or `layout.tsx` (pre-existing errors in unrelated files like `CommunityPanel.tsx`, noted earlier this session, are not this task's concern).

- [ ] **Step 5: Commit**

```bash
git add dashboard/lib/api.ts dashboard/lib/accountContext.tsx dashboard/app/layout.tsx
git commit -m "feat: dashboard API client + account context for multi-account support"
```

---

## Task 15: Account switcher in the dashboard header

**Files:**
- Modify: dashboard's main layout/sidebar component (the one showing "Auto-Poster / @bitnomad1" per the earlier screenshot — locate via `grep -rl "Pipeline Running" dashboard/components dashboard/app`).

**Interfaces:**
- Consumes: `useAccount()` (Task 14).

- [ ] **Step 1: Locate the header/sidebar component**

Run: `grep -rl "Pipeline Running" dashboard/components dashboard/app` to find the exact file (per the Shorts screenshot shared earlier this session, this text sits directly under the channel name in the left sidebar).

- [ ] **Step 2: Add a dropdown switcher below the channel name**

Using the same dropdown pattern already established in `ShortsPanel.tsx`'s `ContentTypeDropdown` (a button that toggles an absolutely/fixed-positioned list, `lucide-react`'s `ChevronDown`/`Check` icons, `useState` for open/closed) — add a small account switcher:
```tsx
import { useAccount } from "@/lib/accountContext";

function AccountSwitcher() {
  const { accountId, setAccountId, accounts } = useAccount();
  const [open, setOpen] = useState(false);
  const current = accounts.find((a) => a.id === accountId);

  return (
    <div style={{ position: "relative" }}>
      <button onClick={() => setOpen((o) => !o)} className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium">
        <span>{current?.label || accountId}</span>
        <ChevronDown size={12} className={open ? "rotate-180" : ""} />
      </button>
      {open && (
        <div style={{ position: "absolute", top: "100%", left: 0, zIndex: 50, background: "#080c18", border: "1px solid rgba(79,195,247,0.25)", borderRadius: 8, minWidth: 180 }}>
          {accounts.map((a) => (
            <button
              key={a.id}
              onClick={() => { setAccountId(a.id); setOpen(false); }}
              style={{ width: "100%", display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", fontSize: 13, textAlign: "left", color: a.id === accountId ? "#4FC3F7" : "#e2e8f0" }}
            >
              <span style={{ flex: 1 }}>{a.label}</span>
              {a.id === accountId && <Check size={12} />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
```
Render `<AccountSwitcher />` directly under the existing channel-name/"Pipeline Running..." block in the sidebar.

- [ ] **Step 3: Verify visually**

Start the dashboard dev server if not already running (`npm run dev` in `dashboard/`), open `http://localhost:3000`, confirm the switcher appears showing "Default Channel" and opens/closes on click.

- [ ] **Step 4: Commit**

```bash
git add dashboard/components/<the located file>
git commit -m "feat: account switcher in dashboard sidebar"
```

---

## Task 16: Accounts settings panel

**Files:**
- Create: `dashboard/components/AccountsPanel.tsx`
- Modify: whichever file defines the dashboard's sidebar nav (same area located in Task 15) to add an "Accounts" entry.

**Interfaces:**
- Consumes: `api.listAccounts()`, `api.toggleAccount()` (Task 14).

- [ ] **Step 1: Write the panel**

```tsx
"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface AccountRow {
  id: string;
  label: string;
  locale: string;
  enabled: boolean;
  created_at: string;
  token_exists: boolean;
}

export default function AccountsPanel() {
  const [accounts, setAccounts] = useState<AccountRow[]>([]);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    api.listAccounts().then((data) => {
      setAccounts(data.accounts || []);
      setLoading(false);
    });
  };

  useEffect(load, []);

  const toggle = async (id: string, enabled: boolean) => {
    await api.toggleAccount(id, enabled);
    load();
  };

  return (
    <div className="p-6">
      <h1 className="text-xl font-bold mb-2">YouTube Accounts</h1>
      <p className="text-sm text-slate-400 mb-6">
        Each account has its own content niche, schedule, and locale. To connect a new one, run
        from a terminal: <code>python setup_auth.py --account &lt;id&gt; --label "Channel Name" --locale hi</code>
      </p>
      {loading ? (
        <p>Loading...</p>
      ) : (
        <div className="flex flex-col gap-3">
          {accounts.map((a) => (
            <div key={a.id} className="flex items-center justify-between p-4 rounded-lg border border-slate-700">
              <div>
                <div className="font-medium">{a.label}</div>
                <div className="text-xs text-slate-400">
                  id: {a.id} · locale: {a.locale} · connected: {a.token_exists ? "yes" : "NO TOKEN FILE"}
                </div>
              </div>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={a.enabled} onChange={(e) => toggle(a.id, e.target.checked)} />
                Enabled
              </label>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Wire it into the sidebar nav**

In the file located in Task 15, add an "Accounts" nav item following the exact pattern of the existing "Settings" entry (same icon-import style from `lucide-react`, e.g. `Users` or `UserCog`), routing to wherever the dashboard's client-side view-switching mechanism points (check whether this dashboard uses Next.js file-based routes per section or a single-page `useState` view switcher, matching whichever pattern `Settings`/`Topics` already use).

- [ ] **Step 3: Verify visually**

Open the dashboard, click "Accounts" in the sidebar, confirm the default account row renders with "connected: yes" and the checkbox toggles (toggle it off, confirm `api/accounts.json` on disk shows `"enabled": false` for `default`, then toggle back on).

- [ ] **Step 4: Commit**

```bash
git add dashboard/components/AccountsPanel.tsx dashboard/components/<nav file>
git commit -m "feat: Accounts settings panel"
```

---

## Task 17: Long-form "Generate now" panel + Shorts account dropdown + scope existing panels

**Files:**
- Create: `dashboard/components/VideoGeneratePanel.tsx`
- Modify: `dashboard/components/ShortsPanel.tsx`
- Modify: whichever dashboard components fetch `/api/videos`, `/api/shorts`, `/api/logs` (to add `account_id` from `useAccount()`)

**Interfaces:**
- Consumes: `api.generateVideo`, `useAccount()` (Task 14), existing `api.generateShort`.

- [ ] **Step 1: Write the long-form generate-now panel, mirroring `ShortsPanel.tsx`'s existing generate form**

```tsx
"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAccount } from "@/lib/accountContext";

export default function VideoGeneratePanel() {
  const { accountId } = useAccount();
  const [categories, setCategories] = useState<Record<string, { label: string }>>({});
  const [category, setCategory] = useState("");
  const [customTopic, setCustomTopic] = useState("");
  const [locale, setLocale] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState("");

  useEffect(() => {
    api.getAccountTopicConfig(accountId).then((cfg) => {
      setCategories(cfg.categories || {});
      const keys = Object.keys(cfg.categories || {});
      if (keys.length) setCategory(keys[0]);
    });
  }, [accountId]);

  const generate = async () => {
    setBusy(true);
    setResult("Generating... this takes a few minutes.");
    try {
      const res = await api.generateVideo(accountId, category, customTopic, locale);
      setResult(res.ok ? `Done: ${res.title} -> https://youtube.com/watch?v=${res.youtube_id}` : `Failed: ${res.detail || "unknown error"}`);
    } catch (e) {
      setResult(`Failed: ${e}`);
    }
    setBusy(false);
  };

  return (
    <div className="p-4 rounded-xl border border-slate-700">
      <h3 className="font-semibold mb-3">Generate a long-form video now</h3>
      <div className="flex flex-col gap-3">
        <select value={category} onChange={(e) => setCategory(e.target.value)} className="bg-transparent border border-slate-700 rounded-lg px-3 py-2 text-sm">
          {Object.entries(categories).map(([key, c]) => (
            <option key={key} value={key}>{c.label}</option>
          ))}
        </select>
        <input
          value={customTopic}
          onChange={(e) => setCustomTopic(e.target.value)}
          placeholder="Optional custom topic — leave blank for a fresh trending topic"
          className="bg-transparent border border-slate-700 rounded-lg px-3 py-2 text-sm"
        />
        <input
          value={locale}
          onChange={(e) => setLocale(e.target.value)}
          placeholder="Optional locale override (e.g. hi, en) — leave blank for account default"
          className="bg-transparent border border-slate-700 rounded-lg px-3 py-2 text-sm"
        />
        <button onClick={generate} disabled={busy || !category} className="bg-blue-600 rounded-lg px-4 py-2 text-sm font-medium disabled:opacity-50">
          {busy ? "Generating..." : "Generate"}
        </button>
        {result && <p className="text-xs text-slate-400">{result}</p>}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Add the account dropdown to `ShortsPanel.tsx`'s generate form**

In the `GeneratePanel` section of `ShortsPanel.tsx` (lines ~295-392 per the earlier project survey), import `useAccount` from `@/lib/accountContext`, destructure `{ accountId }`, and pass it through the existing `api.generateShort(feed, customTopic, contentType)` call — this call needs a 4th argument now. Update the call to `api.generateShort(feed, customTopic, contentType, accountId)`, and correspondingly update `api.generateShort`'s definition in `dashboard/lib/api.ts` to accept and forward `accountId: string` as the 4th parameter, included in its POST body as `account_id`.

- [ ] **Step 3: Add `account_id` to the Videos/Shorts/Logs panels' fetch calls**

For each dashboard component that currently calls something like `fetch(`${BASE}/api/videos`)` or `fetch(`${BASE}/api/shorts`)` (find via `grep -rn "/api/videos\|/api/shorts\|/api/logs" dashboard/components`), import `useAccount`, destructure `accountId`, and append `?account_id=${accountId}` to each such URL (or add it as an additional query param if the URL already has one, using `&` instead of `?`).

- [ ] **Step 4: Verify visually**

With both the API and dashboard dev servers running: open the dashboard, confirm the new "Generate a long-form video now" panel appears (wire it into whichever existing page hosts the Videos list — likely alongside or above the existing videos grid), shows the default account's real categories in the dropdown, and confirm the Shorts panel's generate form still works with the account dropdown present. Do not necessarily click "Generate" for a full real run in this verification pass unless you want to actually publish a video — checking that categories populate correctly is sufficient to confirm the wiring works.

- [ ] **Step 5: Commit**

```bash
git add dashboard/components/VideoGeneratePanel.tsx dashboard/components/ShortsPanel.tsx dashboard/lib/api.ts dashboard/components/<videos/shorts/logs panels>
git commit -m "feat: long-form generate-now panel, Shorts account dropdown, account-scoped panels"
```

---

## Self-Review Notes

- **Spec coverage**: account model (Task 1), migration (Task 1), CLI onboarding (Task 5), output restructure (Tasks 7-11, 13), per-account Shorts config (Tasks 4, 8), on-demand long-form generation (Tasks 9, 13, 17), dashboard account switcher/management (Tasks 15-16), generation forms for both formats (Task 17) — every spec section maps to at least one task.
- **Type/signature consistency checked**: `Account` dataclass fields (Task 1) are used identically in Tasks 2, 3, 6-13 (`.token_file`, `.dir`, `.topic_config_path`, `.shorts_config_path`, `.output_dir`, `.locale`, `.id`, `.label`); `token_file`/`cache_dir`/`base_dir` optional-parameter names are consistent across `pipeline/uploader.py` (Task 2), `pipeline/topic_history.py` (Task 3), and every call site in `scheduler.py` (Tasks 7-9); `generate_video_now`'s return shape (`meta` dict with `"youtube_id"` added) matches what Task 13's endpoint reads (`meta.get("youtube_id")`) and what Task 17's panel displays.
- **No placeholders**: every step above contains real, complete code or an exact runnable command with an expected output to check against — none say "add appropriate handling" or "similar to Task N" without inlining the actual code.
