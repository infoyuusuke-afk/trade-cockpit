param(
    [string]$Root = "C:\AI_Cockpit_OneClick_Starter",
    [switch]$InspectOnly,
    [switch]$ArchiveVerifiedStaleState,
    [string]$ExpectedSessionId = "",
    [string]$ExpectedStateSha256 = ""
)

# Stops only the PIDs this Controller (AI_COCKPIT_CONTROLLER_V10.ps1) itself
# recorded in V10_CONTROLLER_STATE.json. Never scans the system process
# table by name/window-title pattern, so it cannot touch an unrelated
# Excel session or PowerShell window. Excel is stopped only if its PID
# still matches the tracked window title, same rule the Controller's own
# supervision loop uses.

$ErrorActionPreference = "SilentlyContinue"
$StateFile = Join-Path $Root "V10_CONTROLLER_STATE.json"

if ($InspectOnly -and $ArchiveVerifiedStaleState) {
    Write-Host "RECOVERY_ARCHIVE=REFUSED_CONFLICTING_MODES; no changes." -ForegroundColor Red
    exit 2
}
if (-not (Test-Path -LiteralPath $StateFile)) {
    if ($ArchiveVerifiedStaleState) {
        Write-Host "RECOVERY_ARCHIVE=REFUSED_NO_STATE; no changes." -ForegroundColor Red
        exit 2
    }
    if ($InspectOnly) {
        Write-Host "V10_STOP_INSPECTION=READONLY"
        Write-Host "RECOVERY_CLASS=NO_STATE"
        Write-Host "STATE_MUTATED=0"
        Write-Host "PROCESS_TERMINATED=0"
        Write-Host "EXCEL_CLOSED=0"
        exit 0
    }
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
    if ($ArchiveVerifiedStaleState) {
        Write-Host "RECOVERY_ARCHIVE=REFUSED_INVALID_STATE; no changes." -ForegroundColor Red
        exit 2
    }
    if ($InspectOnly) {
        Write-Host "V10_STOP_INSPECTION=BLOCKED_UNVERIFIED"
        Write-Host "RECOVERY_CLASS=INVALID_STATE"
        Write-Host "STATE_MUTATED=0"
        Write-Host "PROCESS_TERMINATED=0"
        Write-Host "EXCEL_CLOSED=0"
        exit 2
    }
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

# Distinguish a proven absent PID from an inaccessible process inventory.
# The script's global SilentlyContinue policy must never turn access denied
# into an apparently completed STOP. No process is terminated by this probe.
function Get-V10TrackedPidEvidence([int]$ProcessId) {
    if ($ProcessId -le 0) { return "INVALID" }
    try {
        $cim = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $ProcessId) -ErrorAction Stop
        if ($null -eq $cim) { return "ABSENT" }
        if ([int]$cim.ProcessId -ne $ProcessId) { return "UNKNOWN" }
        $process = Get-Process -Id $ProcessId -ErrorAction Stop
        if ($null -eq $process -or $process.HasExited -or
            [int]$process.Id -ne $ProcessId) { return "UNKNOWN" }
        $handle = $process.Handle
        if ($handle -eq [IntPtr]::Zero) { return "UNKNOWN" }
        $cimStarted = ([datetime]$cim.CreationDate).ToUniversalTime()
        $processStarted = $process.StartTime.ToUniversalTime()
        if ([Math]::Abs(($cimStarted - $processStarted).TotalSeconds) -gt 2) {
            return "UNKNOWN"
        }
        return "ALIVE"
    } catch {
        return "UNKNOWN"
    }
}

# Check every recorded PID before ANY mutation. Missing optional fields are
# handled by the existing strict identity contracts; malformed or unobservable
# recorded PIDs must never be interpreted as already stopped.
function Test-V10RecordedPidInventory($State) {
    if ($null -eq $State) { return $false }
    foreach ($field in @("controller_pid","excel_pid","watcher_pid","heartbeat_pid",
        "collector_pid","gateway_pid","brain_gateway_pid","voice_bridge_pid",
        "sbv2_pid","shadow_supervisor_pid","brain_observer_pid")) {
        $entry = $State.PSObject.Properties[$field]
        if ($null -eq $entry) { continue }
        $id = 0
        if (-not [int]::TryParse([string]$entry.Value,[ref]$id) -or $id -lt 0) {
            return $false
        }
        if ($id -eq 0) { continue }
        if ((Get-V10TrackedPidEvidence $id) -in @("UNKNOWN","INVALID")) {
            return $false
        }
    }
    return $true
}

function Stop-OwnedJobBridge([int]$Port,[int]$ExpectedParentId,[string]$Label) {
    if ($ExpectedParentId -le 0) { return }
    $owner = Get-PortOwner $Port
    if ($owner -le 0) { return }
    try {
        $expectedScript = switch ($Port) {
            28580 { "MS2_RSS_100_Collector.ps1" }
            28582 { "Kioxia_RSS_Live_Watcher.ps1" }
            default { "" }
        }
        if (-not $expectedScript) { throw "UNRECOGNIZED_BRIDGE" }
        $parent = Get-Process -Id $ExpectedParentId -ErrorAction Stop
        $child = Get-Process -Id $owner -ErrorAction Stop
        $parentHandle = $parent.Handle
        $childHandle = $child.Handle
        if ($parentHandle -eq [IntPtr]::Zero -or $childHandle -eq [IntPtr]::Zero -or
            $parent.HasExited -or $child.HasExited) { throw "PROCESS_HANDLE_NOT_LIVE" }
        $parentCim = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $ExpectedParentId) -ErrorAction Stop
        $childCim = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $owner) -ErrorAction Stop
        if ([int]$childCim.ParentProcessId -ne $ExpectedParentId -or
            [string]$parentCim.Name -notmatch '^(powershell|pwsh)\.exe$' -or
            [string]$childCim.Name -notmatch '^(powershell|pwsh)\.exe$' -or
            ([string]$parentCim.CommandLine).IndexOf($expectedScript,[StringComparison]::OrdinalIgnoreCase) -lt 0 -or
            [int]$parent.SessionId -ne [int]$child.SessionId) {
            throw "BRIDGE_PARENT_IDENTITY_FAILED"
        }
        $parentStarted = $parent.StartTime.ToUniversalTime()
        $childStarted = $child.StartTime.ToUniversalTime()
        if ($childStarted -lt $parentStarted.AddSeconds(-2) -or
            [Math]::Abs(($parentStarted - ([datetime]$parentCim.CreationDate).ToUniversalTime()).TotalSeconds) -gt 2 -or
            [Math]::Abs(($childStarted - ([datetime]$childCim.CreationDate).ToUniversalTime()).TotalSeconds) -gt 2) {
            throw "BRIDGE_START_TIME_MISMATCH"
        }
        # Same verified child handle for identity and Kill: never re-resolve PID.
        $child.Kill()
        if (-not $child.WaitForExit(5000) -or -not $child.HasExited) {
            throw "BRIDGE_NOT_TERMINATED"
        }
        Write-Host ("Stopped verified " + $Label + " bridge child.") -ForegroundColor Green
    } catch {
        $script:bridgeStopVerified = $false
        Write-Host ("Bridge child ownership or exit unverified; retained state.") -ForegroundColor Red
    }
}

