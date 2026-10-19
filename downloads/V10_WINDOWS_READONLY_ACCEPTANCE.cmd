@echo off
setlocal
REM OWNER-operated local inspection only. NO Controller start/stop or trading.
set "SCRIPT=%~dp0V10_WINDOWS_READONLY_ACCEPTANCE.ps1"
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%SCRIPT%"
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" echo V10 observation check BLOCKED. Do not bypass safety checks.
pause
exit /b %RC%
