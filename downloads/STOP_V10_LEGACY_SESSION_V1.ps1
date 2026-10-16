<#
P0-26B: one-command Safe Stop for the OWNER's legacy V10 session, whose
V10_CONTROLLER_STATE.json predates brain_observer_pid (the normal STOP
refuses that state on purpose).

Admission is delegated to the existing read-only gate
PREFLIGHT_V10_LEGACY_SHUTDOWN_V1.ps1 (-AdmissionOut). Nothing is stopped
unless that gate passes. Then:
  1. every admitted process is pinned by an opened handle whose creation
     time must equal the admitted one (PID reuse cannot retarget a kill);
  2. the Controller/RUN host is stopped first so it cannot restart workers;
  3. the gate runs again; the state file must be unchanged and no process
     may appear that was not admitted the first time;
  4. bridge children, workers and an admitted BRAIN are stopped through
     their pinned handles only (workers before their bridge children);
  5. success requires every pinned process exited, no LISTEN on 28580-28584,
     no ai_brain_observer.py host and an unchanged Excel process set.
Excel is never closed, killed or contacted by COM. Business Excel and the
managed workbook are both left exactly as they are.

Without -Execute this is a dry run: admission and handle pinning only.
Any failure after the first kill is reported as PARTIAL_STOP, keeps the
state file in place and writes the evidence folder. Output carries status
and counts only, never PIDs, paths or command lines.
#>
param(
    [string]$Root = "C:\AI_Cockpit_OneClick_Starter",
    [switch]$Execute,
    # Synthetic-only fault injection for the Windows Actions tests. Ignored
    # unless running inside GitHub Actions with Root under RUNNER_TEMP.
    [string]$SimulateKillFailureRole = ""
)
$ErrorActionPreference = "Stop"
$V10Ports = @(28580, 28581, 28582, 28583, 28584)
$WorkerOrder = @("watcher_pid", "collector_pid", "heartbeat_pid", "gateway_pid",
    "brain_gateway_pid", "voice_bridge_pid", "sbv2_pid", "shadow_supervisor_pid")
$script:Evidence = $null
$script:KillLog = New-Object System.Collections.ArrayList
$script:AnyKill = $false

function Get-Sha256([string]$Path) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash([IO.File]::ReadAllBytes($Path)))).Replace("-", "") }
    finally { $sha.Dispose() }
}

function Write-Utf8([string]$Path, [string]$Text) {
    [IO.File]::WriteAllText($Path, $Text, (New-Object Text.UTF8Encoding($false)))
}

function Finish([int]$Code, [string]$Result, [string]$Reason, [hashtable]$Counts) {
    if ($null -eq $Counts) { $Counts = @{} }
    if ($null -ne $script:Evidence -and (Test-Path -LiteralPath $script:Evidence)) {
        $body = [ordered]@{
            schema = "V10_LEGACY_STOP_RESULT_V1"; result = $Result; reason = $Reason
            finished_at = (Get-Date).ToUniversalTime().ToString("o")
            counts = $Counts; kills = @($script:KillLog)
        }
        try { Write-Utf8 (Join-Path $script:Evidence "result.json") (ConvertTo-Json -Depth 6 $body) } catch {}
    }
    Write-Output ("LEGACY_STOP_RESULT=" + $Result)
    if ($Reason) { Write-Output ("LEGACY_STOP_REASON=" + $Reason) }
    foreach ($k in ($Counts.Keys | Sort-Object)) { Write-Output ($k + "=" + $Counts[$k]) }
    if ($Code -eq 3) {
        Write-Output "STATE_FILE=RETAINED"
        Write-Output "RECOVERY=EVIDENCE_FOLDER_WRITTEN;RERUN_THIS_SCRIPT_OR_START_OLD_STARTER"
    }
    Write-Output "EXCEL_ACTION=NONE"
    Write-Output "REAL_SUBMIT_ALLOWED=false"
    exit $Code
}

function Get-V10Listeners {
    return @(Get-NetTCPConnection -State Listen -ErrorAction Stop |
        Where-Object { $V10Ports -contains [int]$_.LocalPort })
}

function Get-BrainHosts {
    return @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
        ([string]$_.CommandLine).IndexOf("ai_brain_observer.py", [StringComparison]::OrdinalIgnoreCase) -ge 0
    })
}