# Parse the actual interpreter script argument. A script basename appearing only
# in -c, -Command, a comment, or another inert argument is not ownership.
function Test-StopWorkerScriptArgument([string]$CommandLine,[string]$Field,[string[]]$ExpectedNames,[string]$RepoPath,[string]$RuntimePath) {
    try {
        if (-not ("V10StopWorkerArgv" -as [type])) {
            Add-Type -ErrorAction Stop -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class V10StopWorkerArgv {
    [DllImport("shell32.dll", SetLastError=true)]
    static extern IntPtr CommandLineToArgvW([MarshalAs(UnmanagedType.LPWStr)] string cmd, out int n);
    [DllImport("kernel32.dll")] static extern IntPtr LocalFree(IntPtr p);
    public static string[] Split(string cmd) {
        int n; IntPtr p = CommandLineToArgvW(cmd, out n);
        if (p == IntPtr.Zero) throw new InvalidOperationException();
        try {
            string[] args = new string[n];
            for (int i = 0; i < n; i++) args[i] = Marshal.PtrToStringUni(Marshal.ReadIntPtr(p, i * IntPtr.Size));
            return args;
        } finally { LocalFree(p); }
    }
}
"@
        }
        $argv = @([V10StopWorkerArgv]::Split($CommandLine))
        if ($argv.Count -lt 2) { return $false }
        $exe = [IO.Path]::GetFileName($argv[0])
        $scriptPath = ""
        if ($exe -imatch '^(powershell|pwsh)\.exe$') {
            if ($Field -in @("shadow_supervisor_pid", "brain_observer_pid", "sbv2_pid")) { return $false }
            $fileIndex = -1
            for ($i = 1; $i -lt $argv.Count; $i++) {
                if ($argv[$i] -imatch '^-(Command|EncodedCommand|CommandWithArgs)$') { return $false }
                if ($argv[$i] -ieq "-File") {
                    if ($fileIndex -ge 0 -or $i + 1 -ge $argv.Count) { return $false }
                    $fileIndex = $i + 1
                }
            }
            if ($fileIndex -lt 0) { return $false }
            $scriptPath = [string]$argv[$fileIndex]
            if (-not [IO.Path]::IsPathRooted($scriptPath)) { return $false }
        } elseif ($exe -imatch '^(python|pythonw|py)\.exe$') {
            if ($Field -notin @("shadow_supervisor_pid", "brain_observer_pid", "sbv2_pid")) { return $false }
            $index = 1
            if ($exe -ieq "py.exe") {
                if ($argv.Count -le $index -or $argv[$index] -cne "-3") { return $false }
                $index++
            }
            if ($argv.Count -gt $index -and $argv[$index] -cne "-u" -and
                $Field -in @("shadow_supervisor_pid", "brain_observer_pid")) { return $false }
            if ($argv.Count -gt $index -and $argv[$index] -ceq "-u") { $index++ }
            if ($argv.Count -le $index -or $argv[$index] -match '^-') { return $false }
            $scriptPath = [string]$argv[$index]
            if ($Field -ne "sbv2_pid" -and -not [IO.Path]::IsPathRooted($scriptPath)) { return $false }
        } else { return $false }
        # SBV2 also needs path-accurate ownership. The Controller now launches
        # the fixed absolute server path, so unrelated server_fastapi.py
        # scripts (or another interpreter) cannot be killed.
        if ($Field -eq "sbv2_pid") {
            if (-not [IO.Path]::IsPathRooted($scriptPath) -or
                -not [IO.Path]::IsPathRooted($argv[0])) { return $false }
            $sbvRoot = "C:\sbv2\Style-Bert-VITS2"
            $expectedServer = [IO.Path]::GetFullPath((Join-Path $sbvRoot "server_fastapi.py"))
            $actualServer = [IO.Path]::GetFullPath($scriptPath)
            $actualInterpreter = [IO.Path]::GetFullPath($argv[0])
            $expectedExe = if ($exe -ieq "pythonw.exe") { "pythonw.exe" } else { "python.exe" }
            $expectedInterpreter = [IO.Path]::GetFullPath((Join-Path $sbvRoot ("venv\Scripts\" + $expectedExe)))
            return ([string]::Equals($actualServer, $expectedServer, [StringComparison]::OrdinalIgnoreCase) -and
                [string]::Equals($actualInterpreter, $expectedInterpreter, [StringComparison]::OrdinalIgnoreCase))
        }
        if (-not [IO.Path]::IsPathRooted($scriptPath) -or
            -not [IO.Path]::IsPathRooted($RepoPath) -or
            -not [IO.Path]::IsPathRooted($RuntimePath)) { return $false }
        $expectedDir = switch ($Field) {
            { $_ -in @("watcher_pid", "heartbeat_pid", "collector_pid") } { $RuntimePath; break }
            { $_ -in @("controller_pid", "gateway_pid", "brain_gateway_pid", "voice_bridge_pid") } {
                Join-Path $RepoPath "downloads"; break
            }
            { $_ -in @("shadow_supervisor_pid", "brain_observer_pid") } {
                Join-Path $RepoPath "scripts"; break
            }
            default { "" }
        }
        if ([string]::IsNullOrWhiteSpace($expectedDir)) { return $false }
        $actualPath = [IO.Path]::GetFullPath($scriptPath)
        foreach ($name in $ExpectedNames) {
            $expectedPath = [IO.Path]::GetFullPath((Join-Path $expectedDir $name))
            if ([string]::Equals($actualPath, $expectedPath, [StringComparison]::OrdinalIgnoreCase)) {
                return $true
            }
        }
        return $false
    } catch { return $false }
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
        $proc = Get-Process -Id $ProcessId -ErrorAction Stop
        if ($proc.HasExited -or $proc.Handle -eq [IntPtr]::Zero) { return $false }
        $cimStarted = ([datetime]$wmi.CreationDate).ToUniversalTime()
        $handleStarted = $proc.StartTime.ToUniversalTime()
        if ([Math]::Abs(($handleStarted - $cimStarted).TotalSeconds) -gt 2) { return $false }
        if ([int]$wmi.ProcessId -ne $ProcessId -or [string]$wmi.Name -notmatch '^(powershell|pwsh|python|pythonw|py)\.exe$') { return $false }
        $selfSession = (Get-Process -Id $PID -ErrorAction Stop).SessionId
        if ([int]$proc.SessionId -ne [int]$selfSession) { return $false }
        # Token boundaries exclude spoofed names such as fake_RUN_AI_COCKPIT_V10.ps1.
        $names = if ($Field -eq "controller_pid") {
            @("AI_COCKPIT_CONTROLLER_V10.ps1", "RUN_AI_COCKPIT_V10.ps1")
        } else { @($expected) }
        foreach ($name in $names) {
            $escaped = [regex]::Escape($name)
            if ([regex]::IsMatch($cmd, '(?i)(?<![A-Za-z0-9_.-])' + $escaped + '(?=$|[\s"'']|\\)') -and
                (Test-StopWorkerScriptArgument $cmd $Field $names ([string]$state.repo_root) ([string]$state.runtime_dir))) {
                return $true
            }
        }
        return $false
    } catch { return $false }
}


function Test-BrainCommandLine([string]$CommandLine,[string]$Repo,[string]$Runtime) {
    try {
        if ([string]::IsNullOrWhiteSpace($CommandLine) -or
            -not [IO.Path]::IsPathRooted($Repo) -or
            -not [IO.Path]::IsPathRooted($Runtime)) { return $false }
        if (-not ("V10StopBrainArgv" -as [type])) {
            Add-Type -ErrorAction Stop -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class V10StopBrainArgv {
    [DllImport("shell32.dll", SetLastError=true)]
    static extern IntPtr CommandLineToArgvW([MarshalAs(UnmanagedType.LPWStr)] string cmd, out int n);
    [DllImport("kernel32.dll")] static extern IntPtr LocalFree(IntPtr p);
    public static string[] Split(string cmd) {
        int n; IntPtr p = CommandLineToArgvW(cmd, out n);
        if (p == IntPtr.Zero) throw new InvalidOperationException();
        try {
            string[] args = new string[n];
            for (int i = 0; i < n; i++) args[i] = Marshal.PtrToStringUni(Marshal.ReadIntPtr(p, i * IntPtr.Size));
            return args;
        } finally { LocalFree(p); }
    }
}
"@
        }
        $argv = @([V10StopBrainArgv]::Split($CommandLine))
        if ($argv.Count -lt 2) { return $false }
        $exe = [IO.Path]::GetFileName($argv[0])
        $offset = 1
        if ($exe -ieq "py.exe") {
            if ($argv[1] -cne "-3") { return $false }
            $offset = 2
        } elseif ($exe -inotmatch '^(python|pythonw)\.exe$') { return $false }
        # Match the Controller's complete launch contract. -c/-m, suffixes,
        # duplicated switches and paths merely mentioned as data never qualify.
        $expected = @("-u", (Join-Path $Repo "scripts\ai_brain_observer.py"),
            "--live", (Join-Path $Runtime "live_ms2.json"),
            "--status", (Join-Path $Runtime "ai_brain_observer_status_v1.json"),
            "--interval", "5")
        if ($argv.Count -ne $offset + $expected.Count) { return $false }
        for ($i = 0; $i -lt $expected.Count; $i++) {
            if ($i -in @(1,3,5)) {
                if (-not [IO.Path]::IsPathRooted($argv[$offset+$i]) -or
                    -not [string]::Equals([IO.Path]::GetFullPath($argv[$offset+$i]),
                        [IO.Path]::GetFullPath($expected[$i]), [StringComparison]::OrdinalIgnoreCase)) { return $false }
            } elseif ($argv[$offset+$i] -cne $expected[$i]) { return $false }
        }
        return $true
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
        if (-not (Test-BrainCommandLine $cmd $repo $runtime)) { return $false }
        $fromHandle = $Proc.StartTime.ToUniversalTime()
        $fromCim = ([datetime]$cim.CreationDate).ToUniversalTime()
        if ([Math]::Abs(($fromHandle - $fromCim).TotalSeconds) -gt 2) { return $false }
        $controllerStarted = ([datetime]$State.started_at).ToUniversalTime()
        return ($fromHandle -ge $controllerStarted.AddSeconds(-10))
    } catch { return $false }
}

# A tracked Excel PID is not an ownership token; require matching session,
# canonical workbook, original Controller parent and creation time.
# Only an exclusive canonical workbook may be closed as part of V10 STOP.
# Same-PID foreign workbooks are not visible to the process-level checks.
function Test-OnlyCanonicalExcelWorkbookOpen($Application,[string]$WorkbookPath) {
    if ($null -eq $Application -or [string]::IsNullOrWhiteSpace($WorkbookPath)) { return $false }
    try {
        $books = @($Application.Workbooks)
        if ($books.Count -ne 1) { return $false }
        $openPath = [string]$books[0].FullName
        if ([string]::IsNullOrWhiteSpace($openPath)) { return $false }
        return [string]::Equals([IO.Path]::GetFullPath($openPath),
            [IO.Path]::GetFullPath($WorkbookPath), [StringComparison]::OrdinalIgnoreCase)
    } catch { return $false }
}

# Do not force-kill a hidden Excel process unless the same COM application
# (HWND -> recorded PID) currently exposes ZERO remaining workbooks.
# Missing/unavailable ROT identity is UNKNOWN: fail closed and retain state.
function Test-NoExcelWorkbooksForPid([int]$ExcelPid) {
    if ($ExcelPid -le 0 -or -not ("AIExcelNative" -as [type])) { return $false }
    $application = $null
    try {
        $application = [Runtime.InteropServices.Marshal]::GetActiveObject("Excel.Application")
        if ($null -eq $application) { return $false }
        $hwnd = [int64]$application.Hwnd
        $foundPid = [uint32]0
        [void][AIExcelNative]::GetWindowThreadProcessId([IntPtr]$hwnd, [ref]$foundPid)
        if ([int]$foundPid -ne $ExcelPid) { return $false }
        return (@($application.Workbooks).Count -eq 0)
    } catch { return $false }
    finally {
        if ($null -ne $application) {
            try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($application) } catch {}
        }
    }
}

function Stop-VerifiedHiddenManagedExcelOrphan([int]$ExcelPid,[string]$WorkbookPath,
    [datetime]$ExpectedStartUtc,[int]$ExpectedControllerPid) {
    if ($ExcelPid -le 0 -or [string]::IsNullOrWhiteSpace($WorkbookPath) -or
        $ExpectedControllerPid -le 0 -or
        $ExpectedStartUtc -le [datetime]"2020-01-01") { return $false }
    $xp = Get-Process -Id $ExcelPid -ErrorAction SilentlyContinue
    if ($null -eq $xp) { return $true }

    try {
        # The opened handle remains the kill target even if PID changes.
        $handle = $xp.Handle
        if ($handle -eq [IntPtr]::Zero -or $xp.HasExited -or
            [string]$xp.ProcessName -ine "EXCEL") { return $false }
        $info = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $ExcelPid) -ErrorAction Stop
        if ($null -eq $info -or [int]$info.ProcessId -ne $ExcelPid -or
            [string]$info.Name -ine "EXCEL.EXE" -or
            [int]$info.ParentProcessId -ne $ExpectedControllerPid) { return $false }
        $cimStart = ([datetime]$info.CreationDate).ToUniversalTime()
        $handleStart = $xp.StartTime.ToUniversalTime()
        if ([Math]::Abs(($handleStart - $cimStart).TotalSeconds) -gt 2 -or
            $handleStart -lt $ExpectedStartUtc.ToUniversalTime().AddSeconds(-10)) { return $false }
        $selfSession = [int](Get-Process -Id $PID -ErrorAction Stop).SessionId
        if ([int]$xp.SessionId -ne $selfSession -or
            $xp.MainWindowHandle -ne 0) { return $false }
        $cmd = [string]$info.CommandLine
        if ([string]::IsNullOrWhiteSpace($cmd) -or
            $cmd.IndexOf($WorkbookPath,[StringComparison]::OrdinalIgnoreCase) -lt 0) { return $false }
        # Avoid force-killing any Excel if another one in this Windows session
        # may have unsaved Owner workbooks.
        $otherExcel = @(
            Get-Process EXCEL -ErrorAction Stop |
            Where-Object { $_.Id -ne $ExcelPid -and $_.SessionId -eq $selfSession }
        )
        if ($otherExcel.Count -gt 0 -or $xp.HasExited) { return $false }
        if (-not (Test-NoExcelWorkbooksForPid $ExcelPid)) { return $false }

        $xp.Kill()
        return ($xp.WaitForExit(5000) -and $xp.HasExited)
    } catch { return $false }
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

        # Verify exact workbook exclusivity before any COM mutation. A
        # company workbook may share this PID despite the target window title.
        if (-not (Test-OnlyCanonicalExcelWorkbookOpen $app $WorkbookPath)) {
            return $false
        }
        foreach ($book in @($app.Workbooks)) {
            $full = ""
            try { $full = [string]$book.FullName } catch {}
            if (-not [string]::IsNullOrWhiteSpace($full) -and
                [string]::Equals([IO.Path]::GetFullPath($full),
                    [IO.Path]::GetFullPath($WorkbookPath), [StringComparison]::OrdinalIgnoreCase)) {
                $targetBook = $book
                break
            }
            try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($book) } catch {}
        }
        if ($null -eq $targetBook) { return $false }
        # Close only the canonical RSS workbook. Do not set DisplayAlerts=false
        # on the entire Excel instance; foreign unsaved work must never be
        # discarded by automation.
        $targetBook.Close($false)
        # A foreign workbook may have been opened while Close was running.
        # Quit is authorized only if the application now has zero workbooks.
        if (@($app.Workbooks).Count -ne 0) { return $false }
        try { $app.Quit() } catch { return $false }

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

