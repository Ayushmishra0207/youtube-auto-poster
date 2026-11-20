"""
Password hashing (PBKDF2-SHA256, stdlib only, no new dependency) and
session-token management, backed by db.py's SQLite tables.

Threat model: a small number of trusted users (you + teammates you create
accounts for yourself via create_user.py), not a public signup service.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from db import db_cursor

_PBKDF2_ITERATIONS = 260_000
SESSION_TTL_DAYS = 30


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ITERATIONS
    ).hex()


def create_user(username: str, password: str) -> int:
    """Create a new login user. Raises db.IntegrityError if username is taken."""
    salt = secrets.token_hex(16)
    password_hash = _hash_password(password, salt)
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO users (username, password_hash, salt, created_at) VALUES (?, ?, ?, ?)",
            (username, password_hash, salt, datetime.now(timezone.utc).isoformat()),
        )
        return cur.lastrowid


def ensure_user(username: str, password: str) -> int:
    """Create the user if missing, else reset its password to match. Idempotent.

    Used to bootstrap the admin account from ADMIN_USERNAME/ADMIN_PASSWORD env
    vars on startup, since the SQLite user store is gitignored and Render's
    free-tier disk doesn't persist across deploys — create_user.py run
    locally has no effect on the deployed backend.
    """
    salt = secrets.token_hex(16)
    password_hash = _hash_password(password, salt)
    with db_cursor() as cur:
        cur.execute("SELECT id FROM users WHERE username = ?", (username,))
        row = cur.fetchone()
        if row:
            cur.execute(
                "UPDATE users SET password_hash = ?, salt = ? WHERE id = ?",
                (password_hash, salt, row["id"]),
            )
            return row["id"]
        cur.execute(
            "INSERT INTO users (username, password_hash, salt, created_at) VALUES (?, ?, ?, ?)",
            (username, password_hash, salt, datetime.now(timezone.utc).isoformat()),
        )
        return cur.lastrowid


def verify_user(username: str, password: str) -> int | None:
    """Return the user_id if credentials are valid, else None."""
    with db_cursor() as cur:
        cur.execute("SELECT id, password_hash, salt FROM users WHERE username = ?", (username,))
        row = cur.fetchone()
    if not row:
        return None
    if _hash_password(password, row["salt"]) != row["password_hash"]:
        return None
    return row["id"]


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=SESSION_TTL_DAYS)
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, now.isoformat(), expires.isoformat()),
        )
    return token


def get_user_for_session(token: str) -> dict | None:
    """Return {"id", "username"} for a valid, unexpired session token, else None."""
    if not token:
        return None
    with db_cursor() as cur:
        cur.execute(
            "SELECT s.user_id, s.expires_at, u.username FROM sessions s "
            "JOIN users u ON u.id = s.user_id WHERE s.token = ?",
            (token,),
        )
        row = cur.fetchone()
    if not row:
        return None
    expires_at = datetime.fromisoformat(row["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        return None
    return {"id": row["user_id"], "username": row["username"]}


def delete_session(token: str) -> None:
    with db_cursor() as cur:
        cur.execute("DELETE FROM sessions WHERE token = ?", (token,))


def list_users() -> list[dict]:
    with db_cursor() as cur:
        cur.execute("SELECT id, username, created_at FROM users ORDER BY id")
        return [dict(r) for r in cur.fetchall()]
