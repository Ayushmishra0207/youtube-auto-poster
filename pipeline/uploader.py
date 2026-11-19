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
import os
import pickle
from datetime import datetime, timezone

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from config import (
    YOUTUBE_CLIENT_SECRETS,
    YOUTUBE_TOKEN_FILE,
    YT_CATEGORY_ID,
    YT_DEFAULT_LANGUAGE,
    YT_MADE_FOR_KIDS,
)
from pipeline.logger import log
from pipeline.text_utils import (
    YT_DESCRIPTION_MAX_BYTES,
    fit_youtube_tags,
    fit_youtube_text,
    safe_truncate,
)

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

def _get_service():
    creds = None

    # Cloud (Render): the token arrives as YOUTUBE_TOKEN_B64 — previously only the
    # API's own helper decoded it, so a pipeline run on a fresh instance fell
    # through to the browser OAuth flow and every upload failed.
    if not os.path.exists(YOUTUBE_TOKEN_FILE) and os.environ.get("YOUTUBE_TOKEN_B64"):
        import base64
        with open(YOUTUBE_TOKEN_FILE, "wb") as f:
            f.write(base64.b64decode(os.environ["YOUTUBE_TOKEN_B64"]))

    if os.path.exists(YOUTUBE_TOKEN_FILE):
        with open(YOUTUBE_TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            log.info("Refreshing YouTube OAuth token...")
            creds.refresh(Request())
        else:
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

        with open(YOUTUBE_TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)

    return build("youtube", "v3", credentials=creds)


# ─── Upload ───────────────────────────────────────────────────────────────────

def upload_video(
    video_path: str,
    title: str,
    description: str,
    tags: list,
    publish_at_utc: datetime,
    category_id: str = YT_CATEGORY_ID,
    yt_language: str = YT_DEFAULT_LANGUAGE,
) -> str:
    """
    Upload video_path to YouTube and schedule it for publish_at_utc.
    yt_language sets both defaultLanguage and defaultAudioLanguage — pass
    locale.yt_language (pipeline/locales.py) for non-Hindi content.

    Returns the YouTube video ID.
    """
    svc = _get_service()

    if publish_at_utc.tzinfo is None:
        publish_at_utc = publish_at_utc.replace(tzinfo=timezone.utc)
    publish_str = publish_at_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    body = {
        "snippet": {
            "title":                safe_truncate((title or "").replace("<", "‹").replace(">", "›"), 100),
            "description":          fit_youtube_text(description, YT_DESCRIPTION_MAX_BYTES),
            "tags":                 fit_youtube_tags(tags),
            "categoryId":           category_id,
            "defaultLanguage":      yt_language,
            "defaultAudioLanguage": yt_language,
        },
        "status": {
            "privacyStatus":            "private",
            "publishAt":                publish_str,
            "selfDeclaredMadeForKids":  YT_MADE_FOR_KIDS,
        },
    }

    # 10 MB chunks + num_retries: one transient socket error / 5xx used to abort
    # the whole single-request upload and lose that day's video.
    media = MediaFileUpload(
        video_path, mimetype="video/mp4", chunksize=10 * 1024 * 1024, resumable=True
    )
    request = svc.videos().insert(
        part=",".join(body.keys()), body=body, media_body=media
    )

    response = None
    while response is None:
        status, response = request.next_chunk(num_retries=5)
        if status:
            pct = int(status.progress() * 100)
            log.info("Upload progress: %d%%", pct)

    vid_id = response["id"]
    log.info("Uploaded → https://youtube.com/watch?v=%s  (scheduled: %s)", vid_id, publish_str)
    return vid_id


# ─── Post-upload engagement ───────────────────────────────────────────────────
# YouTube's Community-post tab has no public API (it's Studio/app-only), but
# top-level comments ARE a real, supported endpoint — this posts a channel-
# owner CTA comment on a freshly uploaded video/Short to prime engagement.

def post_engagement_comment(video_id: str, text: str) -> bool:
    """
    Post a top-level comment as the channel owner on video_id.
    Returns True on success, False on failure (e.g. comments disabled).
    """
    try:
        svc = _get_service()
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


def upload_thumbnail(video_id: str, thumbnail_path: str) -> bool:
    """
    Set a custom thumbnail for an already-uploaded video.

    Returns True on success, False if thumbnail upload is not permitted
    (channel not verified) or the file doesn't exist.
    """
    if not os.path.exists(thumbnail_path):
        log.warning("Thumbnail file not found: %s", thumbnail_path)
        return False

    try:
        svc = _get_service()
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
