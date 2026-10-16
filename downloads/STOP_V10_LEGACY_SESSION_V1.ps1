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
Any failure or exception after the first kill is reported as PARTIAL_STOP,
keeps the state file in place and writes the evidence folder. Success is
committed in a fixed order: verified state copy into the evidence folder,
then the root result bound to that evidence, then removal of the original.
A rerun with no state file reports ALREADY_STOPPED only when that evidence
still verifies and no admitted process, managed host, BRAIN or V10 LISTEN
remains. -RecoveryCheck is read-only and is the gate before a rerun or an
old-starter restart after PARTIAL_STOP. Output carries status and counts
only, never PIDs, paths or command lines.
#>
param(
    [string]$Root = "C:\AI_Cockpit_OneClick_Starter",
    [switch]$Execute,
    # Read-only: what is still alive after a PARTIAL_STOP, and whether a
    # rerun or an old-starter restart is safe. Never stops anything.
    [switch]$RecoveryCheck,
    # Synthetic-only fault injection for the Windows Actions tests:
    # kill:<role>, after_controller, result_write, state_remove. Ignored
    # unless running inside GitHub Actions with Root under RUNNER_TEMP.
    [string]$SimulateFault = ""
)
$ErrorActionPreference = "Stop"
$V10Ports = @(28580, 28581, 28582, 28583, 28584)
$WorkerOrder = @("watcher_pid", "collector_pid", "heartbeat_pid", "gateway_pid",
    "brain_gateway_pid", "voice_bridge_pid", "sbv2_pid", "shadow_supervisor_pid", "venv_child")
$ManagedLeaves = @("AI_COCKPIT_CONTROLLER_V10.ps1", "RUN_AI_COCKPIT_V10.ps1", "Kioxia_RSS_Live_Watcher.ps1",
    "Kioxia_Safety_Heartbeat.ps1", "MS2_RSS_100_Collector.ps1", "AI_COCKPIT_GATEWAY_V10.ps1",
    "AI_COCKPIT_VOICE_BRIDGE_V10.ps1", "server_fastapi.py", "ai_shadow_supervisor.py", "ai_brain_observer.py")
$script:Evidence = $null
$script:KillLog = New-Object System.Collections.ArrayList
$script:StopBegan = $false
$script:Counts = @{}
$script:StateFile = $null

function Test-Fault([string]$Name) {
    if (-not $SimulateFault -or $env:GITHUB_ACTIONS -ne "true" -or -not $env:RUNNER_TEMP) { return $false }
    if (-not ([IO.Path]::GetFullPath($Root)).StartsWith([IO.Path]::GetFullPath($env:RUNNER_TEMP), [StringComparison]::OrdinalIgnoreCase)) { return $false }
    return (@($SimulateFault -split ",") -ccontains $Name)
}

function Get-Sha256([string]$Path) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash([IO.File]::ReadAllBytes($Path)))).Replace("-", "") }
    finally { $sha.Dispose() }
}

function Write-Utf8([string]$Path, [string]$Text) {
    [IO.File]::WriteAllText($Path, $Text, (New-Object Text.UTF8Encoding($false)))
}

function Finish([int]$Code, [string]$Result, [string]$Reason, [hashtable]$Counts, [string]$Detail = "") {
    if ($null -eq $Counts) { $Counts = @{} }
    $evidenceWritten = $false
    if ($null -ne $script:Evidence -and (Test-Path -LiteralPath $script:Evidence)) {
        $body = [ordered]@{
            schema = "V10_LEGACY_STOP_RESULT_V1"; result = $Result; reason = $Reason; detail = $Detail
            finished_at = (Get-Date).ToUniversalTime().ToString("o")
            counts = $Counts; kills = @($script:KillLog)
        }
        try { Write-Utf8 (Join-Path $script:Evidence "result.json") (ConvertTo-Json -Depth 6 $body); $evidenceWritten = $true } catch {}
    }
    Write-Output ("LEGACY_STOP_RESULT=" + $Result)
    if ($Reason) { Write-Output ("LEGACY_STOP_REASON=" + $Reason) }
    foreach ($k in ($Counts.Keys | Sort-Object)) { Write-Output ($k + "=" + $Counts[$k]) }
    if ($Code -eq 3 -or $Result -ceq "STOPPED_VERIFIED") {
        $kept = $true
        try { $kept = Test-Path -LiteralPath $script:StateFile } catch {}
        Write-Output ("STATE_FILE=" + $(if ($kept) { "RETAINED" } else { "ARCHIVED_IN_EVIDENCE" }))
    }
    if ($Code -eq 3) {
        Write-Output ("EVIDENCE_RESULT_WRITTEN=" + ([string]$evidenceWritten).ToLowerInvariant())
        Write-Output "RECOVERY=RUN_RECOVERY_CHECK_BEFORE_RERUN_OR_OLD_STARTER"
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

# Any script host that mentions a legacy V10 script. Deliberately loose:
# it can only block a success claim, never select something to stop.
function Get-ManagedHosts {
    return @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
        $line = [string]$_.CommandLine
        [int]$_.ProcessId -ne $PID -and [string]$_.Name -match '^(powershell|pwsh|cmd|python|pythonw|py)\.exe$' -and
        @($ManagedLeaves | Where-Object { $line.IndexOf($_, [StringComparison]::OrdinalIgnoreCase) -ge 0 }).Count -gt 0
    })
}

