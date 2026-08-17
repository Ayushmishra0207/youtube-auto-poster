# Multi-Account YouTube Support — Design

## Goal

Support multiple connected YouTube channels, each with its own content niche
(categories, schedule, locale), plus richer per-video customization (account,
category/niche, custom topic, locale) for both long-form and Shorts
generation — on demand, not just via the daily automatic schedule.

## Current state (single account, confirmed by code read)

- `config.py`: `YOUTUBE_CLIENT_SECRETS` / `YOUTUBE_TOKEN_FILE` are hardcoded
  single paths (`client_secrets.json`, `youtube_token.pickle`).
- `setup_auth.py` takes zero args; always overwrites the one token file.
- `topic_config.json` (long-form categories + daily slots) is a single
  global file at repo root, read by `scheduler.py::_load_slot_plan()`.
- Shorts has no equivalent config file — feeds/content-types are hardcoded
  lists in `shorts_creator`/`generate_short_now.py`.
- `output/<date>/video_NN` and `output/<date>/short_NN` are unscoped — no
  account dimension anywhere.
- `pipeline/uploader.py::_get_service()` always loads the one token file.
- Per-run state files (`longform_topic_history.json`,
  `shorts_topic_history.json`, `youtube_playlists.json`) are single global
  files.
- Dashboard: `ShortsPanel.tsx`'s generate-now form has feed/topic/content-type
  fields, no account field. Long-form has **no** generate-now form at all —
  only the daily schedule, plus a per-slot "Regenerate" button.
- `SettingsPanel.tsx` / `/api/settings` cover API keys and a few tunables,
  persisted to `.env` — no YouTube-credential or account concept at all.

## Account model

New top-level registry, `accounts.json` (repo root):

```json
{
  "accounts": [
    {
      "id": "hindi_news",
      "label": "Hindi News Channel",
      "locale": "hi",
      "token_file": "youtube_token_hindi_news.pickle",
      "enabled": true,
      "created_at": "2026-08-16"
    }
  ]
}
```

- `id`: slug, used as the directory/namespace key everywhere below.
- `token_file`: relative to `BASE_DIR`; each account's own OAuth token.
- The OAuth **client** (`client_secrets.json`) stays shared across all
  accounts — one Google Cloud OAuth client, multiple Google accounts
  consenting to it, each producing its own token. No per-account client
  secret needed.
- `locale`: default locale for this account's content (existing
  `pipeline/locales.py` codes) — per-video generation can still override it.

Per-account config directory: `accounts/<id>/`
- `topic_config.json` — same shape as today's global file (categories +
  daily long-form slots), now scoped per account.
- `shorts_config.json` — **new file**, same shape/spirit as
  `topic_config.json` but for Shorts: feeds, enabled content-types, daily
  Shorts slot count/times. Replaces today's hardcoded lists.
- `longform_topic_history.json`, `shorts_topic_history.json`,
  `youtube_playlists.json` — the existing state files, now written inside
  the account's own directory instead of `BASE_DIR` directly.

## Migration (existing single account → first account)

On first run after this feature ships:
1. If `accounts.json` doesn't exist, auto-create it with one account:
   `id: "default"`, `label` prompted or defaulted to the channel's real
   name (fetched via the existing token), `token_file: "youtube_token.pickle"`
   (the existing file, **not renamed** — avoids breaking the working
   credential).
2. Move today's root `topic_config.json` → `accounts/default/topic_config.json`
   (copy, don't delete the original blindly — leave a `.migrated` marker or
   just copy and log it).
3. Move `output/<date>/...` → `output/default/<date>/...` for any existing
   dated folders, so historical videos remain visible in the dashboard under
   the `default` account instead of disappearing.
4. Move the existing state files (`longform_topic_history.json`, etc.) into
   `accounts/default/`.

This keeps the currently-running channel working with zero manual steps;
new accounts are added explicitly afterward.

## Connecting a new account