# Preflight Excel BEFORE stopping the Controller or workers. A tracked PID,
# matching title or matching substring alone never authorizes a partial stop.
# Inaccessible Excel COM/ROT is UNKNOWN and must retain the original session.
function Test-StopExcelPreflight($State) {
    $excelPid = 0
    if ($null -eq $State -or
        -not [int]::TryParse([string]$State.excel_pid,[ref]$excelPid) -or $excelPid -lt 0) {
        return $false
    }
    if ($excelPid -eq 0) { return $true }
    $proc = Get-Process -Id $excelPid -ErrorAction SilentlyContinue
    if ($null -eq $proc) { return $true }
    $app = $null
    try {
        $handle = $proc.Handle
        if ($handle -eq [IntPtr]::Zero -or $proc.HasExited -or
            [string]$proc.ProcessName -ine "EXCEL") { return $false }
        $controllerPid = 0
        if (-not [int]::TryParse([string]$State.controller_pid,[ref]$controllerPid) -or
            $controllerPid -le 0) { return $false }
        $workbookPath = [string]$State.workbook_path
        if ([string]::IsNullOrWhiteSpace($workbookPath) -or
            -not [IO.Path]::IsPathRooted($workbookPath)) { return $false }
        $info = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $excelPid) -ErrorAction Stop
        if ($null -eq $info -or [int]$info.ProcessId -ne $excelPid -or
            [string]$info.Name -ine "EXCEL.EXE" -or
            [int]$info.ParentProcessId -ne $controllerPid) { return $false }
        $started = $proc.StartTime.ToUniversalTime()
        if ([Math]::Abs(($started -
            ([datetime]$info.CreationDate).ToUniversalTime()).TotalSeconds) -gt 2 -or
            $started -lt ([datetime]$State.started_at).ToUniversalTime().AddSeconds(-10)) {
            return $false
        }
        $selfSession = (Get-Process -Id $PID -ErrorAction Stop).SessionId
        if ([int]$proc.SessionId -ne [int]$selfSession) { return $false }
        $cmd = [string]$info.CommandLine
        $canonicalLaunch = '/x "' + $workbookPath + '"'
        if ([string]::IsNullOrWhiteSpace($cmd) -or
            $cmd.IndexOf($canonicalLaunch, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
            return $false
        }
        $otherExcel = @(Get-Process EXCEL -ErrorAction Stop |
            Where-Object { $_.Id -ne $excelPid -and $_.SessionId -eq $selfSession })
        if ($otherExcel.Count -ne 0) { return $false }

        if (-not ("V10StopExcelPreflightNative" -as [type])) {
            Add-Type -ErrorAction Stop -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class V10StopExcelPreflightNative {
    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
}
"@
        }
        $app = [Runtime.InteropServices.Marshal]::GetActiveObject("Excel.Application")
        if ($null -eq $app) { return $false }
        $hwnd = [int64]$app.Hwnd
        if ($hwnd -eq 0) { return $false }
        $resolvedPid = [uint32]0
        [void][V10StopExcelPreflightNative]::GetWindowThreadProcessId([IntPtr]$hwnd,[ref]$resolvedPid)
        if ([int]$resolvedPid -ne $excelPid) { return $false }
        $count = @($app.Workbooks).Count
        if ($count -eq 0) { return ($proc.MainWindowHandle -eq 0) }
        return (Test-OnlyCanonicalExcelWorkbookOpen $app $workbookPath)
    } catch { return $false }
    finally {
        if ($null -ne $app) {
            try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($app) } catch {}
        }
    }
}

