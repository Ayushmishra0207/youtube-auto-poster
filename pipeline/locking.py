"""
PID lock files shared by scheduler.py (pipeline.lock) and generate_short_now.py
(short_generate.lock).

- Creation is atomic (O_CREAT|O_EXCL), so two processes can never both create it.
- A stale lock (owner PID dead) is taken over by atomically *renaming* it to a
  unique name first: only one of several racing processes can win that rename,
  so a second process can no longer delete a lock the first one just re-created.
- A lock whose PID can't be read yet (created, PID not written) counts as live
  unless it's older than a minute.
- PID liveness works on Windows (tasklist) and on Linux/Render (os.kill 0) —
  the old tasklist-only check always said "dead" on Linux, so locks never held.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


def pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            r = subprocess.run(["tasklist", "/fi", f"PID eq {pid}", "/nh"],
                               capture_output=True, text=True, timeout=5)
            return str(pid) in r.stdout
        except Exception:
            return True   # can't tell → assume alive rather than steal a live lock
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True       # exists, owned by another user
    except OSError:
        return False


def _try_create(path: Path) -> bool:
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w") as f:
        f.write(str(os.getpid()))
    return True


def lock_owner(path: Path) -> int | None:
    """PID holding the lock, 0 if held but PID not written yet, None if no live lock."""
    try:
        text = path.read_text().strip()
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return None
    if not text:
        return 0 if time.time() - mtime < 60 else None
    try:
        pid = int(text)
    except ValueError:
        return None
    return pid if pid_running(pid) else None


def acquire(path: Path) -> bool:
    """True if this process now holds the lock."""
    if _try_create(path):
        return True
    if lock_owner(path) is not None:
        return False
    # Stale: move it aside atomically — exactly one racer succeeds
    aside = path.with_name(f"{path.name}.stale-{os.getpid()}")
    try:
        os.replace(path, aside) if sys.platform != "win32" else os.rename(path, aside)
    except OSError:
        return _try_create(path)   # someone else already handled it
    aside.unlink(missing_ok=True)
    return _try_create(path)


def acquire_wait(path: Path, timeout_s: float, poll_s: float = 15.0) -> bool:
    deadline = time.time() + timeout_s
    while True:
        if acquire(path):
            return True
        if time.time() >= deadline:
            return False
        time.sleep(poll_s)


def release(path: Path) -> None:
    """Remove the lock only if this process owns it."""
    try:
        if path.read_text().strip() == str(os.getpid()):
            path.unlink(missing_ok=True)
    except FileNotFoundError:
        pass
