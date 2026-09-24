param(
    [string]$RepoRoot = "",
    [string]$Branch = "",
    [switch]$SkipGitUpdate
)

# One-shot entry point: update (git fetch/checkout this branch) + backup
# (previous V8 logs/state, timestamped) + start (Controller V8), so the
# person running this never has to type several separate diagnostic
# commands by hand. Safe to re-run any time - it only ever touches this
# repo checkout's working tree and this controller's own state/log files.

$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
    if (-not [string]::IsNullOrWhiteSpace($RepoRoot)) { return $RepoRoot }
    $candidate = Split-Path -Parent $PSScriptRoot
    if (Test-Path -LiteralPath (Join-Path $candidate "card_system.js")) { return $candidate }
    throw "Could not resolve the trade-cockpit repo root from this script's location. Pass -RepoRoot explicitly."
}

$repo = Resolve-RepoRoot
Write-Host "==================================================" -ForegroundColor DarkCyan
Write-Host " AI COCKPIT V8 - update + backup + start" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor DarkCyan
Write-Host ("Repo: " + $repo) -ForegroundColor Cyan

if (-not $SkipGitUpdate) {
    Push-Location -LiteralPath $repo
    try {
        $currentBranch = (& git rev-parse --abbrev-ref HEAD 2>$null).Trim()
        $targetBranch = if ([string]::IsNullOrWhiteSpace($Branch)) { $currentBranch } else { $Branch }
        Write-Host ("Updating checkout: fetching origin, checking out " + $targetBranch + "...") -ForegroundColor Yellow
        & git fetch origin $targetBranch --quiet 2>&1 | Out-Null
        & git checkout $targetBranch --quiet 2>&1 | Out-Null
        & git reset --hard ("origin/" + $targetBranch) --quiet 2>&1 | Out-Null
        $sha = (& git rev-parse --short HEAD 2>$null).Trim()
        Write-Host ("Now on " + $targetBranch + " @ " + $sha) -ForegroundColor Green
    } catch {
        Write-Host ("Git update failed, continuing with the checkout as-is: " + $_.Exception.Message) -ForegroundColor Yellow
    } finally {
        Pop-Location
    }
} else {
    Write-Host "Skipping git update (-SkipGitUpdate)." -ForegroundColor DarkGray
}

$root = "C:\AI_Cockpit_OneClick_Starter"
$logDir = Join-Path $root "Logs\V8"
if (Test-Path -LiteralPath $logDir) {
    $backupDir = Join-Path $root ("Logs\V8_backup_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
    Write-Host ("Backing up previous logs to: " + $backupDir) -ForegroundColor Yellow
    Move-Item -LiteralPath $logDir -Destination $backupDir -Force -ErrorAction SilentlyContinue
}
$stateFile = Join-Path $root "V8_CONTROLLER_STATE.json"
if (Test-Path -LiteralPath $stateFile) {
    $stateBackup = Join-Path $root ("V8_CONTROLLER_STATE_backup_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".json")
    Copy-Item -LiteralPath $stateFile -Destination $stateBackup -Force -ErrorAction SilentlyContinue
}

Write-Host "Starting Controller V8..." -ForegroundColor Cyan
Write-Host ""
& (Join-Path $repo "downloads\AI_COCKPIT_CONTROLLER_V8.ps1") -RepoRoot $repo
