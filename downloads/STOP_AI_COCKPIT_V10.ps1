param(
    [string]$Root = "C:\AI_Cockpit_OneClick_Starter"
)

# Stops only the PIDs this Controller (AI_COCKPIT_CONTROLLER_V10.ps1) itself
# recorded in V10_CONTROLLER_STATE.json. Never scans the system process
# table by name/window-title pattern, so it cannot touch an unrelated
# Excel session or PowerShell window. Excel is stopped only if its PID
# still matches the tracked window title, same rule the Controller's own
# supervision loop uses.

$ErrorActionPreference = "SilentlyContinue"
$StateFile = Join-Path $Root "V10_CONTROLLER_STATE.json"

if (-not (Test-Path -LiteralPath $StateFile)) {
    Write-Host "No V10 state file found - nothing to stop." -ForegroundColor DarkGray
    exit 0
}

# Get-Content -Raw does not reliably treat a BOM-less UTF-8 file as UTF-8
# under Windows PowerShell 5.1 (can fall back to the system ANSI codepage,
# corrupting Japanese paths on read-back) - read explicitly as UTF-8.
# A missing or corrupt state must never be interpreted as an empty clean stop.
try {
    $state = [IO.File]::ReadAllText($StateFile, [Text.Encoding]::UTF8) | ConvertFrom-Json -ErrorAction Stop
    if ($null -eq $state -or [int]$state.controller_pid -le 0) {
        throw "Controller identity missing"
    }
} catch {
    Write-Host "V10 Controller state missing or invalid; refusing unverified Safe Stop." -ForegroundColor Red
    exit 2
}

function Get-PortOwner([int]$Port) {
    try {
        $conn = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $conn) { return [int]$conn.OwningProcess }
    } catch {}
    return 0
}

function Stop-OwnedJobBridge([int]$Port,[int]$ExpectedParentId,[string]$Label) {
    if ($ExpectedParentId -le 0) { return }
    $owner = Get-PortOwner $Port
    if ($owner -le 0) { return }
    try {
        $info = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $owner) -ErrorAction SilentlyContinue
        if ($null -eq $info) { return }
        if ([int]$info.ParentProcessId -eq $ExpectedParentId -and [string]$info.Name -match "^(powershell|pwsh)\.exe$") {
            Stop-Process -Id $owner -Force -ErrorAction SilentlyContinue
            Write-Host ("Stopped " + $Label + " bridge child (PID " + $owner + ")") -ForegroundColor Green
        }
    } catch {}
}

function Test-OwnedPidIdentity([string]$Field,[int]$ProcessId) {
    $expected = switch ($Field) {
        "watcher_pid"      { "Kioxia_RSS_Live_Watcher.ps1" }
        "heartbeat_pid"    { "Kioxia_Safety_Heartbeat.ps1" }
        "collector_pid"    { "MS2_RSS_100_Collector.ps1" }
        "gateway_pid"      { "AI_COCKPIT_GATEWAY_V10.ps1" }
        "brain_gateway_pid" { "AI_COCKPIT_GATEWAY_V10.ps1" }
        "voice_bridge_pid" { "AI_COCKPIT_VOICE_BRIDGE_V10.ps1" }
        "sbv2_pid"         { "server_fastapi.py" }
        "shadow_supervisor_pid" { "ai_shadow_supervisor.py" }
        "brain_observer_pid" { "ai_brain_observer.py" }
        # RUN invokes Controller synchronously with &, so controller_pid is
        # the RUN PowerShell host itself. Accept either identity, but never
        # a generic powershell.exe match.
        "controller_pid"   { "__V10_CONTROLLER_OR_RUN__" }
        default            { "" }
    }
    if ([string]::IsNullOrWhiteSpace($expected)) { return $false }
    try {
        $wmi = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $ProcessId) -ErrorAction SilentlyContinue
        $cmd = if ($null -ne $wmi) { [string]$wmi.CommandLine } else { "" }
        if ([string]::IsNullOrWhiteSpace($cmd)) { return $false }
        if ($Field -eq "controller_pid") {
            return (
                $cmd -match [regex]::Escape("AI_COCKPIT_CONTROLLER_V10.ps1") -or
                $cmd -match [regex]::Escape("RUN_AI_COCKPIT_V10.ps1")
            )
        }
        return ($cmd -match [regex]::Escape($expected))
    } catch { return $false }
}


