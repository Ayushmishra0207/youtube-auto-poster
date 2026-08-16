"""
FastAPI backend for the YouTube Auto-Poster Dashboard.

Endpoints:
  GET  /api/status                          Pipeline running state + today's stats
  GET  /api/videos                          List today's generated videos
  POST /api/videos/{date}/{n}/regenerate    Regenerate one video slot in place
  POST /api/shorts/{date}/{n}/regenerate    Regenerate one Short in place
  GET  /api/locales                         Country/continent targets, grouped by continent
  POST /api/shorts/generate                 Generate Short(s); locale + count for batch regional generation
  GET  /api/community-posts                 Draft Community-post captions (copy into YouTube Studio yourself)
  POST /api/community-posts/{id}/dismiss    Remove a draft from the queue
  POST /api/community-posts/generate        Force an engagement pass (auto-comments + draft top-up) now
  GET  /api/topics                          Current topic list (override or auto)
  POST /api/topics                          Set topic overrides
  DELETE /api/topics                        Clear topic overrides
  GET  /api/topic-config                    Get category config for all 8 slots
  PUT  /api/topic-config                    Save category config
  GET  /api/analytics                       YouTube channel + recent video stats
  GET  /api/monetization                    Real progress toward YPP eligibility (standard + Shorts paths)
  POST /api/run                             Trigger scheduler.py --now
  GET  /api/logs?lines=N                    Last N log lines
  WS   /ws/logs                             Real-time log stream (new lines only)
  GET  /api/videos/{date}/{n}/thumbnail     Serve thumbnail JPEG
  GET  /api/videos/{date}/{n}/video         Serve MP4
  GET  /api/videos/{date}/{n}/script        Serve script JSON
  GET  /api/settings                        Read editable config values
  POST /api/settings                        Persist config overrides to .env

Run with:
  uvicorn api.main:app --reload --port 8000
"""
import asyncio
import base64
import json
import os
import pickle
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

import auth as auth_module
from config import ENGAGEMENT_POLL_SECONDS, INSTAGRAM_POLL_SECONDS, UPLOAD_SLOTS_IST
from db import init_db
from pipeline.accounts import load_accounts, get_account, set_account_enabled, add_account
from pipeline.locales import DEFAULT_LOCALE, LOCALES, locales_by_continent
from pipeline.logger import log
from pipeline.shorts_config import load_shorts_config, save_shorts_config

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR         = Path(__file__).parent.parent
OUTPUT_DIR       = BASE_DIR / "output"
LOG_FILE         = BASE_DIR / "logs" / "pipeline.log"
ENV_FILE         = BASE_DIR / ".env"
TOPICS_FILE      = BASE_DIR / "topics_override.json"
TOPIC_CONFIG     = BASE_DIR / "topic_config.json"
TOKEN_FILE       = BASE_DIR / "youtube_token.pickle"
PYTHON           = sys.executable

IST = timezone(timedelta(hours=5, minutes=30))
UPLOAD_SLOTS = UPLOAD_SLOTS_IST

_pipeline_proc: Optional[subprocess.Popen] = None
_short_proc: Optional[subprocess.Popen] = None
SHORT_LOCK_FILE = BASE_DIR / "short_generate.lock"

# Per-item regenerate subprocesses, keyed by "video:{date}:{index}" / "short:{date}:{index}"
_regen_procs: dict[str, subprocess.Popen] = {}


def _regen_key(kind: str, date: str, index: int) -> str:
    return f"{kind}:{date}:{index}"


def _regen_running(key: str) -> bool:
    proc = _regen_procs.get(key)
    return proc is not None and proc.poll() is None

# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(title="YouTube Auto-Poster API", version="2.0.0")

_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
# Allow Vercel/custom frontend domain via env var (set in Render)
_frontend_url = os.environ.get("FRONTEND_URL", "")
if _frontend_url:
    _ALLOWED_ORIGINS.append(_frontend_url.rstrip("/"))

# ── Auth ───────────────────────────────────────────────────────────────────────
# Small trusted user base (created via create_user.py, no public signup).
# Session token via "Authorization: Bearer <token>" header, or a "token"
# query param as a fallback for plain <img>/<video> tags that can't set
# custom headers.
_PUBLIC_PATHS = {"/api/auth/login", "/docs", "/openapi.json", "/redoc"}


@app.on_event("startup")
async def _startup():
    init_db()
    admin_username = os.environ.get("ADMIN_USERNAME", "")
    admin_password = os.environ.get("ADMIN_PASSWORD", "")
    if admin_username and admin_password:
        auth_module.ensure_user(admin_username, admin_password)
        log.info(f"Bootstrapped admin user '{admin_username}' from env vars")
    asyncio.create_task(_engagement_loop())
    asyncio.create_task(_instagram_loop())


async def _engagement_loop():
    """Background poll loop: auto-comment CTAs on new uploads + top up the
    Community-post draft queue. See pipeline/engagement.py for the actual work."""
    from pipeline.engagement import run_engagement_pass
    while True:
        try:
            result = await asyncio.to_thread(run_engagement_pass)
            if result["posted_comments"] or result["draft_count"]:
                log.info("Engagement pass: %s", result)
        except Exception as exc:
            log.error("Engagement pass failed: %s", exc, exc_info=True)
        await asyncio.sleep(ENGAGEMENT_POLL_SECONDS)


