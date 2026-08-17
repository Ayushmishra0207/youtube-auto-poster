"""
Upload a video to YouTube and schedule its publish time.
Optionally uploads a custom thumbnail after the video is live.

Auth flow (first run only):
  python setup_auth.py        → opens browser → saves youtube_token.pickle
Subsequent runs use the saved token (auto-refreshed when it expires).

Scope note: if you are upgrading from an older token that only has
youtube.upload scope, delete youtube_token.pickle and re-run setup_auth.py
so the broader youtube scope (needed for thumbnails) is granted. The same
applies after the yt-analytics.readonly scope was added (for monetization
progress tracking), and again after youtube.force-ssl was added (for
auto-posting engagement comments) — delete youtube_token.pickle and re-run
setup_auth.py once to re-consent with the new scope.
"""
import json
import os
import pickle
from datetime import datetime, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaInMemoryUpload

from config import (
    BASE_DIR,
    YOUTUBE_CLIENT_SECRETS,
    YOUTUBE_TOKEN_FILE,
    YT_CATEGORY_ID,
    YT_DEFAULT_LANGUAGE,
    YT_MADE_FOR_KIDS,
)
from pipeline.logger import log
from pipeline.text_utils import safe_truncate

def _playlist_cache_file(cache_dir: Path | None = None) -> Path:
    return (cache_dir or BASE_DIR) / "youtube_playlists.json"

# youtube scope is a superset of youtube.upload and also allows thumbnail management.
# yt-analytics.readonly enables watch-hours/Shorts-views queries for monetization tracking.
# youtube.force-ssl is required specifically for posting comments (commentThreads.insert).
SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


# ─── Auth ─────────────────────────────────────────────────────────────────────

