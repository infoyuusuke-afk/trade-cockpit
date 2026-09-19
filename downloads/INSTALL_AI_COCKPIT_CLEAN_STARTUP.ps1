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

    $live = foreach ($r in $roots) {
        Get-ChildItem -LiteralPath $r -Recurse -File -Filter "live_ms2.json" -ErrorAction SilentlyContinue
    }
    $hit = @($live | Sort-Object LastWriteTime -Descending | Select-Object -First 1)
    if ($hit.Count -gt 0) { return $hit[0].Directory.FullName }

    $collectors = foreach ($r in $roots) {
        Get-ChildItem -LiteralPath $r -Recurse -File -Filter "MS2_RSS_100_Collector.ps1" -ErrorAction SilentlyContinue
    }
    $hit = @($collectors | Sort-Object LastWriteTime -Descending | Select-Object -First 1)
    if ($hit.Count -gt 0) { return $hit[0].Directory.FullName }

    throw "MS2 runtime folder not found."
}

$RuntimeDir = Resolve-RuntimeDir
$Ps1 = Join-Path $Root "START_AI_COCKPIT.ps1"
$Cmd = Join-Path $Root "START_AI_COCKPIT.cmd"
$Gateway = Join-Path $Root "AI_Cockpit_Local_Gateway.ps1"
$ApiStarter = Join-Path $Root "START_SBV2_API.ps1"
$Collector = Join-Path $RuntimeDir "MS2_RSS_100_Collector.ps1"

foreach($p in @($Ps1,$Cmd,$Collector)){
    if(-not(Test-Path -LiteralPath $p)){ throw "Required file not found: $p" }
}

$stamp=Get-Date -Format "yyyyMMdd_HHmmss"
Copy-Item -LiteralPath $Ps1 -Destination ($Ps1+".bak_clean_"+$stamp) -Force
Copy-Item -LiteralPath $Cmd -Destination ($Cmd+".bak_clean_"+$stamp) -Force
Copy-Item -LiteralPath $Collector -Destination ($Collector+".bak_clean_"+$stamp) -Force

Invoke-WebRequest "https://raw.githubusercontent.com/infoyuusuke-afk/trade-cockpit/main/ms2_live/MS2_RSS_100_Collector.ps1" -OutFile $Collector -UseBasicParsing -TimeoutSec 30
Invoke-WebRequest "https://raw.githubusercontent.com/infoyuusuke-afk/trade-cockpit/main/downloads/AI_Cockpit_Local_Gateway.ps1" -OutFile $Gateway -UseBasicParsing -TimeoutSec 30
Invoke-WebRequest "https://raw.githubusercontent.com/infoyuusuke-afk/trade-cockpit/main/downloads/START_SBV2_API.ps1" -OutFile $ApiStarter -UseBasicParsing -TimeoutSec 30

$c=[IO.File]::ReadAllText($Ps1)

$c=[regex]::Replace(
    $c,
    '(?im)^\s*\$SbV2Bat\s*=.*$',
    '$SbV2Bat = $null # Gradio disabled; FastAPI port 5000 is used'
)

$c=[regex]::Replace(
    $c,
    '(?im)^(?<indent>\s*)Start-Process[^\r\n]*(?:App\.bat|7860|\$SbV2Bat)[^\r\n]*$',
    '$' + '{indent}Write-Log "SBV2 Gradio UI suppressed; FastAPI runs hidden on port 5000." "OK"'
)

$c=[regex]::Replace(
    $c,
    '(?im)^(?<indent>\s*)Start-Process[^\r\n]*(?:AI_Cockpit_MS2_LIVE\.html|cockpitFile|github\.io\/trade-cockpit|publicCockpitUrl)[^\r\n]*$',
    '$' + '{indent}Write-Log "Cockpit browser open delegated to START_AI_COCKPIT.cmd." "OK"'
)

$utf8bom=New-Object System.Text.UTF8Encoding($true)
[IO.File]::WriteAllText($Ps1,$c,$utf8bom)

$cmdText=@'
@echo off
setlocal
cd /d "%~dp0"
title AI Cockpit Launcher
chcp 65001 >nul

start "" /min powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0AI_Cockpit_Local_Gateway.ps1" -RuntimeDir "__RUNTIME__"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0START_AI_COCKPIT.ps1"

start "" "http://127.0.0.1:28581/?live=1"

endlocal
exit /b 0
'@
$cmdText=$cmdText.Replace("__RUNTIME__",$RuntimeDir)
[IO.File]::WriteAllText($Cmd,$cmdText,$utf8bom)

Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
Where-Object {
    $_.CommandLine -and
    (
        ($_.CommandLine -match 'Style-Bert-VITS2' -and $_.CommandLine -match 'app\.py') -or
        ($_.CommandLine -match 'Style-Bert-VITS2' -and $_.CommandLine -match 'App\.bat')
    ) -and
    ($_.CommandLine -notmatch 'server_fastapi\.py')
} |
ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host " CLEAN STARTUP installed" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "Visible after startup:" -ForegroundColor Cyan
Write-Host "  1) Collector PowerShell"
Write-Host "  2) AI Cockpit browser (127.0.0.1:28581)"
Write-Host ""
Write-Host "Hidden:" -ForegroundColor Cyan
Write-Host "  Heartbeat / Gateway / SBV2 FastAPI"
Write-Host ""
Write-Host "Launcher window now closes automatically." -ForegroundColor Green