async def _instagram_loop():
    """Background poll loop: publish queued Instagram Reels once their
    scheduled time arrives. See pipeline/instagram_queue.py for the actual
    work — this loop just ticks it on a timer, same shape as _engagement_loop."""
    from pipeline.instagram_queue import run_pending_posts
    while True:
        try:
            result = await asyncio.to_thread(run_pending_posts)
            if result["posted"] or result["failed"]:
                log.info("Instagram pass: %s", result)
        except Exception as exc:
            log.error("Instagram pass failed: %s", exc, exc_info=True)
        await asyncio.sleep(INSTAGRAM_POLL_SECONDS)


app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _session_token_from_request(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[len("Bearer "):].strip()
    return request.query_params.get("token", "")


_VERCEL_ORIGIN_RE = re.compile(r"https://.*\.vercel\.app")


def _cors_headers_for(request: Request) -> dict[str, str]:
    """
    Manually mirror CORSMiddleware's Access-Control-Allow-Origin logic onto
    a response built directly here, instead of via `return await
    call_next(...)`. CORSMiddleware only patches headers onto responses that
    flow back through its own wrapped `send` — but `@app.middleware("http")`
    (BaseHTTPMiddleware) sits between it and this function in a way that,
    confirmed live, drops the header specifically on the early-return 401
    path (an OPTIONS preflight to the deployed API got the header correctly;
    the real GET request's 401 response, from the same origin, did not).
    Since every unauthenticated request hits this exact path — it's the
    first thing that happens before a token exists — the fix has to attach
    the header here directly rather than rely on the outer middleware.
    """
    origin = request.headers.get("origin", "")
    if origin and (origin in _ALLOWED_ORIGINS or _VERCEL_ORIGIN_RE.fullmatch(origin)):
        return {"Access-Control-Allow-Origin": origin, "Access-Control-Allow-Credentials": "true", "Vary": "Origin"}
    return {}


@app.middleware("http")
async def _require_auth(request: Request, call_next):
    if request.method == "OPTIONS" or request.url.path in _PUBLIC_PATHS:
        return await call_next(request)

    token = _session_token_from_request(request)
    user = auth_module.get_user_for_session(token)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"},
                            headers=_cors_headers_for(request))

    request.state.user = user
    return await call_next(request)


class LoginPayload(BaseModel):
    username: str
    password: str

@app.post("/api/auth/login")
async def login(payload: LoginPayload):
    user_id = auth_module.verify_user(payload.username, payload.password)
    if not user_id:
        raise HTTPException(401, "Invalid username or password")
    token = auth_module.create_session(user_id)
    return {"token": token, "username": payload.username}

@app.post("/api/auth/logout")
async def logout(request: Request):
    auth_module.delete_session(_session_token_from_request(request))
    return {"ok": True}

@app.get("/api/auth/me")
async def me(request: Request):
    return {"user": request.state.user}

# ── Helpers ────────────────────────────────────────────────────────────────────

def _today() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")

def _video_dir(date: str, index: int) -> Path:
    return OUTPUT_DIR / date / f"video_{index:02d}"

def _pipeline_running() -> bool:
    global _pipeline_proc
    return _pipeline_proc is not None and _pipeline_proc.poll() is None

def _lock_pid_alive() -> bool:
    """True only if pipeline.lock exists AND its PID is a live process.
    A stale lock (dead PID) must not make the dashboard show 'Running' forever."""
    lock_file = BASE_DIR / "pipeline.lock"
    if not lock_file.exists():
        return False
    try:
        pid = int(lock_file.read_text().strip())
        r = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True, text=True, timeout=10,
        )
        return str(pid) in r.stdout
    except Exception:
        return False

def _read_env() -> dict:
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env

def _write_env(data: dict):
    existing = _read_env()
    existing.update(data)
    ENV_FILE.write_text("\n".join(f"{k}={v}" for k, v in existing.items()) + "\n", encoding="utf-8")

def _tail_log(n: int = 100) -> list[str]:
    if not LOG_FILE.exists():
        return []
    lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-n:]

def _video_status(vdir: Path) -> str:
    if (vdir / "youtube_id.txt").exists():  return "uploaded"
    if (vdir / "final.mp4").exists():       return "ready"
    if (vdir / "thumbnail.jpg").exists():   return "rendering"
    if any(vdir.glob("voices/*.mp3")):      return "generating"
    return "pending"

def _short_status(sdir: Path) -> str:
    if (sdir / "youtube_id.txt").exists(): return "uploaded"
    if (sdir / "short.mp4").exists():      return "ready"
    if (sdir / "script.json").exists():    return "generating"
    return "pending"

def _short_proc_running() -> bool:
    global _short_proc
    return _short_proc is not None and _short_proc.poll() is None

def _short_lock_pid_alive() -> bool:
    if not SHORT_LOCK_FILE.exists():
        return False
    try:
        pid = int(SHORT_LOCK_FILE.read_text().strip())
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True, timeout=10)
        return str(pid) in r.stdout
    except Exception:
        return False

def _load_topic_config() -> dict:
    # Cloud: seed from env var on first boot if file doesn't exist
    if not TOPIC_CONFIG.exists():
        seed = os.environ.get("TOPIC_CONFIG_JSON", "")
        if seed:
            TOPIC_CONFIG.write_text(seed, encoding="utf-8")
    if TOPIC_CONFIG.exists():
        return json.loads(TOPIC_CONFIG.read_text(encoding="utf-8"))
    return {"slots": [], "categories": {}}

def _get_youtube_credentials():
    from google.auth.transport.requests import Request

    # Cloud deployment: load token from YOUTUBE_TOKEN_B64 env var if file absent
    if not TOKEN_FILE.exists():
        token_b64 = os.environ.get("YOUTUBE_TOKEN_B64", "")
        if not token_b64:
            raise HTTPException(503, "YouTube token not found. Set YOUTUBE_TOKEN_B64 env var or run setup_auth.py locally.")
        TOKEN_FILE.write_bytes(base64.b64decode(token_b64))

    with open(TOKEN_FILE, "rb") as f:
        creds = pickle.load(f)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)
    return creds

