@echo off
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0GROK_TO_COCKPIT_V10.ps1" -Kind grok
echo.
pause
