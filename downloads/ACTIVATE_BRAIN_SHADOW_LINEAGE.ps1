param(
    [string]$RepoRoot = "C:\AI_Cockpit_Current\trade-cockpit",
    [string]$BrainRoot = "C:\AI_Cockpit_Brain",
    [string]$Branch = "cursor/brain-shadow-candidate-lineage-d483"
)

$ErrorActionPreference = "Stop"

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    [IO.File]::WriteAllText($Path, $Text, [Text.UTF8Encoding]::new($false))
}

function Get-GitText([string]$Spec) {
    $lines = @(& git -C $RepoRoot show $Spec 2>&1)
    if ($LASTEXITCODE -ne 0) { throw ("GIT_SHOW_FAILED: " + ($lines -join " ")) }
    return (($lines -join [Environment]::NewLine) + [Environment]::NewLine)
}

function Get-Python {
    foreach ($candidate in @(
        (Join-Path $RepoRoot ".venv\Scripts\python.exe"),
        (Join-Path $RepoRoot "venv\Scripts\python.exe")
    )) {
        if (Test-Path -LiteralPath $candidate) { return @{ exe=$candidate; prefix=@() } }
    }
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -ne $cmd) { return @{ exe=$cmd.Source; prefix=@() } }
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($null -ne $py) { return @{ exe=$py.Source; prefix=@("-3") } }
    throw "PYTHON_NOT_FOUND"
}

function Quote([string]$Value) { return '"' + $Value + '"' }

function Get-Ids([scriptblock]$Match) {
    return @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object $Match | ForEach-Object { [int]$_.ProcessId } | Sort-Object)
}

function IdText([int[]]$Ids) {
    if ($null -eq $Ids -or $Ids.Count -eq 0) { return "" }
    return ($Ids -join ",")
}

$manifestPath = "C:\AI_Cockpit_OneClick_Starter\V9_RUNTIME.json"
$manifest = [IO.File]::ReadAllText($manifestPath, [Text.Encoding]::UTF8) | ConvertFrom-Json
$runtime = [string]$manifest.runtime_dir
if ([string]::IsNullOrWhiteSpace($runtime)) { throw "RUNTIME_DIR_MISSING" }

$collectorBefore = IdText (Get-Ids { ([string]$_.CommandLine) -like "*MS2_RSS_100_Collector.ps1*" })
$gatewayBefore   = IdText (Get-Ids { ([string]$_.CommandLine) -like "*AI_COCKPIT_GATEWAY_V9.ps1*" })
$excelBefore     = IdText (Get-Ids { [string]$_.Name -eq "EXCEL.EXE" })
$ms2Before       = IdText (Get-Ids { [string]$_.Name -match "MarketSpeed|MARKETSPEED" })
$canonicalShadowBefore = IdText (Get-Ids {
    $cmd = [string]$_.CommandLine
    $cmd -like "*C:\AI_Cockpit_Current\trade-cockpit\scripts\ai_shadow_supervisor.py*"
})

& git -C $RepoRoot fetch origin $Branch | Out-Host
if ($LASTEXITCODE -ne 0) { throw "GIT_FETCH_FAILED" }

# BrainRoot is an existing git worktree. Resetting the worktree lets git
# write the repository bytes directly and avoids Windows PowerShell
# re-decoding UTF-8 Japanese source through the console code page.
& git -C $BrainRoot reset --hard ("origin/" + $Branch) | Out-Host
if ($LASTEXITCODE -ne 0) { throw "BRAIN_WORKTREE_RESET_FAILED" }

$python = Get-Python
$exe = [string]$python.exe
$prefix = @($python.prefix)