def _get_youtube_service():
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=_get_youtube_credentials())

def _get_analytics_service():
    from googleapiclient.discovery import build
    return build("youtubeAnalytics", "v2", credentials=_get_youtube_credentials())


# ── Status ─────────────────────────────────────────────────────────────────────

@app.get("/api/status")
async def status():
    today_dir = OUTPUT_DIR / _today()
    video_count = len(list(today_dir.glob("video_*"))) if today_dir.exists() else 0
    last_log = _tail_log(1)
    is_running = _pipeline_running() or _lock_pid_alive()
    return {
        "is_running": is_running,
        "today_date": _today(),
        "today_video_count": video_count,
        "total_slots": len(UPLOAD_SLOTS),
        "next_scheduled_run": "14:30 IST",
        "upload_window": f"{UPLOAD_SLOTS[0]} – {UPLOAD_SLOTS[-1]} IST",
        "last_log": last_log[0] if last_log else "",
    }


# ── Videos ─────────────────────────────────────────────────────────────────────

@app.get("/api/videos")
async def list_videos(date: Optional[str] = None):
    target = date or _today()
    today_dir = OUTPUT_DIR / target
    videos = []
    if today_dir.exists():
        dirs = sorted(d for d in today_dir.iterdir() if d.is_dir() and d.name.startswith("video_"))
        for i, vdir in enumerate(dirs):
            script_path = vdir / "script.json"
            title = vdir.name
            title_english = description = thumbnail_text = ""
            tags: list = []
            if script_path.exists():
                try:
                    s = json.loads(script_path.read_text(encoding="utf-8"))
                    title = s.get("title", title)
                    title_english = s.get("title_english", "")
                    description = s.get("description", "")
                    tags = s.get("tags", [])
                    thumbnail_text = s.get("thumbnail_text", "")
                except Exception:
                    pass
            slot = UPLOAD_SLOTS[i] if i < len(UPLOAD_SLOTS) else "—"
            yt_id_path = vdir / "youtube_id.txt"
            yt_id  = yt_id_path.read_text().strip() if yt_id_path.exists() else ""
            yt_url = f"https://youtube.com/watch?v={yt_id}" if yt_id else ""
            videos.append({
                "index": i + 1,
                "dir": vdir.name,
                "date": target,
                "title": title,
                "title_english": title_english,
                "description": description,
                "tags": tags,
                "thumbnail_text": thumbnail_text,
                "slot": slot,
                "status": _video_status(vdir),
                "has_video": (vdir / "final.mp4").exists(),
                "has_thumbnail": (vdir / "thumbnail.jpg").exists(),
                "has_script": script_path.exists(),
                "thumbnail_url": f"/api/videos/{target}/{i+1}/thumbnail",
                "video_url": f"/api/videos/{target}/{i+1}/video",
                "script_url": f"/api/videos/{target}/{i+1}/script",
                "youtube_id": yt_id,
                "youtube_url": yt_url,
                "is_regenerating": _regen_running(_regen_key("video", target, i + 1)),
            })
    return {"date": target, "videos": videos}


class RegenerateVideoPayload(BaseModel):
    locale: str = ""  # optional override; empty = keep the slot's configured locale