function Get-ExcelSet {
    $set = New-Object 'System.Collections.Generic.HashSet[string]'
    foreach ($x in @(Get-CimInstance Win32_Process -Filter "Name = 'EXCEL.EXE'" -ErrorAction Stop)) {
        [void]$set.Add(([string]$x.ProcessId) + ":" + ([datetime]$x.CreationDate).ToUniversalTime().Ticks)
    }
    return , $set
}

function Get-AdmissionEntries($Rec) {
    $entries = @()
    foreach ($m in @($Rec.members)) { if ($null -ne $m) { $entries += $m } }
    foreach ($b in @($Rec.bridges)) { if ($null -ne $b) { $entries += $b } }
    if ($null -ne $Rec.brain) { $entries += $Rec.brain }
    return , $entries
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
    return @{ Ok = $true; Record = $rec; Entries = (Get-AdmissionEntries $rec) }
}

function Get-EntryKey($Entry) { return ([string][int]$Entry.pid) + ":" + ([string][long]$Entry.created_utc_ticks) }

# Same PID and same creation time as admitted. Unreadable counts as alive.
function Test-EntryAlive($Entry) {
    $p = Get-Process -Id ([int]$Entry.pid) -ErrorAction SilentlyContinue
    if ($null -eq $p) { return $false }
    try {
        if ($p.HasExited) { return $false }
        return ([Math]::Abs($p.StartTime.ToUniversalTime().Ticks - [long]$Entry.created_utc_ticks) -le [TimeSpan]::TicksPerSecond * 2)
    } catch { return $true }
}

