@echo off
title YouTube Auto-Poster — Local Servers
echo.
echo  Starting YouTube Auto-Poster servers...
echo  Dashboard : http://localhost:3000
echo  API       : http://localhost:8000
echo.

:: Prefer the "py" launcher: on many Windows installs "python" is only the
:: Microsoft Store placeholder, which prints an install hint and exits.
set "PY=python"
where py >nul 2>&1 && set "PY=py"

:: Start FastAPI backend in a new window.
:: run_api.py (not the `uvicorn` CLI) so reload_excludes can be passed as a
:: real Python list — on Windows, uvicorn's CLI (click) auto-expands `*` in
:: --reload-exclude arguments itself, which breaks it. Without the excludes,
:: the reloader watches the whole repo including output/, logs/, and the
:: *.json state files the live pipeline writes to continuously, restarting
:: the server (killing any in-flight request) on every single write.
start "YT API (port 8000)" cmd /k "cd /d %~dp0 && %PY% run_api.py"

:: Give the API a moment to bind
timeout /t 2 /nobreak >nul

:: Start Next.js dashboard in a new window
start "YT Dashboard (port 3000)" cmd /k "cd /d %~dp0\dashboard && npm run dev"

echo  Both servers starting in separate windows.
echo  Press any key to exit this launcher...
pause >nul