# Opens the specific tracked process handle before checking command line and
# creation time. A later PID reuse must never retarget a Stop-Process -Id call.
function Test-ExactBrainHandle([System.Diagnostics.Process]$Proc,$State) {
    if ($null -eq $Proc) { return $false }
    try {
        $handle = $Proc.Handle
        if ($handle -eq [IntPtr]::Zero -or $Proc.HasExited) { return $false }
        $cim = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $Proc.Id) -ErrorAction Stop
        if ($null -eq $cim -or [string]$cim.Name -notmatch '^(python|pythonw|py)\.exe$') {
            return $false
        }
        $cmd = [string]$cim.CommandLine
        $repo = [string]$State.repo_root
        $runtime = [string]$State.runtime_dir
        if ([string]::IsNullOrWhiteSpace($repo) -or [string]::IsNullOrWhiteSpace($runtime) -or
            [string]::IsNullOrWhiteSpace($cmd)) { return $false }
        foreach ($arg in @(
            (Join-Path $repo "scripts\ai_brain_observer.py"),
            (Join-Path $runtime "live_ms2.json"),
            (Join-Path $runtime "ai_brain_observer_status_v1.json"),
            "--live", "--status"
        )) {
            if ($cmd.IndexOf($arg, [StringComparison]::OrdinalIgnoreCase) -lt 0) { return $false }
        }
        $fromHandle = $Proc.StartTime.ToUniversalTime()
        $fromCim = ([datetime]$cim.CreationDate).ToUniversalTime()
        if ([Math]::Abs(($fromHandle - $fromCim).TotalSeconds) -gt 2) { return $false }
        $controllerStarted = ([datetime]$State.started_at).ToUniversalTime()
        return ($fromHandle -ge $controllerStarted.AddSeconds(-10))
    } catch { return $false }
}

function Stop-VerifiedHiddenManagedExcelOrphan([int]$ExcelPid,[string]$WorkbookPath) {
    if ($ExcelPid -le 0 -or [string]::IsNullOrWhiteSpace($WorkbookPath)) { return $false }
    $xp = Get-Process -Id $ExcelPid -ErrorAction SilentlyContinue
    if ($null -eq $xp) { return $true }

    try {
        $info = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $ExcelPid) -ErrorAction Stop
        $cmd = [string]$info.CommandLine
        $selfSession = [int](Get-Process -Id $PID -ErrorAction Stop).SessionId
        $sameSession = ([int]$xp.SessionId -eq $selfSession)
        $isExcel = ([string]$xp.ProcessName -ieq "EXCEL")
        $isHidden = ($xp.MainWindowHandle -eq 0)
        $hasCanonicalPath = (-not [string]::IsNullOrWhiteSpace($cmd) -and $cmd.IndexOf($WorkbookPath,[StringComparison]::OrdinalIgnoreCase) -ge 0)

        $otherExcel = @(
            Get-Process EXCEL -ErrorAction SilentlyContinue |
            Where-Object { $_.Id -ne $ExcelPid -and $_.SessionId -eq $selfSession }
        )

        if ($isExcel -and $sameSession -and $isHidden -and $hasCanonicalPath -and $otherExcel.Count -eq 0) {
            Stop-Process -Id $ExcelPid -Force -ErrorAction Stop
            foreach ($attempt in 1..20) {
                Start-Sleep -Milliseconds 250
                if ($null -eq (Get-Process -Id $ExcelPid -ErrorAction SilentlyContinue)) { return $true }
            }
        }
    } catch {}

    return ($null -eq (Get-Process -Id $ExcelPid -ErrorAction SilentlyContinue))
}

