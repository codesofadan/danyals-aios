@echo off
REM ============================================================
REM   AIOS - Build the Citation Assistant browser extension
REM
REM   Produces extension\dist, which is THE FOLDER YOU LOAD INTO
REM   CHROME. Loading the `extension` folder itself does not work
REM   and never has: manifest.json there names service-worker.js,
REM   panel.html and filler.js, which only exist after this build.
REM   Chrome reports that as "Could not load manifest" / "Could not
REM   load background script".
REM
REM   dist\ is deliberately not in git, so the loaded extension can
REM   never drift from the source that produced it. Re-run this
REM   after pulling changes, then press Reload on the extension in
REM   chrome://extensions.
REM
REM   Requires Node.js.
REM ============================================================
cd /d "%~dp0extension"
title AIOS - Build Citation Assistant

echo.
echo   Building the Citation Assistant extension ...
echo.

if not exist node_modules (
  echo   Installing dependencies (first run only) ...
  call npm install || goto :failed
)

call npm run build || goto :failed

echo.
echo   Done. Now load it in Chrome:
echo.
echo     1. Open  chrome://extensions
echo     2. Turn on  Developer mode  (top right)
echo     3. Click  Load unpacked
echo     4. Select this folder:
echo.
echo          %~dp0extension\dist
echo.
echo   Then pair it: in the dashboard go to Settings - Extension,
echo   create a token, and paste it into the extension's side panel
echo   along with the dashboard URL. If that URL is not localhost,
echo   Chrome will ask permission to reach it - choose Allow.
echo.
pause >nul
exit /b 0

:failed
echo.
echo   BUILD FAILED. The output above says why; dist\ was not updated.
echo.
pause >nul
exit /b 1
