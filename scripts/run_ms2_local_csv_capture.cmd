@echo off
setlocal
if not "%~1"=="" (
  echo BLOCKED: ARGUMENTS_NOT_SUPPORTED
  exit /b 2
)
pushd "%~dp0.." || (
  echo BLOCKED: CHECKOUT_NOT_FOUND
  exit /b 1
)
python -m scripts.ms2_local_csv_capture
set "capture_exit=%ERRORLEVEL%"
popd
if not defined CI pause
exit /b %capture_exit%
