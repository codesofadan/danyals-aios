@echo off
REM ============================================================
REM   AIOS - Start the Dashboard locally (opens in your browser)
REM   The UI runs on your machine at http://localhost:3000.
REM   Its API calls (/api/v1) are proxied to the backend you choose:
REM     - LOCAL backend  -> run Start-Backend.bat first (full local, Claude-Code-driven)
REM     - CLOUD backend  -> set BACKEND_ORIGIN below to https://app.qanry.com
REM ============================================================
cd /d "%~dp0frontend"
title AIOS Dashboard (local)

REM Where the dashboard sends its API requests. Default = local backend on :8000.
REM To use the live cloud backend instead, change this to:  https://app.qanry.com
set "BACKEND_ORIGIN=http://127.0.0.1:8000"

echo.
echo   Starting the AIOS dashboard...
echo   API requests go to: %BACKEND_ORIGIN%
echo   Opening http://localhost:3000 in your browser.
echo.

REM Launch the dev server in its own window, wait for it to boot, then open the browser.
start "AIOS Dashboard - dev server" cmd /k "set BACKEND_ORIGIN=%BACKEND_ORIGIN% && npm run dev"
timeout /t 9 /nobreak >nul
start "" http://localhost:3000

echo   Dashboard opening. Leave the dev-server window running while you use it.
echo   Close that window to stop the dashboard.
pause >nul