@app.post("/api/videos/{date}/{index}/regenerate")
async def regenerate_video(date: str, index: int, payload: RegenerateVideoPayload = RegenerateVideoPayload()):
    """Regenerate an existing video slot in place (new script/voice/images/render, no auto-upload)."""
    key = _regen_key("video", date, index)
    if _regen_running(key) or _pipeline_running() or _lock_pid_alive():
        return {"ok": False, "message": "A video generation/regeneration is already in progress"}

    args = [PYTHON, str(BASE_DIR / "regenerate_video.py"), "--date", date, "--index", str(index)]
    if payload.locale.strip():
        if payload.locale not in LOCALES:
            raise HTTPException(400, f"Unknown locale '{payload.locale}'")
        args += ["--locale", payload.locale]

    proc = subprocess.Popen(
        args,
        cwd=str(BASE_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _regen_procs[key] = proc
    return {"ok": True, "pid": proc.pid, "message": f"Regenerating video {index}"}


# ── Locales (country/continent targeting) ──────────────────────────────────────

@app.get("/api/locales")
async def get_locales():
    """Locales grouped by continent, for the region/continent picker UI."""
    grouped = locales_by_continent()
    return {
        "default": DEFAULT_LOCALE,
        "continents": {
            continent: [
                {
                    "code": loc.code,
                    "label": loc.label,
                    "language_name": loc.language_name,
                    "script": loc.script,
                }
                for loc in locs
            ]
            for continent, locs in grouped.items()
        },
    }


# ── Topics (manual override) ────────────────────────────────────────────────────

@app.get("/api/topics")
async def get_topics():
    if TOPICS_FILE.exists():
        try:
            return {"topics": json.loads(TOPICS_FILE.read_text(encoding="utf-8")), "source": "override"}
        except Exception:
            pass
    return {"topics": [], "source": "auto"}

class TopicsPayload(BaseModel):
    topics: list[str]

@app.post("/api/topics")
async def set_topics(payload: TopicsPayload):
    TOPICS_FILE.write_text(json.dumps(payload.topics, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "topics": payload.topics}

@app.delete("/api/topics")
async def clear_topics():
    if TOPICS_FILE.exists():
        TOPICS_FILE.unlink()
    return {"ok": True, "source": "auto"}


# ── Topic Config (category-based control) ──────────────────────────────────────

@app.get("/api/topic-config")
async def get_topic_config():
    return _load_topic_config()

class TopicConfigSlot(BaseModel):
    slot: str
    category: str
    custom_topic: Optional[str] = None
    locale: Optional[str] = None  # country/continent target for this slot; None = default (hi)

class TopicConfigPayload(BaseModel):
    slots: list[TopicConfigSlot]

@app.put("/api/topic-config")
async def save_topic_config(payload: TopicConfigPayload):
    config = _load_topic_config()
    config["slots"] = [s.model_dump() for s in payload.slots]
    TOPIC_CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True}


# ── Analytics ──────────────────────────────────────────────────────────────────

@app.get("/api/analytics")
async def get_analytics():
    """YouTube channel stats + recent video metrics using saved OAuth token."""
    try:
        svc = _get_youtube_service()

        ch_resp = svc.channels().list(
            part="snippet,statistics,contentDetails",
            mine=True,
        ).execute()

        if not ch_resp.get("items"):
            raise HTTPException(404, "No YouTube channel found for this account")

        ch = ch_resp["items"][0]
        stats = ch["statistics"]

        channel_info = {
            "id": ch["id"],
            "title": ch["snippet"]["title"],
            "description": ch["snippet"].get("description", "")[:200],
            "thumbnail": ch["snippet"]["thumbnails"].get("default", {}).get("url", ""),
            "subscribers": int(stats.get("subscriberCount", 0)),
            "total_views": int(stats.get("viewCount", 0)),
            "video_count": int(stats.get("videoCount", 0)),
            "hidden_subscribers": stats.get("hiddenSubscriberCount", False),
        }

        # Recent uploads via search API
        search_resp = svc.search().list(
            part="snippet",
            forMine=True,
            type="video",
            order="date",
            maxResults=20,
        ).execute()

        video_ids = [item["id"]["videoId"] for item in search_resp.get("items", [])]

        recent_videos = []
        if video_ids:
            vid_resp = svc.videos().list(
                part="snippet,statistics,status",
                id=",".join(video_ids),
            ).execute()
            for item in vid_resp.get("items", []):
                snip = item["snippet"]
                vstats = item.get("statistics", {})
                recent_videos.append({
                    "id": item["id"],
                    "title": snip["title"],
                    "published_at": snip["publishedAt"],
                    "thumbnail": snip["thumbnails"].get("medium", {}).get("url", ""),
                    "views": int(vstats.get("viewCount", 0)),
                    "likes": int(vstats.get("likeCount", 0)),
                    "comments": int(vstats.get("commentCount", 0)),
                    "privacy": item.get("status", {}).get("privacyStatus", "unknown"),
                    "url": f"https://youtube.com/watch?v={item['id']}",
                })

        return {"channel": channel_info, "recent_videos": recent_videos}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"YouTube API error: {e}")


_STANDARD_SUBS_TARGET  = 1000
_STANDARD_HOURS_TARGET = 4000
_SHORTS_SUBS_TARGET    = 1000
_SHORTS_VIEWS_TARGET   = 10_000_000

@app.get("/api/monetization")
async def get_monetization_progress():
    """
    Real progress toward YouTube Partner Program eligibility, both paths:
      - Standard: 1,000 subscribers + 4,000 public watch hours (last 365 days)
      - Shorts:   1,000 subscribers + 10,000,000 public Shorts views (last 90 days)
    Requires the yt-analytics.readonly scope — re-run setup_auth.py once if
    the saved token predates it (it auto-detects and forces re-consent).
    """
    try:
        yt_svc = _get_youtube_service()
        ch_resp = yt_svc.channels().list(part="statistics", mine=True).execute()
        if not ch_resp.get("items"):
            raise HTTPException(404, "No YouTube channel found for this account")
        subscribers = int(ch_resp["items"][0]["statistics"].get("subscriberCount", 0))

        analytics_svc = _get_analytics_service()
        today = datetime.now(IST).date()

        watch_resp = analytics_svc.reports().query(
            ids="channel==MINE",
            startDate=(today - timedelta(days=365)).isoformat(),
            endDate=today.isoformat(),
            metrics="estimatedMinutesWatched",
        ).execute()
        watch_rows = watch_resp.get("rows") or []
        watch_hours = (watch_rows[0][0] if watch_rows else 0) / 60.0

        shorts_resp = analytics_svc.reports().query(
            ids="channel==MINE",
            startDate=(today - timedelta(days=90)).isoformat(),
            endDate=today.isoformat(),
            metrics="views",
            filters="creatorContentType==shorts",
        ).execute()
        shorts_rows = shorts_resp.get("rows") or []
        shorts_views = shorts_rows[0][0] if shorts_rows else 0

        subs_pct        = min(100.0, subscribers / _STANDARD_SUBS_TARGET * 100)
        hours_pct       = min(100.0, watch_hours / _STANDARD_HOURS_TARGET * 100)
        shorts_subs_pct = min(100.0, subscribers / _SHORTS_SUBS_TARGET * 100)
        views_pct       = min(100.0, shorts_views / _SHORTS_VIEWS_TARGET * 100)

        standard_overall = min(subs_pct, hours_pct)
        shorts_overall   = min(shorts_subs_pct, views_pct)

        return {
            "subscribers": subscribers,
            "watch_hours_365d": round(watch_hours, 1),
            "shorts_views_90d": shorts_views,
            "standard_path": {
                "subs_target": _STANDARD_SUBS_TARGET,
                "hours_target": _STANDARD_HOURS_TARGET,
                "subs_pct": round(subs_pct, 1),
                "hours_pct": round(hours_pct, 1),
                "overall_pct": round(standard_overall, 1),
            },
            "shorts_path": {
                "subs_target": _SHORTS_SUBS_TARGET,
                "views_target": _SHORTS_VIEWS_TARGET,
                "subs_pct": round(shorts_subs_pct, 1),
                "views_pct": round(views_pct, 1),
                "overall_pct": round(shorts_overall, 1),
            },
            "recommended_path": "shorts" if shorts_overall >= standard_overall else "standard",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"YouTube Analytics API error: {e}")


# ── Manual Upload ──────────────────────────────────────────────────────────────

@app.post("/api/upload")
async def manual_upload(
    video:         UploadFile        = File(...),
    title:         str               = Form(...),
    description:   str               = Form(""),
    tags:          str               = Form(""),
    category_id:   str               = Form("25"),
    privacy:       str               = Form("public"),
    schedule_time: Optional[str]     = Form(None),
    thumbnail:     Optional[UploadFile] = File(None),
):
    """Upload a video file directly to YouTube with metadata."""
    tmp_video = None
    tmp_thumb = None
    try:
        svc = _get_youtube_service()

        # Stream video to a temp file (avoids loading entire file into RAM)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as f:
            shutil.copyfileobj(video.file, f)
            tmp_video = f.name

        tag_list = [t.strip() for t in tags.split(",") if t.strip()]

        body: dict = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tag_list,
                "categoryId": category_id,
                "defaultLanguage": "hi",
            },
            "status": {
                "privacyStatus": "private" if schedule_time else privacy,
                "selfDeclaredMadeForKids": False,
            },
        }
        if schedule_time:
            body["status"]["publishAt"] = schedule_time

        from googleapiclient.http import MediaFileUpload

        def _do_upload() -> dict:
            """Blocking upload — runs in a worker thread so the event loop stays free."""
            media = MediaFileUpload(tmp_video, mimetype="video/mp4", resumable=True,
                                    chunksize=10 * 1024 * 1024)
            req = svc.videos().insert(part="snippet,status", body=body, media_body=media)
            response = None
            while response is None:
                # retries transient socket / 5xx errors with exponential backoff
                _, response = req.next_chunk(num_retries=5)
            return response

        response = await asyncio.to_thread(_do_upload)
        video_id = response["id"]

        # Optional thumbnail
        if thumbnail:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as f:
                shutil.copyfileobj(thumbnail.file, f)
                tmp_thumb = f.name
            try:
                svc.thumbnails().set(
                    videoId=video_id,
                    media_body=MediaFileUpload(tmp_thumb, mimetype="image/jpeg"),
                ).execute()
            except Exception:
                pass  # thumbnail upload non-critical

        return {
            "ok": True,
            "video_id": video_id,
            "url": f"https://youtube.com/watch?v={video_id}",
            "studio_url": f"https://studio.youtube.com/video/{video_id}/edit",
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Upload failed: {e}")
    finally:
        if tmp_video and os.path.exists(tmp_video):
            os.unlink(tmp_video)
        if tmp_thumb and os.path.exists(tmp_thumb):
            os.unlink(tmp_thumb)


# ── Upload a pipeline-generated video to YouTube ───────────────────────────────

@app.post("/api/upload-generated/{date}/{index}")
async def upload_generated_video(date: str, index: int):
    """Upload an already-generated pipeline video to YouTube."""
    vdir       = _video_dir(date, index)
    video_path = vdir / "final.mp4"
    thumb_path = vdir / "thumbnail.jpg"
    script_path= vdir / "script.json"
    id_file    = vdir / "youtube_id.txt"

    if not video_path.exists():
        raise HTTPException(404, "Video file not found — generate it first via Run Now.")

    # Read metadata from script.json
    title = f"Hindi Video {index} | {date}"
    description = ""
    tags: list[str] = []
    category_id = "25"
    category_key = ""
    category_label = ""
    script_data: dict = {}

    if script_path.exists():
        try:
            s = json.loads(script_path.read_text(encoding="utf-8"))
            script_data = s
            title       = s.get("title", title)[:100]
            description = s.get("description", "")[:5000]
            tags        = [str(t)[:500] for t in s.get("tags", [])[:500]]
            # Look up this video's real category (e.g. movie_explained -> Film
            # & Animation) instead of hardcoding News & Politics for
            # everything — this endpoint previously ignored the topic
            # category entirely, which is why manually-uploaded videos kept
            # landing in the wrong YouTube category regardless of topic.
            category_key = s.get("_category", "")
            category_info = _load_topic_config().get("categories", {}).get(category_key, {})
            category_id = category_info.get("yt_category_id") or "25"
            category_label = category_info.get("label", category_key)
        except Exception:
            pass

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": category_id,
            "defaultLanguage": "hi",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }

    def _do_upload() -> dict:
        """Blocking upload — runs in a worker thread so the event loop stays free."""
        svc = _get_youtube_service()

        from googleapiclient.http import MediaFileUpload
        media = MediaFileUpload(
            str(video_path), mimetype="video/mp4",
            resumable=True, chunksize=10 * 1024 * 1024,
        )
        req = svc.videos().insert(part="snippet,status", body=body, media_body=media)

        response = None
        while response is None:
            # num_retries: exponential-backoff retries on transient socket /
            # 5xx errors (e.g. WinError 10053 mid-upload)
            _, response = req.next_chunk(num_retries=5)

        video_id = response["id"]
        id_file.write_text(video_id, encoding="utf-8")  # persist for status tracking

        # Thumbnail
        if thumb_path.exists():
            try:
                svc.thumbnails().set(
                    videoId=video_id,
                    media_body=MediaFileUpload(str(thumb_path), mimetype="image/jpeg"),
                ).execute()
            except Exception:
                pass  # thumbnail upload non-critical

        # Playlist (session watch-time lever) + captions (real timed track,
        # beats YouTube's own ASR for TTS-narrated content) — same treatment
        # the daily scheduled pipeline gives every long-form upload.
        from pipeline.uploader import add_video_to_playlist, upload_captions
        from pipeline.video_creator import build_captions_srt
        try:
            add_video_to_playlist(video_id, category_key, category_label)
        except Exception:
            pass
        try:
            sections = script_data.get("sections", [])
            voice_paths = [str(vdir / "voices" / f"voice_{s.get('id', i):02d}.mp3")
                          for i, s in enumerate(sections)]
            srt_text = build_captions_srt(script_data, voice_paths)
            upload_captions(video_id, srt_text, language=script_data.get("_locale", "hi"))
        except Exception:
            pass

        return {
            "ok": True,
            "video_id": video_id,
            "url": f"https://youtube.com/watch?v={video_id}",
        }

    try:
        return await asyncio.to_thread(_do_upload)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Upload failed: {e}")


