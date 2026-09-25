
param(
    [string]$RepoRoot = "C:\Users\yusuk\code\trade-cockpit",
    [string]$Branch = "fix/v9-ui-voice-convergence",
    [Parameter(Mandatory=$true)][string]$ExpectedSha,
    [string]$Root = "C:\AI_Cockpit_OneClick_Starter"
)

$ErrorActionPreference = "Stop"
$V8State = Join-Path $Root "V8_CONTROLLER_STATE.json"
$V8ControllerName = "AI_COCKPIT_CONTROLLER_V8.ps1"

function Invoke-GitFatal([string]$RepoPath,[string[]]$GitArgs,[string]$Message) {
    $out = & git -C $RepoPath @GitArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw ($Message + " (git " + ($GitArgs -join " ") + "): " + ($out -join " | "))
    }
    return @($out)
}

function Get-CommandLine([int]$Pid) {
    try {
        $p = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $Pid) -ErrorAction SilentlyContinue
        if ($null -eq $p) { return "" }
        return [string]$p.CommandLine
    } catch { return "" }
}

function Test-PidIdentity([int]$Pid,[string]$ExpectedScript) {
    if ($Pid -le 0 -or [string]::IsNullOrWhiteSpace($ExpectedScript)) { return $false }
    $cmd = Get-CommandLine $Pid
    return (-not [string]::IsNullOrWhiteSpace($cmd) -and $cmd -match [regex]::Escape($ExpectedScript))
}

function Stop-ExactProcess([int]$Pid,[string]$ExpectedScript,[string]$Label) {
    if ($Pid -le 0) { return }
    $p = Get-Process -Id $Pid -ErrorAction SilentlyContinue
    if ($null -eq $p) { return }
    if (-not (Test-PidIdentity $Pid $ExpectedScript)) {
        Write-Host ("  NOT stopping PID {0}: it no longer matches {1}" -f $Pid,$ExpectedScript) -ForegroundColor Yellow
        return
    }
    Stop-Process -Id $Pid -Force -ErrorAction Stop
    Write-Host ("  stopped {0} PID {1}" -f $Label,$Pid) -ForegroundColor Green
}

function Get-PortOwner([int]$Port) {
    try {
        $c = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $c) { return [int]$c.OwningProcess }
    } catch {}
    return 0
}

function Wait-PortsClear([int[]]$Ports,[int]$Seconds=15) {
    $deadline=(Get-Date).AddSeconds($Seconds)
    while((Get-Date) -lt $deadline) {
        $busy=@($Ports | Where-Object { (Get-PortOwner $_) -gt 0 })
        if($busy.Count -eq 0) { return $true }
        Start-Sleep -Milliseconds 300
    }
    return $false
}

function Read-JsonUtf8([string]$Path) {
    return ([IO.File]::ReadAllText($Path,[Text.Encoding]::UTF8) | ConvertFrom-Json)
}

Write-Host "==================================================" -ForegroundColor DarkCyan
Write-Host " AI COCKPIT V8 -> V9 SAFE SWITCH" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor DarkCyan
Write-Host ""

# Prepare the exact target first. Nothing in live V8 is touched until the
# V9 commit is available and the checkout is clean.
if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot ".git"))) {
    throw "RepoRoot is not a git checkout: $RepoRoot"
}
$dirty = (Invoke-GitFatal $RepoRoot @("status","--porcelain") "git status failed") -join [Environment]::NewLine
if (-not [string]::IsNullOrWhiteSpace($dirty)) {
    throw "Repo checkout has uncommitted changes. V8 was NOT stopped. Resolve/stash them before switching."
}

Write-Host ("Preparing " + $Branch + " @ " + $ExpectedSha.Substring(0,[Math]::Min(8,$ExpectedSha.Length)) + "...") -ForegroundColor Cyan
Invoke-GitFatal $RepoRoot @("fetch","origin",$Branch,"--quiet") "git fetch failed; V8 was NOT stopped" | Out-Null
$remoteSha = ((Invoke-GitFatal $RepoRoot @("rev-parse",("origin/"+$Branch)) "could not resolve target branch") -join "").Trim()
if (-not $remoteSha.StartsWith($ExpectedSha)) {
    throw "Target SHA changed/mismatched. Expected $ExpectedSha but origin/$Branch is $remoteSha. V8 was NOT stopped."
}
Write-Host "  target commit verified before teardown." -ForegroundColor Green

