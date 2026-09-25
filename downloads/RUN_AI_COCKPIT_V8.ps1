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

# 2026-09-25 P0 fix (blocker before real-machine use): this script used to
# only update the git checkout and assume that was enough. It is not -
# the Controller runs Watcher/Heartbeat/Collector from Desktop-side
# RuntimeDir (the MS2 kit install), a completely separate location from
# the repo checkout. Repo updated != runtime updated. Concretely: the
# Watcher bridge port was moved 28581->28582 in the repo, but without this
# deploy phase the OLD Watcher.ps1 (still hardcoding 28581) stays running
# from RuntimeDir forever, re-colliding with the new Gateway. This phase
# copies the 3 runtime scripts into RuntimeDir every run, validating each
# one (staged copy -> AST parse -> SHA256 confirm) before touching
# anything real, and refuses to deploy at all - not partially - if even
# one fails.
function Resolve-RuntimeDirForDeploy {
    $roots = @(
        [Environment]::GetFolderPath("Desktop"),
        (Join-Path $env:USERPROFILE "Desktop"),
        (Join-Path $env:USERPROFILE "OneDrive\Desktop")
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique
    $hits = foreach ($r in $roots) {
        Get-ChildItem -LiteralPath $r -Recurse -File -Filter "MS2_RSS_100_Collector.ps1" -ErrorAction SilentlyContinue
    }
    # Only the canonical ...\MarketSpeed II RSS\files directory is a
    # valid runtime. Nested backup/staging folders under "files" must
    # never be selected as RuntimeDir.
    $canonical = @($hits | Where-Object {
        $_.Directory.Name -eq "files" -and
        $null -ne $_.Directory.Parent -and
        $_.Directory.Parent.Name -eq "MarketSpeed II RSS"
    } | Sort-Object FullName -Unique)
    if ($canonical.Count -eq 1) { return $canonical[0].Directory.FullName }
    if ($canonical.Count -gt 1) {
        $paths = ($canonical | ForEach-Object { $_.Directory.FullName } | Select-Object -Unique) -join " | "
        throw "Multiple canonical MS2 runtime folders found. Refusing to guess: $paths"
    }
    throw "Canonical MS2 runtime folder not found under Desktop (expected ...\MarketSpeed II RSS\files)."
}

function Get-Sha256Hex([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
}

function Test-PowerShellSyntaxOk([string]$Path) {
    $parseErrors = $null
    $tokens = $null
    [System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$parseErrors) | Out-Null
    return $parseErrors.Count -eq 0
}

$RUNTIME_DEPLOY_FILES = @(
    "Kioxia_RSS_Live_Watcher.ps1",
    "Kioxia_Safety_Heartbeat.ps1",
    "MS2_RSS_100_Collector.ps1"
)

function Deploy-RuntimeFiles([string]$RepoRoot, [string]$RuntimeDir) {
    $staged = @{}
    $allStagedPaths = @()
    try {
        # Phase 1: stage + validate every file first. Nothing real is
        # touched yet - a failure here leaves RuntimeDir completely
        # untouched (fail-closed, not a partial deploy).
        foreach ($name in $RUNTIME_DEPLOY_FILES) {
            $source = Join-Path $RepoRoot ("ms2_live\" + $name)
            if (-not (Test-Path -LiteralPath $source)) {
                throw "Runtime deploy source missing: $source"
            }
            $dest = Join-Path $RuntimeDir $name
            $stagedPath = $dest + ".staged_" + [Guid]::NewGuid().ToString("N").Substring(0, 8) + ".tmp"
            Copy-Item -LiteralPath $source -Destination $stagedPath -Force
            # Track the staged path immediately, before validation, so the
            # catch block below can always clean it up - including when
            # THIS file is the one that fails validation.
            $allStagedPaths += $stagedPath
            if (-not (Test-PowerShellSyntaxOk $stagedPath)) {
                throw "Runtime deploy: AST parse failed for staged copy of $name - not deploying anything."
            }
            $sourceHash = Get-Sha256Hex $source
            $stagedHash = Get-Sha256Hex $stagedPath
            if ($sourceHash -ne $stagedHash) {
                throw "Runtime deploy: SHA256 mismatch between source and staged copy of $name - not deploying anything."
            }
            $staged[$name] = @{ staged_path = $stagedPath; dest_path = $dest; sha256 = $sourceHash }
        }
    } catch {
        foreach ($stagedPath in $allStagedPaths) {
            Remove-Item -LiteralPath $stagedPath -Force -ErrorAction SilentlyContinue
        }
        throw
    }

    # Phase 2: every file validated - back up what's currently there, then
    # atomically replace (staged temp files already live in RuntimeDir, so
    # Move-Item is a same-volume rename, not a cross-volume copy).
    $backupRoot = Join-Path (Split-Path -Parent $RuntimeDir) "_v8_runtime_backups"
    if (-not (Test-Path -LiteralPath $backupRoot)) { New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null }
    $backupDir = Join-Path $backupRoot ("runtime_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    $deployedHashes = [ordered]@{}
    foreach ($name in $RUNTIME_DEPLOY_FILES) {
        $entry = $staged[$name]
        if (Test-Path -LiteralPath $entry.dest_path) {
            Copy-Item -LiteralPath $entry.dest_path -Destination (Join-Path $backupDir $name) -Force
        }
        Move-Item -LiteralPath $entry.staged_path -Destination $entry.dest_path -Force
        $deployedHashes[$name] = $entry.sha256
    }

    # Verify from the ACTUAL deployed files, not the source - confirms the
    # move landed the bytes we validated, not something else. Read as
    # explicit UTF-8 (not Get-Content -Raw) for the same BOM-less-UTF-8
    # reason as the JSON reads elsewhere in this file.
    $watcherText = [IO.File]::ReadAllText((Join-Path $RuntimeDir "Kioxia_RSS_Live_Watcher.ps1"), [Text.Encoding]::UTF8)
    if ($watcherText -notmatch [regex]::Escape('Start-LocalJsonBridge $watcherJsonPath 28582')) {
        throw "Runtime deploy verification failed: deployed Watcher does not reference port 28582."
    }
    $collectorText = [IO.File]::ReadAllText((Join-Path $RuntimeDir "MS2_RSS_100_Collector.ps1"), [Text.Encoding]::UTF8)
    if ($collectorText -notmatch "28580") {
        throw "Runtime deploy verification failed: deployed Collector does not reference port 28580."
    }

    return @{ hashes = $deployedHashes; backup_dir = $backupDir }
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

    Write-Host ""
    Write-Host "Deploying runtime scripts (Watcher/Heartbeat/Collector) to RuntimeDir..." -ForegroundColor Yellow
    $runtimeDirForDeploy = Resolve-RuntimeDirForDeploy
    Write-Host ("  RuntimeDir: " + $runtimeDirForDeploy) -ForegroundColor Cyan
    $deployResult = Deploy-RuntimeFiles -RepoRoot $repo -RuntimeDir $runtimeDirForDeploy
    Write-Host ("  Deployed " + $RUNTIME_DEPLOY_FILES.Count + " files, backup: " + $deployResult.backup_dir) -ForegroundColor Green

    $runtimeManifestRoot = "C:\AI_Cockpit_OneClick_Starter"
    if (-not (Test-Path -LiteralPath $runtimeManifestRoot)) { New-Item -ItemType Directory -Path $runtimeManifestRoot -Force | Out-Null }
    $runtimeManifest = [ordered]@{
        repo_sha    = $actualSha
        repo_branch = $actualBranch
        runtime_dir = $runtimeDirForDeploy
        files       = $deployResult.hashes
        deployed_at = (Get-Date).ToString("o")
    }
    $runtimeManifestPath = Join-Path $runtimeManifestRoot "V8_RUNTIME.json"
    [IO.File]::WriteAllText($runtimeManifestPath, ($runtimeManifest | ConvertTo-Json -Depth 6), [Text.UTF8Encoding]::new($false))
    Write-Host ("  Runtime manifest written: " + $runtimeManifestPath) -ForegroundColor Green
} catch {
    Write-Host ""
    Write-Host "==================================================" -ForegroundColor Red
    Write-Host " UPDATE/DEPLOY FAILED - CONTROLLER NOT STARTED (fail-closed)" -ForegroundColor Red
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