function Get-V10RecoverySha256([byte[]]$Payload) {
    if ($null -eq $Payload) { throw "STATE_BYTES_UNAVAILABLE" }
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return [BitConverter]::ToString($sha.ComputeHash($Payload)).Replace("-","").ToLowerInvariant()
    } finally { $sha.Dispose() }
}

# Read-only recovery inspector: a prior failed STOP can block startup because
# Controller intentionally preserves V10_CONTROLLER_STATE.json. Diagnose the
# cause without granting this script permission to kill, close, save, deploy,
# change state or override guarded RUN. A result is never an authorization to
# delete a stale state file or to submit a live order.
function Invoke-V10StopReadOnlyInspection($RecordedState) {
    Write-Host "V10_STOP_INSPECTION=READONLY"
    Write-Host "STATE_MUTATED=0"
    Write-Host "PROCESS_TERMINATED=0"
    Write-Host "EXCEL_CLOSED=0"
    Write-Host "REAL_SUBMIT_ALLOWED=0"
    $blocked = $false
    $live = $false
    $recorded = 0
    foreach ($field in @("controller_pid","excel_pid","watcher_pid",
        "heartbeat_pid","collector_pid","gateway_pid","brain_gateway_pid",
        "voice_bridge_pid","sbv2_pid","shadow_supervisor_pid","brain_observer_pid")) {
        $entry = $RecordedState.PSObject.Properties[$field]
        $pidValue = 0
        $status = "NOT_RECORDED"
        if ($null -eq $entry -or
            -not [int]::TryParse([string]$entry.Value,[ref]$pidValue) -or
            $pidValue -lt 0) {
            $status = "UNKNOWN"
            $blocked = $true
        } elseif ($pidValue -eq 0) {
            $status = "NOT_STARTED"
        } else {
            $recorded++
            $status = Get-V10TrackedPidEvidence $pidValue
            if ($status -eq "ALIVE") {
                $owned = $false
                if ($field -eq "excel_pid") {
                    $owned = Test-StopExcelPreflight $RecordedState
                } else {
                    $owned = Test-OwnedPidIdentity $field $pidValue
                    if ($owned -and $field -eq "brain_observer_pid") {
                        $opened = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
                        $owned = (Test-ExactBrainHandle $opened $RecordedState)
                    }
                }
                if ($owned) {
                    $status = "ALIVE_OWNED"
                    $live = $true
                } else {
                    $status = "ALIVE_FOREIGN_OR_UNVERIFIED"
                    $blocked = $true
                }
            } elseif ($status -eq "UNKNOWN" -or $status -eq "INVALID") {
                $blocked = $true
            }
        }
        Write-Host ("PID_" + $field + "=" + $status)
    }
    try {
        $listeners = @(Get-NetTCPConnection -State Listen -ErrorAction Stop |
            Where-Object { @(28580,28581,28582,28583,28584) -contains [int]$_.LocalPort })
        foreach ($port in @(28580,28581,28582,28583,28584)) {
            $present = @($listeners | Where-Object { [int]$_.LocalPort -eq $port }).Count -gt 0
            Write-Host ("PORT_" + $port + "=" + $(if ($present) { "LISTEN" } else { "FREE" }))
            if ($present) { $blocked = $true }
        }
    } catch {
        foreach ($port in @(28580,28581,28582,28583,28584)) {
            Write-Host ("PORT_" + $port + "=UNKNOWN")
        }
        $blocked = $true
    }
    if ($blocked) {
        Write-Host "V10_STOP_INSPECTION=BLOCKED_UNVERIFIED"
        Write-Host "RECOVERY_CLASS=REQUIRES_INDEPENDENT_REVIEW"
        Write-Host "AUTOMATIC_STATE_DELETION_ALLOWED=0"
        return 2
    }
    if ($live) {
        Write-Host "RECOVERY_CLASS=ACTIVE_V10_PROCESS"
    } elseif ($recorded -gt 0) {
        Write-Host "RECOVERY_CLASS=STALE_STATE_REVIEW_REQUIRED"
    } else {
        Write-Host "RECOVERY_CLASS=EMPTY_TRACKING_REVIEW_REQUIRED"
    }
    Write-Host "AUTOMATIC_STATE_DELETION_ALLOWED=0"
    return 0
}