# ── Pipeline trigger ────────────────────────────────────────────────────────────

@app.post("/api/run")
async def run_pipeline():
    global _pipeline_proc

    if _pipeline_running():
        return {"ok": False, "message": "Pipeline is already running"}

    _pipeline_proc = subprocess.Popen(
        [PYTHON, str(BASE_DIR / "scheduler.py"), "--now"],
        cwd=str(BASE_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {"ok": True, "pid": _pipeline_proc.pid, "message": "Pipeline started"}


# ── YouTube Shorts ───────────────────────────────────────────────────────────────

def _short_dir(date: str, index: int) -> Path:
    return OUTPUT_DIR / date / f"short_{index:02d}"

def _ensure_short_thumbnail(short_dir: Path) -> bool:
    """
    Self-heal: some older Shorts finished rendering short.mp4 but the process
    died/crashed before the final thumbnail-capture step ran, leaving them
    stuck on the generic placeholder forever. If short.mp4 exists but
    thumbnail.jpg doesn't, extract one now (cached to disk — runs once).
    Returns whether a thumbnail exists after this call.
    """
    thumb = short_dir / "thumbnail.jpg"
    if thumb.exists():
        return True
    video = short_dir / "short.mp4"
    if not video.exists():
        return False
    # A render still actively writing this file will always look "invalid"
    # to ffmpeg mid-write — don't hammer it every ~8s poll while it's hot.
    if time.time() - video.stat().st_mtime < 30:
        return False
    try:
        import moviepy as mpe
        from PIL import Image
        clip = mpe.VideoFileClip(str(video))
        frame_t = min(0.5, clip.duration / 2) if clip.duration else 0
        Image.fromarray(clip.get_frame(frame_t)).save(str(thumb), "JPEG", quality=90)
        clip.close()
        return True
    except Exception as e:
        log.warning("Thumbnail self-heal failed for %s: %s", short_dir, e)
        return False

@app.get("/api/shorts")
async def list_shorts(date: Optional[str] = None):
    target = date or _today()
    today_dir = OUTPUT_DIR / target
    shorts = []
    if today_dir.exists():
        dirs = sorted(d for d in today_dir.iterdir() if d.is_dir() and d.name.startswith("short_"))
        for d in dirs:
            index = int(d.name.split("_")[1])
            has_thumbnail = _ensure_short_thumbnail(d)
            script_path = d / "script.json"
            title = d.name
            description = ""
            tags: list = []
            if script_path.exists():
                try:
                    s = json.loads(script_path.read_text(encoding="utf-8"))
                    title = s.get("title", title)
                    description = s.get("description", "")
                    tags = s.get("tags", [])
                except Exception:
                    pass
            yt_id_path = d / "youtube_id.txt"
            yt_id  = yt_id_path.read_text().strip() if yt_id_path.exists() else ""
            yt_url = f"https://youtube.com/watch?v={yt_id}" if yt_id else ""
            shorts.append({
                "index": index,
                "dir": d.name,
                "date": target,
                "title": title,
                "description": description,
                "tags": tags,
                "status": _short_status(d),
                "has_video": (d / "short.mp4").exists(),
                "has_thumbnail": has_thumbnail,
                "has_script": script_path.exists(),
                "thumbnail_url": f"/api/shorts/{target}/{index}/thumbnail",
                "video_url": f"/api/shorts/{target}/{index}/video",
                "script_url": f"/api/shorts/{target}/{index}/script",
                "youtube_id": yt_id,
                "youtube_url": yt_url,
                "is_regenerating": _regen_running(_regen_key("short", target, index)),
            })
    return {
        "date": target,
        "shorts": shorts,
        "is_generating": _short_proc_running() or _short_lock_pid_alive(),
    }

@app.get("/api/shorts/{date}/{index}/thumbnail")
async def serve_short_thumbnail(date: str, index: int):
    short_dir = _short_dir(date, index)
    path = short_dir / "thumbnail.jpg"
    if not path.exists():
        _ensure_short_thumbnail(short_dir)
    if not path.exists():
        raise HTTPException(404, "Thumbnail not found")
    return FileResponse(path, media_type="image/jpeg")

@app.get("/api/shorts/{date}/{index}/video")
async def serve_short_video(date: str, index: int):
    path = _short_dir(date, index) / "short.mp4"
    if not path.exists():
        raise HTTPException(404, "Video not found")
    return FileResponse(path, media_type="video/mp4")

@app.get("/api/shorts/{date}/{index}/script")
async def serve_short_script(date: str, index: int):
    path = _short_dir(date, index) / "script.json"
    if not path.exists():
        raise HTTPException(404, "Script not found")
    return json.loads(path.read_text(encoding="utf-8"))

_SHORT_CONTENT_TYPES = (
    "news", "funny", "story", "short_story", "motivational", "entertainment",
    "bollywood", "history", "imagination", "devotional", "sports", "tech",
    "comedy_skit", "horror_mystery", "books", "poetry",
)

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
    if payload.content_type not in _SHORT_CONTENT_TYPES:
        raise HTTPException(400, f"content_type must be one of: {', '.join(_SHORT_CONTENT_TYPES)}")
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

    _short_proc = subprocess.Popen(
        args,
        cwd=str(BASE_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {"ok": True, "pid": _short_proc.pid,
            "message": f"Generating {count} Short(s) ({payload.locale})" if count > 1 else "Short generation started"}


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
    if payload.content_type not in _SHORT_CONTENT_TYPES:
        raise HTTPException(400, f"content_type must be one of: {', '.join(_SHORT_CONTENT_TYPES)}")
    if payload.locale not in LOCALES:
        raise HTTPException(400, f"Unknown locale '{payload.locale}'")

    args = [PYTHON, str(BASE_DIR / "generate_short_now.py"), "--date", date, "--index", str(index),
            "--locale", payload.locale, "--content-type", payload.content_type or "news"]
    args += ["--topic", topic] if topic else ["--feed", payload.feed]

    proc = subprocess.Popen(
        args,
        cwd=str(BASE_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _regen_procs[key] = proc
    return {"ok": True, "pid": proc.pid, "message": f"Regenerating short {index}"}

@app.post("/api/shorts/upload/{date}/{index}")
async def upload_generated_short(date: str, index: int):
    """Upload an already-generated Short to YouTube as a Short (#Shorts)."""
    sdir       = _short_dir(date, index)
    video_path = sdir / "short.mp4"
    thumb_path = sdir / "thumbnail.jpg"
    script_path= sdir / "script.json"
    id_file    = sdir / "youtube_id.txt"

    if not video_path.exists():
        raise HTTPException(404, "Short video not found — generate it first.")

    title = f"Breaking News Short {index} | {date} #Shorts"
    description = "#Shorts #News #Breaking"
    tags: list[str] = ["shorts", "news", "breaking news"]

    if script_path.exists():
        try:
            s = json.loads(script_path.read_text(encoding="utf-8"))
            title       = s.get("title", title)[:100]
            if "#shorts" not in title.lower():
                title = title[:90] + " #Shorts"
            description = s.get("description", description)[:5000]
            tags        = [str(t)[:500] for t in s.get("tags", tags)[:500]]
        except Exception:
            pass

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "25",
            "defaultLanguage": "hi",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }

    def _do_upload() -> dict:
        svc = _get_youtube_service()
        from googleapiclient.http import MediaFileUpload
        media = MediaFileUpload(
            str(video_path), mimetype="video/mp4",
            resumable=True, chunksize=10 * 1024 * 1024,
        )
        req = svc.videos().insert(part="snippet,status", body=body, media_body=media)

        response = None
        while response is None:
            _, response = req.next_chunk(num_retries=5)

        video_id = response["id"]
        id_file.write_text(video_id, encoding="utf-8")

        if thumb_path.exists():
            try:
                svc.thumbnails().set(
                    videoId=video_id,
                    media_body=MediaFileUpload(str(thumb_path), mimetype="image/jpeg"),
                ).execute()
            except Exception:
                pass

        return {
            "ok": True,
            "video_id": video_id,
            "url": f"https://youtube.com/watch?v={video_id}",
        }

    try:
        return await asyncio.to_thread(_do_upload)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Upload failed: {e}")


# ── Logs ───────────────────────────────────────────────────────────────────────

@app.get("/api/logs")
async def get_logs(lines: int = 150):
    return {"logs": _tail_log(lines)}


# ── Settings ───────────────────────────────────────────────────────────────────

class SettingsPayload(BaseModel):
    ANTHROPIC_API_KEY: Optional[str] = None
    PEXELS_API_KEY: Optional[str] = None
    KEEP_OUTPUT_DAYS: Optional[str] = None
    TTS_VOICE: Optional[str] = None
    TTS_RATE: Optional[str] = None
    TTS_PITCH: Optional[str] = None
    SHORTS_PER_DAY: Optional[str] = None
    INSTAGRAM_APP_ID: Optional[str] = None
    INSTAGRAM_APP_SECRET: Optional[str] = None
    INSTAGRAM_ACCESS_TOKEN: Optional[str] = None
    INSTAGRAM_PAGE_ID: Optional[str] = None
    INSTAGRAM_BUSINESS_ACCOUNT_ID: Optional[str] = None
    R2_ACCOUNT_ID: Optional[str] = None
    R2_ACCESS_KEY_ID: Optional[str] = None
    R2_SECRET_ACCESS_KEY: Optional[str] = None
    R2_BUCKET_NAME: Optional[str] = None

@app.get("/api/settings")
async def get_settings():
    env = _read_env()
    return {
        "ANTHROPIC_API_KEY": "***" if env.get("ANTHROPIC_API_KEY") else "",
        "PEXELS_API_KEY": "***" if env.get("PEXELS_API_KEY") else "",
        "KEEP_OUTPUT_DAYS": env.get("KEEP_OUTPUT_DAYS", "3"),
        "TTS_VOICE": env.get("TTS_VOICE", "hi-IN-MadhurNeural"),
        "TTS_RATE": env.get("TTS_RATE", "-5%"),
        "TTS_PITCH": env.get("TTS_PITCH", "-8Hz"),
        "SHORTS_PER_DAY": env.get("SHORTS_PER_DAY", "5"),
        "INSTAGRAM_APP_ID": env.get("INSTAGRAM_APP_ID", ""),
        "INSTAGRAM_APP_SECRET": "***" if env.get("INSTAGRAM_APP_SECRET") else "",
        "INSTAGRAM_ACCESS_TOKEN": "***" if env.get("INSTAGRAM_ACCESS_TOKEN") else "",
        "INSTAGRAM_PAGE_ID": env.get("INSTAGRAM_PAGE_ID", ""),
        "INSTAGRAM_BUSINESS_ACCOUNT_ID": env.get("INSTAGRAM_BUSINESS_ACCOUNT_ID", ""),
        "R2_ACCOUNT_ID": env.get("R2_ACCOUNT_ID", ""),
        "R2_ACCESS_KEY_ID": "***" if env.get("R2_ACCESS_KEY_ID") else "",
        "R2_SECRET_ACCESS_KEY": "***" if env.get("R2_SECRET_ACCESS_KEY") else "",
        "R2_BUCKET_NAME": env.get("R2_BUCKET_NAME", ""),
        "upload_slots": UPLOAD_SLOTS,
    }

@app.post("/api/settings")
async def save_settings(payload: SettingsPayload):
    updates = {k: v for k, v in payload.model_dump().items() if v is not None and v != "***"}
    if updates:
        _write_env(updates)
    return {"ok": True}


# ── Accounts ───────────────────────────────────────────────────────────────────

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


# ── File serving ───────────────────────────────────────────────────────────────

@app.get("/api/videos/{date}/{index}/thumbnail")
async def serve_thumbnail(date: str, index: int):
    path = _video_dir(date, index) / "thumbnail.jpg"
    if not path.exists():
        raise HTTPException(404, "Thumbnail not found")
    return FileResponse(path, media_type="image/jpeg")

@app.get("/api/videos/{date}/{index}/video")
async def serve_video(date: str, index: int):
    path = _video_dir(date, index) / "final.mp4"
    if not path.exists():
        raise HTTPException(404, "Video not found")
    return FileResponse(path, media_type="video/mp4")

@app.get("/api/videos/{date}/{index}/script")
async def serve_script(date: str, index: int):
    path = _video_dir(date, index) / "script.json"
    if not path.exists():
        raise HTTPException(404, "Script not found")
    return json.loads(path.read_text(encoding="utf-8"))


# ── Community-post drafts + engagement automation ───────────────────────────────
# YouTube's Community tab has no public API, so these drafts are for a human
# to copy into YouTube Studio/the app. The auto-CTA-comment side of this
# feature (which IS real and automated) runs on its own background loop —
# see _engagement_loop() above and pipeline/engagement.py.

@app.get("/api/community-posts")
async def get_community_posts():
    from pipeline.engagement import list_drafts
    return {"drafts": list_drafts()}

@app.post("/api/community-posts/{draft_id}/dismiss")
async def dismiss_community_post(draft_id: str):
    from pipeline.engagement import dismiss_draft
    ok = dismiss_draft(draft_id)
    if not ok:
        raise HTTPException(404, "Draft not found")
    return {"ok": True}

@app.post("/api/community-posts/generate")
async def generate_community_post_now():
    """Force an engagement pass right now instead of waiting for the next poll tick."""
    from pipeline.engagement import run_engagement_pass
    result = await asyncio.to_thread(run_engagement_pass)
    return {"ok": True, **result}


# ── Instagram Reels queue ────────────────────────────────────────────────────
# See _instagram_loop() above and pipeline/instagram_queue.py. Each YouTube
# Short is enqueued automatically (scheduler.py); this section exposes that
# queue's status to the dashboard and allows a manual "run now" / retry.

@app.get("/api/instagram/posts")
async def get_instagram_posts():
    from pipeline.instagram_queue import list_posts
    return {"posts": list_posts()}

@app.post("/api/instagram/posts/{post_id}/retry")
async def retry_instagram_post(post_id: str):
    from pipeline.instagram_queue import retry_post
    ok = retry_post(post_id)
    if not ok:
        raise HTTPException(404, "Post not found or not in a failed state")
    return {"ok": True}

@app.post("/api/instagram/run")
async def run_instagram_now():
    """Force an Instagram publish pass right now instead of waiting for the next poll tick."""
    from pipeline.instagram_queue import run_pending_posts
    result = await asyncio.to_thread(run_pending_posts)
    return {"ok": True, **result}


# ── WebSocket log stream ────────────────────────────────────────────────────────

@app.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket):
    """Stream new lines from pipeline.log in real time."""
    # HTTP middleware doesn't run for websocket connections, so auth is
    # checked here directly. Browsers can't set custom headers on a
    # WebSocket handshake, so the token travels as a query param.
    token = websocket.query_params.get("token", "")
    if not auth_module.get_user_for_session(token):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    try:
        for line in _tail_log(50):
            await websocket.send_text(line)
        if LOG_FILE.exists():
            with open(LOG_FILE, encoding="utf-8", errors="replace") as f:
                f.seek(0, 2)
                while True:
                    line = f.readline()
                    if line:
                        await websocket.send_text(line.rstrip())
                    else:
                        await asyncio.sleep(0.4)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
