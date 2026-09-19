param(
    [string]$Root = "C:\AI_Cockpit_OneClick_Starter"
)

$ErrorActionPreference = "Stop"

function Resolve-RuntimeDir {
    $desktopRoots = @(
        [Environment]::GetFolderPath("Desktop"),
        (Join-Path $env:USERPROFILE "Desktop"),
        (Join-Path $env:USERPROFILE "OneDrive\Desktop")
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique

    $liveHits = foreach ($d in $desktopRoots) {
        Get-ChildItem -LiteralPath $d -Recurse -File -Filter "live_ms2.json" -ErrorAction SilentlyContinue
    }
    $live = @($liveHits | Sort-Object LastWriteTime -Descending | Select-Object -First 1)
    if ($live.Count -gt 0) { return $live[0].Directory.FullName }

    $collectorHits = foreach ($d in $desktopRoots) {
        Get-ChildItem -LiteralPath $d -Recurse -File -Filter "MS2_RSS_100_Collector.ps1" -ErrorAction SilentlyContinue
    }
    $collector = @($collectorHits | Sort-Object LastWriteTime -Descending | Select-Object -First 1)
    if ($collector.Count -gt 0) { return $collector[0].Directory.FullName }

    throw "MS2 runtime folder could not be found."
}

$RuntimeDir = Resolve-RuntimeDir
$LauncherPs1 = Join-Path $Root "START_AI_COCKPIT.ps1"
$LauncherCmd = Join-Path $Root "START_AI_COCKPIT.cmd"
$Gateway = Join-Path $Root "AI_Cockpit_Local_Gateway.ps1"
$ApiStarter = Join-Path $Root "START_SBV2_API.ps1"
$Collector = Join-Path $RuntimeDir "MS2_RSS_100_Collector.ps1"

if (-not (Test-Path -LiteralPath $LauncherPs1)) { throw "Launcher PS1 not found: $LauncherPs1" }
if (-not (Test-Path -LiteralPath $LauncherCmd)) { throw "Launcher CMD not found: $LauncherCmd" }
if (-not (Test-Path -LiteralPath $Collector)) { throw "Collector not found: $Collector" }

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
Copy-Item -LiteralPath $LauncherPs1 -Destination ($LauncherPs1 + ".bak_single_tab_" + $stamp) -Force
Copy-Item -LiteralPath $LauncherCmd -Destination ($LauncherCmd + ".bak_single_tab_" + $stamp) -Force
Copy-Item -LiteralPath $Collector -Destination ($Collector + ".bak_single_tab_" + $stamp) -Force

# Refresh the runtime components.
Invoke-WebRequest "https://raw.githubusercontent.com/infoyuusuke-afk/trade-cockpit/main/ms2_live/MS2_RSS_100_Collector.ps1" -OutFile $Collector -UseBasicParsing -TimeoutSec 30
Invoke-WebRequest "https://raw.githubusercontent.com/infoyuusuke-afk/trade-cockpit/main/downloads/AI_Cockpit_Local_Gateway.ps1" -OutFile $Gateway -UseBasicParsing -TimeoutSec 30
Invoke-WebRequest "https://raw.githubusercontent.com/infoyuusuke-afk/trade-cockpit/main/downloads/START_SBV2_API.ps1" -OutFile $ApiStarter -UseBasicParsing -TimeoutSec 30

# Patch the PS1 so it does not open the generated local HTML or the SBV2 Gradio WebUI.
$c = [IO.File]::ReadAllText($LauncherPs1)

$c = $c.Replace(
    'Start-Process -FilePath $cockpitFile.FullName | Out-Null',
    'Write-Log ("Cockpit browser open is handled by START_AI_COCKPIT.cmd: " + $cockpitFile.Name) "OK"'
)
$c = $c.Replace(
    'Start-Process $cockpitFile.FullName | Out-Null',
    'Write-Log ("Cockpit browser open is handled by START_AI_COCKPIT.cmd: " + $cockpitFile.Name) "OK"'
)

# Disable App.bat/Gradio auto-start. Runtime voice is FastAPI on port 5000.
$c = [regex]::Replace(
    $c,
    '\$SbV2Bat\s*=\s*"[^"]*"',
    '$SbV2Bat = "" # Gradio WebUI disabled; voice uses FastAPI port 5000'
)

$utf8bom = New-Object System.Text.UTF8Encoding($true)
[IO.File]::WriteAllText($LauncherPs1,$c,$utf8bom)

# The CMD is the single owner of browser launch: localhost cockpit only.
$cmd = @'
@echo off
setlocal
cd /d "%~dp0"
title AI Cockpit Launcher
chcp 65001 >nul

REM 1) Start local gateway in the background.
start "" /min powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0AI_Cockpit_Local_Gateway.ps1" -RuntimeDir "__RUNTIME__"

REM 2) Run MarketSpeed / Excel / Collector / Heartbeat / SBV2 FastAPI startup checks.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0START_AI_COCKPIT.ps1"

REM 3) Open exactly one cockpit browser target.
start "" "http://127.0.0.1:28581/?live=1"

echo.
echo ========================================
echo  AI Cockpit LIVE
echo  http://127.0.0.1:28581/?live=1
echo ========================================
echo  Local HTML / GitHub public cockpit / SBV2 WebUI are not auto-opened.
echo  Press any key to close this launcher window.
pause >nul
endlocal
'@
$cmd = $cmd.Replace("__RUNTIME__",$RuntimeDir)
[IO.File]::WriteAllText($LauncherCmd,$cmd,$utf8bom)

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host " AI Cockpit SINGLE-TAB startup installed" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ("Runtime : " + $RuntimeDir)
Write-Host "Browser : http://127.0.0.1:28581/?live=1" -ForegroundColor Cyan
Write-Host "Disabled: local HTML auto-open / GitHub public auto-open / SBV2 WebUI auto-open" -ForegroundColor Cyan