if ($InspectOnly) {
    try {
        $snapshotSha = Get-V10RecoverySha256 ([IO.File]::ReadAllBytes($StateFile))
    } catch {
        Write-Host "V10_STOP_INSPECTION=BLOCKED_UNVERIFIED"
        Write-Host "RECOVERY_CLASS=STATE_READ_FAILED"
        Write-Host "STATE_MUTATED=0"
        Write-Host "PROCESS_TERMINATED=0"
        Write-Host "EXCEL_CLOSED=0"
        exit 2
    }
    Write-Host ("STATE_SHA256=" + $snapshotSha)
    Write-Host ("SESSION_ID=" + [string]$state.session_id)
    $inspectionResult = Invoke-V10StopReadOnlyInspection $state
    exit $inspectionResult
}

# The only permitted path from a proven stale V10 state to a fresh startup
# is an EXPLICIT, session-and-hash-pinned archive of the original evidence.
# No process/Excel/port is stopped here. This mode is not called by RUN.
# Refuse unknown, foreign, corrupt, untracked legacy BRAIN or active PID/port.
# Read-only discovery of UNTRACKED V10 components. Never use a broad
# process-name scan as kill authority. Treat positive V10 script argv evidence
# as a reason to refuse archive, including workers missing from stale JSON.
function Test-NoUntrackedV10Process {
    try {
        $all = @(Get-CimInstance Win32_Process -ErrorAction Stop)
        $patterns = @(
            '(?i)(?:^|[\\/"\s])AI_COCKPIT_CONTROLLER_V10\.ps1(?:["\s]|$)',
            '(?i)(?:^|[\\/"\s])RUN_AI_COCKPIT_V10\.ps1(?:["\s]|$)',
            '(?i)(?:^|[\\/"\s])AI_COCKPIT_GATEWAY_V10\.ps1(?:["\s]|$)',
            '(?i)(?:^|[\\/"\s])AI_COCKPIT_VOICE_BRIDGE_V10\.ps1(?:["\s]|$)',
            '(?i)(?:^|[\\/"\s])Kioxia_RSS_Live_Watcher\.ps1(?:["\s]|$)',
            '(?i)(?:^|[\\/"\s])MS2_RSS_100_Collector\.ps1(?:["\s]|$)',
            '(?i)(?:^|[\\/"\s])ai_brain_observer\.py(?:["\s]|$)',
            '(?i)(?:^|[\\/"\s])ai_shadow_supervisor\.py(?:["\s]|$)',
            '(?i)(?:^|[\\/"\s])server_fastapi\.py(?:["\s]|$)'
        )
        foreach ($process in $all) {
            $name = [string]$process.Name
            if ($name -notmatch '^(powershell|pwsh|python|pythonw|py)\.exe$') {
                continue
            }
            $cmd = [string]$process.CommandLine
            if ([string]::IsNullOrWhiteSpace($cmd)) { return $false }
            foreach ($pattern in $patterns) {
                if ($cmd -match $pattern) { return $false }
            }
        }
        return $true
    } catch { return $false }
}