Extend `setup_auth.py` with `--account <id> --label "<name>" [--locale hi]`:
- Runs the existing OAuth browser flow, writes to
  `youtube_token_<id>.pickle`.
- Appends the new entry to `accounts.json`.
- Creates `accounts/<id>/` with a starter `topic_config.json` /
  `shorts_config.json` (copied from a template, categories left for the
  user to edit via the dashboard afterward).

**Not building** a dashboard "click to connect" OAuth flow — that requires
the FastAPI server to handle Google's OAuth redirect callback, a
meaningfully larger and riskier build than reusing the already-proven CLI
flow. The dashboard's Accounts panel is management/viewing only; it
surfaces the exact CLI command to run for adding a new one.

## Output/addressing restructure

`output/<date>/video_NN` → `output/<account_id>/<date>/video_NN` (same for
`short_NN`). This is the highest-blast-radius change — every path in
`scheduler.py`, `generate_short_now.py`, `regenerate_video.py`, and every
`api/main.py` route that serves/lists videos, Shorts, thumbnails, or logs
needs an `account_id` added to its addressing (path param or query param).
Dashboard components (Videos, Shorts, Logs panels) all need to pass the
currently-selected account through to these calls.

## Scheduler changes

`run_pipeline()` becomes a loop:

```python
def run_pipeline():
    for account in load_enabled_accounts():
        run_pipeline_for_account(account)
```

`run_pipeline_for_account` is today's existing logic, parameterized by:
- `account.token_file` → threaded into `pipeline.uploader` so it builds a
  service for the right credentials (new: `get_service(token_file)` instead
  of a hardcoded path).
- `accounts/<id>/topic_config.json` instead of the global file.
- `output/<id>/<date>/` instead of `output/<date>/`.
- `account.locale` as the default locale for that account's slots.

`_run_shorts()` gets the same treatment, reading `accounts/<id>/shorts_config.json`.

Each account's run stays independent — a failure in one account's pipeline
must not abort another's (wrap each account's run in its own try/except at
the loop level, matching the existing per-video exception isolation).

## New: on-demand long-form generation

A new manual generate-now path (dashboard button + API endpoint), mirroring
Shorts' existing one: pick account, category (from that account's
`topic_config.json` categories), optional custom topic override, locale
override. Produces one video into that account's `output/<id>/<date>/video_NN`
immediately, without waiting for the daily schedule — reusing
`scheduler._run_single_video()` under the hood (already parameterized enough
for this after the account changes above).

## API changes (`api/main.py`)

- `GET /api/accounts` — list accounts (id, label, locale, enabled, and a
  cheap health check: does the token file exist/load).
- `POST /api/accounts/{id}/toggle` — enable/disable.
- `GET/POST /api/accounts/{id}/topic-config` and `/shorts-config` — reuse
  today's topic-config read/write logic, scoped per account.
- `POST /api/videos/generate` — new, the on-demand long-form endpoint above.
- Every existing videos/shorts/logs/upload/regenerate route gains an
  `account_id` parameter and resolves paths under `output/<account_id>/...`.

## Dashboard changes

- Global account switcher in the header — sets the "current account"
  context that Videos/Shorts/Logs/Topics panels all read from.
- New Accounts section (under Settings or its own sidebar item): account
  list, enable/disable toggle, per-account category/schedule editor (reusing
  the existing Topics panel UI, scoped to the selected account), and the
  exact `setup_auth.py --account ...` command to run for adding a new one.
- `ShortsPanel.tsx`'s generate-now form gains an account dropdown.
- New long-form generate-now panel (account + category + custom topic +
  locale), matching Shorts' existing form pattern.

## Explicitly out of scope

- Dashboard-driven OAuth connection flow (CLI-only, see above).
- Cross-account content sharing/deduplication (each account's topic history
  and playlists are fully independent, even if two accounts happen to share
  a niche).
- Automatic load-balancing of upload slots across accounts — each account
  keeps its own independent daily slot schedule.
