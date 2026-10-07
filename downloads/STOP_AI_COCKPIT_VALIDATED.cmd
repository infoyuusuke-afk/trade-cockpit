@echo off
title AI Cockpit Validated Stop
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "C:\AI_Cockpit_Current\trade-cockpit\downloads\STOP_AI_COCKPIT_VALIDATED.ps1"
if errorlevel 1 (
  echo.
  echo AI Cockpit shutdown needs checking. Keep this window open and show the error.
)
pause
