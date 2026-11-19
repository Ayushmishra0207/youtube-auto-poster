"""
Install (or update) a Windows Task Scheduler entry that runs the pipeline
once every day at the generation time (config: first upload slot minus
GENERATION_LEAD_HOURS → 14:30 IST), while you are logged in.

It runs `scheduler.py --now` (one run, then exit) rather than the long-lived
daemon: Task Scheduler stops tasks after 72 h by default and skips a trigger
while the previous instance is still running, which made the daemon approach
silently miss days.

Usage (run once as Administrator):
  python install_task.py          -- install/update the task
  python install_task.py --remove -- delete the task

The task runs under your current Windows user account.
It starts minimised so it doesn't interrupt your desktop.

Requirements:
  - Must be run from an elevated (Administrator) command prompt.
  - The Python interpreter and scheduler.py path are auto-detected from
    the current virtual environment / sys.executable.
"""
import subprocess
import sys
from pathlib import Path

TASK_NAME = "YouTubeAutoPoster"
sys.path.insert(0, str(Path(__file__).parent))
from config import GENERATION_LEAD_HOURS, UPLOAD_SLOTS_IST  # noqa: E402

_first_h, _first_m = map(int, UPLOAD_SLOTS_IST[0].split(":"))
TRIGGER_TIME = f"{_first_h - GENERATION_LEAD_HOURS:02d}:{_first_m:02d}"   # local time (PC timezone must be IST)


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")


def install():
    python  = sys.executable
    script  = str(Path(__file__).parent / "scheduler.py")

    # schtasks uses local system time; ensure Windows clock is set to IST.
    cmd = [
        "schtasks", "/create",
        "/tn",  TASK_NAME,
        "/tr",  f'"{python}" "{script}" --now',
        "/sc",  "DAILY",
        "/st",  TRIGGER_TIME,
        "/rl",  "HIGHEST",     # run with highest available privileges
        "/f",                  # overwrite if task already exists
        # No /ru → runs as the current interactive user (has OAuth token access)
    ]

    result = _run(cmd)
    if result.returncode == 0:
        print(f"[ok] Task '{TASK_NAME}' installed successfully.")
        print(f"     Fires daily at {TRIGGER_TIME} local time.")
        print(f"     Python: {python}")
        print(f"     Script: {script}")
        print()
        print("     IMPORTANT: make sure your Windows timezone is set to IST (UTC+5:30).")
        print("     Control Panel → Clock → Date and Time → Change time zone")
    else:
        print(f"[fail] schtasks returned error:\n{result.stderr or result.stdout}")
        print()
        print("       Tip: run this script from an elevated (Administrator) terminal.")
        sys.exit(1)


def remove():
    result = _run(["schtasks", "/delete", "/tn", TASK_NAME, "/f"])
    if result.returncode == 0:
        print(f"[ok] Task '{TASK_NAME}' removed.")
    else:
        print(f"[fail] Could not remove task:\n{result.stderr or result.stdout}")
        sys.exit(1)


def status():
    result = _run(["schtasks", "/query", "/tn", TASK_NAME, "/fo", "LIST"])
    if result.returncode == 0:
        print(result.stdout)
    else:
        print(f"Task '{TASK_NAME}' not found.")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--remove" in args:
        remove()
    elif "--status" in args:
        status()
    else:
        install()
