@echo off
setlocal
set "SCRIPT=%~dp0RUN_AI_COCKPIT_V10.ps1"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" pause
exit /b %RC%
