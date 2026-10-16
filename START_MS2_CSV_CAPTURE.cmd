@echo off
setlocal
if not "%~1"=="" (
  echo BLOCKED: ARGUMENTS_NOT_SUPPORTED
  exit /b 2
)
call "%~dp0scripts\run_ms2_local_csv_capture.cmd"
exit /b %ERRORLEVEL%
