# YouTube Auto-Poster — Complete Guide

Hindi YouTube channel automation pipeline with a full-featured control dashboard.

---

## What This App Does

Every day at **2:30 AM IST** the pipeline automatically:
1. Fetches trending topics from Google Trends (India), guided by your chosen content categories
2. Generates Hindi scripts via **Claude AI** (category-specific style)
3. Synthesizes voice-over with **Microsoft Edge TTS** (Madhur Neural — deep Hindi male)
4. Fetches background images from **Pexels**
5. Renders **MP4 videos** (1920×1080, 24fps) with MoviePy
6. Uploads to **YouTube** with scheduled publish times (6:30–7:30 AM IST, 10-min gaps)
7. Sets custom thumbnails
8. Purges output files older than 3 days

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.10+ | python.org |
| Node.js | 18+ | nodejs.org |
| pip | latest | bundled with Python |
| npm | latest | bundled with Node.js |

---

## One-Time Setup

Run these once before using the app for the first time.

### 1. Install Python dependencies

```bash
cd c:\Users\kalki\My_workspace\Py_projects\Py-Projects\youtube-auto-poster
pip install -r requirements.txt
pip install uvicorn fastapi python-dotenv
```

### 2. Install dashboard dependencies

```bash
cd dashboard
npm install
cd ..
```

### 3. Download Hindi fonts

```bash
python setup_fonts.py
```

Downloads `NotoSansDevanagari-Bold.ttf` and `NotoSansDevanagari-Regular.ttf` into `assets/fonts/`.

### 4. Set up environment variables

Create a `.env` file in the project root:

```env
ANTHROPIC_API_KEY=sk-ant-...        # Required — Claude script generation
PEXELS_API_KEY=...                  # Optional — background images (falls back to gradients)
KEEP_OUTPUT_DAYS=3                  # Optional — days to keep output before auto-delete
TTS_VOICE=hi-IN-MadhurNeural       # Optional — Edge TTS voice
TTS_RATE=-5%                        # Optional — speech rate
TTS_PITCH=-8Hz                      # Optional — voice pitch
```

Get your Anthropic API key from: https://console.anthropic.com

### 5. Authenticate with YouTube (OAuth)

```bash
python setup_auth.py
```

- A browser window opens — sign in with your **YouTube channel's Google account**
- Click **Allow** (you may see an "unverified app" warning — click **Advanced → Go to app**)
- Token is saved as `youtube_token.pickle` — never needs repeating unless deleted

### 6. Enable YouTube Data API v3

Go to this URL and click **Enable**:
```
https://console.developers.google.com/apis/api/youtube.googleapis.com/overview?project=845448281427
```

This enables the Analytics panel in the dashboard to show live channel stats.

---

## Starting the App

You need **two terminals** open simultaneously.

### Terminal 1 — Python API Server

```bash
cd c:\Users\kalki\My_workspace\Py_projects\Py-Projects\youtube-auto-poster
uvicorn api.main:app --reload --port 8000
```

Leave this running. You should see:
```
INFO:     Uvicorn running on http://127.0.0.1:8000
```

### Terminal 2 — Dashboard Frontend

```bash
cd c:\Users\kalki\My_workspace\Py_projects\Py-Projects\youtube-auto-poster\dashboard
npm run dev
```

Leave this running. You should see:
```
▲ Next.js 14.2.3
- Local: http://localhost:3000
```

### Open the dashboard

Visit: **http://localhost:3000**

---

## Dashboard Panels

### Overview
- Pipeline running status (live polling every 5 seconds)
- Today's video count out of 7 slots
- Progress bar for the day
- Next scheduled run time
- Recent pipeline log feed (last 20 lines)

### Analytics
- **Channel stats** — subscribers, total views, total video count
- **View performance chart** — bar chart for your last 20 uploads
- **Recent uploads table** — thumbnail, title, views, likes, comments, privacy status
- Direct link to **YouTube Studio**

> Requires YouTube Data API v3 to be enabled (see setup step 6)

### Topics & Categories
Full control over what the pipeline generates each day.

**7 upload slots (06:30–07:30 IST)** — each slot gets:
- A **category** that drives the type of video generated
- An optional **pinned topic** to override auto-trending

| Category | What Claude generates |
|----------|----------------------|
| News India | Current Indian national news, factual reporting style |
| World News | International news and global events |
| Historical Story | Engaging historical storytelling with vivid detail |
| Cartoon / Animation | Fun animated story with moral lesson |
| Science & Tech | Complex topics explained simply |
| Sports | Exciting commentary and match/event news |
| Entertainment | Bollywood, celebrity, OTT news |
| Health & Lifestyle | Practical health and wellness tips |
| Finance & Market | Stock market and economic news |
| Spiritual | Devotional stories, mythology |

**To pin a specific topic:** Click "Pin topic" on any slot → type the topic → press Enter → Save Changes

**To use auto-trending:** Leave the slot unpinned. The pipeline will find trending content for that category from Google Trends.

