@echo off
REM ============================================================
REM   AIOS - Start the local job Worker
REM   Runs the Celery worker that ACTUALLY EXECUTES background jobs:
REM   audits, content generation, citation audits, WordPress design
REM   replication, web2 publishing, reports.
REM
REM   WITHOUT THIS RUNNING, submitted jobs are accepted and stay
REM   "Queued" forever. That is not a bug in the dashboard - nothing
REM   is there to pick them up. Start-Backend.bat only serves the API.
REM
REM   -Q IS REQUIRED. A worker started without it consumes only the
REM   default "celery" queue, so every job the contract routes to a
REM   duration class (interactive/standard/long/browser) sits unread
REM   and the platform looks idle rather than broken. Keep this list in
REM   step with JobQueue in backend/app/jobs/status.py.
REM
REM   --pool=threads because Celery's default prefork pool does not
REM   work on Windows.
REM
REM   Requires local PostgreSQL + Redis (same backend\.env as the API).
REM ============================================================
cd /d "%~dp0backend"
title AIOS Worker (local jobs)

echo.
echo   Starting the local AIOS job worker ...
echo   (Needs PostgreSQL + Redis running - see backend\.env)
echo   Leave this window open while you use the dashboard.
echo.

.venv\Scripts\python.exe -m celery -A workers.celery_app worker --loglevel=info --pool=threads --concurrency=4 -Q celery,interactive,standard,long,browser

echo.
echo   Worker stopped. Queued jobs will wait until it runs again.
pause >nul
