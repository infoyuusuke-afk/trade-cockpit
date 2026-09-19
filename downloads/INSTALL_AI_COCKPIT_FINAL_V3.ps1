param(
    [string]$Root = "C:\AI_Cockpit_OneClick_Starter"
)

$ErrorActionPreference = "Stop"

function Resolve-RuntimeDir {
    $roots = @(
        [Environment]::GetFolderPath("Desktop"),
        (Join-Path $env:USERPROFILE "Desktop"),
        (Join-Path $env:USERPROFILE "OneDrive\Desktop")
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique

    $collectorHits = foreach($r in $roots) {
        Get-ChildItem -LiteralPath $r -Recurse -File -Filter "MS2_RSS_100_Collector.ps1" -ErrorAction SilentlyContinue
    }

    $preferred = @(
        $collectorHits |
        Where-Object { $_.FullName -like "*MarketSpeed II RSS\files*" } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    )
    if($preferred.Count -gt 0) { return $preferred[0].Directory.FullName }

    $liveHits = foreach($r in $roots) {
        Get-ChildItem -LiteralPath $r -Recurse -File -Filter "live_ms2.json" -ErrorAction SilentlyContinue
    }
    $live = @($liveHits | Sort-Object LastWriteTime -Descending | Select-Object -First 1)
    if($live.Count -gt 0) { return $live[0].Directory.FullName }

    $any = @($collectorHits | Sort-Object LastWriteTime -Descending | Select-Object -First 1)
    if($any.Count -gt 0) { return $any[0].Directory.FullName }

    throw "MS2 runtime folder not found."
}

function Decode-Utf8Base64([string]$Value) {
    return [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Value))
}

if(-not(Test-Path -LiteralPath $Root)) {
    New-Item -ItemType Directory -Path $Root -Force | Out-Null
}

$RuntimeDir = Resolve-RuntimeDir
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"

$rootFiles = @(
    "START_AI_COCKPIT.ps1",
    "START_AI_COCKPIT.cmd",
    "START_SBV2_API.ps1",
    "AI_Cockpit_Local_Gateway.ps1",
    "STOP_AI_COCKPIT.ps1",
    "STOP_AI_COCKPIT.cmd"
)

$runtimeFiles = @(
    "MS2_RSS_100_Collector.ps1",
    "Kioxia_Safety_Heartbeat.ps1",
    "BUILD_KIOXIA_TIME_STATS.ps1",
    "MS2_Common_Engine.ps1",
    "watchlist_100.json"
)

foreach($name in $rootFiles) {
    $p = Join-Path $Root $name
    if(Test-Path -LiteralPath $p) {
        Copy-Item -LiteralPath $p -Destination ($p + ".bak_final_" + $stamp) -Force
    }
}

foreach($name in $runtimeFiles) {
    $p = Join-Path $RuntimeDir $name
    if(Test-Path -LiteralPath $p) {
        Copy-Item -LiteralPath $p -Destination ($p + ".bak_final_" + $stamp) -Force
    }
}

Write-Host "[1/6] Stopping old AI Cockpit processes..." -ForegroundColor Cyan
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object {
    $cmd = [string]$_.CommandLine
    if([string]::IsNullOrWhiteSpace($cmd)) { return }

    $managed = (
        $cmd -match 'MS2_RSS_100_Collector\.ps1' -or
        $cmd -match 'Kioxia_Safety_Heartbeat\.ps1' -or
        $cmd -match 'AI_Cockpit_Local_Gateway\.ps1' -or
        $cmd -match 'Kioxia_RSS_Live_Watcher\.ps1' -or
        $cmd -match 'AUTO_START_MS2_100\.ps1' -or
        $cmd -match 'server_fastapi\.py' -or
        ($cmd -match 'Style-Bert-VITS2' -and $cmd -match 'app\.py') -or
        ($cmd -match 'Style-Bert-VITS2' -and $cmd -match 'App\.bat')
    )

    if($managed) {
        try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {}
    }
}

$base = "https://raw.githubusercontent.com/infoyuusuke-afk/trade-cockpit/main"
$cache = "?x=" + (Get-Date -Format "yyyyMMddHHmmss")

Write-Host "[2/6] Installing clean launcher..." -ForegroundColor Cyan
Invoke-WebRequest ($base + "/downloads/START_AI_COCKPIT_CLEAN.ps1" + $cache) -OutFile (Join-Path $Root "START_AI_COCKPIT.ps1") -UseBasicParsing -TimeoutSec 30
Invoke-WebRequest ($base + "/downloads/START_AI_COCKPIT_CLEAN.cmd" + $cache) -OutFile (Join-Path $Root "START_AI_COCKPIT.cmd") -UseBasicParsing -TimeoutSec 30
Invoke-WebRequest ($base + "/downloads/START_SBV2_API.ps1" + $cache) -OutFile (Join-Path $Root "START_SBV2_API.ps1") -UseBasicParsing -TimeoutSec 30
Invoke-WebRequest ($base + "/downloads/AI_Cockpit_Local_Gateway.ps1" + $cache) -OutFile (Join-Path $Root "AI_Cockpit_Local_Gateway.ps1") -UseBasicParsing -TimeoutSec 30
Invoke-WebRequest ($base + "/downloads/STOP_AI_COCKPIT.ps1" + $cache) -OutFile (Join-Path $Root "STOP_AI_COCKPIT.ps1") -UseBasicParsing -TimeoutSec 30

