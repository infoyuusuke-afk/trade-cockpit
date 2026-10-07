param(
    [string]$RepoRoot = "C:\AI_Cockpit_Current\trade-cockpit"
)
$ErrorActionPreference = "Stop"
$desktop = [Environment]::GetFolderPath("Desktop")
$items = @(
    @{ source = (Join-Path $RepoRoot "downloads\START_AI_COCKPIT_VALIDATED.cmd"); dest = (Join-Path $desktop "AI_Cockpit_Start.cmd") },
    @{ source = (Join-Path $RepoRoot "downloads\STOP_AI_COCKPIT_VALIDATED.cmd");  dest = (Join-Path $desktop "AI_Cockpit_Stop.cmd") }
)
foreach ($item in $items) {
    if (-not (Test-Path -LiteralPath $item.source)) { throw ("STARTER_SOURCE_NOT_FOUND: " + $item.source) }
    Copy-Item -LiteralPath $item.source -Destination $item.dest -Force
    Write-Host ("INSTALLED=" + $item.dest) -ForegroundColor Green
}
Write-Host "Daily operation: log in to MarketSpeed II -> AI_Cockpit_Start.cmd. End of day -> AI_Cockpit_Stop.cmd." -ForegroundColor Green
