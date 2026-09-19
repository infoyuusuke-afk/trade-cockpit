@echo off
cd /d "%~dp0"
title AI Cockpit Startup
chcp 65001 >nul
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0START_AI_COCKPIT.ps1"
exit /b %ERRORLEVEL%
