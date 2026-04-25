"""
FastAPI backend for the YouTube Auto-Poster Dashboard.

Endpoints:
  GET  /api/status                          Pipeline running state + today's stats
  GET  /api/videos                          List today's generated videos
  GET  /api/topics                          Current topic list (override or auto)
  POST /api/topics                          Set topic overrides
  DELETE /api/topics                        Clear topic overrides
  GET  /api/topic-config                    Get category config for all 7 slots
  PUT  /api/topic-config                    Save category config
  GET  /api/analytics                       YouTube channel + recent video stats
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
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

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
UPLOAD_SLOTS = ["18:30", "18:40", "18:50", "19:00", "19:10", "19:20", "19:30"]

_pipeline_proc: Optional[subprocess.Popen] = None

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Helpers ────────────────────────────────────────────────────────────────────

def _today() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")

def _video_dir(date: str, index: int) -> Path:
    return OUTPUT_DIR / date / f"video_{index:02d}"

def _pipeline_running() -> bool:
    global _pipeline_proc
    return _pipeline_proc is not None and _pipeline_proc.poll() is None

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

def _load_topic_config() -> dict:
    # Cloud: seed from env var on first boot if file doesn't exist
    if not TOPIC_CONFIG.exists():
        seed = os.environ.get("TOPIC_CONFIG_JSON", "")
        if seed:
            TOPIC_CONFIG.write_text(seed, encoding="utf-8")
    if TOPIC_CONFIG.exists():
        return json.loads(TOPIC_CONFIG.read_text(encoding="utf-8"))
    return {"slots": [], "categories": {}}

def _get_youtube_service():
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

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
    return build("youtube", "v3", credentials=creds)


# ── Status ─────────────────────────────────────────────────────────────────────

@app.get("/api/status")
async def status():
    today_dir = OUTPUT_DIR / _today()
    video_count = len(list(today_dir.glob("video_*"))) if today_dir.exists() else 0
    last_log = _tail_log(1)
    lock_file = BASE_DIR / "pipeline.lock"
    is_running = _pipeline_running() or lock_file.exists()
    return {
        "is_running": is_running,
        "today_date": _today(),
        "today_video_count": video_count,
        "total_slots": len(UPLOAD_SLOTS),
        "next_scheduled_run": "14:30 IST",
        "upload_window": "18:30 – 19:30 IST",
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
            })
    return {"date": target, "videos": videos}


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
        media = MediaFileUpload(tmp_video, mimetype="video/mp4", resumable=True,
                                chunksize=10 * 1024 * 1024)
        req = svc.videos().insert(part="snippet,status", body=body, media_body=media)

        response = None
        while response is None:
            _, response = req.next_chunk()

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

    if script_path.exists():
        try:
            s = json.loads(script_path.read_text(encoding="utf-8"))
            title       = s.get("title", title)[:100]
            description = s.get("description", "")[:5000]
            tags        = [str(t)[:500] for t in s.get("tags", [])[:500]]
            category_id = "25"
        except Exception:
            pass

    try:
        svc = _get_youtube_service()

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

        from googleapiclient.http import MediaFileUpload
        media = MediaFileUpload(
            str(video_path), mimetype="video/mp4",
            resumable=True, chunksize=10 * 1024 * 1024,
        )
        req = svc.videos().insert(part="snippet,status", body=body, media_body=media)

        response = None
        while response is None:
            _, response = req.next_chunk()

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
                pass

        return {
            "ok": True,
            "video_id": video_id,
            "url": f"https://youtube.com/watch?v={video_id}",
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Upload failed: {e}")


# ── Pipeline trigger ────────────────────────────────────────────────────────────

@app.post("/api/run")
async def run_pipeline():
    global _pipeline_proc

    # Render sets RENDER=true automatically — pipeline cannot run in cloud
    if os.environ.get("RENDER"):
        return {
            "ok": False,
            "cloud_mode": True,
            "message": "Pipeline runs on your local Windows PC. Run 'python scheduler.py --now' locally.",
        }

    if _pipeline_running():
        return {"ok": False, "message": "Pipeline is already running"}

    _pipeline_proc = subprocess.Popen(
        [PYTHON, str(BASE_DIR / "scheduler.py"), "--now"],
        cwd=str(BASE_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {"ok": True, "pid": _pipeline_proc.pid, "message": "Pipeline started"}


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
        "upload_slots": UPLOAD_SLOTS,
    }

@app.post("/api/settings")
async def save_settings(payload: SettingsPayload):
    updates = {k: v for k, v in payload.model_dump().items() if v is not None and v != "***"}
    if updates:
        _write_env(updates)
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


# ── WebSocket log stream ────────────────────────────────────────────────────────

@app.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket):
    """Stream new lines from pipeline.log in real time."""
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
