param(
    [Parameter(Mandatory = $true)]
    [string]$DedicatedUser,

    [string]$RepoRoot = "",
    [string]$SourceRuntimeDir = "",
    [string]$DestinationRoot = "C:\AI_Cockpit_Dedicated"
)

$ErrorActionPreference = "Stop"

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Resolve-RepoRoot([string]$Explicit) {
    if (-not [string]::IsNullOrWhiteSpace($Explicit)) {
        $resolved = [IO.Path]::GetFullPath($Explicit)
        if (-not (Test-Path -LiteralPath (Join-Path $resolved "card_system.js"))) {
            throw "RepoRoot is not a trade-cockpit checkout: $resolved"
        }
        return $resolved
    }

    $candidate = Split-Path -Parent $PSScriptRoot
    if (Test-Path -LiteralPath (Join-Path $candidate "card_system.js")) {
        return $candidate
    }

    throw "Could not resolve RepoRoot. Pass -RepoRoot explicitly."
}

function Resolve-SourceRuntime([string]$Explicit) {
    if (-not [string]::IsNullOrWhiteSpace($Explicit)) {
        $resolved = [IO.Path]::GetFullPath($Explicit)
        if (-not (Test-Path -LiteralPath $resolved -PathType Container)) {
            throw "SourceRuntimeDir does not exist: $resolved"
        }
        return $resolved
    }

    $roots = @(
        [Environment]::GetFolderPath("Desktop"),
        (Join-Path $env:USERPROFILE "Desktop"),
        (Join-Path $env:USERPROFILE "OneDrive\Desktop")
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique

    $hits = foreach ($root in $roots) {
        Get-ChildItem -LiteralPath $root -Recurse -File -Filter "Kioxia_MS2_RSS_Live_Signals.xlsx" -ErrorAction SilentlyContinue
    }

    $canonical = @($hits | Where-Object {
        $_.Directory.Name -eq "files" -and
        $null -ne $_.Directory.Parent -and
        $_.Directory.Parent.Name -eq "MarketSpeed II RSS"
    } | Sort-Object FullName -Unique)

    if ($canonical.Count -eq 1) { return $canonical[0].Directory.FullName }
    if ($canonical.Count -gt 1) {
        $paths = ($canonical | ForEach-Object { $_.Directory.FullName }) -join " | "
        throw "Multiple canonical source runtimes found: $paths"
    }

    throw "Canonical source runtime was not found under Desktop."
}

function Resolve-LocalAccount([string]$Name) {
    if ($null -ne (Get-Command Get-LocalUser -ErrorAction SilentlyContinue)) {
        try { return Get-LocalUser -Name $Name -ErrorAction Stop } catch {}
    }

    $escaped = $Name.Replace("'","''")
    $hit = @(Get-CimInstance Win32_UserAccount -Filter ("LocalAccount=True AND Name='" + $escaped + "'") -ErrorAction SilentlyContinue)
    if ($hit.Count -gt 0) { return $hit[0] }
    return $null
}

if (-not (Test-IsAdministrator)) {
    throw "Run this preparation script from an elevated PowerShell. Administrator rights are required to create the shared runtime and grant the dedicated account access."
}

$currentUser = [Environment]::UserName
if ($currentUser -ieq $DedicatedUser) {
    throw "DedicatedUser must be different from the work account."
}

$account = Resolve-LocalAccount $DedicatedUser
if ($null -eq $account) {
    throw "Local Windows account '$DedicatedUser' does not exist. Create the dedicated account first, then run this preparation."
}

$repo = Resolve-RepoRoot $RepoRoot
$source = Resolve-SourceRuntime $SourceRuntimeDir
$runtime = Join-Path $DestinationRoot "runtime"

$sourceBook = Join-Path $source "Kioxia_MS2_RSS_Live_Signals.xlsx"
if (-not (Test-Path -LiteralPath $sourceBook -PathType Leaf)) {
    throw "Source workbook is missing: $sourceBook"
}

# Never seed from a workbook that is currently open in Excel.
$openKioxia = @()
foreach ($p in @(Get-CimInstance Win32_Process -Filter "Name='EXCEL.EXE'" -ErrorAction SilentlyContinue)) {
    $cmd = [string]$p.CommandLine
    if (
        (-not [string]::IsNullOrWhiteSpace($cmd) -and
         $cmd.IndexOf($sourceBook,[StringComparison]::OrdinalIgnoreCase) -ge 0) -or
        $cmd -match "Kioxia_MS2_RSS_Live_Signals"
    ) {
        $openKioxia += $p
    }
}
if ($openKioxia.Count -gt 0) {
    $ids = ($openKioxia | ForEach-Object { $_.ProcessId }) -join ","
    throw "Kioxia RSS workbook is currently open in Excel PID(s) $ids. Close only the Kioxia workbook before preparing the dedicated runtime."
}

New-Item -ItemType Directory -Path $DestinationRoot -Force | Out-Null
New-Item -ItemType Directory -Path $runtime -Force | Out-Null

# Seed the workbook plus the non-generated runtime dependencies.
$seedFiles = @(
    @{ Source = $sourceBook; Destination = (Join-Path $runtime "Kioxia_MS2_RSS_Live_Signals.xlsx") },
    @{ Source = (Join-Path $repo "ms2_live\watchlist_100.json"); Destination = (Join-Path $runtime "watchlist_100.json") },
    @{ Source = (Join-Path $repo "ms2_live\MS2_Common_Engine.ps1"); Destination = (Join-Path $runtime "MS2_Common_Engine.ps1") },
    @{ Source = (Join-Path $repo "ms2_live\BUILD_KIOXIA_TIME_STATS.ps1"); Destination = (Join-Path $runtime "BUILD_KIOXIA_TIME_STATS.ps1") }
)

foreach ($item in $seedFiles) {
    if (-not (Test-Path -LiteralPath $item.Source -PathType Leaf)) {
        throw "Required dedicated-runtime seed file is missing: " + $item.Source
    }
    Copy-Item -LiteralPath $item.Source -Destination $item.Destination -Force
}

foreach ($optionalName in @(
    "investor_regime.json",
    "overnight_hold_history.csv",
    "overnight_hold_stats.json",
    "overnight_actual_fills.csv",
    "overnight_hold_results_v2.csv"
)) {
    $candidate = Join-Path $source $optionalName
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
        Copy-Item -LiteralPath $candidate -Destination (Join-Path $runtime $optionalName) -Force
    }
}

