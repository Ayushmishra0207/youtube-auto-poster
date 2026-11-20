# Going live: Vercel + Render + Supabase + GitHub Actions

Everything runs on free tiers.

| Piece | Does | Where it's configured |
|---|---|---|
| **Vercel** | Dashboard website | `dashboard/` (already linked) |
| **Render** (free web service) | API: login, dashboard data, starts jobs | `render.yaml` (already linked) |
| **GitHub Actions** | Heavy work: daily run at 14:30 IST, Regenerate, Generate Short, Upload; engagement every 30 min | `.github/workflows/autoposter.yml`, `engagement.yml` |
| **Supabase** | Permanent memory: logins, settings, topic config, queues, video index, thumbnails + previews | `DATABASE_URL`, `SUPABASE_*` |

The **Clip Maker stays on your PC** (`start.bat`): YouTube blocks video downloads from cloud servers, and Whisper needs more memory than Render's free plan.

> **Keep every key out of chats, commits and screenshots.** They go only into the
> Render / GitHub / Vercel secret settings below. The repo is public, and so are GitHub
> Actions logs (secrets are masked automatically).

---

## 1. Supabase (≈5 min)

1. Go to <https://supabase.com> → **New project** (free). Pick the region closest to India (e.g. *Mumbai*). Save the database password somewhere safe.
2. **`DATABASE_URL`** → top bar **Connect** → **Session pooler** → copy the URI and put your database password into it.
   *Use the Session pooler (port 5432 on `…pooler.supabase.com`). The "Direct connection" is IPv6-only and won't work from Render or GitHub.*
3. **`SUPABASE_URL`** → Project Settings → **Data API** → Project URL (`https://xxxx.supabase.co`).
4. **`SUPABASE_SERVICE_KEY`** → Project Settings → **API Keys** → a **secret** key (`sb_secret_…`), or the legacy `service_role` key.

You don't need to create tables or buckets: the app creates them on first start (`media` bucket, private).

## 2. GitHub token for Render (≈2 min)

Render starts the GitHub Actions runs, so it needs a token:

GitHub → your avatar → **Settings → Developer settings → Fine-grained tokens → Generate new token**
- Repository access: **Only select repositories** → `youtube-auto-poster`
- Permissions → Repository → **Actions: Read and write** (nothing else)
- Expiration: up to 1 year (set a reminder to renew it)

This is **`GITHUB_DISPATCH_TOKEN`**.

## 3. Values from your PC

```
py get_deploy_secrets.py
```
It prints **`YOUTUBE_TOKEN_B64`** (from `youtube_token.pickle`). Other keys (`ANTHROPIC_API_KEY`, `PEXELS_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, …) are in your `.env`.

## 4. GitHub secrets

Repo → **Settings → Secrets and variables → Actions → New repository secret**, one per line:

| Secret | Required |
|---|---|
| `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` | yes |
| `YOUTUBE_TOKEN_B64` | yes |
| `ANTHROPIC_API_KEY` | yes (scripts) — or `GEMINI_API_KEY` / `OPENROUTER_API_KEY` as fallbacks |
| `PEXELS_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `HUGGINGFACE_API_KEY`, `JAMENDO_CLIENT_ID` | optional |
| `INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_BUSINESS_ACCOUNT_ID`, `R2_*` | only for Instagram Reels |

Then **Actions** tab → enable workflows if GitHub asks.

## 5. Render environment

Render → `yt-autoposter-api` → **Environment**:

| Key | Value |
|---|---|
| `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` | same as GitHub |
| `YOUTUBE_TOKEN_B64`, `ANTHROPIC_API_KEY`, … | same as GitHub |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | the dashboard login you want (created on every start) |
| `GITHUB_REPO` | `Ayushmishra0207/youtube-auto-poster` |
| `GITHUB_DISPATCH_TOKEN` | token from step 2 |
| `FRONTEND_URL` | your Vercel URL, e.g. `https://your-app.vercel.app` |

If the Render service was created by hand (not as a Blueprint from `render.yaml`), also set:
- **Build command:** `pip install -r requirements.txt && pip install -r api/requirements.txt`
- **Start command:** `uvicorn api.main:app --host 0.0.0.0 --port $PORT --no-access-log`

## 6. Vercel

Project → **Settings → Environment Variables**:
`NEXT_PUBLIC_API_URL` = your Render URL, e.g. `https://yt-autoposter-api.onrender.com` (no trailing slash) → **Redeploy**.

## 7. Push and check

```
git push origin main
```
Render and Vercel redeploy automatically. Then:

1. Open the Vercel site → sign in with `ADMIN_USERNAME` / `ADMIN_PASSWORD` (the first request can take ~1 min while Render wakes up).
2. Topics tab → save your slot setup once (it now lives in Supabase).
3. Press **Run Now** → GitHub → **Actions** shows a running "Auto-poster" job (≈1–2 h for 8 videos + 5 Shorts). Videos appear in the dashboard as they finish.
4. From then on it runs by itself every day at **14:30 IST**.

## How things behave live

- **"Upload to YouTube"** on a not-yet-uploaded video starts a GitHub run that publishes it ~5 min later. Long videos use the full-quality file kept for **3 days**; after that, Regenerate first.
- **Dashboard video player** shows a small preview (360p for long videos, full quality for Shorts) — Supabase's free plan allows 50 MB per file, 1 GB total. Old items are deleted after `KEEP_OUTPUT_DAYS`.
- **Settings page**: only non-secret values can be changed (days to keep, voice, Shorts per day). Keys are changed in Render/GitHub secrets.
- **Logs tab** links to the GitHub Actions run logs.
- GitHub may start the 14:30 run a few minutes late; publish times are set at upload, so videos still go out at their slots. A slot that already passed is published ~15 min after upload.

## Local use is unchanged

Without `DATABASE_URL` in `.env`, everything works exactly as before on your PC (SQLite + `output/` folder + `start.bat`), including the Clip Maker.