$state=$null
if (Test-Path -LiteralPath $V8State) {
    try { $state=Read-JsonUtf8 $V8State } catch { throw "Could not read V8 state safely. V8 was NOT stopped: " + $_.Exception.Message }
}

# Stop V8 controller first so it cannot restart workers during teardown.
# Exact script identity only; no generic PowerShell or Excel process scan.
Write-Host "Stopping V8 controller..." -ForegroundColor Cyan
$controllers=@(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    ([string]$_.CommandLine) -match [regex]::Escape($V8ControllerName)
})
foreach($ctl in $controllers) {
    Stop-ExactProcess ([int]$ctl.ProcessId) $V8ControllerName "V8 controller"
}
Start-Sleep -Milliseconds 700

# Stop only V8 state-owned worker PIDs whose CURRENT command line still
# identifies the expected script. PID reuse cannot kill an unrelated app.
if ($null -ne $state) {
    Write-Host "Stopping V8-owned workers..." -ForegroundColor Cyan
    $map=[ordered]@{
        watcher_pid   = "Kioxia_RSS_Live_Watcher.ps1"
        heartbeat_pid = "Kioxia_Safety_Heartbeat.ps1"
        collector_pid = "MS2_RSS_100_Collector.ps1"
        gateway_pid   = "AI_COCKPIT_GATEWAY_V8.ps1"
    }
    foreach($entry in $map.GetEnumerator()) {
        $prop=$state.PSObject.Properties[$entry.Key]
        if($null -eq $prop) { continue }
        Stop-ExactProcess ([int]$prop.Value) ([string]$entry.Value) ([string]$entry.Key)
    }
}

# Excel and MarketSpeed II are deliberately NOT killed. V9 reuses the
# canonical workbook if it is already open and validates Workbook.FullName.
Write-Host "Waiting for V8 ports 28580/28581/28582 to clear..." -ForegroundColor Cyan
if (-not (Wait-PortsClear @(28580,28581,28582) 15)) {
    Write-Host ""
    Write-Host "FOREIGN/STALE SESSION STILL PRESENT - V9 NOT STARTED" -ForegroundColor Red
    foreach($port in @(28580,28581,28582)) {
        $owner=Get-PortOwner $port
        if($owner -gt 0) {
            $cmd=Get-CommandLine $owner
            Write-Host ("  port {0}: PID {1}  {2}" -f $port,$owner,$cmd) -ForegroundColor Yellow
        }
    }
    throw "Required V8 ports did not clear. No broad process kill was attempted."
}
Write-Host "  V8 runtime ports are clear." -ForegroundColor Green

# Move checkout to the exact pre-verified V9 commit.
Invoke-GitFatal $RepoRoot @("checkout",$Branch,"--quiet") "V9 checkout failed after V8 stop" | Out-Null
Invoke-GitFatal $RepoRoot @("reset","--hard",$ExpectedSha,"--quiet") "V9 reset failed after V8 stop" | Out-Null
$actual=((Invoke-GitFatal $RepoRoot @("rev-parse","HEAD") "could not verify V9 checkout") -join "").Trim()
if (-not $actual.StartsWith($ExpectedSha)) {
    throw "V9 checkout verification failed: expected $ExpectedSha, got $actual"
}

$runner=Join-Path $RepoRoot "downloads\RUN_AI_COCKPIT_V9.ps1"
if (-not (Test-Path -LiteralPath $runner)) {
    throw "V9 runner missing after verified checkout: $runner"
}

Write-Host ""
Write-Host "V8 stopped cleanly. Starting verified V9..." -ForegroundColor Green
& $runner -RepoRoot $RepoRoot -Branch $Branch -ExpectedSha $ExpectedSha -SkipGitUpdate
