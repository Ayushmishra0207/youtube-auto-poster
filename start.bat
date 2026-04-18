@echo off
title YouTube Auto-Poster — Local Servers
echo.
echo  Starting YouTube Auto-Poster servers...
echo  Dashboard : http://localhost:3000
echo  API       : http://localhost:8000
echo.

:: Start FastAPI backend in a new window
start "YT API (port 8000)" cmd /k "cd /d %~dp0 && python -m uvicorn api.main:app --reload --port 8000"

:: Give the API a moment to bind
timeout /t 2 /nobreak >nul

:: Start Next.js dashboard in a new window
start "YT Dashboard (port 3000)" cmd /k "cd /d %~dp0\dashboard && npm run dev"

echo  Both servers starting in separate windows.
echo  Press any key to exit this launcher...
pause >nul