function Get-ExcelSet {
    $set = New-Object 'System.Collections.Generic.HashSet[string]'
    foreach ($x in @(Get-CimInstance Win32_Process -Filter "Name = 'EXCEL.EXE'" -ErrorAction Stop)) {
        [void]$set.Add(([string]$x.ProcessId) + ":" + ([datetime]$x.CreationDate).ToUniversalTime().Ticks)
    }
    return , $set
}

function Invoke-Admission([string]$Out) {
    $gate = Join-Path $PSScriptRoot "PREFLIGHT_V10_LEGACY_SHUTDOWN_V1.ps1"
    $ps = Join-Path $PSHOME "powershell.exe"
    # PS5.1 turns redirected native stderr into terminating errors under Stop.
    $ErrorActionPreference = "Continue"
    $lines = @(& $ps -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $gate -Root $Root -AdmissionOut $Out 2>$null)
    $code = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    $reason = ""
    foreach ($l in $lines) { if ([string]$l -like "PREFLIGHT_BLOCK_REASON=*") { $reason = ([string]$l).Substring(23) } }
    if ($code -ne 0 -or -not ($lines -contains "PREFLIGHT_RESULT=EVIDENCE_ONLY_PASS") -or
        -not (Test-Path -LiteralPath $Out -PathType Leaf)) {
        if (-not $reason) { $reason = "UNVERIFIED" }
        return @{ Ok = $false; Reason = $reason }
    }
    $rec = [IO.File]::ReadAllText($Out, [Text.Encoding]::UTF8) | ConvertFrom-Json
    if ([string]$rec.schema -cne "V10_LEGACY_STOP_ADMISSION_V1") { return @{ Ok = $false; Reason = "ADMISSION_SCHEMA" } }
    $entries = @()
    foreach ($m in @($rec.members)) { if ($null -ne $m) { $entries += $m } }
    foreach ($b in @($rec.bridges)) { if ($null -ne $b) { $entries += $b } }
    if ($null -ne $rec.brain) { $entries += $rec.brain }
    return @{ Ok = $true; Record = $rec; Entries = $entries }
}

function Get-EntryKey($Entry) { return ([string][int]$Entry.pid) + ":" + ([string][long]$Entry.created_utc_ticks) }

# Opens the handle once; identity is creation time plus executable name.
function Get-PinnedProcess($Entry) {
    $procId = [int]$Entry.pid
    if ($procId -le 0 -or $procId -eq $PID) { throw "PIN_INVALID_PID" }
    $p = Get-Process -Id $procId -ErrorAction Stop
    $h = $p.Handle
    if ($h -eq [IntPtr]::Zero -or $p.HasExited) { throw "PIN_HANDLE_NOT_LIVE" }
    if ([string]$p.ProcessName -ieq "EXCEL") { throw "PIN_REFUSES_EXCEL" }
    $delta = [Math]::Abs($p.StartTime.ToUniversalTime().Ticks - [long]$Entry.created_utc_ticks)
    if ($delta -gt [TimeSpan]::TicksPerSecond * 2) { throw "PIN_CREATION_TIME_MISMATCH" }
    $exe = [IO.Path]::GetFileNameWithoutExtension([string]$Entry.exe)
    if ([string]$p.ProcessName -ine $exe) { throw "PIN_EXECUTABLE_MISMATCH" }
    return $p
}

function Stop-Pinned([string]$Role, [System.Diagnostics.Process]$Proc) {
    $row = [ordered]@{ role = $Role; pid = [int]$Proc.Id; outcome = "" }
    try {
        if ($Proc.HasExited) { $row.outcome = "ALREADY_EXITED" }
        elseif ($SimulateKillFailureRole -and $Role -ceq $SimulateKillFailureRole -and
                $env:GITHUB_ACTIONS -eq "true" -and $env:RUNNER_TEMP -and
                ([IO.Path]::GetFullPath($Root)).StartsWith([IO.Path]::GetFullPath($env:RUNNER_TEMP), [StringComparison]::OrdinalIgnoreCase)) {
            $row.outcome = "KILL_FAILED_SIMULATED"
        } else {
            # Same handle that was identity-checked; the numeric PID is never resolved again.
            $script:AnyKill = $true
            $Proc.Kill()
            if ($Proc.WaitForExit(10000) -and $Proc.HasExited) { $row.outcome = "STOPPED" }
            else { $row.outcome = "STILL_RUNNING" }
        }
    } catch {
        $row.outcome = if ($Proc.HasExited) { "STOPPED" } else { "KILL_DENIED" }
    }
    [void]$script:KillLog.Add($row)
    return ($row.outcome -eq "STOPPED" -or $row.outcome -eq "ALREADY_EXITED")
}

