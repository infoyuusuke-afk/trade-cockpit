@echo off
setlocal
cd /d "%~dp0"
title KIOXIA RSS LIVE DIAGNOSTIC

echo ================================================
echo KIOXIA RSS LIVE - DIAGNOSTIC START
echo ================================================
echo.
echo Current folder:
echo %CD%
echo.

if not exist "%~dp0Kioxia_MS2_RSS_Live_Signals.xlsx" (
  echo ERROR: Kioxia_MS2_RSS_Live_Signals.xlsx is missing.
  echo Put all extracted files in the same folder.
  echo.
  pause
  exit /b 1
)

if not exist "%~dp0Kioxia_RSS_Live_Watcher.ps1" (
  echo ERROR: Kioxia_RSS_Live_Watcher.ps1 is missing.
  echo Put all extracted files in the same folder.
  echo.
  pause
  exit /b 1
)

where powershell.exe >nul 2>&1
if errorlevel 1 (
  echo ERROR: powershell.exe was not found.
  echo.
  pause
  exit /b 1
)

echo 1. Start MarketSpeed II and log in.
echo 2. Open the Excel workbook in this folder.
echo 3. In Excel, confirm the MarketSpeed II RSS tab is CONNECTED.
echo 4. Keep Excel open, then press any key here.
echo.
echo PowerShell will stay open even if an error occurs.
echo Send a screenshot of the red error text to ChatGPT.
echo.

pause

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -NoExit -Command "& '%~dp0Kioxia_RSS_Live_Watcher.ps1'"

echo.
echo PowerShell returned to the launcher.
pause
