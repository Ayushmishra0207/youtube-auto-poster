"""
Cloud implementations of the dashboard endpoints (active when DATABASE_URL is set).

Generation happens on GitHub Actions, so the Render API never has the files:
lists come from the Supabase index (pipeline.media_store), media is served via
short-lived Supabase signed URLs, and the action buttons start workflow runs.
Responses keep exactly the local endpoints' shapes, so the dashboard is unchanged.
"""
from __future__ import annotations

from fastapi import HTTPException
from fastapi.responses import RedirectResponse

from api import github_actions as gha
from pipeline import media_store


def _yt_url(kind: str, vid: str) -> str:
    if not vid:
        return ""
    return f"https://youtube.com/shorts/{vid}" if kind == "short" else f"https://youtube.com/watch?v={vid}"


def list_items(kind: str, date: str, upload_slots: list[str]) -> list[dict]:
    route = "videos" if kind == "video" else "shorts"
    out = []
    for it in media_store.list_items(date, kind):
        n = it["index"]
        regen_task = "regenerate_video" if kind == "video" else "regenerate_short"
        regenerating = any(r["title"].startswith(f"{regen_task} ") and f'"date":"{date}"' in r["title"]
                           and f'"index":{n}' in r["title"] for r in gha.active_runs())
        entry = {
            "index": n,
            "dir": f"{kind}_{n:02d}",
            "date": date,
            "title": it.get("title", ""),
            "description": it.get("description", ""),
            "tags": it.get("tags", []),
            "status": it.get("status", "pending"),
            "has_video": bool(it.get("preview_key")),
            "has_thumbnail": bool(it.get("thumb_key")),
            "has_script": bool(it.get("script")),
            "thumbnail_url": f"/api/{route}/{date}/{n}/thumbnail",
            "video_url": f"/api/{route}/{date}/{n}/video",
            "script_url": f"/api/{route}/{date}/{n}/script",
            "youtube_id": it.get("youtube_id", ""),
            "youtube_url": _yt_url(kind, it.get("youtube_id", "")),
            "is_regenerating": regenerating,
        }
        if kind == "video":
            entry.update({
                "title_english": it.get("title_english", ""),
                "thumbnail_text": it.get("thumbnail_text", ""),
                "slot": it.get("slot") or (upload_slots[n - 1] if n <= len(upload_slots) else "—"),
            })
        out.append(entry)
    return out


def media_redirect(kind: str, date: str, index: int, which: str) -> RedirectResponse:
    it = media_store.get_item(date, kind, index)
    key = (it or {}).get("thumb_key" if which == "thumbnail" else "preview_key")
    if not key:
        raise HTTPException(404, f"{which.capitalize()} not found")
    try:
        url = media_store.signed_url(key, expires_s=3600)
    except Exception as exc:
        raise HTTPException(502, f"Storage error: {exc}")
    return RedirectResponse(url, status_code=307)


def script(kind: str, date: str, index: int) -> dict:
    it = media_store.get_item(date, kind, index)
    if not it or not it.get("script"):
        raise HTTPException(404, "Script not found")
    return it["script"]


def start(task: str, args: dict, busy_message: str) -> dict:
    if gha.is_active(task, args) or (task == "pipeline" and gha.is_active("pipeline")):
        return {"ok": False, "message": busy_message}
    try:
        gha.dispatch(task, args)
    except gha.DispatchError as exc:
        return {"ok": False, "message": str(exc)}
    return {"ok": True, "message": "Started on GitHub Actions — it shows up here in a minute or two.",
            "runs_url": gha.runs_page_url()}


def upload(kind: str, date: str, index: int) -> dict:
    it = media_store.get_item(date, kind, index)
    if not it:
        raise HTTPException(404, f"{kind.capitalize()} not found")
    if it.get("youtube_id"):
        vid = it["youtube_id"]
        return {"ok": True, "video_id": vid, "url": _yt_url(kind, vid), "already": True}
    res = start("upload", {"date": date, "kind": kind, "index": index},
                "This upload is already running on GitHub Actions.")
    if not res["ok"]:
        raise HTTPException(409, res["message"])
    # 202-style answer: the dashboard shows a "started" note instead of a YouTube link
    return {"ok": True, "queued": True, "video_id": "", "url": "", "message": res["message"]}


def pipeline_running() -> bool:
    return any(r["title"].startswith("pipeline") for r in gha.active_runs())


def short_generating() -> bool:
    return any(r["title"].startswith(("generate_short ", "regenerate_short ")) for r in gha.active_runs())


def log_lines() -> list[str]:
    runs = gha.active_runs()
    lines = ["[cloud] Videos are generated on GitHub Actions — full logs: " + (gha.runs_page_url() or "(GITHUB_REPO not set)")]
    lines += [f"[cloud] {r['status']}: {r['title']}  {r['url']}" for r in runs] or ["[cloud] No runs in progress."]
    return lines
