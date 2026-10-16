@echo off
setlocal
if not "%~1"=="" (
  echo BLOCKED: ARGUMENTS_NOT_SUPPORTED
  exit /b 2
)
where powershell.exe >nul 2>nul
if errorlevel 1 (
  echo BLOCKED: POWERSHELL_UNAVAILABLE
  pause
  exit /b 1
)
powershell.exe -NoLogo -NoProfile -STA -File "%~dp0scripts\ms2_native_offline_capture.ps1"
set "exitcode=%ERRORLEVEL%"
pause
exit /b %exitcode%