function Test-V10RecoveryStateInvariants($RecordedState) {
    if ($null -eq $RecordedState) { return $false }
    foreach ($field in @("controller_pid","excel_pid","watcher_pid","heartbeat_pid",
        "collector_pid","gateway_pid","brain_gateway_pid","voice_bridge_pid",
        "sbv2_pid","shadow_supervisor_pid","brain_observer_pid")) {
        $entry = $RecordedState.PSObject.Properties[$field]
        $id = 0
        if ($null -eq $entry -or
            -not [int]::TryParse([string]$entry.Value,[ref]$id) -or
            $id -lt 0) { return $false }
        if ($field -in @("controller_pid","brain_observer_pid") -and $id -le 0) {
            return $false
        }
        if ($id -gt 0 -and (Get-V10TrackedPidEvidence $id) -ne "ABSENT") {
            return $false
        }
    }
    try {
        if ([string]::IsNullOrWhiteSpace([string]$RecordedState.session_id) -or
            [string]::IsNullOrWhiteSpace([string]$RecordedState.repo_root) -or
            [string]::IsNullOrWhiteSpace([string]$RecordedState.runtime_dir) -or
            -not [IO.Path]::IsPathRooted([string]$RecordedState.repo_root) -or
            -not [IO.Path]::IsPathRooted([string]$RecordedState.runtime_dir) -or
            -not [IO.Path]::IsPathRooted([string]$RecordedState.workbook_path)) {
            return $false
        }
        $expectedWorkbook = [IO.Path]::GetFullPath(
            (Join-Path ([string]$RecordedState.runtime_dir) "Kioxia_MS2_RSS_Live_Signals.xlsx"))
        if (-not [string]::Equals(
            ([IO.Path]::GetFullPath([string]$RecordedState.workbook_path)),
            $expectedWorkbook, [StringComparison]::OrdinalIgnoreCase)) {
            return $false
        }
        $startedAt = [datetimeoffset]::Parse([string]$RecordedState.started_at)
        if ($startedAt -gt [datetimeoffset]::UtcNow.AddMinutes(5)) { return $false }
        $ports = @(Get-NetTCPConnection -State Listen -ErrorAction Stop |
            Where-Object { @(28580,28581,28582,28583,28584) -contains [int]$_.LocalPort })
        if ($ports.Count -ne 0) { return $false }
        if (-not (Test-NoUntrackedV10Process)) { return $false }
        return $true
    } catch { return $false }
}