Write-Host "[3/6] Refreshing Collector, Heartbeat and stats..." -ForegroundColor Cyan
Invoke-WebRequest ($base + "/ms2_live/MS2_RSS_100_Collector.ps1" + $cache) -OutFile (Join-Path $RuntimeDir "MS2_RSS_100_Collector.ps1") -UseBasicParsing -TimeoutSec 30
Invoke-WebRequest ($base + "/ms2_live/Kioxia_Safety_Heartbeat.ps1" + $cache) -OutFile (Join-Path $RuntimeDir "Kioxia_Safety_Heartbeat.ps1") -UseBasicParsing -TimeoutSec 30
Invoke-WebRequest ($base + "/ms2_live/BUILD_KIOXIA_TIME_STATS.ps1" + $cache) -OutFile (Join-Path $RuntimeDir "BUILD_KIOXIA_TIME_STATS.ps1") -UseBasicParsing -TimeoutSec 30
Invoke-WebRequest ($base + "/ms2_live/MS2_Common_Engine.ps1" + $cache) -OutFile (Join-Path $RuntimeDir "MS2_Common_Engine.ps1") -UseBasicParsing -TimeoutSec 30
Invoke-WebRequest ($base + "/ms2_live/watchlist_100.json" + $cache) -OutFile (Join-Path $RuntimeDir "watchlist_100.json") -UseBasicParsing -TimeoutSec 30

Write-Host "[4/6] Converting PowerShell files to UTF-8 BOM..." -ForegroundColor Cyan
$utf8bom = New-Object System.Text.UTF8Encoding($true)
$psFiles = @(
    (Join-Path $Root "START_AI_COCKPIT.ps1"),
    (Join-Path $Root "START_SBV2_API.ps1"),
    (Join-Path $Root "AI_Cockpit_Local_Gateway.ps1"),
    (Join-Path $Root "STOP_AI_COCKPIT.ps1"),
    (Join-Path $RuntimeDir "MS2_RSS_100_Collector.ps1"),
    (Join-Path $RuntimeDir "Kioxia_Safety_Heartbeat.ps1"),
    (Join-Path $RuntimeDir "BUILD_KIOXIA_TIME_STATS.ps1"),
    (Join-Path $RuntimeDir "MS2_Common_Engine.ps1")
)

foreach($p in $psFiles) {
    $txt = [IO.File]::ReadAllText($p,[Text.Encoding]::UTF8)
    [IO.File]::WriteAllText($p,$txt,$utf8bom)
}

Write-Host "[5/6] Installing start/stop shortcuts..." -ForegroundColor Cyan
$stopCmd = Join-Path $Root "STOP_AI_COCKPIT.cmd"
$stopText = @'
@echo off
cd /d "%~dp0"
title AI Cockpit Stop
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0STOP_AI_COCKPIT.ps1"
timeout /t 2 /nobreak >nul
exit /b 0
'@
[IO.File]::WriteAllText($stopCmd,$stopText,$utf8bom)

$desktop = [Environment]::GetFolderPath("Desktop")
$ws = New-Object -ComObject WScript.Shell

$startName = Decode-Utf8Base64 "QUnjgrPjgq/jg5Tjg4Pjg4jotbfli5U="
$stopName  = Decode-Utf8Base64 "QUnjgrPjgq/jg5Tjg4Pjg4jntYLkuoY="

$startLnk = Join-Path $desktop ($startName + ".lnk")
$s = $ws.CreateShortcut($startLnk)
$s.TargetPath = Join-Path $Root "START_AI_COCKPIT.cmd"
$s.WorkingDirectory = $Root
$s.Description = "AI Cockpit clean startup"
$s.Save()

$stopLnk = Join-Path $desktop ($stopName + ".lnk")
$s2 = $ws.CreateShortcut($stopLnk)
$s2.TargetPath = $stopCmd
$s2.WorkingDirectory = $Root
$s2.Description = "Stop AI Cockpit background processes"
$s2.Save()

Write-Host "[6/6] Verifying installation..." -ForegroundColor Cyan
$collectorText = [IO.File]::ReadAllText((Join-Path $RuntimeDir "MS2_RSS_100_Collector.ps1"),[Text.Encoding]::UTF8)
$heartbeatText = [IO.File]::ReadAllText((Join-Path $RuntimeDir "Kioxia_Safety_Heartbeat.ps1"),[Text.Encoding]::UTF8)
$launcherText = [IO.File]::ReadAllText((Join-Path $Root "START_AI_COCKPIT.ps1"),[Text.Encoding]::UTF8)

if($collectorText -notmatch 'SBV2 ONLY') { throw "Collector SBV2-only verification failed." }
if($heartbeatText -match 'New-Object -ComObject SAPI\.SpVoice') { throw "Heartbeat still contains Windows SAPI." }
if($launcherText -notmatch 'READY - opening one AI Cockpit page') { throw "Clean launcher verification failed." }

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host " AI COCKPIT FINAL MIGRATION COMPLETE" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ("Runtime : " + $RuntimeDir)
Write-Host "Voice   : SBV2 ONLY" -ForegroundColor Cyan
Write-Host "Browser : localhost:28581 ONLY" -ForegroundColor Cyan
Write-Host "Console : UTF-8 BOM" -ForegroundColor Cyan
Write-Host "Startup : progress from 0 to 100 percent" -ForegroundColor Cyan
Write-Host ""
Write-Host "Close old browser tabs once, then use the desktop AI Cockpit start shortcut." -ForegroundColor Yellow
