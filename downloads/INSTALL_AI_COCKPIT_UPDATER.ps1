param(
    [string]$Root = "C:\\AI_Cockpit_OneClick_Starter"
)

$ErrorActionPreference = "Stop"
$UpdaterUrl = "https://infoyuusuke-afk.github.io/trade-cockpit/downloads/AI_Cockpit_Updater.ps1"
$Launcher = Join-Path $Root "START_AI_COCKPIT.ps1"
$Updater = Join-Path $Root "UPDATE_AI_COCKPIT.ps1"

if (-not (Test-Path -LiteralPath $Root)) {
    throw "AI Cockpit root was not found: $Root"
}
if (-not (Test-Path -LiteralPath $Launcher)) {
    throw "Launcher was not found: $Launcher"
}

New-Item -ItemType Directory -Force -Path (Join-Path $Root "Logs"),(Join-Path $Root "Updates") | Out-Null

Write-Host "Downloading AI Cockpit updater..." -ForegroundColor Cyan
Invoke-WebRequest -Uri $UpdaterUrl -OutFile $Updater -UseBasicParsing -TimeoutSec 30

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backup = "$Launcher.bak_updater_$stamp"
Copy-Item -LiteralPath $Launcher -Destination $backup -Force

$content = [IO.File]::ReadAllText($Launcher)
$marker = '# AI_COCKPIT_REMOTE_UPDATER_V1'

if ($content -notmatch [regex]::Escape($marker)) {
    $needle = '$Root = Split-Path -Parent $MyInvocation.MyCommand.Path'
    if (-not $content.Contains($needle)) {
        throw "Launcher structure is different from expected. Backup kept at: $backup"
    }

    $patch = @'
# AI_COCKPIT_REMOTE_UPDATER_V1
$UpdaterScript = Join-Path $Root "UPDATE_AI_COCKPIT.ps1"
if (Test-Path -LiteralPath $UpdaterScript) {
    try {
        & $UpdaterScript -Root $Root
    } catch {
        Write-Host ("[WARN] Update check failed safely: " + $_.Exception.Message) -ForegroundColor Yellow
    }
}
'@

    $content = $content.Replace($needle, $needle + [Environment]::NewLine + $patch)
    $utf8bom = New-Object System.Text.UTF8Encoding($true)
    [IO.File]::WriteAllText($Launcher,$content,$utf8bom)
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host " AI Cockpit updater installed" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ("Launcher backup : " + $backup)
Write-Host ("Updater         : " + $Updater)
Write-Host ""
Write-Host "From the next launch, the latest stable kit will be checked and downloaded automatically." -ForegroundColor Green
Write-Host "Downloaded kits are staged under the Updates folder and are not auto-applied until validation passes." -ForegroundColor Yellow