function Invoke-V10VerifiedStaleArchive($RecordedState) {
    Write-Host "RECOVERY_ARCHIVE=EXPLICIT_REVIEWED_OPERATION"
    Write-Host "REAL_SUBMIT_ALLOWED=0"
    Write-Host "PROCESS_TERMINATED=0"
    Write-Host "EXCEL_CLOSED=0"
    # A user must explicitly supply the exact session and SHA-256 observed in
    # read-only inspection. A generic -ArchiveVerifiedStaleState is insufficient.
    if ([string]::IsNullOrWhiteSpace($ExpectedSessionId) -or
        [string]$ExpectedSessionId -cne [string]$RecordedState.session_id -or
        [string]$ExpectedStateSha256 -notmatch '^[a-fA-F0-9]{64}$') {
        Write-Host "RECOVERY_ARCHIVE=REFUSED_MISSING_OR_WRONG_EXPECTED_IDENTITY"
        return 2
    }
    try {
        $item = Get-Item -LiteralPath $StateFile -ErrorAction Stop
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "REPARSE_POINT_STATE"
        }
        $before = [IO.File]::ReadAllBytes($StateFile)
        $pin = Get-V10RecoverySha256 $before
        if ($pin -cne $ExpectedStateSha256.ToLowerInvariant()) {
            throw "STATE_HASH_CHANGED"
        }
        # Do not use the earlier parsed state as a substitute for the pinned
        # snapshot. Parse the exact bytes being reviewed.
        $verified = [Text.Encoding]::UTF8.GetString($before) |
            ConvertFrom-Json -ErrorAction Stop
        if ($null -eq $verified -or
            [string]$verified.session_id -cne $ExpectedSessionId -or
            -not (Test-V10RecoveryStateInvariants $verified)) {
            throw "STALE_STATE_PROOF_FAILED"
        }
        # Recheck after disk read: PID reuse or a new TCP listener must refuse
        # the archive even when the state hash itself has not changed.
        if (-not (Test-V10RecoveryStateInvariants $verified)) {
            throw "RECHECK_PROOF_FAILED"
        }
        $archiveName = "V10_CONTROLLER_STATE.archived." +
            ([datetime]::UtcNow.ToString("yyyyMMddTHHmmssZ")) + "." +
            ([guid]::NewGuid().ToString("N")) + ".json"
        $target = Join-Path $Root $archiveName
        if (Test-Path -LiteralPath $target) { throw "ARCHIVE_COLLISION" }
        # Same-directory rename preserves the bytes; never erase or overwrite
        # the original state as a shortcut. Confirm the snapshot again.
        if ((Get-V10RecoverySha256 ([IO.File]::ReadAllBytes($StateFile))) -cne $pin) {
            throw "STATE_CHANGED_BEFORE_RENAME"
        }
        # A newly launched, unrecorded V10 process must block the final
        # state rename even if its listener has not yet bound a port.
        if (-not (Test-V10RecoveryStateInvariants $verified)) {
            throw "PRE_RENAME_PROCESS_OR_PORT_CHANGED"
        }
        [IO.File]::Move($StateFile,$target)
        if (-not (Test-Path -LiteralPath $target -PathType Leaf) -or
            (Test-Path -LiteralPath $StateFile) -or
            (Get-V10RecoverySha256 ([IO.File]::ReadAllBytes($target))) -cne $pin) {
            throw "ARCHIVE_VERIFICATION_FAILED"
        }
        Write-Host "RECOVERY_ARCHIVE=VERIFIED_ARCHIVED"
        Write-Host ("ARCHIVED_STATE_SHA256=" + $pin)
        Write-Host ("ARCHIVE_PATH=" + $target)
        Write-Host "ACTIVE_STATE_ARCHIVED=1"
        Write-Host "CONTROLLER_STARTED=0"
        Write-Host "STOP_ALLOWED=0"
        return 0
    } catch {
        Write-Host ("RECOVERY_ARCHIVE=REFUSED_OR_UNVERIFIED; reason=" + $_.Exception.Message) -ForegroundColor Red
        Write-Host "AUTOMATIC_STATE_DELETION_ALLOWED=0"
        return 2
    }
}

