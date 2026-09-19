param(
    [string]$Root = "C:\\AI_Cockpit_OneClick_Starter"
)

$ErrorActionPreference = "Stop"

function Resolve-RuntimeDir {
    $roots = @(
        [Environment]::GetFolderPath("Desktop"),
        (Join-Path $env:USERPROFILE "Desktop"),
        (Join-Path $env:USERPROFILE "OneDrive\Desktop")
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique

    $liveHits = foreach($r in $roots){
        Get-ChildItem -LiteralPath $r -Recurse -File -Filter "live_ms2.json" -ErrorAction SilentlyContinue
    }
    $live = @($liveHits | Sort-Object LastWriteTime -Descending | Select-Object -First 1)
    if($live.Count -gt 0){ return $live[0].Directory.FullName }

    $collectorHits = foreach($r in $roots){
        Get-ChildItem -LiteralPath $r -Recurse -File -Filter "MS2_RSS_100_Collector.ps1" -ErrorAction SilentlyContinue
    }
    $preferred = @($collectorHits | Where-Object { $_.FullName -like "*MarketSpeed II RSS\files*" } | Sort-Object LastWriteTime -Descending | Select-Object -First 1)
    if($preferred.Count -gt 0){ return $preferred[0].Directory.FullName }

    $any = @($collectorHits | Sort-Object LastWriteTime -Descending | Select-Object -First 1)
    if($any.Count -gt 0){ return $any[0].Directory.FullName }

    throw "MS2 runtime folder not found."
}

if(-not(Test-Path -LiteralPath $Root)){
    New-Item -ItemType Directory -Path $Root -Force | Out-Null
}
$RuntimeDir=Resolve-RuntimeDir
$stamp=Get-Date -Format "yyyyMMdd_HHmmss"

$targets=@(
    (Join-Path $Root "START_AI_COCKPIT.ps1"),
    (Join-Path $Root "START_AI_COCKPIT.cmd"),
    (Join-Path $Root "START_SBV2_API.ps1"),
    (Join-Path $Root "AI_Cockpit_Local_Gateway.ps1"),
    (Join-Path $Root "STOP_AI_COCKPIT.ps1"),
    (Join-Path $RuntimeDir "MS2_RSS_100_Collector.ps1"),
    (Join-Path $RuntimeDir "Kioxia_Safety_Heartbeat.ps1"),
    (Join-Path $RuntimeDir "BUILD_KIOXIA_TIME_STATS.ps1"),
    (Join-Path $RuntimeDir "MS2_Common_Engine.ps1"),
    (Join-Path $RuntimeDir "watchlist_100.json")
)

foreach($t in $targets){
    if(Test-Path -LiteralPath $t){
        Copy-Item -LiteralPath $t -Destination ($t+".bak_final_"+$stamp) -Force
    }
}

# Stop old AI Cockpit managed processes so old voices/tabs cannot survive this migration.
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object {
    $cmd=[string]$_.CommandLine
    if([string]::IsNullOrWhiteSpace($cmd)){ return }
    if(
        $cmd -match 'MS2_RSS_100_Collector\.ps1' -or
        $cmd -match 'Kioxia_Safety_Heartbeat\.ps1' -or
        $cmd -match 'AI_Cockpit_Local_Gateway\.ps1' -or
        $cmd -match 'Kioxia_RSS_Live_Watcher\.ps1' -or
        $cmd -match 'AUTO_START_MS2_100\.ps1' -or
        $cmd -match 'server_fastapi\.py' -or
        ($cmd -match 'Style-Bert-VITS2' -and $cmd -match 'app\.py') -or
        ($cmd -match 'Style-Bert-VITS2' -and $cmd -match 'App\.bat')
    ){
        try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {}
    }
}

$base="https://raw.githubusercontent.com/infoyuusuke-afk/trade-cockpit/main"
$cache="?x="+(Get-Date -Format "yyyyMMddHHmmss")

Invoke-WebRequest ($base+"/downloads/START_AI_COCKPIT_CLEAN.ps1"+$cache) -OutFile (Join-Path $Root "START_AI_COCKPIT.ps1") -UseBasicParsing -TimeoutSec 30
Invoke-WebRequest ($base+"/downloads/START_AI_COCKPIT_CLEAN.cmd"+$cache) -OutFile (Join-Path $Root "START_AI_COCKPIT.cmd") -UseBasicParsing -TimeoutSec 30
Invoke-WebRequest ($base+"/downloads/START_SBV2_API.ps1"+$cache) -OutFile (Join-Path $Root "START_SBV2_API.ps1") -UseBasicParsing -TimeoutSec 30
Invoke-WebRequest ($base+"/downloads/AI_Cockpit_Local_Gateway.ps1"+$cache) -OutFile (Join-Path $Root "AI_Cockpit_Local_Gateway.ps1") -UseBasicParsing -TimeoutSec 30
Invoke-WebRequest ($base+"/downloads/STOP_AI_COCKPIT.ps1"+$cache) -OutFile (Join-Path $Root "STOP_AI_COCKPIT.ps1") -UseBasicParsing -TimeoutSec 30

Invoke-WebRequest ($base+"/ms2_live/MS2_RSS_100_Collector.ps1"+$cache) -OutFile (Join-Path $RuntimeDir "MS2_RSS_100_Collector.ps1") -UseBasicParsing -TimeoutSec 30
Invoke-WebRequest ($base+"/ms2_live/Kioxia_Safety_Heartbeat.ps1"+$cache) -OutFile (Join-Path $RuntimeDir "Kioxia_Safety_Heartbeat.ps1") -UseBasicParsing -TimeoutSec 30
Invoke-WebRequest ($base+"/ms2_live/BUILD_KIOXIA_TIME_STATS.ps1"+$cache) -OutFile (Join-Path $RuntimeDir "BUILD_KIOXIA_TIME_STATS.ps1") -UseBasicParsing -TimeoutSec 30
Invoke-WebRequest ($base+"/ms2_live/MS2_Common_Engine.ps1"+$cache) -OutFile (Join-Path $RuntimeDir "MS2_Common_Engine.ps1") -UseBasicParsing -TimeoutSec 30
Invoke-WebRequest ($base+"/ms2_live/watchlist_100.json"+$cache) -OutFile (Join-Path $RuntimeDir "watchlist_100.json") -UseBasicParsing -TimeoutSec 30

# Re-save PowerShell scripts with UTF-8 BOM so Windows PowerShell 5.1 renders Japanese safely.
$utf8bom=New-Object System.Text.UTF8Encoding($true)
$psFiles=@(
    (Join-Path $Root "START_AI_COCKPIT.ps1"),
    (Join-Path $Root "START_SBV2_API.ps1"),
    (Join-Path $Root "AI_Cockpit_Local_Gateway.ps1"),
    (Join-Path $Root "STOP_AI_COCKPIT.ps1"),
    (Join-Path $RuntimeDir "MS2_RSS_100_Collector.ps1"),
    (Join-Path $RuntimeDir "Kioxia_Safety_Heartbeat.ps1"),
    (Join-Path $RuntimeDir "BUILD_KIOXIA_TIME_STATS.ps1"),
    (Join-Path $RuntimeDir "MS2_Common_Engine.ps1")
)
foreach($p in $psFiles){
    $txt=[IO.File]::ReadAllText($p,[Text.Encoding]::UTF8)
    [IO.File]::WriteAllText($p,$txt,$utf8bom)
}

# Stop command wrapper.
$stopCmd=Join-Path $Root "STOP_AI_COCKPIT.cmd"
$stopText=@'
@echo off
cd /d "%~dp0"
title AI Cockpit Stop
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0STOP_AI_COCKPIT.ps1"
timeout /t 2 /nobreak >nul
exit /b 0
'@
[IO.File]::WriteAllText($stopCmd,$stopText,$utf8bom)

# Desktop shortcuts: overwrite start target and add stop shortcut.
$desktop=[Environment]::GetFolderPath("Desktop")
$ws=New-Object -ComObject WScript.Shell

$startLnk=Join-Path $desktop "AIコクピット起動.lnk"
$s=$ws.CreateShortcut($startLnk)
$s.TargetPath=Join-Path $Root "START_AI_COCKPIT.cmd"
$s.WorkingDirectory=$Root
$s.Description="AI Cockpit clean startup"
$s.Save()

$stopLnk=Join-Path $desktop "AIコクピット終了.lnk"
$s2=$ws.CreateShortcut($stopLnk)
$s2.TargetPath=$stopCmd
$s2.WorkingDirectory=$Root
$s2.Description="Stop AI Cockpit background processes"
$s2.Save()

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host " AI COCKPIT FINAL MIGRATION COMPLETE" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ("Runtime : "+$RuntimeDir)
Write-Host "Voice   : SBV2 ONLY (Windows SAPI disabled)" -ForegroundColor Cyan
Write-Host "Browser : localhost:28581 only" -ForegroundColor Cyan
Write-Host "Console : UTF-8 BOM refreshed" -ForegroundColor Cyan
Write-Host "Progress: 0-100 percent shown during startup" -ForegroundColor Cyan
Write-Host ""
Write-Host "Close the two old browser tabs once. They will not be reopened by the new launcher." -ForegroundColor Yellow
Write-Host "Then use desktop shortcut: AIコクピット起動" -ForegroundColor Green
