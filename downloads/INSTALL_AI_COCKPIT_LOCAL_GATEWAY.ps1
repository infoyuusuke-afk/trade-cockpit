param(
    [string]$Root = "C:\\AI_Cockpit_OneClick_Starter"
)

$ErrorActionPreference="Stop"
$GatewayUrl="https://raw.githubusercontent.com/infoyuusuke-afk/trade-cockpit/main/downloads/AI_Cockpit_Local_Gateway.ps1"
$Gateway=Join-Path $Root "AI_Cockpit_Local_Gateway.ps1"
$LauncherPs1=Join-Path $Root "START_AI_COCKPIT.ps1"
$LauncherCmd=Join-Path $Root "START_AI_COCKPIT.cmd"

if(-not(Test-Path -LiteralPath $Root)){throw "Root not found: $Root"}
if(-not(Test-Path -LiteralPath $LauncherPs1)){throw "Launcher PS1 not found: $LauncherPs1"}
if(-not(Test-Path -LiteralPath $LauncherCmd)){throw "Launcher CMD not found: $LauncherCmd"}

Invoke-WebRequest -Uri $GatewayUrl -OutFile $Gateway -UseBasicParsing -TimeoutSec 30

$stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$backup="$LauncherCmd.bak_localgateway_$stamp"
Copy-Item -LiteralPath $LauncherCmd -Destination $backup -Force

$cmd = @'
@echo off
setlocal
cd /d "%~dp0"
title AI Cockpit Launcher
chcp 65001 >nul

REM Start local LIVE gateway first. If already running, the second instance will exit when port is busy.
start "" /min powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0AI_Cockpit_Local_Gateway.ps1"

REM Start the existing AI Cockpit sequence (MarketSpeed II / Excel / Collector / checks).
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0START_AI_COCKPIT.ps1"

REM Open the LIVE cockpit from localhost so browser security does not block local MS2 data.
start "" "http://127.0.0.1:28581/?live=1"

echo.
echo ========================================
echo  AI Cockpit LIVE: http://127.0.0.1:28581/?live=1
echo  Press any key to close this window.
echo ========================================
pause >nul
endlocal
'@

$utf8bom=New-Object System.Text.UTF8Encoding($true)
[IO.File]::WriteAllText($LauncherCmd,$cmd,$utf8bom)

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host " Local LIVE Gateway installed" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ("Gateway     : "+$Gateway)
Write-Host ("CMD backup  : "+$backup)
Write-Host ""
Write-Host "The installer no longer patches START_AI_COCKPIT.ps1." -ForegroundColor Cyan
Write-Host "START_AI_COCKPIT.cmd now starts the gateway, runs the existing launcher, then opens localhost LIVE." -ForegroundColor Cyan
Write-Host "Next start URL: http://127.0.0.1:28581/?live=1" -ForegroundColor Green