if ($ArchiveVerifiedStaleState) {
    exit (Invoke-V10VerifiedStaleArchive $state)
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

# The global SilentlyContinue preference must not hide access-denied
# process discovery. Complete PID inventory is required before ANY stop.
if (-not (Test-V10RecordedPidInventory $state)) {
    Write-Host "SAFE_STOP_PREFLIGHT=PID_INVENTORY_UNVERIFIED; no processes stopped." -ForegroundColor Red
    exit 2
}

# P0-25 verify every recorded worker BEFORE terminating the supervisor.
# A reused PID or unrelated process prevents partial teardown.
foreach ($field in @("watcher_pid","heartbeat_pid","collector_pid","gateway_pid",
    "brain_gateway_pid","voice_bridge_pid","sbv2_pid","shadow_supervisor_pid")) {
    $member = $state.PSObject.Properties[$field]
    if ($null -eq $member) { continue }
    $tracked = 0
    if (-not [int]::TryParse([string]$member.Value,[ref]$tracked) -or $tracked -lt 0) {
        Write-Host "SAFE_STOP_PREFLIGHT=BLOCKED_INVALID_WORKER_PID; no workers stopped." -ForegroundColor Red
        exit 2
    }
    $handle = if ($tracked -gt 0) { Get-Process -Id $tracked -ErrorAction SilentlyContinue } else { $null }
    if ($null -ne $handle -and -not (Test-OwnedPidIdentity $field $tracked)) {
        Write-Host "SAFE_STOP_PREFLIGHT=BLOCKED_FOREIGN_WORKER_PID; retain state." -ForegroundColor Red
        exit 2
    }
}

# No partial worker or Controller shutdown when Excel already fails
# ownership or workbook-exclusivity checks.
if (-not (Test-StopExcelPreflight $state)) {
    Write-Host "SAFE_STOP_PREFLIGHT=BLOCKED_EXCEL_IDENTITY_OR_WORKBOOKS; no processes stopped." -ForegroundColor Red
    exit 2
}

# Stop the supervising RUN/Controller host FIRST. Otherwise it can restart
# Gateway/Voice/Shadow while Safe Stop is still tearing workers down.
$controllerVal = $state.PSObject.Properties["controller_pid"]
if ($null -ne $controllerVal -and [int]$controllerVal.Value -gt 0) {
    $controllerPid = [int]$controllerVal.Value
    $controllerProc = Get-Process -Id $controllerPid -ErrorAction SilentlyContinue
    if ($null -ne $controllerProc -and (Test-OwnedPidIdentity "controller_pid" $controllerPid)) {
        try {
            # Terminate through the already-opened Controller process handle.
            # A recycled numeric PID must never redirect the stop operation.
            $controllerHandle = $controllerProc.Handle
            if ($controllerHandle -eq [IntPtr]::Zero -or $controllerProc.HasExited) {
                throw "CONTROLLER_HANDLE_NOT_LIVE"
            }
            $controllerProc.Kill()
            if (-not $controllerProc.WaitForExit(5000) -or -not $controllerProc.HasExited) {
                throw "CONTROLLER_NOT_TERMINATED"
            }
            Write-Host ("Stopped verified controller_pid (PID " + $controllerPid + ")") -ForegroundColor Green
        } catch {
            Write-Host ("Controller/RUN PID " + $controllerPid + " stop unverified; aborting before worker teardown.") -ForegroundColor Red
            exit 2
        }
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
        [string]$latest.started_at -cne [string]$state.started_at -or
        [string]$latest.repo_root -cne [string]$state.repo_root -or
        [string]$latest.runtime_dir -cne [string]$state.runtime_dir -or
        [int]$latest.excel_pid -ne [int]$state.excel_pid -or
        [string]$latest.workbook_path -cne [string]$state.workbook_path -or
        [int]$latest.brain_observer_pid -le 0) {
        throw "BRAIN identity or session not recorded"
    }
    $state = $latest
} catch {
    Write-Host "Latest BRAIN PID/state unverified after Controller exit; retained state." -ForegroundColor Red
    exit 2
}

# The Controller may have refreshed worker PIDs before exiting. Confirm
# its final state has no unreadable or recycled process identities before
# proceeding to bridge/worker/Excel teardown.
if (-not (Test-V10RecordedPidInventory $state) -or
    -not (Test-StopExcelPreflight $state)) {
    Write-Host "SAFE_STOP_VERIFY=LATEST_PID_OR_EXCEL_UNVERIFIED; retained state." -ForegroundColor Red
    exit 2
}

# Every record must belong to the saved session before stopping ANY worker.
# A reused PID or unrelated process prevents partial teardown.
foreach ($field in @("watcher_pid","heartbeat_pid","collector_pid","gateway_pid",
    "brain_gateway_pid","voice_bridge_pid","sbv2_pid","shadow_supervisor_pid")) {
    $member = $state.PSObject.Properties[$field]
    if ($null -eq $member) { continue }
    $tracked = 0
    if (-not [int]::TryParse([string]$member.Value,[ref]$tracked) -or $tracked -lt 0) {
        Write-Host "SAFE_STOP_PREFLIGHT=BLOCKED_INVALID_WORKER_PID; no workers stopped." -ForegroundColor Red
        exit 2
    }
    $handle = if ($tracked -gt 0) { Get-Process -Id $tracked -ErrorAction SilentlyContinue } else { $null }
    if ($null -ne $handle -and -not (Test-OwnedPidIdentity $field $tracked)) {
        Write-Host "SAFE_STOP_PREFLIGHT=BLOCKED_FOREIGN_WORKER_PID; retain state." -ForegroundColor Red
        exit 2
    }
}

$script:bridgeStopVerified = $true
Stop-OwnedJobBridge 28580 ([int]$state.collector_pid) "Collector JSON"
Stop-OwnedJobBridge 28582 ([int]$state.watcher_pid) "Watcher JSON"

$brainStopVerified = $true
$workerStopVerified = $true
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
        try {
            # Hold the verified Process object instead of looking up a
            # numeric PID again (which could have been recycled).
            $openedHandle = $p.Handle
            if ($openedHandle -eq [IntPtr]::Zero -or $p.HasExited) {
                throw "PROCESS_HANDLE_INVALID"
            }
            $p.Kill()
            if (-not $p.WaitForExit(5000) -or -not $p.HasExited) {
                throw "WORKER_STILL_RUNNING"
            }
            Write-Host ("Stopped verified " + $field) -ForegroundColor Green
        } catch {
            $workerStopVerified = $false
            Write-Host ("Worker " + $field + " exit unverified; retained state.") -ForegroundColor Red
        }
    } elseif ($null -ne $p) {
        $workerStopVerified = $false
        Write-Host ("Worker " + $field + " ownership changed; retaining state.") -ForegroundColor Red
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
                    Write-Host ("Verified V10 Excel PID " + $excelPid + " became a hidden orphan after no-save close; attempting handle-pinned identity cleanup...") -ForegroundColor Yellow
                    $excelCleanupOk = Stop-VerifiedHiddenManagedExcelOrphan $excelPid $workbookPath `
                        ([datetime]$state.started_at).ToUniversalTime() ([int]$state.controller_pid)
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

if (-not $brainStopVerified -or -not $workerStopVerified -or -not $script:bridgeStopVerified) {
    Write-Host "V10 safe stop incomplete; recorded state retained for owner review." -ForegroundColor Red
    exit 2
}

# A worker may outlive its wrapper via a child JSON bridge, or a new
# listener may bind before teardown ends. Never claim stopped / delete
# recovery evidence while any of the V10 ports are still in LISTEN.
try {
    $listeners = @(Get-NetTCPConnection -State Listen -ErrorAction Stop |
        Where-Object { @(28580,28581,28582,28583,28584) -contains [int]$_.LocalPort })
    if ($listeners.Count -gt 0) {
        Write-Host "SAFE_STOP_VERIFY=LISTEN_PORTS_REMAIN; retained state." -ForegroundColor Red
        exit 2
    }
} catch {
    Write-Host "SAFE_STOP_VERIFY=PORT_AUDIT_FAILED; retained state." -ForegroundColor Red
    exit 2
}
foreach ($field in @("controller_pid","excel_pid","watcher_pid","heartbeat_pid",
    "collector_pid","gateway_pid","brain_gateway_pid","voice_bridge_pid",
    "sbv2_pid","shadow_supervisor_pid","brain_observer_pid")) {
    $entry = $state.PSObject.Properties[$field]
    if ($null -eq $entry) { continue }
    $tracked = 0
    if (-not [int]::TryParse([string]$entry.Value,[ref]$tracked) -or $tracked -lt 0) {
        Write-Host "SAFE_STOP_VERIFY=TRACKED_PID_INVALID; retained state." -ForegroundColor Red
        exit 2
    }
    if ($tracked -eq 0) { continue }
    $evidence = Get-V10TrackedPidEvidence $tracked
    if ($evidence -ne "ABSENT") {
        Write-Host ("SAFE_STOP_VERIFY=TRACKED_PID_NOT_PROVEN_ABSENT; field=" + $field +
            "; evidence=" + $evidence + "; retained state.") -ForegroundColor Red
        exit 2
    }
}

# Another writer may have modified the state while workers stopped. Never
# delete recovery evidence belonging to a different session or PID list.
try {
    $onDisk = [IO.File]::ReadAllText($StateFile,[Text.Encoding]::UTF8) |
        ConvertFrom-Json -ErrorAction Stop
    if ($null -eq $onDisk -or
        [string]$onDisk.session_id -cne [string]$state.session_id -or
        [string]$onDisk.started_at -cne [string]$state.started_at -or
        [int]$onDisk.controller_pid -ne [int]$state.controller_pid -or
        [int]$onDisk.excel_pid -ne [int]$state.excel_pid -or
        [string]$onDisk.workbook_path -cne [string]$state.workbook_path) {
        throw "SESSION_CHANGED"
    }
    foreach ($field in @("watcher_pid","heartbeat_pid","collector_pid",
        "gateway_pid","brain_gateway_pid","voice_bridge_pid","sbv2_pid",
        "shadow_supervisor_pid","brain_observer_pid")) {
        if ([string]$onDisk.$field -cne [string]$state.$field) {
            throw "WORKER_LIST_CHANGED"
        }
    }
} catch {
    Write-Host "SAFE_STOP_VERIFY=STATE_CHANGED_BEFORE_DELETE; retained state." -ForegroundColor Red
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