**Save Changes button** appears when you make edits — click it to persist to `topic_config.json`.

### Videos
- Grid of all videos generated today
- Thumbnail preview, Hindi title, publish slot, render status
- Click the play button to preview the video in-browser
- Shows script sections (headings + narration preview)

Status badges:
- **Ready** — video rendered, uploaded to YouTube
- **Rendering** — video is being created
- **Generating** — voices/images being fetched
- **Pending** — not started yet
- **Failed** — error during generation

### Logs
- Real-time log stream from `logs/pipeline.log` via WebSocket
- Color-coded: info (grey), success (green), warning (yellow), error (red)
- Timestamped entries
- Auto-scrolls to latest

### Schedule
- Visual timeline showing all 7 upload slots (06:30–07:30 IST)
- Shows which slots have generated videos vs. empty
- Status indicator per slot (Pending / Uploading / Uploaded)

### Settings
- Edit API keys, retention period, TTS voice/rate/pitch
- Changes are written to `.env` and picked up on the next pipeline run

---

## Run Pipeline Manually

### From the dashboard
Click the **Run Now** button in the top of the sidebar. The pipeline starts immediately and logs stream into the Logs panel.

### From the terminal
```bash
cd c:\Users\kalki\My_workspace\Py_projects\Py-Projects\youtube-auto-poster
python scheduler.py --now
```

---

## Automatic Daily Schedule

The pipeline fires automatically at **2:30 AM IST** every day when the scheduler is running.

### Start as a long-running daemon

```bash
python scheduler.py
```

Keep this terminal open (or run it as a Windows service).

### Install as Windows Task Scheduler job (runs even when terminal is closed)

Run once as Administrator:
```bash
python install_task.py
```

Check status / remove:
```bash
python install_task.py --status
python install_task.py --remove
```

---

## File Structure

```
youtube-auto-poster/
├── scheduler.py              Main pipeline orchestrator
├── config.py                 All settings (paths, video specs, slots)
├── topic_config.json         Category + topic assignments per slot (editable via dashboard)
├── topics_override.json      Legacy manual topic overrides (auto-managed)
├── youtube_token.pickle      YouTube OAuth token (auto-refreshed)
├── client_secrets.json       Google OAuth credentials
├── .env                      Your API keys
│
├── pipeline/
│   ├── script_generator.py   Claude AI → Hindi JSON script
│   ├── voice_generator.py    Edge TTS → MP3 voice clips
│   ├── image_fetcher.py      Pexels → background images
│   ├── video_creator.py      MoviePy → MP4 video + thumbnail
│   ├── uploader.py           YouTube Data API upload
│   ├── trends.py             Google Trends topic fetching
│   ├── logger.py             Rotating log (logs/pipeline.log)
│   └── retry.py              Exponential backoff decorator
│
├── api/
│   └── main.py               FastAPI backend (port 8000)
│
├── dashboard/
│   ├── app/page.tsx          Main dashboard layout
│   ├── components/           All UI panels
│   └── lib/api.ts            API client
│
├── output/
│   └── YYYY-MM-DD/
│       └── video_NN/
│           ├── final.mp4     Rendered video
│           ├── thumbnail.jpg Custom YouTube thumbnail
│           ├── script.json   Generated Hindi script
│           ├── voices/       TTS audio clips per section
│           └── images/       Pexels background images
│
└── logs/
    └── pipeline.log          Rotating log (5 MB × 7 files)
```

---

## Troubleshooting

### Dashboard shows "Cannot reach API server"
The Python API is not running. Start it:
```bash
uvicorn api.main:app --reload --port 8000
```

### Analytics shows error
YouTube Data API v3 is not enabled. Enable it:
```
https://console.developers.google.com/apis/api/youtube.googleapis.com/overview?project=845448281427
```

### Pipeline fails with "OAuth token not found"
Run setup again:
```bash
python setup_auth.py
```

### Videos render but don't upload (403 error on thumbnail)
Your YouTube channel needs **phone verification** to set custom thumbnails.
Go to: https://www.youtube.com/verify

### WinError 32 (file locked) during video render
Two pipeline instances ran at the same time. The lock file system prevents this, but if it happens:
```bash
del pipeline.lock
```

### Edge TTS fails / no voice
Check internet connection. The voice generator falls back to gTTS (Google TTS) automatically.

### Google Trends returns no results
The pipeline falls back to category-specific fallback topics defined in `topic_config.json`.

---

## Free Cloud Deployment

Deploy the dashboard globally so you can access it from any device, anywhere.

### Architecture

```
Your Windows PC          →   runs scheduler.py (generates & uploads videos)
Render.com (free)        →   FastAPI backend   (analytics, topic control, logs)
Vercel.com (free)        →   Next.js dashboard (the UI you see in the browser)
```

The heavy video generation stays on your PC. The dashboard and API live in the cloud.

---

### Step 1 — Get your deploy secrets (run once, on your PC)

```bash
python get_deploy_secrets.py
```

