"""
One-time Instagram Graph API token setup.

Usage:
  python setup_instagram_auth.py

Prerequisites (do these once in a browser first — see INSTAGRAM_SETUP.md):
  1. Instagram account converted to Business/Creator, linked to a Facebook Page.
  2. A Meta Developer app created, with the Instagram Graph API product added,
     and your account added as an Instagram Tester (a Development Mode
     requirement — only tester accounts can be posted to before App Review).
  3. A short-lived User Access Token generated via Graph API Explorer
     (developers.facebook.com/tools/explorer) with these permissions:
     instagram_basic, instagram_content_publish, pages_show_list,
     pages_read_engagement.

This script exchanges that short-lived token for a long-lived one (~60 days),
looks up your Facebook Page ID and linked Instagram Business Account ID, and
writes all 5 values into .env. Re-run it every ~60 days to refresh the token.
"""
from pathlib import Path

import requests

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"
ENV_FILE = Path(__file__).parent / ".env"


def _exchange_long_lived_token(app_id: str, app_secret: str, short_token: str) -> str:
    resp = requests.get(
        f"{GRAPH_API_BASE}/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": short_token,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if "access_token" not in data:
        raise RuntimeError(
            f"Meta API did not return an access_token. Response: {data}"
        )
    return data["access_token"]


def _find_page_and_ig_account(long_token: str) -> tuple[str, str]:
    resp = requests.get(
        f"{GRAPH_API_BASE}/me/accounts",
        params={"access_token": long_token},
        timeout=30,
    )
    resp.raise_for_status()
    pages = resp.json().get("data", [])
    if not pages:
        raise RuntimeError("No Facebook Pages found for this account/token.")
    if "id" not in pages[0]:
        raise RuntimeError(
            f"First page entry missing 'id' field. Response: {pages[0]}"
        )
    page_id = pages[0]["id"]

    resp = requests.get(
        f"{GRAPH_API_BASE}/{page_id}",
        params={"fields": "instagram_business_account", "access_token": long_token},
        timeout=30,
    )
    resp.raise_for_status()
    ig_account = resp.json().get("instagram_business_account")
    if not ig_account:
        raise RuntimeError(
            f"Page {page_id} has no linked Instagram Business account. "
            "Re-check the Facebook Page link in Instagram's "
            "'Professional account' settings (see INSTAGRAM_SETUP.md)."
        )
    return page_id, ig_account["id"]


def _write_env(updates: dict) -> None:
    existing = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                existing[k.strip()] = v.strip()
    existing.update(updates)
    ENV_FILE.write_text("\n".join(f"{k}={v}" for k, v in existing.items()) + "\n", encoding="utf-8")


if __name__ == "__main__":
    print("Instagram Graph API one-time setup")
    print("(See INSTAGRAM_SETUP.md if you haven't completed the browser steps yet.)\n")

    app_id      = input("Meta App ID: ").strip()
    if not app_id:
        raise SystemExit("Error: Meta App ID cannot be empty.")
    app_secret  = input("Meta App Secret: ").strip()
    if not app_secret:
        raise SystemExit("Error: Meta App Secret cannot be empty.")
    short_token = input("Short-lived User Access Token (from Graph API Explorer): ").strip()
    if not short_token:
        raise SystemExit("Error: Short-lived User Access Token cannot be empty.")

    print("\nExchanging for a long-lived token...")
    long_token = _exchange_long_lived_token(app_id, app_secret, short_token)
    print("[ok] Long-lived token obtained (valid ~60 days).")

    print("Looking up your Facebook Page and linked Instagram Business account...")
    page_id, ig_account_id = _find_page_and_ig_account(long_token)
    print(f"[ok] Page ID: {page_id}")
    print(f"[ok] Instagram Business Account ID: {ig_account_id}")

    _write_env({
        "INSTAGRAM_APP_ID": app_id,
        "INSTAGRAM_APP_SECRET": app_secret,
        "INSTAGRAM_ACCESS_TOKEN": long_token,
        "INSTAGRAM_PAGE_ID": page_id,
        "INSTAGRAM_BUSINESS_ACCOUNT_ID": ig_account_id,
    })
    print("\nAll 5 values written to .env. Instagram Reels automation is ready")
    print("(assuming R2_* values are also set — see INSTAGRAM_SETUP.md).")
    print("Note: the long-lived token expires in ~60 days — re-run this script to refresh it.")
