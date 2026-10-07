param(
    [string]$RepoRoot = "C:\AI_Cockpit_Current\trade-cockpit"
)
$ErrorActionPreference = "Stop"
$source = Join-Path $RepoRoot "downloads\START_AI_COCKPIT_VALIDATED.cmd"
if (-not (Test-Path -LiteralPath $source)) { throw "STARTER_SOURCE_NOT_FOUND" }
$desktop = [Environment]::GetFolderPath("Desktop")
$dest = Join-Path $desktop "AI_Cockpit_Start.cmd"
Copy-Item -LiteralPath $source -Destination $dest -Force
Write-Host ("INSTALLED=" + $dest) -ForegroundColor Green
Write-Host "Tomorrow: log in to MarketSpeed II, then double-click AI_Cockpit_Start.cmd." -ForegroundColor Green
