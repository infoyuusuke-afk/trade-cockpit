@echo off
setlocal
if not "%~1"=="" exit /b 2
pushd "%~dp0.." || exit /b 1
python -m scripts.ms2_offline_acceptance
set "acceptance_exit=%ERRORLEVEL%"
popd
exit /b %acceptance_exit%
