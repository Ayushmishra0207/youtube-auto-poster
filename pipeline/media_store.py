"""
Cloud index + storage for generated videos/Shorts (used when DATABASE_URL is set).

Generation runs on throw-away GitHub Actions machines and the API on Render,
so neither can rely on the other's disk:

  media_items (Postgres)     one row per output/<date>/<kind>_<NN>: title, script,
                             status, YouTube id, storage keys, producing run id
  Supabase Storage "media"   thumbnail.jpg + a ≤45 MB preview.mp4 per item
                             (free plan: 50 MB/file, 1 GB total). Shorts fit
                             at full quality; long videos get a 360p preview.
  GitHub Actions artifact    the full-quality long-form MP4 (kept 3 days) for the
                             dashboard's "Upload to YouTube" button.

Locally (no DATABASE_URL) everything here is a no-op and the dashboard reads
output/ directly, exactly as before.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

import db
from pipeline.logger import log

BUCKET = os.environ.get("SUPABASE_BUCKET", "media")
PREVIEW_MAX_BYTES = 45 * 1024 * 1024


def enabled() -> bool:
    return db.is_postgres()


def storage_enabled() -> bool:
    return bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_KEY"))


# ── Supabase Storage (REST) ─────────────────────────────────────────────────────

def _base() -> str:
    return os.environ["SUPABASE_URL"].rstrip("/") + "/storage/v1"


def _headers(extra: dict | None = None) -> dict:
    key = os.environ["SUPABASE_SERVICE_KEY"].strip()
    h = {"apikey": key}
    if key.startswith("eyJ"):            # legacy service_role JWT; new sb_secret_ keys go in apikey only
        h["Authorization"] = f"Bearer {key}"
    if extra:
        h.update(extra)
    return h


_bucket_checked = False


def _ensure_bucket() -> None:
    global _bucket_checked
    if _bucket_checked:
        return
    r = requests.get(f"{_base()}/bucket/{BUCKET}", headers=_headers(), timeout=30)
    if r.status_code != 200:
        r = requests.post(f"{_base()}/bucket", headers=_headers(), timeout=30,
                          json={"id": BUCKET, "name": BUCKET, "public": False})
        if r.status_code not in (200, 201) and "already exists" not in r.text.lower():
            raise RuntimeError(f"Could not create Supabase bucket '{BUCKET}': {r.status_code} {r.text[:200]}")
    _bucket_checked = True


def upload(local: Path, key: str, content_type: str) -> str:
    _ensure_bucket()
    with open(local, "rb") as f:
        r = requests.post(f"{_base()}/object/{BUCKET}/{key}", data=f, timeout=600,
                          headers=_headers({"Content-Type": content_type, "x-upsert": "true",
                                            "Cache-Control": "max-age=300"}))
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Supabase upload of {key} failed: {r.status_code} {r.text[:200]}")
    return key


def download(key: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(f"{_base()}/object/{BUCKET}/{key}", headers=_headers(), stream=True, timeout=600) as r:
        if r.status_code != 200:
            raise RuntimeError(f"Supabase download of {key} failed: {r.status_code}")
        with open(dest, "wb") as f:
            shutil.copyfileobj(r.raw, f)
    return dest


def signed_url(key: str, expires_s: int = 3600) -> str:
    r = requests.post(f"{_base()}/object/sign/{BUCKET}/{key}", headers=_headers(),
                      json={"expiresIn": expires_s}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Could not sign {key}: {r.status_code} {r.text[:200]}")
    data = r.json()
    path = data.get("signedURL") or data.get("signedUrl") or ""
    return _base() + path if path.startswith("/") else path


def remove(keys: list[str]) -> None:
    if not keys:
        return
    requests.delete(f"{_base()}/object/{BUCKET}", headers=_headers(), json={"prefixes": keys}, timeout=60)


# ── Index (media_items) ─────────────────────────────────────────────────────────

def get_item(date: str, kind: str, idx: int) -> dict | None:
    with db.db_cursor() as cur:
        cur.execute("SELECT data FROM media_items WHERE date = ? AND kind = ? AND idx = ?", (date, kind, idx))
        row = cur.fetchone()
    return json.loads(row["data"]) if row else None


def list_items(date: str | None = None, kind: str | None = None) -> list[dict]:
    sql, params = "SELECT date, kind, idx, data FROM media_items WHERE 1=1", []
    if date:
        sql += " AND date = ?"
        params.append(date)
    if kind:
        sql += " AND kind = ?"
        params.append(kind)
    sql += " ORDER BY date, kind, idx"
    with db.db_cursor() as cur:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
    return [{**json.loads(r["data"]), "date": r["date"], "kind": r["kind"], "index": r["idx"]} for r in rows]


def max_index(date: str, kind: str) -> int:
    with db.db_cursor() as cur:
        cur.execute("SELECT MAX(idx) AS m FROM media_items WHERE date = ? AND kind = ?", (date, kind))
        row = cur.fetchone()
    return int(row["m"] or 0) if row else 0


def put_item(date: str, kind: str, idx: int, data: dict) -> None:
    with db.db_cursor() as cur:
        cur.execute(
            "INSERT INTO media_items (date, kind, idx, data, updated_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT (date, kind, idx) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
            (date, kind, idx, json.dumps(data, ensure_ascii=False), datetime.now(timezone.utc).isoformat()),
        )


def update_item(date: str, kind: str, idx: int, **fields) -> dict | None:
    with db.db_cursor() as cur:
        cur.execute("SELECT data FROM media_items WHERE date = ? AND kind = ? AND idx = ?" + db.for_update(),
                    (date, kind, idx))
        row = cur.fetchone()
        if not row:
            return None
        data = {**json.loads(row["data"]), **fields}
        cur.execute("UPDATE media_items SET data = ?, updated_at = ? WHERE date = ? AND kind = ? AND idx = ?",
                    (json.dumps(data, ensure_ascii=False), datetime.now(timezone.utc).isoformat(), date, kind, idx))
    return data


def delete_item(date: str, kind: str, idx: int) -> None:
    item = get_item(date, kind, idx)
    if item and storage_enabled():
        remove([k for k in (item.get("thumb_key"), item.get("preview_key")) if k])
    with db.db_cursor() as cur:
        cur.execute("DELETE FROM media_items WHERE date = ? AND kind = ? AND idx = ?", (date, kind, idx))


# ── Publishing from a worker run ────────────────────────────────────────────────

def _status(work_dir: Path, video_name: str) -> str:
    if (work_dir / "youtube_id.txt").exists():
        return "uploaded"
    if (work_dir / video_name).exists():
        return "ready"
    if (work_dir / "thumbnail.jpg").exists():
        return "rendering"
    if (work_dir / "script.json").exists():
        return "generating"
    return "pending"


def _make_preview(video: Path, out: Path, vertical: bool) -> Path:
    """≤45 MB H.264 copy for the dashboard player (bitrate fitted to the duration)."""
    from clipper.common import ffmpeg_exe, probe  # ffmpeg helpers already shipped with the repo
    if video.stat().st_size <= PREVIEW_MAX_BYTES:
        shutil.copy2(video, out)
        return out
    dur = max(1.0, probe(video).duration)
    total_kbps = int(PREVIEW_MAX_BYTES * 8 / 1000 / dur * 0.92)
    v_kbps = max(150, min(1200, total_kbps - 64))
    scale = "scale=-2:640" if vertical else "scale=-2:360"
    subprocess.run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(video), "-vf", scale,
                    "-c:v", "libx264", "-preset", "veryfast", "-b:v", f"{v_kbps}k", "-maxrate", f"{v_kbps}k",
                    "-bufsize", f"{v_kbps * 2}k", "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart",
                    str(out)], check=True)
    return out


def publish(work_dir: Path, date: str, kind: str, idx: int, slot: str = "") -> None:
    """Record one output folder in the cloud index (+ thumbnail/preview in Storage).
    Safe to call repeatedly (after render, after upload). Never raises."""
    if not enabled():
        return
    try:
        video_name = "final.mp4" if kind == "video" else "short.mp4"
        prev = get_item(date, kind, idx) or {}
        script = {}
        if (work_dir / "script.json").exists():
            try:
                script = json.loads((work_dir / "script.json").read_text(encoding="utf-8"))
            except ValueError:
                pass
        yt_file = work_dir / "youtube_id.txt"
        data = {
            "title": script.get("title", prev.get("title", work_dir.name)),
            "title_english": script.get("title_english", prev.get("title_english", "")),
            "description": script.get("description", prev.get("description", "")),
            "tags": script.get("tags", prev.get("tags", [])),
            "thumbnail_text": script.get("thumbnail_text", prev.get("thumbnail_text", "")),
            "script": script or prev.get("script", {}),
            "slot": slot or prev.get("slot", ""),
            "status": _status(work_dir, video_name),
            # Only this folder's own youtube_id.txt counts: a regenerated video replaces
            # an uploaded one and must show as "ready", not inherit the old id.
            "youtube_id": yt_file.read_text(encoding="utf-8").strip() if yt_file.exists() else "",
            "previous_youtube_id": (prev.get("youtube_id") or prev.get("previous_youtube_id", ""))
                                   if not yt_file.exists() else prev.get("previous_youtube_id", ""),
            "thumb_key": prev.get("thumb_key", ""),
            "preview_key": prev.get("preview_key", ""),
            "hd_artifact": prev.get("hd_artifact", {}),
            "run_id": os.environ.get("GITHUB_RUN_ID", prev.get("run_id", "")),
        }
        if data["youtube_id"]:
            data["status"] = "uploaded"
        base_key = f"{date}/{kind}_{idx:02d}"
        if storage_enabled():
            thumb = work_dir / "thumbnail.jpg"
            if thumb.exists():
                data["thumb_key"] = upload(thumb, f"{base_key}/thumbnail.jpg", "image/jpeg")
            video = work_dir / video_name
            marker = work_dir / ".preview_uploaded"
            if video.exists() and not (marker.exists() and marker.read_text() == str(video.stat().st_mtime)):
                with tempfile.TemporaryDirectory() as td:
                    pv = _make_preview(video, Path(td) / "preview.mp4", vertical=(kind == "short"))
                    data["preview_key"] = upload(pv, f"{base_key}/preview.mp4", "video/mp4")
                marker.write_text(str(video.stat().st_mtime))
                if kind == "video" and os.environ.get("GITHUB_RUN_ID"):
                    # full-quality file is uploaded as an Actions artifact by the workflow
                    data["hd_artifact"] = {"run_id": os.environ["GITHUB_RUN_ID"], "name": "hd-videos"}
        put_item(date, kind, idx, data)
    except Exception as exc:
        log.error("Cloud publish failed for %s/%s_%02d: %s", date, kind, idx, exc, exc_info=True)


def publish_dir(base_dir: Path, slots: list[str] | None = None) -> None:
    """Publish every video_NN / short_NN folder under one date dir."""
    if not enabled() or not base_dir.exists():
        return
    for d in sorted(base_dir.iterdir()):
        if not d.is_dir() or "_" not in d.name:
            continue
        kind, _, num = d.name.partition("_")
        if kind not in ("video", "short") or not num.isdigit():
            continue
        idx = int(num)
        slot = slots[idx - 1] if (kind == "video" and slots and idx <= len(slots)) else ""
        publish(d, base_dir.name, kind, idx, slot)


def cleanup(keep_days: int) -> None:
    """Drop index rows + stored files older than keep_days (by date folder name)."""
    if not enabled():
        return
    cutoff = (datetime.now(timezone(timedelta(hours=5, minutes=30))).date() - timedelta(days=keep_days)).isoformat()
    try:
        old = [i for i in list_items() if i["date"] < cutoff]
        if storage_enabled():
            remove([k for i in old for k in (i.get("thumb_key"), i.get("preview_key")) if k])
        with db.db_cursor() as cur:
            cur.execute("DELETE FROM media_items WHERE date < ?", (cutoff,))
        if old:
            log.info("Cloud cleanup: removed %d item(s) older than %s", len(old), cutoff)
    except Exception as exc:
        log.warning("Cloud cleanup failed: %s", exc)
