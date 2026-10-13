@echo off
setlocal
set "SCRIPT=%~dp0READ_ONLY_BROKER_CSV_CHECK_WIN.ps1"
if not exist "%SCRIPT%" (
  echo CSV checker is missing. No data was read or sent.
  pause
  exit /b 2
)
where powershell.exe >nul 2>nul
if errorlevel 1 (
  echo Windows PowerShell is unavailable. No data was read or sent.
  pause
  exit /b 2
)
REM No execution-policy override, account connection, network request or install.
powershell.exe -NoProfile -File "%SCRIPT%"
if errorlevel 1 (
  echo Diagnostic blocked or could not run. No CSV was uploaded.
  pause
  exit /b 2
)
exit /b 0
