"""
Upload a rendered Reel to Cloudflare R2 for temporary public hosting, then
publish it to Instagram via the Graph API's two-step container flow
(create container -> poll until processed -> publish). R2 is used purely as
a presigned-URL relay: Instagram's Graph API requires a public video URL and
has no direct file-upload path, unlike YouTube's MediaFileUpload.

One-time setup: see INSTAGRAM_SETUP.md, then run setup_instagram_auth.py.
"""
import time
import uuid

import boto3
import requests

from config import (
    INSTAGRAM_ACCESS_TOKEN,
    INSTAGRAM_BUSINESS_ACCOUNT_ID,
    R2_ACCOUNT_ID,
    R2_ACCESS_KEY_ID,
    R2_SECRET_ACCESS_KEY,
    R2_BUCKET_NAME,
)
from pipeline.logger import log
from pipeline.retry import with_retry

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"
CONTAINER_POLL_INTERVAL_SECONDS = 5
CONTAINER_POLL_MAX_ATTEMPTS = 24  # ~2 minutes total
PRESIGNED_URL_EXPIRY_SECONDS = 3600


def _get_r2_client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )


@with_retry(max_attempts=3, base_delay=5, exceptions=(Exception,))
def upload_to_r2(video_path: str) -> tuple[str, str]:
    """Upload video_path to R2, return (presigned_public_url, r2_key)."""
    r2_key = f"reels/{uuid.uuid4().hex}.mp4"
    client = _get_r2_client()
    client.upload_file(video_path, R2_BUCKET_NAME, r2_key, ExtraArgs={"ContentType": "video/mp4"})
    public_url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": R2_BUCKET_NAME, "Key": r2_key},
        ExpiresIn=PRESIGNED_URL_EXPIRY_SECONDS,
    )
    log.info("Uploaded %s to R2 (key=%s), presigned URL expires in %ds", video_path, r2_key, PRESIGNED_URL_EXPIRY_SECONDS)
    return public_url, r2_key


def delete_from_r2(r2_key: str) -> None:
    try:
        _get_r2_client().delete_object(Bucket=R2_BUCKET_NAME, Key=r2_key)
        log.info("Deleted R2 object %s", r2_key)
    except Exception as exc:
        log.warning("Failed to delete R2 object %s: %s", r2_key, exc)


@with_retry(max_attempts=3, base_delay=5, exceptions=(requests.exceptions.RequestException,))
def _create_container(video_url: str, caption: str) -> str:
    resp = requests.post(
        f"{GRAPH_API_BASE}/{INSTAGRAM_BUSINESS_ACCOUNT_ID}/media",
        data={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "access_token": INSTAGRAM_ACCESS_TOKEN,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["id"]


@with_retry(max_attempts=3, base_delay=5, exceptions=(requests.exceptions.RequestException,))
def _wait_until_ready(container_id: str) -> None:
    for _ in range(CONTAINER_POLL_MAX_ATTEMPTS):
        resp = requests.get(
            f"{GRAPH_API_BASE}/{container_id}",
            params={"fields": "status_code", "access_token": INSTAGRAM_ACCESS_TOKEN},
            timeout=30,
        )
        resp.raise_for_status()
        status = resp.json().get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"Instagram container {container_id} failed processing")
        time.sleep(CONTAINER_POLL_INTERVAL_SECONDS)
    raise TimeoutError(f"Instagram container {container_id} did not finish processing in time")


@with_retry(max_attempts=3, base_delay=5, exceptions=(requests.exceptions.RequestException,))
def _publish_container(container_id: str) -> str:
    resp = requests.post(
        f"{GRAPH_API_BASE}/{INSTAGRAM_BUSINESS_ACCOUNT_ID}/media_publish",
        data={"creation_id": container_id, "access_token": INSTAGRAM_ACCESS_TOKEN},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def publish_reel(video_path: str, caption: str) -> str:
    """Upload video_path to R2, publish it to Instagram as a Reel, then always
    clean up the R2 object. Returns the Instagram media id. Raises on
    unrecoverable failure — the caller (pipeline.instagram_queue) is
    responsible for catching and recording it."""
    public_url, r2_key = upload_to_r2(video_path)
    try:
        container_id = _create_container(public_url, caption)
        _wait_until_ready(container_id)
        return _publish_container(container_id)
    finally:
        delete_from_r2(r2_key)
