param(
    [string]$RepoRoot = "",
    [string]$Branch = "integration/v7-runtime-and-cards",
    [string]$ExpectedSha = "",
    [switch]$SkipGitUpdate
)

# One-shot entry point: update (git fetch/checkout a PINNED branch, or an
# exact SHA if given) + backup (previous V8 logs/state, timestamped) +
# start (Controller V8), so the person running this never has to type
# several separate diagnostic commands by hand.
#
# 2026-09-25 P0 fix: $Branch used to default to "" and silently fall back
# to "whatever branch this checkout happens to be on right now" - an
# implicit, unverified target. It now defaults to the one reviewed
# integration branch, and every git step that can fail (fetch/checkout/
# reset) is fatal: on failure this script stops before ever starting the
# Controller ("fail-closed"), it does not fall back to running whatever
# happened to already be on disk. After updating, the actual branch/SHA is
# re-read from git and compared against what was requested; a mismatch is
# also fatal. Pass -SkipGitUpdate only when you deliberately want to run
# the exact commit already checked out (e.g. re-running after a crash) -
# even then, the branch/SHA actually on disk is printed so it's never
# ambiguous what is about to start.

$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
    if (-not [string]::IsNullOrWhiteSpace($RepoRoot)) { return $RepoRoot }
    $candidate = Split-Path -Parent $PSScriptRoot
    if (Test-Path -LiteralPath (Join-Path $candidate "card_system.js")) { return $candidate }
    throw "Could not resolve the trade-cockpit repo root from this script's location. Pass -RepoRoot explicitly."
}

function Invoke-GitFatal([string]$RepoPath, [string[]]$GitArgs, [string]$FailMessage) {
    $output = & git -C $RepoPath @GitArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw ($FailMessage + " (git " + ($GitArgs -join ' ') + "): " + ($output -join " | "))
    }
    return $output
}

$repo = Resolve-RepoRoot
Write-Host "==================================================" -ForegroundColor DarkCyan
Write-Host " AI COCKPIT V8 - update + backup + start" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor DarkCyan
Write-Host ("Repo:   " + $repo) -ForegroundColor Cyan
Write-Host ("Branch: " + $Branch) -ForegroundColor Cyan
if (-not [string]::IsNullOrWhiteSpace($ExpectedSha)) {
    Write-Host ("Pinned SHA: " + $ExpectedSha) -ForegroundColor Cyan
}

try {
    if (-not $SkipGitUpdate) {
        Write-Host ("Updating checkout: fetching origin/" + $Branch + "...") -ForegroundColor Yellow
        Invoke-GitFatal $repo @("fetch", "origin", $Branch, "--quiet") "git fetch failed - refusing to start with a possibly-stale or partial checkout" | Out-Null
        Invoke-GitFatal $repo @("checkout", $Branch, "--quiet") "git checkout failed" | Out-Null
        Invoke-GitFatal $repo @("reset", "--hard", ("origin/" + $Branch), "--quiet") "git reset --hard failed" | Out-Null
    } else {
        Write-Host "Skipping git update (-SkipGitUpdate) - using whatever is already checked out." -ForegroundColor DarkGray
    }

    $actualBranch = (Invoke-GitFatal $repo @("rev-parse", "--abbrev-ref", "HEAD") "could not read the current branch after update").Trim()
    $actualSha = (Invoke-GitFatal $repo @("rev-parse", "HEAD") "could not read the current commit after update").Trim()
    Write-Host ("Now on " + $actualBranch + " @ " + $actualSha.Substring(0, 8)) -ForegroundColor Green

    if (-not $SkipGitUpdate -and $actualBranch -ne $Branch) {
        throw "Branch mismatch after checkout: expected '$Branch', got '$actualBranch'. Refusing to start Controller against an unexpected branch."
    }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedSha) -and -not $actualSha.StartsWith($ExpectedSha)) {
        throw "SHA mismatch after checkout: expected '$ExpectedSha', got '$actualSha'. Refusing to start Controller against an unverified commit."
    }
} catch {
    Write-Host ""
    Write-Host "==================================================" -ForegroundColor Red
    Write-Host " UPDATE FAILED - CONTROLLER NOT STARTED (fail-closed)" -ForegroundColor Red
    Write-Host "==================================================" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Press Enter to close"
    [Environment]::Exit(1)
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
& (Join-Path $repo "downloads\AI_COCKPIT_CONTROLLER_V8.ps1") -RepoRoot $repo -ExpectedBranch $Branch
