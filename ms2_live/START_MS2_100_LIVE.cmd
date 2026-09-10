@echo off
setlocal
cd /d "%~dp0"
title MS2 RSS 100 STOCK LIVE

echo ===================================================
echo MS2 RSS - 100 STOCK LIVE TOP5
echo ===================================================
echo 1. MarketSpeed II: login
echo 2. Excel: open Kioxia_MS2_RSS_Live_Signals.xlsx
echo 3. Excel RSS tab: confirm CONNECTED
echo 4. Keep Excel open
echo.
pause

start "AI Cockpit Strategy Voice" /min powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0SPEAK_TODAY_STRATEGY.ps1"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -NoExit -File "%~dp0MS2_RSS_100_Collector.ps1"

echo.
pause
