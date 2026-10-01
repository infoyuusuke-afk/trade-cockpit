param(
    [string]$DedicatedRoot = "C:\AI_Cockpit_Dedicated",
    [string]$RepoRoot = "",
    [string]$RuntimeDir = "",
    [string]$StateRoot = "",
    [string]$Branch = "fix/v9-ui-voice-convergence"
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepoRoot)) { $RepoRoot = Join-Path $DedicatedRoot "repo" }
if ([string]::IsNullOrWhiteSpace($RuntimeDir)) { $RuntimeDir = Join-Path $DedicatedRoot "runtime" }
if ([string]::IsNullOrWhiteSpace($StateRoot)) { $StateRoot = Join-Path $DedicatedRoot "state" }

function Get-ShortUser([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return "" }
    if ($Value.Contains("\")) { return ($Value -split "\\")[-1] }
    if ($Value.Contains("@")) { return ($Value -split "@")[0] }
    return $Value
}

function Invoke-GitChecked([string[]]$Args) {
    $output = & git @Args 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw ("git " + ($Args -join " ") + " failed: " + ($output -join " | "))
    }
    return $output
}

$markerPath = Join-Path $DedicatedRoot "DEDICATED_SESSION_APPROVED.json"
if (-not (Test-Path -LiteralPath $markerPath -PathType Leaf)) {
    throw "Dedicated-session marker is missing. Run PREPARE_AI_COCKPIT_DEDICATED_RUNTIME_V1.ps1 from the work account first."
}

$marker = [IO.File]::ReadAllText($markerPath,[Text.Encoding]::UTF8) | ConvertFrom-Json
$currentUser = Get-ShortUser ([Environment]::UserName)
$expectedUser = Get-ShortUser ([string]$marker.dedicated_user)
$preparedBy = Get-ShortUser ([string]$marker.prepared_by)

if ([string]::IsNullOrWhiteSpace($expectedUser)) { throw "Marker has no dedicated_user." }
if ($currentUser -ine $expectedUser) {
    throw "Wrong Windows user. Current=$currentUser, expected dedicated user=$expectedUser."
}
if (-not [string]::IsNullOrWhiteSpace($preparedBy) -and $currentUser -ieq $preparedBy) {
    throw "Dedicated host must not run under the work account."
}

$self = Get-Process -Id $PID -ErrorAction Stop
$sessionId = [int]$self.SessionId
if ($sessionId -le 0) {
    throw "Dedicated host requires an interactive Windows session; session 0 is not allowed."
}

$interactive = $false
foreach ($explorer in @(Get-CimInstance Win32_Process -Filter ("Name='explorer.exe' AND SessionId=" + $sessionId) -ErrorAction SilentlyContinue)) {
    try {
        $owner = Invoke-CimMethod -InputObject $explorer -MethodName GetOwner -ErrorAction Stop
        if ((Get-ShortUser ([string]$owner.User)) -ieq $currentUser) {
            $interactive = $true
            break
        }
    } catch {}
}
if (-not $interactive) {
    throw "No Explorer desktop owned by $currentUser was found in session $sessionId. Sign into the dedicated Windows account interactively first."
}

if (-not (Test-Path -LiteralPath $RuntimeDir -PathType Container)) {
    throw "Dedicated runtime does not exist: $RuntimeDir"
}

$workbookPath = Join-Path $RuntimeDir "Kioxia_MS2_RSS_Live_Signals.xlsx"
if (-not (Test-Path -LiteralPath $workbookPath -PathType Leaf)) {
    throw "Dedicated runtime workbook is missing: $workbookPath"
}

if (-not [string]::IsNullOrWhiteSpace([string]$marker.workbook_sha256)) {
    $actualWorkbookHash = (Get-FileHash -LiteralPath $workbookPath -Algorithm SHA256).Hash
    if ($actualWorkbookHash -ne [string]$marker.workbook_sha256) {
        throw "Dedicated workbook hash differs from the prepared marker. Re-run preparation before starting."
    }
}

$foreignExcel = @(Get-Process EXCEL -ErrorAction SilentlyContinue | Where-Object { [int]$_.SessionId -eq $sessionId })
if ($foreignExcel.Count -gt 0) {
    $details = ($foreignExcel | ForEach-Object { "PID " + $_.Id + " / " + $_.MainWindowTitle }) -join " | "
    throw "Excel is already running in the dedicated session. Refusing to start beside it: $details"
}

$ms2 = @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
    $_.ProcessName -match "MarketSpeed|MARKETSPEED" -and [int]$_.SessionId -eq $sessionId
})
if ($ms2.Count -eq 0) {
    throw "MarketSpeed II is not running in dedicated session $sessionId. Start and log in to MarketSpeed II in this dedicated Windows account first."
}

if ($null -eq (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "git.exe is required in the dedicated session."
}

$repoParent = Split-Path -Parent $RepoRoot
if (-not (Test-Path -LiteralPath $repoParent)) {
    New-Item -ItemType Directory -Path $repoParent -Force | Out-Null
}

if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot ".git") -PathType Container)) {
    if (Test-Path -LiteralPath $RepoRoot) {
        $existing = @(Get-ChildItem -LiteralPath $RepoRoot -Force -ErrorAction SilentlyContinue)
        if ($existing.Count -gt 0) {
            throw "RepoRoot exists but is not an empty git checkout: $RepoRoot"
        }
    }
    Invoke-GitChecked @(
        "clone",
        "--branch",$Branch,
        "--single-branch",
        "https://github.com/infoyuusuke-afk/trade-cockpit.git",
        $RepoRoot
    ) | Out-Null
} else {
    Invoke-GitChecked @("-C",$RepoRoot,"fetch","origin",$Branch,"--quiet") | Out-Null
    Invoke-GitChecked @("-C",$RepoRoot,"checkout",$Branch,"--quiet") | Out-Null
    Invoke-GitChecked @("-C",$RepoRoot,"reset","--hard",("origin/" + $Branch),"--quiet") | Out-Null
}

$hostState = [ordered]@{
    user = $currentUser
    session_id = $sessionId
    dedicated_root = $DedicatedRoot
    repo_root = $RepoRoot
    runtime_dir = $RuntimeDir
    state_root = $StateRoot
    branch = $Branch
    started_at = (Get-Date).ToString("o")
}
if (-not (Test-Path -LiteralPath $StateRoot)) {
    New-Item -ItemType Directory -Path $StateRoot -Force | Out-Null
}
[IO.File]::WriteAllText(
    (Join-Path $StateRoot "DEDICATED_SESSION_HOST.json"),
    ($hostState | ConvertTo-Json -Depth 5),
    [Text.UTF8Encoding]::new($false)
)

Write-Host "==================================================" -ForegroundColor DarkCyan
Write-Host " AI COCKPIT DEDICATED SESSION HOST" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor DarkCyan
Write-Host ("User:    " + $currentUser) -ForegroundColor Green
Write-Host ("Session: " + $sessionId) -ForegroundColor Green
Write-Host ("Runtime: " + $RuntimeDir) -ForegroundColor Green
Write-Host ("Repo:    " + $RepoRoot) -ForegroundColor Green
Write-Host ""
Write-Host "Dedicated-session preflight passed. Starting V9..." -ForegroundColor Green

& (Join-Path $RepoRoot "downloads\RUN_AI_COCKPIT_V9.ps1") `
    -RepoRoot $RepoRoot `
    -Branch $Branch `
    -RuntimeDirOverride $RuntimeDir `
    -Root $StateRoot
