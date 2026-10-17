@echo off
setlocal
REM V10 ONLY. Old V8/V9 and desktop shortcuts must not be selected.
REM No implicit branch, no automatic Git mutation, no unapproved startup.
set "LAUNCHER=%~dp0START_AI_COCKPIT_V10.ps1"
set "APPROVAL=%~dp0V10_APPROVED_SOURCE.json"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%LAUNCHER%" -ApprovalFile "%APPROVAL%"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo V10 startup blocked; see the fail-closed reason above.
  pause
)
exit /b %RC%