function Get-EvidenceDirs([string]$RootFull) {
    $evRoot = Join-Path $RootFull "V10_LEGACY_STOP_EVIDENCE"
    if (-not (Test-Path -LiteralPath $evRoot -PathType Container)) { return @() }
    return @(Get-ChildItem -LiteralPath $evRoot -Directory | Where-Object {
        $_.Name -cmatch '^\d{8}T\d{9}Z$' -and (($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0)
    } | Sort-Object Name -Descending)
}

function Read-Admission([string]$Dir) {
    $f = Join-Path $Dir "admission_a.json"
    if (-not (Test-Path -LiteralPath $f -PathType Leaf)) { return $null }
    $rec = [IO.File]::ReadAllText($f, [Text.Encoding]::UTF8) | ConvertFrom-Json
    if ([string]$rec.schema -cne "V10_LEGACY_STOP_ADMISSION_V1") { return $null }
    return @{ Record = $rec; Entries = (Get-AdmissionEntries $rec); Sha = (Get-Sha256 $f) }
}

# Liveness of a recorded cohort: originals by (PID, creation time); every
# V10 listener, BRAIN host and legacy script host outside it is unattributed.
function Get-Residue($Entries) {
    $aliveKeys = New-Object 'System.Collections.Generic.HashSet[int]'
    foreach ($e in @($Entries)) { if (Test-EntryAlive $e) { [void]$aliveKeys.Add([int]$e.pid) } }
    $listeners = @(Get-V10Listeners)
    $brains = @(Get-BrainHosts)
    $hosts = @(Get-ManagedHosts)
    return @{
        ORIGINAL_MANAGED_ALIVE = $aliveKeys.Count
        V10_LISTEN_PORTS = $listeners.Count
        LISTENERS_UNATTRIBUTED = @($listeners | Where-Object { -not $aliveKeys.Contains([int]$_.OwningProcess) }).Count
        BRAIN_HOSTS = $brains.Count
        BRAIN_UNATTRIBUTED = @($brains | Where-Object { -not $aliveKeys.Contains([int]$_.ProcessId) }).Count
        LEGACY_HOSTS_UNATTRIBUTED = @($hosts | Where-Object { -not $aliveKeys.Contains([int]$_.ProcessId) }).Count
    }
}

# A previous STOPPED_VERIFIED counts only while its evidence still binds the
# archived state and admission, and nothing of that session or any other
# legacy host, BRAIN or V10 listener is alive now.
function Test-PreviousStop([string]$RootFull, [string]$ResultFile) {
    $done = $null
    try { $done = [IO.File]::ReadAllText($ResultFile, [Text.Encoding]::UTF8) | ConvertFrom-Json } catch {}
    if ($null -eq $done -or [string]$done.result -cne "STOPPED_VERIFIED") { return @{ Ok = $false; Reason = "STATE_MISSING" } }
    $leaf = [string]$done.evidence
    $dir = $null
    foreach ($d in (Get-EvidenceDirs $RootFull)) { if ($d.Name -ceq $leaf) { $dir = $d.FullName } }
    if ($null -eq $dir) { return @{ Ok = $false; Reason = "PREVIOUS_RESULT_UNVERIFIED" } }
    $legacy = Join-Path $dir "V10_CONTROLLER_STATE.legacy.json"
    $adm = $null
    try { $adm = Read-Admission $dir } catch {}
    if (-not (Test-Path -LiteralPath $legacy -PathType Leaf) -or (Get-Sha256 $legacy) -cne [string]$done.state_sha256 -or
        $null -eq $adm -or $adm.Sha -cne [string]$done.admission_sha256 -or
        [string]$adm.Record.state_sha256 -cne [string]$done.state_sha256) {
        return @{ Ok = $false; Reason = "PREVIOUS_RESULT_UNVERIFIED" }
    }
    $r = Get-Residue $adm.Entries
    $c = @{ ORIGINAL_MANAGED_ALIVE = $r.ORIGINAL_MANAGED_ALIVE; V10_LISTEN_PORTS = $r.V10_LISTEN_PORTS
        BRAIN_HOSTS = $r.BRAIN_HOSTS; LEGACY_HOSTS = $r.LEGACY_HOSTS_UNATTRIBUTED }
    if ($r.ORIGINAL_MANAGED_ALIVE -ne 0) { return @{ Ok = $false; Reason = "PREVIOUS_SESSION_PROCESS_ALIVE"; Counts = $c } }
    if ($r.BRAIN_HOSTS -ne 0) { return @{ Ok = $false; Reason = "BRAIN_HOST_PRESENT"; Counts = $c } }
    if ($r.LEGACY_HOSTS_UNATTRIBUTED -ne 0) { return @{ Ok = $false; Reason = "LEGACY_HOST_PRESENT"; Counts = $c } }
    if ($r.V10_LISTEN_PORTS -ne 0) { return @{ Ok = $false; Reason = "V10_PORTS_LISTENING"; Counts = $c } }
    return @{ Ok = $true; Counts = $c }
}

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
        elseif (Test-Fault ("kill:" + $Role)) { $row.outcome = "KILL_FAILED_SIMULATED" }
        else {
            # Same handle that was identity-checked; the numeric PID is never resolved again.
            $script:StopBegan = $true
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

# Commit order: verified copy of the state into the evidence folder, then the
# root result bound to that evidence, then removal of the original. A failure
# at any step leaves the original state file in place.
function Commit-Stop([string]$StateHash, [string]$ResultFile) {
    if ((Get-Sha256 $script:StateFile) -cne $StateHash) { throw "STATE_CHANGED" }
    $archived = Join-Path $script:Evidence "V10_CONTROLLER_STATE.legacy.json"
    Copy-Item -LiteralPath $script:StateFile -Destination $archived
    if ((Get-Sha256 $archived) -cne $StateHash) { throw "ARCHIVE_COPY_UNVERIFIED" }
    if (Test-Fault "result_write") { throw "SIMULATED_RESULT_WRITE_FAILURE" }
    $summary = [ordered]@{ schema = "V10_LEGACY_STOP_RESULT_V1"; result = "STOPPED_VERIFIED"
        evidence = (Split-Path -Leaf $script:Evidence); state_sha256 = $StateHash
        admission_sha256 = (Get-Sha256 (Join-Path $script:Evidence "admission_a.json"))
        finished_at = (Get-Date).ToUniversalTime().ToString("o") }
    $tmp = $ResultFile + ".tmp"
    Write-Utf8 $tmp (ConvertTo-Json $summary)
    if (Test-Path -LiteralPath $ResultFile) { Remove-Item -LiteralPath $ResultFile }
    [IO.File]::Move($tmp, $ResultFile)
    $back = [IO.File]::ReadAllText($ResultFile, [Text.Encoding]::UTF8) | ConvertFrom-Json
    if ([string]$back.state_sha256 -cne $StateHash -or [string]$back.evidence -cne $summary.evidence) { throw "RESULT_UNVERIFIED" }
    if (Test-Fault "state_remove") { throw "SIMULATED_STATE_REMOVE_FAILURE" }
    Remove-Item -LiteralPath $script:StateFile
    if (Test-Path -LiteralPath $script:StateFile) { throw "STATE_STILL_PRESENT" }
}

function Invoke-RecoveryCheck([string]$RootFull, [string]$ResultFile) {
    $c = [ordered]@{}
    $action = "OWNER_REVIEW_REQUIRED"
    $startOk = $false
    if (-not (Test-Path -LiteralPath $script:StateFile -PathType Leaf)) {
        $c.STATE_FILE = "ABSENT"
        $prev = Test-PreviousStop $RootFull $ResultFile
        if ($prev.Ok) { $action = "NONE_ALREADY_STOPPED"; $startOk = $true }
        $c.PREVIOUS_STOP = $(if ($prev.Ok) { "VERIFIED" } else { [string]$prev.Reason })
    } else {
        $c.STATE_FILE = "PRESENT"
        $hash = Get-Sha256 $script:StateFile
        $adm = $null
        foreach ($d in (Get-EvidenceDirs $RootFull)) {
            try { $x = Read-Admission $d.FullName } catch { $x = $null }
            if ($null -ne $x -and [string]$x.Record.state_sha256 -ceq $hash) { $adm = $x; break }
        }
        if ($null -eq $adm) {
            $c.STOP_ATTEMPT_EVIDENCE = "NONE"
            $action = "NO_STOP_ATTEMPT_FOR_THIS_STATE"
        } else {
            $c.STOP_ATTEMPT_EVIDENCE = "FOUND"
            $r = Get-Residue $adm.Entries
            foreach ($k in $r.Keys) { $c[$k] = $r[$k] }
            $foreign = $r.LISTENERS_UNATTRIBUTED + $r.BRAIN_UNATTRIBUTED + $r.LEGACY_HOSTS_UNATTRIBUTED
            if ($foreign -eq 0 -and $r.ORIGINAL_MANAGED_ALIVE -gt 0) { $action = "RERUN_STOP_EXECUTE" }
            elseif ($foreign -eq 0 -and $r.V10_LISTEN_PORTS -eq 0 -and $r.BRAIN_HOSTS -eq 0) {
                $action = "RERUN_STOP_EXECUTE_OR_START_OLD_STARTER"; $startOk = $true
            }
        }
    }
    Write-Output "RECOVERY_CHECK=COMPLETE"
    foreach ($k in $c.Keys) { Write-Output ($k + "=" + $c[$k]) }
    Write-Output ("RECOVERY_ACTION=" + $action)
    Write-Output ("START_OLD_STARTER_ALLOWED=" + ([string]$startOk).ToLowerInvariant())
    Write-Output "PROCESSES_STOPPED=0"
    Write-Output "EXCEL_ACTION=NONE"
    Write-Output "REAL_SUBMIT_ALLOWED=false"
    exit $(if ($action -ceq "OWNER_REVIEW_REQUIRED" -or $action -ceq "NO_STOP_ATTEMPT_FOR_THIS_STATE") { 2 } else { 0 })
}

try {
    try {
        $rootFull = [IO.Path]::GetFullPath($Root)
        $rootObj = Get-Item -LiteralPath $rootFull -ErrorAction Stop
        if (-not $rootObj.PSIsContainer -or (($rootObj.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
            Finish 2 "BLOCKED" "UNTRUSTED_ROOT" $null
        }
    } catch { Finish 2 "BLOCKED" "UNTRUSTED_ROOT" $null }
    $script:StateFile = Join-Path $rootFull "V10_CONTROLLER_STATE.json"
    $resultFile = Join-Path $rootFull "V10_LEGACY_STOP_RESULT.json"

    if ($RecoveryCheck) { Invoke-RecoveryCheck $rootFull $resultFile }

    if (-not (Test-Path -LiteralPath $script:StateFile -PathType Leaf)) {
        # Re-run after a verified stop: report it only if it still holds.
        $prev = Test-PreviousStop $rootFull $resultFile
        if ($prev.Ok) { Finish 0 "ALREADY_STOPPED" "" $prev.Counts }
        Finish 2 "BLOCKED" $prev.Reason $prev.Counts
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
    Copy-Item -LiteralPath $script:StateFile -Destination $stateCopy
    $stateHash = Get-Sha256 $script:StateFile
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
    $script:Counts = @{ ADMITTED_PROCESSES = $pinned.Count; BRAIN_STATUS = $brainStatus }

    # 1. Controller/RUN host first: it supervises and would restart workers.
    if ($null -ne $controllerKey) {
        if (-not (Stop-Pinned "controller_pid" $pinned[$controllerKey])) {
            Finish 3 "PARTIAL_STOP" "CONTROLLER_NOT_STOPPED" $script:Counts
        }
    }
    if (Test-Fault "after_controller") { throw "SIMULATED_FAULT_AFTER_CONTROLLER" }

    # 2. Re-admit with the Controller gone. The supervisor must not have
    #    restarted or replaced anything between the first admission and its exit.
    $b = Invoke-Admission (Join-Path $script:Evidence "admission_b.json")
    if (-not $b.Ok) { Finish 3 "PARTIAL_STOP" ("READMISSION_BLOCKED:" + $b.Reason) $script:Counts }
    if ((Get-Sha256 $script:StateFile) -ne $stateHash -or [string]$b.Record.state_sha256 -ne $stateHash) {
        Finish 3 "PARTIAL_STOP" "STATE_REWRITTEN_BY_CONTROLLER" $script:Counts
    }
    foreach ($e in $b.Entries) {
        if (-not $pinned.ContainsKey((Get-EntryKey $e))) {
            Finish 3 "PARTIAL_STOP" "NEW_PROCESS_AFTER_CONTROLLER_STOP" $script:Counts
        }
    }

    # 3. Workers (and their venv interpreter children), then their pinned
    #    bridge children (a live parent could respawn a bridge), then BRAIN.
    $ok = $true
    foreach ($role in ($WorkerOrder + @("bridge_child", "brain_venv_child", "brain_observer"))) {
        foreach ($k in @($pinned.Keys)) {
            if ($rolesByKey[$k] -ceq $role) { if (-not (Stop-Pinned $role $pinned[$k])) { $ok = $false } }
        }
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
    $script:Counts = @{ ADMITTED_PROCESSES = $pinned.Count; STOPPED_COUNT = $stopped; MANAGED_PIDS_ALIVE = $alive
        V10_LISTEN_PORTS = $listen; BRAIN_HOSTS_LEFT = $brainLeft; BRAIN_STATUS = $brainStatus
        EXCEL_PROCESSES = $excelAfter.Count; EXCEL_SET_UNCHANGED = ([string]$excelUntouched).ToLowerInvariant() }

    if (-not $ok -or $alive -ne 0) { Finish 3 "PARTIAL_STOP" "MANAGED_PROCESS_NOT_STOPPED" $script:Counts }
    if ($listen -ne 0) { Finish 3 "PARTIAL_STOP" "V10_PORTS_STILL_LISTENING" $script:Counts }
    if ($brainLeft -ne 0) { Finish 3 "PARTIAL_STOP" "BRAIN_HOST_REMAINS" $script:Counts }
    if (-not $excelUntouched) { Finish 3 "PARTIAL_STOP" "EXCEL_SET_CHANGED_NOT_BY_STOP" $script:Counts }

    # 5. Commit success; never delete the only copy of the state.
    try { Commit-Stop $stateHash $resultFile }
    catch { Finish 3 "PARTIAL_STOP" "STATE_COMMIT_FAILED" $script:Counts ([string]$_.Exception.Message) }
    Finish 0 "STOPPED_VERIFIED" "" $script:Counts
} catch {
    # Any unexpected exception: once a kill was attempted this is a partial
    # stop with evidence; before that nothing was stopped.
    $detail = [string]$_.Exception.Message
    if ($script:StopBegan) { Finish 3 "PARTIAL_STOP" "UNEXPECTED_ERROR_AFTER_STOP_BEGAN" $script:Counts $detail }
    Finish 2 "BLOCKED" "UNEXPECTED_ERROR_BEFORE_STOP" $null $detail
}
