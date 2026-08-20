@echo off
REM ============================================================
REM   AIOS - Start the local Backend (the engine)
REM   Runs the FastAPI backend on http://localhost:8000. The local
REM   dashboard (Start-Dashboard.bat) sends its /api/v1 requests here,
REM   and Claude Code drives the heavy processing (audits, content,
REM   citations, web2). Requires local PostgreSQL (:5432) + Redis (:6379)
REM   as configured in backend\.env.
REM ============================================================
cd /d "%~dp0backend"
title AIOS Backend (local :8000)

echo.
echo   Starting the local AIOS backend on http://localhost:8000 ...
echo   (Needs PostgreSQL + Redis running - see backend\.env)
echo.

.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000

echo.
echo   Backend stopped. Close this window.
pause >nul
