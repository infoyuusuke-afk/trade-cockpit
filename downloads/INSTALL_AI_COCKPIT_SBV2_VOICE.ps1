param(
    [string]$Root = "C:\\AI_Cockpit_OneClick_Starter",
    [string]$RuntimeDir = ""
)

$ErrorActionPreference = "Stop"

function Resolve-RuntimeDir {
    param([string]$Preferred)

    if (-not [string]::IsNullOrWhiteSpace($Preferred)) {
        $collector = Join-Path $Preferred "MS2_RSS_100_Collector.ps1"
        if (Test-Path -LiteralPath $collector) { return $Preferred }
    }

    $desktopCandidates = @(
        [Environment]::GetFolderPath("Desktop"),
        (Join-Path $env:USERPROFILE "Desktop"),
        (Join-Path $env:USERPROFILE "OneDrive\Desktop")
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique

    foreach ($desktop in $desktopCandidates) {
        $hit = Get-ChildItem -LiteralPath $desktop -Recurse -File -Filter "MS2_RSS_100_Collector.ps1" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        if ($hit) { return $hit.Directory.FullName }
    }

    throw "MS2_RSS_100_Collector.ps1 was not found under the Desktop folders."
}

$RuntimeDir = Resolve-RuntimeDir $RuntimeDir
$Collector = Join-Path $RuntimeDir "MS2_RSS_100_Collector.ps1"
$Launcher = Join-Path $Root "START_AI_COCKPIT.ps1"
$ApiStarter = Join-Path $Root "START_SBV2_API.ps1"

if (-not (Test-Path -LiteralPath $Root)) { throw "AI Cockpit root not found: $Root" }
if (-not (Test-Path -LiteralPath $Launcher)) { throw "Launcher not found: $Launcher" }

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
Copy-Item -LiteralPath $Collector -Destination ($Collector + ".bak_sbv2_" + $stamp) -Force
Copy-Item -LiteralPath $Launcher -Destination ($Launcher + ".bak_sbv2_" + $stamp) -Force

Invoke-WebRequest "https://raw.githubusercontent.com/infoyuusuke-afk/trade-cockpit/main/ms2_live/MS2_RSS_100_Collector.ps1" -OutFile $Collector -UseBasicParsing -TimeoutSec 30
Invoke-WebRequest "https://raw.githubusercontent.com/infoyuusuke-afk/trade-cockpit/main/downloads/START_SBV2_API.ps1" -OutFile $ApiStarter -UseBasicParsing -TimeoutSec 30

$c = [IO.File]::ReadAllText($Launcher)

# AI Cockpit voice uses Style-Bert-VITS2 FastAPI on port 5000.
$c = $c.Replace('$SbV2Bat = "C:\sbv2\Style-Bert-VITS2\App.bat"','$SbV2Bat = "" # Cockpit voice uses SBV2 FastAPI on port 5000')

$marker = '# AI_COCKPIT_SBV2_API_V1'
if ($c -notmatch [regex]::Escape($marker)) {
    $needle = 'Write-Log "Startup begins. Root: $Root"'
    if (-not $c.Contains($needle)) { throw "Launcher insertion point not found. Backup was kept." }
    $patch = @'
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
    $c = $c.Replace($needle,$patch)
}

$utf8bom = New-Object System.Text.UTF8Encoding($true)
[IO.File]::WriteAllText($Launcher,$c,$utf8bom)

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host " AI Cockpit SBV2 voice installed" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ("Runtime   : " + $RuntimeDir)
Write-Host ("Collector : " + $Collector)
Write-Host ("API start : " + $ApiStarter)
Write-Host ""
Write-Host "Next AI Cockpit launch uses Style-Bert-VITS2 FastAPI on port 5000." -ForegroundColor Cyan
Write-Host "If the API is unavailable, alerts fall back to Windows SAPI." -ForegroundColor Yellow