function Close-VerifiedManagedExcelNoSave([int]$ExcelPid,[string]$WorkbookPath) {
    if ($ExcelPid -le 0 -or [string]::IsNullOrWhiteSpace($WorkbookPath)) { return $false }

    $xp = Get-Process -Id $ExcelPid -ErrorAction SilentlyContinue
    if ($null -eq $xp) { return $true }

    if (-not ("AIExcelNative" -as [type])) {
        Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class AIExcelNative {
    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
}
"@
    }

    $app = $null
    $targetBook = $null
    try {
        # This is the same ROT path that succeeds manually on the Owner PC.
        # We still fail closed unless the resolved Excel.Application HWND maps
        # to the exact PID recorded by V10 state.
        $app = [Runtime.InteropServices.Marshal]::GetActiveObject("Excel.Application")
        if ($null -eq $app) { return $false }

        $appHwnd = 0
        try { $appHwnd = [int64]$app.Hwnd } catch { return $false }
        $resolvedPid = [uint32]0
        [void][AIExcelNative]::GetWindowThreadProcessId([IntPtr]$appHwnd, [ref]$resolvedPid)
        if ([int]$resolvedPid -ne $ExcelPid) { return $false }

        foreach ($book in @($app.Workbooks)) {
            $full = ""
            try { $full = [string]$book.FullName } catch {}
            if (-not [string]::IsNullOrWhiteSpace($full) -and
                [string]::Equals($full, $WorkbookPath, [StringComparison]::OrdinalIgnoreCase)) {
                $targetBook = $book
                break
            }
            try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($book) } catch {}
        }
        if ($null -eq $targetBook) { return $false }

        try { $app.DisplayAlerts = $false } catch {}

        # Runtime RSS writes are transient. Never persist them into the clean
        # canonical workbook during Safe Stop.
        $targetBook.Close($false)
        try { $app.Quit() } catch {}

        # The window can disappear before EXCEL.EXE exits. Wait briefly; the
        # caller will perform the verified hidden-orphan cleanup if needed.
        foreach ($attempt in 1..20) {
            Start-Sleep -Milliseconds 250
            if ($null -eq (Get-Process -Id $ExcelPid -ErrorAction SilentlyContinue)) { return $true }
        }
        return $false
    } catch {
        return $false
    } finally {
        if ($null -ne $targetBook) {
            try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($targetBook) } catch {}
        }
        if ($null -ne $app) {
            try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($app) } catch {}
        }
        [GC]::Collect()
        [GC]::WaitForPendingFinalizers()
    }
}

# P0-25: The legacy state produced before independent BRAIN tracking may
# omit brain_observer_pid even while Controller, Excel and workers are alive.
# Fail closed BEFORE stopping Controller or any worker. Otherwise a half-stop
# leaves 4+ listening ports and the original state behind (unsafe cutover).
# The lack of a recorded BRAIN identity is NOT proof of BRAIN absence.
$brainIdentity = $state.PSObject.Properties["brain_observer_pid"]
$brainPidForGuard = 0
if ($null -eq $brainIdentity -or
    -not [int]::TryParse([string]$brainIdentity.Value,[ref]$brainPidForGuard) -or
    $brainPidForGuard -le 0) {
    Write-Host "SAFE_STOP_PREFLIGHT=BLOCKED_BRAIN_PID_UNRECORDED; no processes stopped." -ForegroundColor Red
    exit 2
}
# The tracked process may already have exited: that is a legitimate
# idempotent stop. A living PID MUST still match the exact BRAIN handle.
$beforeBrain = Get-Process -Id $brainPidForGuard -ErrorAction SilentlyContinue
if ($null -ne $beforeBrain -and
    (-not (Test-OwnedPidIdentity "brain_observer_pid" $brainPidForGuard) -or
     -not (Test-ExactBrainHandle $beforeBrain $state))) {
    Write-Host "SAFE_STOP_PREFLIGHT=BLOCKED_BRAIN_IDENTITY_UNVERIFIED; no processes stopped." -ForegroundColor Red
    exit 2
}

