"""
Install (or update) a Windows Task Scheduler entry that runs growth_audit.py
weekly, so the channel-growth check keeps happening automatically instead
of depending on remembering to ask for it.

Usage (run once as Administrator):
  python install_growth_audit_task.py          -- install/update the task
  python install_growth_audit_task.py --remove -- delete the task
  python install_growth_audit_task.py --status -- show current task status

Requirements:
  - Must be run from an elevated (Administrator) command prompt.
  - The Python interpreter and growth_audit.py path are auto-detected from
    the current virtual environment / sys.executable.
"""
import subprocess
import sys
from pathlib import Path

TASK_NAME = "YouTubeAutoPoster-GrowthAudit"
TRIGGER_TIME = "09:00"   # local time (set your PC timezone to IST)
TRIGGER_DAY = "SUN"      # once a week is plenty for a growth trend


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")


def install():
    python  = sys.executable
    script  = str(Path(__file__).parent / "growth_audit.py")

    cmd = [
        "schtasks", "/create",
        "/tn",  TASK_NAME,
        "/tr",  f'"{python}" "{script}"',
        "/sc",  "WEEKLY",
        "/d",   TRIGGER_DAY,
        "/st",  TRIGGER_TIME,
        "/rl",  "HIGHEST",
        "/f",
        # No /ru → runs as the current interactive user (has OAuth token access)
    ]

    result = _run(cmd)
    if result.returncode == 0:
        print(f"[ok] Task '{TASK_NAME}' installed successfully.")
        print(f"     Fires every {TRIGGER_DAY} at {TRIGGER_TIME} local time.")
        print(f"     Python: {python}")
        print(f"     Script: {script}")
        print()
        print("     Results append to logs/pipeline.log and growth_audit_history.json —")
        print("     just ask 'how's the channel doing' in a future conversation and")
        print("     I can read the accumulated history back.")
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