def _get_service(token_file: str | None = None, allow_browser_flow: bool = False):
    """
    Build a YouTube service for `token_file` (an Account.token_file value —
    a bare filename resolved against BASE_DIR, exactly like
    Account.token_path and api/main.py's _get_youtube_credentials), or for
    the single default-account token when none is given.

    An explicitly-named account token that isn't on disk (or can't be
    refreshed) raises instead of silently dropping into the interactive
    browser OAuth flow: run_local_server() waits forever for a callback in a
    headless, unattended context — e.g. the 2:30 AM scheduled run, which
    would sit there holding pipeline.lock. Interactive onboarding is an
    explicit act, so only the no-token_file default path (and
    setup_auth.py, which opts in with allow_browser_flow=True) may open a
    browser.
    """
    if token_file:
        token_path = Path(token_file)
        if not token_path.is_absolute():
            token_path = BASE_DIR / token_path
        if not token_path.exists() and not allow_browser_flow:
            raise FileNotFoundError(
                f"YouTube token not found for this account: {token_path}. "
                f"Run `python setup_auth.py --account <id> --label <name>` to authorize it."
            )
    else:
        token_path = Path(YOUTUBE_TOKEN_FILE)
        allow_browser_flow = True  # default token: interactive setup is expected

    creds = None

    if token_path.exists():
        with open(token_path, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            log.info("Refreshing YouTube OAuth token...")
            creds.refresh(Request())
        else:
            if not allow_browser_flow:
                raise RuntimeError(
                    f"Saved YouTube token {token_path.name} is missing or unusable and cannot be "
                    f"refreshed without user interaction. Re-run `python setup_auth.py --account <id> "
                    f"--label <name>` to re-authorize it."
                )
            if not os.path.exists(YOUTUBE_CLIENT_SECRETS):
                raise FileNotFoundError(
                    "client_secrets.json not found.\n"
                    "Download it from Google Cloud Console → APIs & Services → Credentials."
                )
            log.info("Starting YouTube OAuth browser flow...")
            flow = InstalledAppFlow.from_client_secrets_file(
                YOUTUBE_CLIENT_SECRETS, SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open(token_path, "wb") as f:
            pickle.dump(creds, f)

    return build("youtube", "v3", credentials=creds)


# ─── Upload ───────────────────────────────────────────────────────────────────

def upload_video(
    video_path: str,
    title: str,
    description: str,
    tags: list,
    publish_at_utc: datetime | None,
    category_id: str = YT_CATEGORY_ID,
    yt_language: str = YT_DEFAULT_LANGUAGE,
    token_file: str | None = None,
) -> str:
    """
    Upload video_path to YouTube.

    publish_at_utc is the scheduled go-live time: the video is uploaded
    `private` with that `publishAt` stamp, which is what the daily pipeline
    wants (upload now, surface at the slot time). Pass None instead for
    "publish immediately" — the video goes up `public` with no publishAt at
    all. Passing "now" is NOT the same thing and must not be used: a
    resumable upload of a full-length video can easily outlast the
    timestamp, leaving a private video with a lapsed schedule that never
    fires.

    yt_language sets both defaultLanguage and defaultAudioLanguage — pass
    locale.yt_language (pipeline/locales.py) for non-Hindi content.

    Returns the YouTube video ID.
    """
    svc = _get_service(token_file)

    if publish_at_utc is None:
        publish_str = ""
        status = {
            "privacyStatus":           "public",
            "selfDeclaredMadeForKids": YT_MADE_FOR_KIDS,
        }
    else:
        if publish_at_utc.tzinfo is None:
            publish_at_utc = publish_at_utc.replace(tzinfo=timezone.utc)
        publish_str = publish_at_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        status = {
            "privacyStatus":           "private",
            "publishAt":               publish_str,
            "selfDeclaredMadeForKids": YT_MADE_FOR_KIDS,
        }

    body = {
        "snippet": {
            "title":                safe_truncate(title, 100),
            "description":          description[:5000],
            "tags":                 [str(t)[:500] for t in tags[:500]],
            "categoryId":           category_id,
            "defaultLanguage":      yt_language,
            "defaultAudioLanguage": yt_language,
        },
        "status": status,
    }

    media = MediaFileUpload(
        video_path, mimetype="video/mp4", chunksize=-1, resumable=True
    )
    request = svc.videos().insert(
        part=",".join(body.keys()), body=body, media_body=media
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            log.info("Upload progress: %d%%", pct)

    vid_id = response["id"]
    log.info("Uploaded → https://youtube.com/watch?v=%s  (%s)", vid_id,
             f"scheduled: {publish_str}" if publish_str else "published immediately")
    return vid_id


# ─── Post-upload engagement ───────────────────────────────────────────────────
# YouTube's Community-post tab has no public API (it's Studio/app-only), but
# top-level comments ARE a real, supported endpoint — this posts a channel-
# owner CTA comment on a freshly uploaded video/Short to prime engagement.

def post_engagement_comment(video_id: str, text: str, token_file: str | None = None) -> bool:
    """
    Post a top-level comment as the channel owner on video_id.
    Returns True on success, False on failure (e.g. comments disabled).
    """
    try:
        svc = _get_service(token_file)
        svc.commentThreads().insert(
            part="snippet",
            body={
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {"snippet": {"textOriginal": text}},
                }
            },
        ).execute()
        log.info("Posted engagement comment on video %s", video_id)
        return True
    except HttpError as e:
        log.warning("Engagement comment failed for %s (comments may be disabled): %s", video_id, e)
        return False
    except Exception as e:
        log.warning("Engagement comment failed for %s: %s", video_id, e)
        return False


def upload_thumbnail(video_id: str, thumbnail_path: str, token_file: str | None = None) -> bool:
    """
    Set a custom thumbnail for an already-uploaded video.

    Returns True on success, False if thumbnail upload is not permitted
    (channel not verified) or the file doesn't exist.
    """
    if not os.path.exists(thumbnail_path):
        log.warning("Thumbnail file not found: %s", thumbnail_path)
        return False

    try:
        svc = _get_service(token_file)
        media = MediaFileUpload(thumbnail_path, mimetype="image/jpeg")
        svc.thumbnails().set(videoId=video_id, media_body=media).execute()
        log.info("Thumbnail uploaded for video %s", video_id)
        return True
    except HttpError as e:
        if e.status_code == 403:
            log.warning(
                "Thumbnail upload not permitted (channel may need phone verification): %s", e
            )
        else:
            log.error("Thumbnail upload failed for %s: %s", video_id, e)
        return False
    except Exception as e:
        log.error("Thumbnail upload failed for %s: %s", video_id, e)
        return False


# ─── Playlists ────────────────────────────────────────────────────────────────
# Grouping same-category videos into a playlist is one of the most effective
# levers for session watch time — YouTube's autoplay/suggested strongly favors
# "watch next in this playlist" once a viewer is in one, which is exactly what
# a channel with a near-zero organic-discovery rate on individual long-form
# videos needs. One playlist per topic_config.json category, created lazily
# and cached locally so repeated uploads reuse the same playlist.

def _load_playlist_cache(cache_dir: Path | None = None) -> dict:
    cache_file = _playlist_cache_file(cache_dir)
    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_playlist_cache(cache: dict, cache_dir: Path | None = None) -> None:
    cache_file = _playlist_cache_file(cache_dir)
    cache_file.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_or_create_playlist(category: str, label: str, token_file: str | None = None, cache_dir: Path | None = None) -> str | None:
    """Return the cached playlist ID for `category`, creating it on first use."""
    if not category:
        return None
    cache = _load_playlist_cache(cache_dir)
    if category in cache:
        return cache[category]

    try:
        svc = _get_service(token_file)
        resp = svc.playlists().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title": label or category,
                    "description": f"Auto-generated {label or category} videos from this channel.",
                },
                "status": {"privacyStatus": "public"},
            },
        ).execute()
        playlist_id = resp["id"]
        cache[category] = playlist_id
        _save_playlist_cache(cache, cache_dir)
        log.info("Created playlist '%s' (%s) for category '%s'", label, playlist_id, category)
        return playlist_id
    except Exception as exc:
        log.warning("Could not create/find playlist for category '%s': %s", category, exc)
        return None


