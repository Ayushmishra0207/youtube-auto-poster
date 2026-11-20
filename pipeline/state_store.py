"""
Named JSON state (topic config, topic overrides, engagement state, Instagram
queue, Shorts topic history, settings overrides…).

  • Local PC: the same JSON files at the repo root as always (topic_config.json …).
  • Cloud (DATABASE_URL set): rows in the app_state table, because Render's and
    GitHub runners' disks are thrown away after every deploy/run.

mutate() is the safe read-modify-write: a row lock in Postgres, a file lock
locally — so the API, the scheduler and the engagement job can't overwrite
each other's changes with a stale copy.
"""
from __future__ import annotations

import copy
import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Callable

from config import BASE_DIR

try:  # db imports psycopg lazily-safe; keep state_store importable without it
    import db as _db
except Exception:  # pragma: no cover
    _db = None


def _cloud() -> bool:
    return _db is not None and _db.is_postgres()


def _file(name: str):
    return BASE_DIR / name


def _seed(name: str, default: Any) -> Any:
    """First-run value in the cloud: the repo's committed file (e.g. topic_config.json)
    or a <NAME>_JSON env var, else the default."""
    env = os.environ.get(name.replace(".json", "").upper() + "_JSON", "").strip()
    if env:
        try:
            return json.loads(env)
        except ValueError:
            pass
    f = _file(name)
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return copy.deepcopy(default)


def load(name: str, default: Any = None) -> Any:
    if _cloud():
        with _db.db_cursor() as cur:
            cur.execute("SELECT value FROM app_state WHERE key = ?", (name,))
            row = cur.fetchone()
        return json.loads(row["value"]) if row else _seed(name, default)
    f = _file(name)
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return copy.deepcopy(default)


def exists(name: str) -> bool:
    if _cloud():
        with _db.db_cursor() as cur:
            cur.execute("SELECT 1 AS x FROM app_state WHERE key = ?", (name,))
            return cur.fetchone() is not None
    return _file(name).exists()


def save(name: str, value: Any) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2)
    if _cloud():
        with _db.db_cursor() as cur:
            cur.execute(
                "INSERT INTO app_state (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (name, payload, datetime.now(timezone.utc).isoformat()),
            )
        return
    f = _file(name)
    tmp = f.with_suffix(f.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, f)


def delete(name: str) -> None:
    if _cloud():
        with _db.db_cursor() as cur:
            cur.execute("DELETE FROM app_state WHERE key = ?", (name,))
        return
    _file(name).unlink(missing_ok=True)


def mutate(name: str, fn: Callable[[Any], Any], default: Any = None) -> Any:
    """Atomically load → fn(state) (mutates in place and/or returns a result) → save.
    Returns fn's result."""
    if _cloud():
        with _db.db_cursor() as cur:
            # make sure a row exists so FOR UPDATE has something to lock
            cur.execute(
                "INSERT INTO app_state (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT (key) DO NOTHING",
                (name, json.dumps(_seed(name, default), ensure_ascii=False), datetime.now(timezone.utc).isoformat()),
            )
            cur.execute("SELECT value FROM app_state WHERE key = ?" + _db.for_update(), (name,))
            state = json.loads(cur.fetchone()["value"])
            result = fn(state)
            cur.execute("UPDATE app_state SET value = ?, updated_at = ? WHERE key = ?",
                        (json.dumps(state, ensure_ascii=False, indent=2),
                         datetime.now(timezone.utc).isoformat(), name))
        return result

    from pipeline import locking
    # The PID lock file only separates *processes*; threads of one process (the
    # API's engagement thread vs. a dashboard request) share the PID, so they
    # also need an in-process lock — otherwise they block each other out.
    with _thread_lock(name):
        lock = _file(name + ".lock")
        if not locking.acquire_wait(lock, timeout_s=60, poll_s=0.2):
            raise RuntimeError(f"{name} is locked by another process")
        try:
            state = load(name, default)
            result = fn(state)
            save(name, state)
            return result
        finally:
            locking.release(lock)


_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


def _thread_lock(name: str) -> threading.Lock:
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(name, threading.Lock())
