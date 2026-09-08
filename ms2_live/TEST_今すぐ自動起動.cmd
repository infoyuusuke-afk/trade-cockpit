@echo off
setlocal
cd /d "%~dp0"
title AI Cockpit MS2 Auto Start Test
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0AUTO_START_MS2_100.ps1"
if errorlevel 1 pause
