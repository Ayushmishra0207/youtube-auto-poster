"""
Local dev launcher for the FastAPI backend.

Equivalent to `python -m uvicorn api.main:app --reload --port 8000`, except
reload_excludes is passed as a real Python list here instead of repeated
`--reload-exclude` CLI flags — on Windows, click (uvicorn's CLI layer)
auto-expands `*` glob patterns in argv itself, which turns something like
`--reload-exclude "output/*"` into hundreds of literal filenames and breaks
argument parsing. Calling uvicorn.run() directly sidesteps that entirely.

Without these excludes, uvicorn's reloader watches the whole repo root,
including output/, logs/, and the *.json state files the live pipeline and
engagement loop write to continuously — every one of those writes triggers
a full server restart, killing any in-flight request (e.g. a real YouTube
upload mid-transfer, which then surfaces in the browser as "Failed to fetch").

Directory entries below are bare names ("output", not "output/*") on
purpose: uvicorn's WatchFilesReload (see FileFilter in
uvicorn/supervisors/watchfilesreload.py) only treats an exclude pattern as a
whole-directory exclusion — matched via `exclude_dir in path.parents`, which
correctly catches files at any depth — when Path(pattern).is_dir() is true.
A pattern with a glob character in it (e.g. "output/*" or ".venv/*") can
never satisfy is_dir(), so it falls through to path.match(pattern) instead,
which only matches ONE path segment — "output/*" matches
"output/foo.txt" but NOT "output/2026-07-21/video_01/final.mp4", and
".venv/*" similarly missed everything more than one level inside .venv
(confirmed: this caused the reloader to keep restarting on
.venv/Lib/site-packages/PIL/* churn after a pip install). The *.ext
patterns don't have this problem — a pattern with no "/" matches against
just a path's final component regardless of depth, per pathlib's own
matching rules.
"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        reload_excludes=[
            "output",
            "logs",
            "*.db",
            "*.log",
            "*_state.json",
            "*_history.json",
            "dashboard",
            ".venv",
        ],
    )
