"""
Periodic channel-growth check — pulls live stats from the YouTube Data/
Analytics API (using the same stored OAuth token uploader.py uses) and
compares against a saved baseline, so you can see whether the channel is
actually trending toward monetization instead of guessing.

Run manually:
  python growth_audit.py

Run as a scheduled task (weekly, via Windows Task Scheduler):
  python install_growth_audit_task.py

First run creates the baseline (assets/growth_audit_baseline.json) from the
2026-08-15 snapshot: 48 subscribers, 362 videos, 166 watch-hours/365d,
72.8% zero-view rate for long-form vs 3.0% for Shorts. Every run after that
appends a dated comparison to logs/growth_audit.log and updates
growth_audit_history.json so trend-over-time is visible, not just the
latest snapshot vs the original baseline.
"""
import json
import re
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import BASE_DIR
from pipeline.logger import log
from pipeline.uploader import _get_service

IST = timezone(timedelta(hours=5, minutes=30))

BASELINE_FILE = BASE_DIR / "growth_audit_baseline.json"
HISTORY_FILE = BASE_DIR / "growth_audit_history.json"

# Captured 2026-08-15 from a live pull (see conversation history) — used
# only if no baseline file exists yet (i.e. the very first run).
_INITIAL_BASELINE = {
    "captured_at": "2026-08-15",
    "subscribers": 48,
    "total_videos": 362,
    "total_views": 36208,
    "watch_hours_365d": 166,
    "longform_zero_view_pct": 72.8,
    "shorts_zero_view_pct": 3.0,
}


def _parse_duration(d: str) -> int:
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d or "")
    if not m or not m.group(0):
        return 0
    h, mnt, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mnt * 60 + s


def _fetch_all_videos(yt) -> list[dict]:
    uploads_id = yt.channels().list(part="contentDetails", mine=True).execute()[
        "items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    video_ids, page_token = [], None
    while True:
        resp = yt.playlistItems().list(
            part="contentDetails", playlistId=uploads_id, maxResults=50, pageToken=page_token
        ).execute()
        video_ids.extend(item["contentDetails"]["videoId"] for item in resp["items"])
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    videos = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        resp = yt.videos().list(part="snippet,statistics,contentDetails", id=",".join(batch)).execute()
        for item in resp["items"]:
            seconds = _parse_duration(item["contentDetails"]["duration"])
            if seconds <= 0:
                continue
            videos.append({
                "id": item["id"],
                "publishedAt": item["snippet"]["publishedAt"],
                "views": int(item["statistics"].get("viewCount", 0)),
                "is_short": seconds <= 61,
            })
    return videos


def _current_snapshot() -> dict:
    yt = _get_service()
    ch = yt.channels().list(part="statistics", mine=True).execute()["items"][0]["statistics"]

    videos = _fetch_all_videos(yt)
    this_year = datetime.now(IST).strftime("%Y")
    ytd = [v for v in videos if v["publishedAt"][:4] == this_year]
    shorts = [v for v in ytd if v["is_short"]]
    longform = [v for v in ytd if not v["is_short"]]

    def zero_pct(group):
        return round(100 * len([v for v in group if v["views"] == 0]) / len(group), 1) if group else None

    creds = yt._http.credentials
    from googleapiclient.discovery import build
    yta = build("youtubeAnalytics", "v2", credentials=creds)
    end = datetime.now(IST).strftime("%Y-%m-%d")
    start = (datetime.now(IST) - timedelta(days=365)).strftime("%Y-%m-%d")
    rows = yta.reports().query(
        ids="channel==MINE", startDate=start, endDate=end, metrics="estimatedMinutesWatched"
    ).execute().get("rows") or [[0]]

    return {
        "captured_at": datetime.now(IST).strftime("%Y-%m-%d"),
        "subscribers": int(ch.get("subscriberCount", 0)),
        "total_videos": int(ch.get("videoCount", 0)),
        "total_views": int(ch.get("viewCount", 0)),
        "watch_hours_365d": round(rows[0][0] / 60, 1),
        "longform_zero_view_pct": zero_pct(longform),
        "shorts_zero_view_pct": zero_pct(shorts),
        "longform_count_ytd": len(longform),
        "shorts_count_ytd": len(shorts),
    }


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def run() -> dict:
    baseline = _load_json(BASELINE_FILE, None)
    if baseline is None:
        baseline = _INITIAL_BASELINE
        BASELINE_FILE.write_text(json.dumps(baseline, indent=2), encoding="utf-8")
        log.info("Growth audit: no baseline found, seeded from 2026-08-15 snapshot.")

    snapshot = _current_snapshot()

    history = _load_json(HISTORY_FILE, [])
    history.append(snapshot)
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

    def delta(key):
        b, s = baseline.get(key), snapshot.get(key)
        if b is None or s is None:
            return "n/a"
        sign = "+" if s - b >= 0 else ""
        return f"{s} ({sign}{round(s - b, 1)} vs baseline)"

    log.info("=" * 60)
    log.info("Growth audit — %s (baseline: %s)", snapshot["captured_at"], baseline["captured_at"])
    log.info("Subscribers:            %s", delta("subscribers"))
    log.info("Total videos:           %s", delta("total_videos"))
    log.info("Total views:            %s", delta("total_views"))
    log.info("Watch hours (365d):     %s", delta("watch_hours_365d"))
    log.info("Long-form zero-view %%:  %s", delta("longform_zero_view_pct"))
    log.info("Shorts zero-view %%:     %s", delta("shorts_zero_view_pct"))
    log.info("=" * 60)

    return snapshot


if __name__ == "__main__":
    run()
