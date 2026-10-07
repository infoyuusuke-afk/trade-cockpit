@echo off
title AI Cockpit Validated Start
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "C:\AI_Cockpit_Current\trade-cockpit\downloads\START_AI_COCKPIT_VALIDATED.ps1"
if errorlevel 1 (
  echo.
  echo AI Cockpit startup failed. Keep this window open and show the error.
)
pause