# Stop the supervising RUN/Controller host FIRST. Otherwise it can restart
# Gateway/Voice/Shadow while Safe Stop is still tearing workers down.
$controllerVal = $state.PSObject.Properties["controller_pid"]
if ($null -ne $controllerVal -and [int]$controllerVal.Value -gt 0) {
    $controllerPid = [int]$controllerVal.Value
    $controllerProc = Get-Process -Id $controllerPid -ErrorAction SilentlyContinue
    if ($null -ne $controllerProc -and (Test-OwnedPidIdentity "controller_pid" $controllerPid)) {
        try { Stop-Process -Id $controllerPid -Force -ErrorAction SilentlyContinue } catch {}
        foreach ($attempt in 1..20) {
            Start-Sleep -Milliseconds 250
            if ($null -eq (Get-Process -Id $controllerPid -ErrorAction SilentlyContinue)) { break }
        }
        if ($null -ne (Get-Process -Id $controllerPid -ErrorAction SilentlyContinue)) {
            Write-Host ("Controller/RUN PID " + $controllerPid + " did not stop; aborting before worker teardown.") -ForegroundColor Red
            exit 2
        }
        Write-Host ("Stopped controller_pid (PID " + $controllerPid + ")") -ForegroundColor Green
    } elseif ($null -ne $controllerProc) {
        Write-Host ("PID " + $controllerPid + " no longer matches V10 Controller/RUN; not stopping it.") -ForegroundColor Red
        exit 2
    }
}

# Controller may have restarted BRAIN and atomically replaced its state after
# our initial read. Re-read only AFTER the Controller has actually exited.
# Refuse a missing, malformed or different session instead of using stale PIDs.
try {
    $latest = [IO.File]::ReadAllText($StateFile, [Text.Encoding]::UTF8) | ConvertFrom-Json -ErrorAction Stop
    if ($null -eq $latest -or
        [int]$latest.controller_pid -ne [int]$state.controller_pid -or
        [string]$latest.session_id -cne [string]$state.session_id -or
        [string]$latest.repo_root -cne [string]$state.repo_root -or
        [int]$latest.brain_observer_pid -le 0) {
        throw "BRAIN identity or session not recorded"
    }
    $state = $latest
} catch {
    Write-Host "Latest BRAIN PID/state unverified after Controller exit; retained state." -ForegroundColor Red
    exit 2
}

Stop-OwnedJobBridge 28580 ([int]$state.collector_pid) "Collector JSON"
Stop-OwnedJobBridge 28582 ([int]$state.watcher_pid) "Watcher JSON"

$brainStopVerified = $true
foreach ($field in @("watcher_pid", "heartbeat_pid", "collector_pid", "gateway_pid", "brain_gateway_pid", "voice_bridge_pid", "sbv2_pid", "shadow_supervisor_pid", "brain_observer_pid")) {
    $val = $state.PSObject.Properties[$field]
    if ($null -eq $val -or [int]$val.Value -le 0) { continue }
    $procId = [int]$val.Value
    $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if ($field -eq "brain_observer_pid") {
        if ($null -eq $p) {
            Write-Host ("Recorded BRAIN observer PID " + $procId + " already exited.") -ForegroundColor Yellow
            continue
        }
        if (-not (Test-OwnedPidIdentity $field $procId) -or
            -not (Test-ExactBrainHandle $p $state)) {
            $brainStopVerified = $false
            Write-Host ("BRAIN observer PID " + $procId + " identity unverified; not stopping.") -ForegroundColor Red
            continue
        }
        try {
            # Kill/WaitForExit operate on the already-opened process object,
            # never look up the same numeric PID again after verification.
            $p.Kill()
            if (-not $p.WaitForExit(5000) -or -not $p.HasExited) {
                $brainStopVerified = $false
                Write-Host ("BRAIN observer PID " + $procId + " remains alive; retain state.") -ForegroundColor Red
            } else {
                Write-Host ("Stopped verified BRAIN observer (PID " + $procId + ")") -ForegroundColor Green
            }
        } catch {
            $brainStopVerified = $false
            Write-Host ("BRAIN observer PID " + $procId + " stop denied; retain state.") -ForegroundColor Red
        }
        continue
    }
    if ($null -ne $p -and (Test-OwnedPidIdentity $field $procId)) {
        try { Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue } catch {}
        Write-Host ("Stopped " + $field + " (PID " + $procId + ")") -ForegroundColor Green
    } elseif ($null -ne $p) {
        Write-Host ("PID " + $procId + " no longer matches " + $field + "; not stopping it.") -ForegroundColor Yellow
    }
}

