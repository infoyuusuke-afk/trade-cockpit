@echo off
setlocal
set "HTML=%~dp0READ_ONLY_BROKER_CSV_CHECK_OFFLINE.html"
if not exist "%HTML%" (
  echo Offline CSV diagnostic HTML is missing. No CSV was read or sent.
  pause
  exit /b 2
)
REM Browser-only offline file; no external app installation or security setting changes.
start "" "%HTML%"
if errorlevel 1 (
  echo Browser launch failed. You may double-click the HTML directly.
  pause
  exit /b 2
)
exit /b 0
