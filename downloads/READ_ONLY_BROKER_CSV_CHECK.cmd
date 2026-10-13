@echo off
setlocal
set "ROOT=%~dp0.."
cd /d "%ROOT%" || exit /b 2
REM Probe both interpreters before showing any dialog. A Windows "python"
REM app-execution alias or an incomplete installation is not a working Python.
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -c "import sys, tkinter; assert sys.version_info >= (3, 9)" >nul 2>nul
  if not errorlevel 1 (
    py -3 "scripts\private_broker_csv_picker.py"
    if errorlevel 1 exit /b 2
    exit /b 0
  )
)
where python >nul 2>nul
if not errorlevel 1 (
  python -c "import sys, tkinter; assert sys.version_info >= (3, 9)" >nul 2>nul
  if not errorlevel 1 (
    python "scripts\private_broker_csv_picker.py"
    if errorlevel 1 exit /b 2
    exit /b 0
  )
)
echo Python 3.9+ with Tkinter is required. No CSV was read or uploaded.
pause
exit /b 2
