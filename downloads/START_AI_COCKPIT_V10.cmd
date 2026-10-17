@echo off
setlocal
set "SCRIPT=%~dp0RUN_AI_COCKPIT_V10.ps1"
REM Fail-closed until OWNER's reviewed V10 branch + immutable full commit pin is installed.
REM This launcher never guesses a branch, SHA, or adopts the current checkout.
set "APPROVAL=%~dp0V10_APPROVED_SOURCE.json"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" -ApprovalFile "%APPROVAL%"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" pause
exit /b %RC%