def add_video_to_playlist(video_id: str, category: str, label: str = "", token_file: str | None = None, cache_dir: Path | None = None) -> bool:
    """Add video_id to its category's playlist (creating the playlist on first use)."""
    playlist_id = _get_or_create_playlist(category, label, token_file, cache_dir)
    if not playlist_id:
        return False
    try:
        svc = _get_service(token_file)
        svc.playlistItems().insert(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {"kind": "youtube#video", "videoId": video_id},
                }
            },
        ).execute()
        log.info("Added video %s to playlist %s (%s)", video_id, playlist_id, label or category)
        return True
    except Exception as exc:
        log.warning("Could not add video %s to playlist '%s': %s", video_id, category, exc)
        return False


# ─── Captions ─────────────────────────────────────────────────────────────────
# End screens/cards have no public Data API v3 endpoint at all (Studio-only,
# no workaround exists), but timed captions do — captions().insert — and are
# unused here despite the exact timing data already existing (see
# pipeline.video_creator.build_captions_srt, which reuses the same per-section
# timeline as build_chapters). Real captions beat YouTube's own auto-generated
# ASR for TTS-narrated content and make the video's own words indexable for
# search — both a distribution and an accessibility win.

def upload_captions(video_id: str, srt_text: str, language: str = "hi", token_file: str | None = None) -> bool:
    """Upload a timed caption track (SRT) for video_id. No-op if srt_text is empty."""
    if not srt_text.strip():
        return False
    try:
        svc = _get_service(token_file)
        media = MediaInMemoryUpload(srt_text.encode("utf-8"), mimetype="application/octet-stream")
        svc.captions().insert(
            part="snippet",
            body={"snippet": {"videoId": video_id, "language": language, "name": "", "isDraft": False}},
            media_body=media,
        ).execute()
        log.info("Captions uploaded for video %s", video_id)
        return True
    except Exception as exc:
        log.warning("Caption upload failed for video %s: %s", video_id, exc)
        return False
