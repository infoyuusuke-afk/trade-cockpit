@echo off
setlocal
cd /d "%~dp0"
title AI Cockpit MS2 Auto Start Setup
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALL_WEEKDAY_AUTO_START.ps1"
if errorlevel 1 (
  echo.
  echo 設定できませんでした。このファイルを右クリックし「管理者として実行」してください。
  pause
)
