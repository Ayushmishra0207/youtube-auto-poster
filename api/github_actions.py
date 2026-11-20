"""
Start and watch the heavy-work workflow (.github/workflows/autoposter.yml) from
the Render API.

Env (Render):
  GITHUB_REPO            "owner/repo", e.g. Ayushmishra0207/youtube-auto-poster
  GITHUB_DISPATCH_TOKEN  fine-grained token for that repo with "Actions: Read and write"
  GITHUB_BRANCH          optional, default "main"
"""
from __future__ import annotations

import json
import os
import threading
import time

import requests

WORKFLOW = "autoposter.yml"
_ACTIVE = ("queued", "in_progress", "waiting", "requested", "pending")
_cache: dict = {"at": 0.0, "runs": []}
_cache_lock = threading.Lock()


class DispatchError(RuntimeError):
    pass


def configured() -> bool:
    return bool(os.environ.get("GITHUB_REPO") and os.environ.get("GITHUB_DISPATCH_TOKEN"))


def _api(path: str) -> str:
    return f"https://api.github.com/repos/{os.environ['GITHUB_REPO']}{path}"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ['GITHUB_DISPATCH_TOKEN']}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def run_title(task: str, args: dict) -> str:
    """Must match `run-name` in autoposter.yml so active runs can be recognised."""
    return f"{task} {json.dumps(args, separators=(',', ':'), sort_keys=True)}"


def dispatch(task: str, args: dict | None = None) -> None:
    if not configured():
        raise DispatchError("GitHub Actions isn't connected — set GITHUB_REPO and GITHUB_DISPATCH_TOKEN on Render.")
    payload = {"ref": os.environ.get("GITHUB_BRANCH", "main"),
               "inputs": {"task": task, "args": json.dumps(args or {}, separators=(",", ":"), sort_keys=True)}}
    r = requests.post(_api(f"/actions/workflows/{WORKFLOW}/dispatches"), headers=_headers(), json=payload, timeout=20)
    if r.status_code != 204:
        raise DispatchError(f"GitHub refused to start the run ({r.status_code}): {r.text[:200]}")
    with _cache_lock:     # make the new run show up as "running" right away
        _cache["runs"] = [{"title": run_title(task, args or {}), "url": "", "status": "queued"}] + _cache["runs"]
        _cache["at"] = time.time()


def active_runs(max_age_s: float = 15.0) -> list[dict]:
    """[{title, url, status}] of queued/running autoposter runs (cached briefly)."""
    if not configured():
        return []
    with _cache_lock:
        if time.time() - _cache["at"] < max_age_s:
            return list(_cache["runs"])
    try:
        r = requests.get(_api(f"/actions/workflows/{WORKFLOW}/runs"), headers=_headers(),
                         params={"per_page": 30}, timeout=15)
        r.raise_for_status()
        runs = [{"title": w.get("display_title", ""), "url": w.get("html_url", ""), "status": w.get("status")}
                for w in r.json().get("workflow_runs", []) if w.get("status") in _ACTIVE]
    except Exception:
        runs = _cache["runs"]   # keep the last known state on a GitHub hiccup
    with _cache_lock:
        _cache.update(at=time.time(), runs=runs)
    return list(runs)


def is_active(task: str, args: dict | None = None) -> bool:
    """A queued/running run for this task (and exactly these args, if given)."""
    for run in active_runs():
        title = run["title"]
        if args is None and (title == task or title.startswith(task + " ")):
            return True
        if args is not None and title == run_title(task, args):
            return True
    return False


def runs_page_url() -> str:
    repo = os.environ.get("GITHUB_REPO", "")
    return f"https://github.com/{repo}/actions/workflows/{WORKFLOW}" if repo else ""
