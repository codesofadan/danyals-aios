@echo off
REM ============================================================
REM   AIOS - Finish Citations (double-click to run)
REM   Opens each directory in a real browser, logged in + pre-filled,
REM   so you do the one human step (category / captcha) and click Publish.
REM ============================================================
cd /d "%~dp0"
title AIOS - Finish Citations

echo.
echo   ===========================================
echo    AIOS  -  Citation Finisher
echo   ===========================================
echo.

REM Show the ready-to-finish queue.
backend\.venv\Scripts\python.exe tools\finish_citation.py

echo.
set /p pick="  Type a directory name to finish, or type ALL for every one: "
echo.

if /i "%pick%"=="all" (
  backend\.venv\Scripts\python.exe tools\finish_citation.py --all
) else (
  backend\.venv\Scripts\python.exe tools\finish_citation.py "%pick%"
)

echo.
echo   Done. Close this window.
pause >nul