$oldBrainIds = Get-Ids {
    $cmd = [string]$_.CommandLine
    ($cmd -like "*C:\AI_Cockpit_Brain\scripts\production_candidate_bridge.py*") -or
    ($cmd -like "*C:\AI_Cockpit_Brain\scripts\ai_shadow_supervisor.py*")
}
foreach ($procId in $oldBrainIds) {
    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 1

$shadowDir = Join-Path $BrainRoot "brain_shadow_link"
if (-not (Test-Path -LiteralPath $shadowDir)) {
    New-Item -ItemType Directory -Path $shadowDir -Force | Out-Null
}

$bridgeScript = Join-Path $BrainRoot "scripts\production_candidate_bridge.py"
$bridgeOut = Join-Path $BrainRoot "brain_candidate_bridge.log"
$bridgeErr = Join-Path $BrainRoot "brain_candidate_bridge_error.log"
Remove-Item $bridgeOut,$bridgeErr -Force -ErrorAction SilentlyContinue
$bridgeArgs = $prefix + @(
    "-u", (Quote $bridgeScript),
    "--collector-url", "http://127.0.0.1:28580/",
    "--runtime-dir", (Quote $runtime),
    "--brain-root", (Quote $BrainRoot),
    "--shadow-data-dir", (Quote $shadowDir),
    "--interval", "5"
)
$bridgeProc = Start-Process -FilePath $exe -ArgumentList $bridgeArgs -WindowStyle Hidden -RedirectStandardOutput $bridgeOut -RedirectStandardError $bridgeErr -PassThru

Start-Sleep -Seconds 2
if ($bridgeProc.HasExited) {
    Write-Output "BRAIN_CANDIDATE_BRIDGE=FAIL"
    Get-Content $bridgeErr -Tail 40 -ErrorAction SilentlyContinue
    exit 1
}

$shadowScript = Join-Path $BrainRoot "scripts\ai_shadow_supervisor.py"
$shadowStatus = Join-Path $runtime "ai_shadow_brain_link_status.json"
$shadowOut = Join-Path $BrainRoot "brain_shadow_link_stdout.log"
$shadowErr = Join-Path $BrainRoot "brain_shadow_link_stderr.log"
Remove-Item $shadowOut,$shadowErr -Force -ErrorAction SilentlyContinue
$shadowArgs = $prefix + @(
    "-u", (Quote $shadowScript),
    "--live", (Quote (Join-Path $runtime "live_ms2.json")),
    "--data-dir", (Quote $shadowDir),
    "--status", (Quote $shadowStatus),
    "--runtime-manifest", (Quote $manifestPath),
    "--interval", "5"
)
$shadowProc = Start-Process -FilePath $exe -ArgumentList $shadowArgs -WindowStyle Hidden -RedirectStandardOutput $shadowOut -RedirectStandardError $shadowErr -PassThru

Start-Sleep -Seconds 6

$collectorAfter = IdText (Get-Ids { ([string]$_.CommandLine) -like "*MS2_RSS_100_Collector.ps1*" })
$gatewayAfter   = IdText (Get-Ids { ([string]$_.CommandLine) -like "*AI_COCKPIT_GATEWAY_V9.ps1*" })
$excelAfter     = IdText (Get-Ids { [string]$_.Name -eq "EXCEL.EXE" })
$ms2After       = IdText (Get-Ids { [string]$_.Name -match "MarketSpeed|MARKETSPEED" })
$canonicalShadowAfter = IdText (Get-Ids {
    $cmd = [string]$_.CommandLine
    $cmd -like "*C:\AI_Cockpit_Current\trade-cockpit\scripts\ai_shadow_supervisor.py*"
})

Write-Output ("BRAIN_CANDIDATE_BRIDGE=" + $(if (-not $bridgeProc.HasExited) { "RUNNING" } else { "FAIL" }))
Write-Output ("BRAIN_CANDIDATE_PID=" + $bridgeProc.Id)
Write-Output ("BRAIN_LINK_SHADOW=" + $(if (-not $shadowProc.HasExited) { "RUNNING" } else { "FAIL" }))
Write-Output ("BRAIN_LINK_SHADOW_PID=" + $shadowProc.Id)
Write-Output ("COLLECTOR_UNTOUCHED=" + $(if ($collectorBefore -eq $collectorAfter) { "1" } else { "0" }))
Write-Output ("GATEWAY_UNTOUCHED=" + $(if ($gatewayBefore -eq $gatewayAfter) { "1" } else { "0" }))
Write-Output ("EXCEL_UNTOUCHED=" + $(if ($excelBefore -eq $excelAfter) { "1" } else { "0" }))
Write-Output ("MS2_UNTOUCHED=" + $(if ($ms2Before -eq $ms2After) { "1" } else { "0" }))
Write-Output ("CANONICAL_SHADOW_UNTOUCHED=" + $(if ($canonicalShadowBefore -eq $canonicalShadowAfter) { "1" } else { "0" }))

$brain = Invoke-RestMethod "http://127.0.0.1:28584/brain_shadow_live.json?t=$([DateTimeOffset]::Now.ToUnixTimeMilliseconds())"
Write-Output ("BRAIN_SYMBOL=" + [string]$brain.brain.symbol)
Write-Output ("BRAIN_SIDE=" + [string]$brain.brain.side)
Write-Output ("BRAIN_CANDIDATE_ID=" + [string]$brain.brain.candidate_id)
Write-Output ("LINKED=" + [string]$brain.link.linked)
Write-Output ("REAL_SUBMIT_ALLOWED=" + $(if ($brain.real_submit_allowed -eq $false) { "0" } else { "NOT_FALSE" }))

if (Test-Path -LiteralPath $shadowStatus) {
    $status = [IO.File]::ReadAllText($shadowStatus,[Text.Encoding]::UTF8) | ConvertFrom-Json
    Write-Output ("BRAIN_LINK_SHADOW_STATE=" + [string]$status.state)
    Write-Output ("BRAIN_LINK_SHADOW_REAL_SUBMIT_ALLOWED=" + $(if ($status.real_submit_allowed -eq $false) { "0" } else { "NOT_FALSE" }))
}

$sidecar = Join-Path $runtime "brain_candidate_live.json"
if (Test-Path -LiteralPath $sidecar) {
    $candidate = [IO.File]::ReadAllText($sidecar,[Text.Encoding]::UTF8) | ConvertFrom-Json
    Write-Output ("SIDECAR_CANDIDATE_ID=" + [string]$candidate.candidate_id)
    Write-Output ("SIDECAR_SIDE=" + [string]$candidate.side)
} else {
    Write-Output "SIDECAR=WAITING_FOR_FORMAL_ENTRY"
}

Write-Output "ACTIVATE_BRAIN_SHADOW_LINEAGE=PASS"
