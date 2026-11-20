"""
Persistence for dashboard login users, sessions, connected YouTube accounts,
app state (key → JSON) and the index of generated media.

Two backends, same API:
  • DATABASE_URL set (Render / GitHub Actions) → Postgres, e.g. Supabase.
    Use Supabase's *Session pooler* connection string: it's IPv4-reachable
    from Render and GitHub runners (the direct connection is IPv6-only).
  • otherwise → local SQLite file app.db at the repo root (gitignored — it
    holds password hashes and session tokens, never commit it).

SQL in callers uses "?" placeholders; they're translated for Postgres here.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager

from config import BASE_DIR

DB_PATH = BASE_DIR / "app.db"


def database_url() -> str:
    return os.environ.get("DATABASE_URL", "").strip()


def is_postgres() -> bool:
    return bool(database_url())


_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS youtube_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    channel_id TEXT,
    channel_title TEXT,
    token_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS media_items (
    date TEXT NOT NULL,
    kind TEXT NOT NULL,
    idx INTEGER NOT NULL,
    data TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (date, kind, idx)
);
"""

_PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS youtube_accounts (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    channel_id TEXT,
    channel_title TEXT,
    token_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS media_items (
    date TEXT NOT NULL,
    kind TEXT NOT NULL,
    idx INTEGER NOT NULL,
    data TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (date, kind, idx)
);
"""

# Postgres has no client-side INSERT OR IGNORE etc. — callers stick to portable
# SQL ("INSERT ... ON CONFLICT (...) DO ..." works in both SQLite ≥3.24 and Postgres).

try:  # Postgres driver is only needed (and installed) in the cloud
    import psycopg
    from psycopg.rows import dict_row
    IntegrityError: tuple = (sqlite3.IntegrityError, psycopg.IntegrityError)
except ImportError:  # pragma: no cover - local installs without psycopg
    psycopg = None
    IntegrityError = (sqlite3.IntegrityError,)


class _Cursor:
    """Thin wrapper so callers write one SQL dialect ("?" params, dict rows)."""

    def __init__(self, raw, pg: bool):
        self._raw = raw
        self._pg = pg
        self.lastrowid = None

    def execute(self, sql: str, params: tuple | list = ()):
        if self._pg:
            sql = sql.replace("?", "%s")
            if sql.lstrip().upper().startswith("INSERT INTO USERS") or \
               sql.lstrip().upper().startswith("INSERT INTO YOUTUBE_ACCOUNTS"):
                sql = sql.rstrip().rstrip(";") + " RETURNING id"
                self._raw.execute(sql, params)
                row = self._raw.fetchone()
                self.lastrowid = row["id"] if row else None
                return self
        self._raw.execute(sql, params)
        if not self._pg:
            self.lastrowid = self._raw.lastrowid
        return self

    def fetchone(self):
        row = self._raw.fetchone()
        return dict(row) if row is not None else None

    def fetchall(self):
        return [dict(r) for r in self._raw.fetchall()]

    @property
    def rowcount(self) -> int:
        return self._raw.rowcount


def _sqlite_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _pg_connection():
    if psycopg is None:
        raise RuntimeError("DATABASE_URL is set but psycopg isn't installed — pip install 'psycopg[binary]'")
    # prepare_threshold=None: Supabase's poolers don't support server-side prepared statements
    return psycopg.connect(database_url(), row_factory=dict_row, prepare_threshold=None, connect_timeout=15)


# A fresh Postgres connection per query cost 1-2 s from Render (Oregon) to Supabase
# (Singapore) and jammed the API under the dashboard's polling — reuse connections.
_pool = None
_pool_lock = __import__("threading").Lock()


def _get_pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                try:
                    from psycopg_pool import ConnectionPool
                except ImportError:
                    return None
                _pool = ConnectionPool(
                    database_url(), min_size=1, max_size=int(os.environ.get("DB_POOL_MAX", "5")),
                    kwargs={"row_factory": dict_row, "prepare_threshold": None, "connect_timeout": 15},
                    max_idle=300, timeout=30, check=ConnectionPool.check_connection, open=True,
                )
    return _pool


def get_connection():
    return _pg_connection() if is_postgres() else _sqlite_connection()


_initialized = False


def init_db() -> None:
    global _initialized
    if is_postgres():
        with _pg_connection() as conn:
            conn.execute(_PG_SCHEMA)
    else:
        conn = _sqlite_connection()
        try:
            conn.executescript(_SQLITE_SCHEMA)
            conn.commit()
        finally:
            conn.close()
    _initialized = True


@contextmanager
def db_cursor():
    """Yields a cursor inside a committed (or rolled-back) transaction."""
    if not _initialized:
        init_db()
    pg = is_postgres()
    pool = _get_pool() if pg else None
    if pool is not None:
        with pool.connection() as conn:   # commits on success, rolls back on error, returns to pool
            yield _Cursor(conn.cursor(), True)
        return
    conn = get_connection()
    try:
        cur = _Cursor(conn.cursor(), pg)
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def for_update() -> str:
    """Row-lock suffix for read-modify-write (Postgres); SQLite locks the whole DB anyway."""
    return " FOR UPDATE" if is_postgres() else ""