$excelPid = [int]$state.excel_pid
$workbookName = [string]$state.workbook_name
$workbookPath = [string]$state.workbook_path
$excelCleanupOk = $true

if ($excelPid -gt 0 -and -not [string]::IsNullOrWhiteSpace($workbookName) -and -not [string]::IsNullOrWhiteSpace($workbookPath)) {
    $xp = Get-Process -Id $excelPid -ErrorAction SilentlyContinue
    if ($null -ne $xp) {
        $excelCleanupOk = $false
        $info = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $excelPid) -ErrorAction SilentlyContinue
        $cmd = if ($null -ne $info) { [string]$info.CommandLine } else { "" }
        $sameSession = $false
        try {
            $selfSession = [int](Get-Process -Id $PID -ErrorAction Stop).SessionId
            $sameSession = ([int]$xp.SessionId -eq $selfSession)
        } catch {}
        $isExcel = ([string]$xp.ProcessName -ieq "EXCEL")
        $hasCanonicalPath = (-not [string]::IsNullOrWhiteSpace($cmd) -and $cmd.IndexOf($workbookPath,[StringComparison]::OrdinalIgnoreCase) -ge 0)
        $titleMatches = (-not [string]::IsNullOrWhiteSpace([string]$xp.MainWindowTitle) -and $xp.MainWindowTitle -like ("*" + $workbookName + "*"))

        if ($isExcel -and $sameSession -and $hasCanonicalPath -and $titleMatches) {
            Write-Host ("Closing verified V10 runtime workbook without saving transient RSS changes (PID " + $excelPid + ") ...") -ForegroundColor Yellow
            $excelCleanupOk = Close-VerifiedManagedExcelNoSave $excelPid $workbookPath
            if (-not $excelCleanupOk) {
                # Excel can transition from a visible workbook window to a
                # hidden orphan a moment AFTER Workbook.Close/Quit returns.
                # Give that state transition a bounded wait before declaring
                # cleanup failure.
                $remaining = $null
                foreach ($attempt in 1..20) {
                    $remaining = Get-Process -Id $excelPid -ErrorAction SilentlyContinue
                    if ($null -eq $remaining) {
                        $excelCleanupOk = $true
                        break
                    }
                    if ($remaining.MainWindowHandle -eq 0) { break }
                    Start-Sleep -Milliseconds 250
                }
                if (-not $excelCleanupOk -and $null -ne $remaining -and $remaining.MainWindowHandle -eq 0) {
                    Write-Host ("Verified V10 Excel PID " + $excelPid + " became a hidden orphan after no-save close; attempting bounded PID-only cleanup...") -ForegroundColor Yellow
                    $excelCleanupOk = Stop-VerifiedHiddenManagedExcelOrphan $excelPid $workbookPath
                }
            }
            if ($excelCleanupOk) {
                Write-Host ("Verified V10 Excel PID " + $excelPid + " closed without save prompt and no orphan remains.") -ForegroundColor Green
            } else {
                Write-Host ("Verified V10 Excel PID " + $excelPid + " could not be fully closed safely; state is retained.") -ForegroundColor Red
            }
        } else {
            Write-Host ("Tracked Excel PID " + $excelPid + " failed ownership checks; not touching it and retaining state.") -ForegroundColor Red
        }
    }
}

if (-not $excelCleanupOk) {
    Write-Host "AI Cockpit V10 worker processes stopped, but managed Excel cleanup is incomplete." -ForegroundColor Red
    exit 2
}

if (-not $brainStopVerified) {
    Write-Host "V10 BRAIN safe stop incomplete; retained state for owner review. No unrelated PID was touched." -ForegroundColor Red
    exit 2
}

try {
    Remove-Item -LiteralPath $StateFile -Force -ErrorAction Stop
    if (Test-Path -LiteralPath $StateFile) { throw "STATE_FILE_STILL_PRESENT" }
} catch {
    Write-Host "V10 state removal failed; cannot report Safe Stop success." -ForegroundColor Red
    exit 2
}
Write-Host "AI Cockpit V10 managed processes and verified managed Excel stopped." -ForegroundColor Green