This prints two values to copy:
- `YOUTUBE_TOKEN_B64` — your OAuth token encoded as base64
- `TOPIC_CONFIG_JSON` — your topic category config as a single JSON line

Keep this terminal open while you complete steps 2 and 3.

---

### Step 2 — Deploy the API to Render (free)

1. Go to **https://render.com** → sign up free (use GitHub login)

2. Click **New → Web Service**

3. Connect your GitHub repo  
   *(push this project to GitHub first if you haven't — see step below)*

4. Set these in the Render form:

   | Field | Value |
   |-------|-------|
   | Root Directory | *(leave blank)* |
   | Runtime | Python 3 |
   | Build Command | `pip install -r api/requirements.txt` |
   | Start Command | `uvicorn api.main:app --host 0.0.0.0 --port $PORT` |
   | Instance Type | **Free** |

5. Scroll to **Environment Variables** → add these:

   | Key | Value |
   |-----|-------|
   | `YOUTUBE_TOKEN_B64` | *(paste from get_deploy_secrets.py output)* |
   | `TOPIC_CONFIG_JSON` | *(paste from get_deploy_secrets.py output)* |
   | `ANTHROPIC_API_KEY` | *(from your .env file)* |
   | `PEXELS_API_KEY` | *(from your .env file, optional)* |

6. Click **Create Web Service** → wait ~3 minutes for deploy

7. Note your API URL: `https://yt-autoposter-api.onrender.com`

> **Free tier note:** Render spins down after 15 min of no traffic. First request after idle takes ~30 seconds to wake up. Analytics and topic config still work perfectly.

---

### Step 3 — Deploy the dashboard to Vercel (free)

**Option A — Vercel CLI (fastest)**

```bash
# Install Vercel CLI once
npm install -g vercel

# Deploy from the dashboard folder
cd dashboard
vercel

# Follow prompts:
#   Set up and deploy? → Y
#   Which scope? → your account
#   Link to existing project? → N
#   Project name → yt-autoposter-dashboard
#   Directory → ./ (you're already in dashboard/)
```

When asked for environment variables, add:
```
NEXT_PUBLIC_API_URL = https://yt-autoposter-api.onrender.com
```

**Option B — Vercel website**

1. Go to **https://vercel.com** → sign up free
2. Click **Add New → Project**
3. Import your GitHub repo
4. Set **Root Directory** → `dashboard`
5. Add environment variable:
   - `NEXT_PUBLIC_API_URL` = `https://yt-autoposter-api.onrender.com`
6. Click **Deploy**

Your dashboard is live at: `https://yt-autoposter-dashboard.vercel.app`

---

### Step 4 — Push project to GitHub (if needed)

```bash
cd c:\Users\kalki\My_workspace\Py_projects\Py-Projects\youtube-auto-poster

git init
git add .
git commit -m "Initial commit"

# Create repo on github.com first, then:
git remote add origin https://github.com/YOUR_USERNAME/youtube-auto-poster.git
git push -u origin main
```

> Add a `.gitignore` to avoid committing secrets — the file below is already set up correctly.

---

### Step 5 — Keep pipeline running on Windows

The video generation pipeline still runs on your Windows PC as before:

```bash
# Generate videos now
python scheduler.py --now

# Run as daily daemon (2:30 AM IST trigger)
python scheduler.py

# Or install as Windows Task Scheduler job (run as Administrator)
python install_task.py
```

Videos are generated locally → uploaded to YouTube automatically. The Render API provides analytics and topic control from the cloud.

---

### Update your YouTube token on Render

The OAuth token refreshes automatically while Render is running. If it ever expires (e.g., after a long downtime):

```bash
# Re-run locally
python setup_auth.py

# Get new base64 value
python get_deploy_secrets.py

# Paste new YOUTUBE_TOKEN_B64 in Render → Environment → redeploy
```

---

### Summary of free URLs

| Service | URL | Cost |
|---------|-----|------|
| Dashboard | `https://your-app.vercel.app` | Free forever |
| API | `https://your-api.onrender.com` | Free (sleeps after 15 min idle) |
| Pipeline | Runs on your Windows PC | Free |

---

## API Endpoints (port 8000)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/status` | Pipeline status, today's video count |
| GET | `/api/analytics` | YouTube channel + recent video stats |
| GET | `/api/topic-config` | Category assignments per slot |
| PUT | `/api/topic-config` | Save category assignments |
| GET | `/api/videos` | Today's generated videos |
| POST | `/api/run` | Trigger pipeline immediately |
| GET | `/api/logs?lines=N` | Last N log lines |
| GET | `/api/settings` | Current config values |
| POST | `/api/settings` | Save config values |
| WS | `/ws/logs` | Real-time log stream |
| GET | `/api/videos/{date}/{n}/thumbnail` | Serve thumbnail image |
| GET | `/api/videos/{date}/{n}/video` | Serve video file |
| GET | `/api/videos/{date}/{n}/script` | Serve script JSON |
