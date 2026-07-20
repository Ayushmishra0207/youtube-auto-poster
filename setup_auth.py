"""
One-time YouTube OAuth setup.

Usage:
  python setup_auth.py

This opens a browser window asking you to log in with the Google account
that owns the @bitnomad1 channel and grant upload + thumbnail permissions.
The token is saved to youtube_token.pickle and reused automatically.

Re-run this script if:
  - You see "insufficient scope" errors (token predates thumbnail support).
  - The token has expired and auto-refresh fails.
  - You switch to a different Google account.

The script detects scope mismatches and automatically deletes the stale token
before starting a fresh OAuth flow.
"""
import os
import pickle

from pipeline.uploader import SCOPES, _get_service, YOUTUBE_TOKEN_FILE


def _check_token_scopes() -> bool:
    """Return True if the saved token has all required scopes."""
    if not os.path.exists(YOUTUBE_TOKEN_FILE):
        return False
    try:
        with open(YOUTUBE_TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)
        granted = set(getattr(creds, "scopes", None) or [])
        required = set(SCOPES)
        return required.issubset(granted)
    except Exception:
        return False


if __name__ == "__main__":
    if os.path.exists(YOUTUBE_TOKEN_FILE):
        if _check_token_scopes():
            print("Existing token found with correct scopes. Re-authenticating anyway to refresh...")
        else:
            print("Existing token is missing a required scope (thumbnail management or analytics).")
            print("Deleting stale token and starting fresh OAuth flow...")
        os.remove(YOUTUBE_TOKEN_FILE)

    print("Opening browser for YouTube OAuth...")
    svc = _get_service()
    me  = svc.channels().list(part="snippet", mine=True).execute()
    name = me["items"][0]["snippet"]["title"]
    print(f"[ok] Authenticated as: {name}")
    print("     Token saved to youtube_token.pickle.")
    print("     Permissions granted: video upload + thumbnail management.")
