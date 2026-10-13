@echo off
setlocal
set "ROOT=%~dp0.."
cd /d "%ROOT%"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 "scripts\private_broker_csv_picker.py"
  exit /b %errorlevel%
)
where python >nul 2>nul
if not errorlevel 1 (
  python "scripts\private_broker_csv_picker.py"
  exit /b %errorlevel%
)
echo Python 3 is required. No CSV was read or uploaded.
pause
exit /b 2