try {
    $rootFull = [IO.Path]::GetFullPath($Root)
    $rootObj = Get-Item -LiteralPath $rootFull -ErrorAction Stop
    if (-not $rootObj.PSIsContainer -or (($rootObj.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
        Finish 2 "BLOCKED" "UNTRUSTED_ROOT" $null
    }
} catch { Finish 2 "BLOCKED" "UNTRUSTED_ROOT" $null }
$stateFile = Join-Path $rootFull "V10_CONTROLLER_STATE.json"
$resultFile = Join-Path $rootFull "V10_LEGACY_STOP_RESULT.json"

if (-not (Test-Path -LiteralPath $stateFile -PathType Leaf)) {
    # Re-run after a verified stop: report it, never invent a stop.
    $done = $null
    try { $done = [IO.File]::ReadAllText($resultFile, [Text.Encoding]::UTF8) | ConvertFrom-Json } catch {}
    if ($null -ne $done -and [string]$done.result -ceq "STOPPED_VERIFIED") {
        $left = @(Get-V10Listeners).Count
        if ($left -eq 0) { Finish 0 "ALREADY_STOPPED" "" @{ V10_LISTEN_PORTS = 0 } }
        Finish 2 "BLOCKED" "V10_PORTS_LISTENING_AFTER_PREVIOUS_STOP" @{ V10_LISTEN_PORTS = $left }
    }
    Finish 2 "BLOCKED" "STATE_MISSING" $null
}

$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssfffZ")
if ($Execute) {
    $evRoot = Join-Path $rootFull "V10_LEGACY_STOP_EVIDENCE"
    if (-not (Test-Path -LiteralPath $evRoot)) { [void](New-Item -ItemType Directory -Path $evRoot) }
    $script:Evidence = Join-Path $evRoot $stamp
} else {
    $script:Evidence = Join-Path ([IO.Path]::GetTempPath()) ("v10-legacy-stop-dryrun-" + $stamp)
}
[void](New-Item -ItemType Directory -Path $script:Evidence)

# Preserve the exact original state before anything else.
$stateCopy = Join-Path $script:Evidence "V10_CONTROLLER_STATE.before.json"
Copy-Item -LiteralPath $stateFile -Destination $stateCopy
$stateHash = Get-Sha256 $stateFile
if ((Get-Sha256 $stateCopy) -ne $stateHash) { Finish 2 "BLOCKED" "STATE_COPY_MISMATCH" $null }

$a = Invoke-Admission (Join-Path $script:Evidence "admission_a.json")
if (-not $a.Ok) { Finish 2 "BLOCKED" $a.Reason $null }
if ([string]$a.Record.state_sha256 -ne $stateHash) { Finish 2 "BLOCKED" "STATE_CHANGED_DURING_ADMISSION" $null }

$excelBefore = Get-ExcelSet
$pinned = @{}
$rolesByKey = @{}
try {
    foreach ($e in $a.Entries) {
        $key = Get-EntryKey $e
        $pinned[$key] = Get-PinnedProcess $e
        $rolesByKey[$key] = [string]$e.role
    }
} catch {
    Finish 2 "BLOCKED" ("IDENTITY_CHANGED_BEFORE_STOP:" + $_.Exception.Message) $null
}
$controllerKey = $null
foreach ($k in $pinned.Keys) { if ($rolesByKey[$k] -ceq "controller_pid") { $controllerKey = $k } }
$brainStatus = [string]$a.Record.brain_status
$plan = @{ ADMITTED_PROCESSES = $pinned.Count; BRAIN_STATUS = $brainStatus
    MANAGED_EXCEL_LIVE = ([string][bool]$a.Record.excel_live).ToLowerInvariant() }

if (-not $Execute) {
    try { Remove-Item -LiteralPath $script:Evidence -Recurse -Force } catch {}
    $script:Evidence = $null
    Finish 0 "DRY_RUN_READY" "" $plan
}

# 1. Controller/RUN host first: it supervises and would restart workers.
if ($null -ne $controllerKey) {
    if (-not (Stop-Pinned "controller_pid" $pinned[$controllerKey])) {
        Finish 3 "PARTIAL_STOP" "CONTROLLER_NOT_STOPPED" @{ STOPPED_COUNT = 0 }
    }
}

# 2. Re-admit with the Controller gone. The supervisor must not have
#    restarted or replaced anything between the first admission and its exit.
$b = Invoke-Admission (Join-Path $script:Evidence "admission_b.json")
if (-not $b.Ok) { Finish 3 "PARTIAL_STOP" ("READMISSION_BLOCKED:" + $b.Reason) @{ STOPPED_COUNT = 1 } }
if ((Get-Sha256 $stateFile) -ne $stateHash -or [string]$b.Record.state_sha256 -ne $stateHash) {
    Finish 3 "PARTIAL_STOP" "STATE_REWRITTEN_BY_CONTROLLER" @{ STOPPED_COUNT = 1 }
}
foreach ($e in $b.Entries) {
    if (-not $pinned.ContainsKey((Get-EntryKey $e))) {
        Finish 3 "PARTIAL_STOP" "NEW_PROCESS_AFTER_CONTROLLER_STOP" @{ STOPPED_COUNT = 1 }
    }
}

# 3. Workers, then their pinned bridge children (a live parent could
#    respawn a bridge), then the admitted BRAIN.
$ok = $true
foreach ($role in $WorkerOrder) {
    foreach ($k in @($pinned.Keys)) {
        if ($rolesByKey[$k] -ceq $role) { if (-not (Stop-Pinned $role $pinned[$k])) { $ok = $false } }
    }
}
foreach ($k in @($pinned.Keys)) {
    if ($rolesByKey[$k] -ceq "bridge_child") { if (-not (Stop-Pinned "bridge_child" $pinned[$k])) { $ok = $false } }
}
foreach ($k in @($pinned.Keys)) {
    if ($rolesByKey[$k] -ceq "brain_observer") { if (-not (Stop-Pinned "brain_observer" $pinned[$k])) { $ok = $false } }
}

# 4. Independent verification of the end state.
$alive = @($pinned.Values | Where-Object { -not $_.HasExited }).Count
$stopped = @($script:KillLog | Where-Object { $_.outcome -eq "STOPPED" }).Count
$listen = -1
foreach ($attempt in 1..10) {
    $listen = @(Get-V10Listeners).Count
    if ($listen -eq 0) { break }
    Start-Sleep -Milliseconds 300
}
$brainLeft = @(Get-BrainHosts).Count
$excelAfter = Get-ExcelSet
$excelUntouched = $excelAfter.SetEquals($excelBefore)
$counts = @{ ADMITTED_PROCESSES = $pinned.Count; STOPPED_COUNT = $stopped; MANAGED_PIDS_ALIVE = $alive
    V10_LISTEN_PORTS = $listen; BRAIN_HOSTS_LEFT = $brainLeft; BRAIN_STATUS = $brainStatus
    EXCEL_PROCESSES = $excelAfter.Count; EXCEL_SET_UNCHANGED = ([string]$excelUntouched).ToLowerInvariant() }

if (-not $ok -or $alive -ne 0) { Finish 3 "PARTIAL_STOP" "MANAGED_PROCESS_NOT_STOPPED" $counts }
if ($listen -ne 0) { Finish 3 "PARTIAL_STOP" "V10_PORTS_STILL_LISTENING" $counts }
if ($brainLeft -ne 0) { Finish 3 "PARTIAL_STOP" "BRAIN_HOST_REMAINS" $counts }
if (-not $excelUntouched) { Finish 3 "PARTIAL_STOP" "EXCEL_SET_CHANGED_NOT_BY_STOP" $counts }

# 5. Archive (move, never delete) the legacy state only after full success.
try {
    if ((Get-Sha256 $stateFile) -ne $stateHash) { throw "STATE_CHANGED" }
    $archived = Join-Path $script:Evidence "V10_CONTROLLER_STATE.legacy.json"
    Move-Item -LiteralPath $stateFile -Destination $archived
    if ((Test-Path -LiteralPath $stateFile) -or (Get-Sha256 $archived) -ne $stateHash) { throw "ARCHIVE_UNVERIFIED" }
    $summary = [ordered]@{ schema = "V10_LEGACY_STOP_RESULT_V1"; result = "STOPPED_VERIFIED"
        evidence = (Split-Path -Leaf $script:Evidence); state_sha256 = $stateHash
        finished_at = (Get-Date).ToUniversalTime().ToString("o") }
    Write-Utf8 $resultFile (ConvertTo-Json $summary)
} catch {
    Finish 3 "PARTIAL_STOP" ("STATE_ARCHIVE_FAILED:" + $_.Exception.Message) $counts
}
Finish 0 "STOPPED_VERIFIED" "" $counts