$hostSource = Join-Path $repo "downloads\AI_COCKPIT_DEDICATED_SESSION_HOST_V1.ps1"
if (-not (Test-Path -LiteralPath $hostSource -PathType Leaf)) {
    # git fetch updates origin/<branch> without updating the local working tree.
    # Materialize the reviewed host script from the fetched branch instead.
    $hostText = & git -C $repo show "origin/fix/v9-ui-voice-convergence:downloads/AI_COCKPIT_DEDICATED_SESSION_HOST_V1.ps1" 2>&1
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace(($hostText -join [Environment]::NewLine))) {
        throw "Dedicated session host script is missing locally and could not be read from origin/fix/v9-ui-voice-convergence."
    }
    $hostSource = Join-Path $env:TEMP "AI_COCKPIT_DEDICATED_SESSION_HOST_V1.ps1"
    [IO.File]::WriteAllText(
        $hostSource,
        ($hostText -join [Environment]::NewLine),
        [Text.UTF8Encoding]::new($false)
    )
}
Copy-Item -LiteralPath $hostSource -Destination (Join-Path $DestinationRoot "START_DEDICATED_SESSION.ps1") -Force

$accountName = if ($DedicatedUser.Contains("\")) { $DedicatedUser } else { $env:COMPUTERNAME + "\" + $DedicatedUser }
$grant = "${accountName}:(OI)(CI)M"
$aclOutput = & icacls.exe $DestinationRoot /inheritance:e /grant $grant /T /C 2>&1
if ($LASTEXITCODE -ne 0) {
    throw ("icacls failed while granting the dedicated account Modify access: " + ($aclOutput -join " | "))
}

$destBook = Join-Path $runtime "Kioxia_MS2_RSS_Live_Signals.xlsx"
$marker = [ordered]@{
    schema = 1
    dedicated_user = $DedicatedUser
    prepared_by = $currentUser
    prepared_at = (Get-Date).ToString("o")
    destination_root = $DestinationRoot
    runtime_dir = $runtime
    source_runtime = $source
    workbook_sha256 = (Get-FileHash -LiteralPath $destBook -Algorithm SHA256).Hash
}

$markerJson = $marker | ConvertTo-Json -Depth 5
[IO.File]::WriteAllText(
    (Join-Path $DestinationRoot "DEDICATED_SESSION_APPROVED.json"),
    $markerJson,
    [Text.UTF8Encoding]::new($false)
)

Write-Host "==================================================" -ForegroundColor DarkCyan
Write-Host " DEDICATED AI COCKPIT RUNTIME PREPARED" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor DarkCyan
Write-Host ("Dedicated user: " + $DedicatedUser) -ForegroundColor Cyan
Write-Host ("Runtime:        " + $runtime) -ForegroundColor Cyan
Write-Host ("Starter:        " + (Join-Path $DestinationRoot "START_DEDICATED_SESSION.ps1")) -ForegroundColor Cyan
Write-Host ""
Write-Host "Next: sign into the dedicated Windows account with Fast User Switching, start/login MarketSpeed II there, then run START_DEDICATED_SESSION.ps1 from that dedicated desktop." -ForegroundColor Yellow
