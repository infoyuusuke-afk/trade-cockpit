param(
    [string]$Root = "C:\\AI_Cockpit_OneClick_Starter",
    [string]$RuntimeDir = (Join-Path $env:USERPROFILE "Desktop\\デイトレ\\MarketSpeed II RSS\\files")
)

$ErrorActionPreference="Stop"
$Collector=Join-Path $RuntimeDir "MS2_RSS_100_Collector.ps1"
$Launcher=Join-Path $Root "START_AI_COCKPIT.ps1"
$ApiStarter=Join-Path $Root "START_SBV2_API.ps1"

if(-not(Test-Path -LiteralPath $RuntimeDir)){throw "Runtime folder not found: $RuntimeDir"}
if(-not(Test-Path -LiteralPath $Launcher)){throw "Launcher not found: $Launcher"}

$stamp=Get-Date -Format "yyyyMMdd_HHmmss"
if(Test-Path -LiteralPath $Collector){Copy-Item $Collector "$Collector.bak_sbv2_$stamp" -Force}
Copy-Item $Launcher "$Launcher.bak_sbv2_$stamp" -Force

Invoke-WebRequest "https://raw.githubusercontent.com/infoyuusuke-afk/trade-cockpit/main/ms2_live/MS2_RSS_100_Collector.ps1" -OutFile $Collector -UseBasicParsing -TimeoutSec 30
Invoke-WebRequest "https://raw.githubusercontent.com/infoyuusuke-afk/trade-cockpit/main/downloads/START_SBV2_API.ps1" -OutFile $ApiStarter -UseBasicParsing -TimeoutSec 30

$c=[IO.File]::ReadAllText($Launcher)

# The cockpit uses FastAPI port 5000. Do not auto-start App.bat/Gradio for runtime voice.
$c=$c.Replace('$SbV2Bat = "C:\sbv2\Style-Bert-VITS2\App.bat"','$SbV2Bat = "" # Cockpit voice uses SBV2 FastAPI on port 5000')

$marker='# AI_COCKPIT_SBV2_API_V1'
if($c -notmatch [regex]::Escape($marker)){
    $needle='Write-Log "Startup begins. Root: $Root"'
    if(-not $c.Contains($needle)){throw "Launcher insertion point not found. Backup kept."}
    $patch=@'
Write-Log "Startup begins. Root: $Root"

# AI_COCKPIT_SBV2_API_V1
$SbV2ApiStarter = Join-Path $Root "START_SBV2_API.ps1"
if (Test-Path -LiteralPath $SbV2ApiStarter) {
    try {
        & $SbV2ApiStarter
        Write-Log "SBV2 FastAPI ready on port 5000." "OK"
    } catch {
        Write-Log ("SBV2 FastAPI startup failed; Windows SAPI fallback will be used: " + $_.Exception.Message) "WARN"
    }
}
'@
    $c=$c.Replace($needle,$patch)
}
$utf8bom=New-Object Text.UTF8Encoding($true)
[IO.File]::WriteAllText($Launcher,$c,$utf8bom)

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host " AI Cockpit SBV2 voice installed" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ("Collector : "+$Collector)
Write-Host ("API start : "+$ApiStarter)
Write-Host ""
Write-Host "Next AI Cockpit launch uses Style-Bert-VITS2 on port 5000." -ForegroundColor Cyan
Write-Host "If the API is unavailable, alerts fall back to Windows SAPI instead of becoming silent." -ForegroundColor Yellow
