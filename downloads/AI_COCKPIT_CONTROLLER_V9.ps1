param(
    [string]$RepoRoot = "",
    [string]$Root = "C:\AI_Cockpit_OneClick_Starter",
    [string]$ExpectedBranch = "",
    [string]$RuntimeDirOverride = "",
    [switch]$IdentityProbeSelfTest
)

# AI Cockpit Controller V8
#
# Rebuilt 2026-09-25 to fix two problems observed with V6/the draft V7:
#   1. The Controller itself could sit blocked for up to 180s (Collector)
#      or 120s (SBV2) during startup, and had no supervision loop after
#      startup at all - if Collector died later, nothing noticed and the
#      Controller process had already exited.
#   2. The card UI (PR #258-#261) never appeared locally because the old
#      Gateway proxies every page from the PUBLIC GitHub Pages site
#      (main branch), not from this local checkout. Until those PRs merge
#      to main, no amount of local script changes makes them visible
#      through that Gateway. Fixed by AI_COCKPIT_GATEWAY_V9.ps1, which
#      serves index.html/card_system.*/etc. directly from $RepoRoot on
#      disk - "checkout the branch you want live" IS the deploy step, and
#      /health reports exactly which git branch/commit is being served.
#
# Design differences from V6/V7 that matter for safety:
#   - Only ever stops PIDs THIS controller itself recorded in its own
#     state file. Never enumerates and kills processes by scanning for
#     "any Excel with no visible window" or similar broad heuristics -
#     that risks killing a user's unrelated Excel session. (This is the
#     one thing the draft V7 PR got wrong; V8 does not repeat it.)
#   - Collector is supervised independently: if it dies or never becomes
#     ready, the Controller and the Gateway/UI stay up and the UI stays
#     fail-closed. The Controller does not exit because Collector failed.
#   - No single wait is longer than 45s. The Controller reports status
#     every few seconds instead of going silent.
#   - Runs as a persistent supervision loop after startup (not "start and
#     exit" like V6) so it can react to Collector dying or Excel closing
#     without the user re-running anything.
#   - Never touches real_submit_allowed, RssOrder, or any order/broker
#     path. Supervises the existing read-only Watcher/Collector/
#     Heartbeat/Gateway processes, one AI SHADOW supervisor, and the
#     Excel process that hosts the workbook. The shadow supervisor does
#     not attach to Excel and does not keep running trades after this
#     controller stops the data path.

$ErrorActionPreference = "Stop"
$Build = "V9-CONTROLLER-20261002-EXCEL-OWNERSHIP-01"
$ExcelIdentityProbeTimeoutSeconds = 35
$sw = [Diagnostics.Stopwatch]::StartNew()

# Port map (fixed 2026-09-25): Collector=28580, Gateway=28581,
# Watcher=28582. Watcher's own local JSON bridge (Kioxia_RSS_Live_Watcher.ps1)
# used to also hardcode 28581, silently colliding with the Gateway - moved
# to 28582 in the same change that added this preflight check.
$PORT_COLLECTOR = 28580
$PORT_GATEWAY = 28581
$PORT_WATCHER = 28582
$PORT_VOICE = 28583

# ---------------------------------------------------------------- utility

function Write-Status([string]$Message, [ConsoleColor]$Color = [ConsoleColor]::Cyan) {
    $sec = [Math]::Round($sw.Elapsed.TotalSeconds, 1)
    Write-Host ("[{0,7}s] {1}" -f $sec, $Message) -ForegroundColor $Color
}

# 2026-09-25 fix: Windows PowerShell 5.1's `Get-Content -Raw` does not
# reliably treat a BOM-less UTF-8 file as UTF-8 - it can fall back to the
# system ANSI codepage (Shift-JIS on this machine), corrupting the
# Japanese RuntimeDir path in V9_RUNTIME.json/V9_CONTROLLER_STATE.json on
# read-back even though they were written as UTF-8. This is what actually
# stopped the Controller on the first real-machine run. Every JSON read in
# this script goes through this helper instead of `Get-Content -Raw`.
function Read-JsonUtf8([string]$Path) {
    $text = [IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8)
    return $text | ConvertFrom-Json
}

function Test-Port([int]$Port, [int]$TimeoutMs = 400) {
    $c = New-Object Net.Sockets.TcpClient
    try {
        $a = $c.BeginConnect("127.0.0.1", $Port, $null, $null)
        if (-not $a.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) { return $false }
        $c.EndConnect($a)
        return $true
    } catch {
        return $false
    } finally {
        try { $c.Close() } catch {}
    }
}

function Wait-PortBounded([int]$Port, [int]$MaxSeconds, [string]$Label) {
    $deadline = (Get-Date).AddSeconds($MaxSeconds)
    $nextReport = 5
    while ((Get-Date) -lt $deadline) {
        if (Test-Port $Port 400) { return $true }
        $elapsed = [int]((Get-Date) - ($deadline.AddSeconds(-$MaxSeconds))).TotalSeconds
        if ($elapsed -ge $nextReport) {
            Write-Status ("  waiting on {0} (port {1})... {2}s / {3}s" -f $Label, $Port, $elapsed, $MaxSeconds) DarkGray
            $nextReport += 5
        }
        Start-Sleep -Milliseconds 400
    }
    return $false
}

function Get-ListeningOwnerPid([int]$Port) {
    try {
        $conn = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $conn) { return [int]$conn.OwningProcess }
    } catch {}
    return 0
}

function Stop-OwnedJobBridge([int]$Port,[int]$ExpectedParentId,[string]$Label) {
    if ($ExpectedParentId -le 0) { return $false }
    $owner = Get-ListeningOwnerPid $Port
    if ($owner -le 0) { return $true }
    try {
        $info = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $owner) -ErrorAction SilentlyContinue
        if ($null -eq $info) { return $false }
        $name = [string]$info.Name
        $parent = [int]$info.ParentProcessId
        if ($parent -eq $ExpectedParentId -and $name -match "^(powershell|pwsh)\.exe$") {
            Stop-Process -Id $owner -Force -ErrorAction SilentlyContinue
            Write-Status ("  stopped owned {0} bridge child: port {1}, PID {2}, parent {3}" -f $Label,$Port,$owner,$ExpectedParentId) DarkGray
            return $true
        }
    } catch {}
    return $false
}

# Preflight: a port already LISTENing is not, by itself, evidence that
# THIS controller's own session is ready - it could be a leftover V6/V7
# process, a stale previous V8 session, or something unrelated entirely.
# Only a PID this controller itself recorded (current run's own state, or
# nothing at all) is acceptable; anything else stops startup outright
# rather than silently treating an unknown listener as "our session".
function Test-ForeignSession([hashtable]$OwnPids) {
    $foreign = @()
    foreach ($entry in @(
        @{ port = $PORT_COLLECTOR; label = "Collector" },
        @{ port = $PORT_GATEWAY; label = "Gateway" },
        @{ port = $PORT_WATCHER; label = "Watcher" },
        @{ port = $PORT_VOICE; label = "VoiceBridge" }
    )) {
        if (-not (Test-Port $entry.port 300)) { continue }
        $owner = Get-ListeningOwnerPid $entry.port
        $isOwn = $false
        foreach ($ownedPid in $OwnPids.Values) {
            if ($ownedPid -gt 0 -and $owner -eq $ownedPid) { $isOwn = $true; break }
        }
        if (-not $isOwn) {
            $procName = "unknown"
            try {
                $p = Get-Process -Id $owner -ErrorAction SilentlyContinue
                if ($null -ne $p) { $procName = $p.ProcessName }
            } catch {}
            $foreign += ("port " + $entry.port + " (" + $entry.label + ") owned by PID " + $owner + " (" + $procName + ")")
        }
    }
    return $foreign
}

function Resolve-RuntimeDir([string]$Explicit) {
    if (-not [string]::IsNullOrWhiteSpace($Explicit)) {
        $resolved = [IO.Path]::GetFullPath($Explicit)
        if (-not (Test-Path -LiteralPath $resolved -PathType Container)) {
            throw "RuntimeDirOverride does not exist: $resolved"
        }
        $book = Join-Path $resolved "Kioxia_MS2_RSS_Live_Signals.xlsx"
        if (-not (Test-Path -LiteralPath $book -PathType Leaf)) {
            throw "RuntimeDirOverride is missing Kioxia_MS2_RSS_Live_Signals.xlsx: $resolved"
        }
        return $resolved
    }

    $roots = @(
        [Environment]::GetFolderPath("Desktop"),
        (Join-Path $env:USERPROFILE "Desktop"),
        (Join-Path $env:USERPROFILE "OneDrive\Desktop")
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique
    $hits = foreach ($r in $roots) {
        Get-ChildItem -LiteralPath $r -Recurse -File -Filter "MS2_RSS_100_Collector.ps1" -ErrorAction SilentlyContinue
    }
    # Do not use "latest matching file": runtime backups also contain the
    # Collector and can otherwise win by timestamp. Accept only a Collector
    # whose immediate parent is exactly "files" and whose parent folder is
    # exactly "MarketSpeed II RSS".
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

function Resolve-RepoRoot([string]$Explicit) {
    if (-not [string]::IsNullOrWhiteSpace($Explicit)) { return $Explicit }
    # Prefer the folder this controller script itself lives two levels
    # above (...\trade-cockpit\downloads\AI_COCKPIT_CONTROLLER_V8.ps1), if
    # that looks like a real checkout; otherwise fall back to a Desktop
    # search, same pattern as Resolve-RuntimeDir.
    $candidate = Split-Path -Parent $PSScriptRoot
    if (Test-Path -LiteralPath (Join-Path $candidate "card_system.js")) { return $candidate }
    $roots = @(
        [Environment]::GetFolderPath("Desktop"),
        (Join-Path $env:USERPROFILE "Desktop"),
        $env:USERPROFILE
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique
    $hits = foreach ($r in $roots) {
        Get-ChildItem -LiteralPath $r -Recurse -File -Filter "card_system.js" -Depth 4 -ErrorAction SilentlyContinue
    }
    $hit = @($hits | Select-Object -First 1)
    if ($hit.Count -gt 0) { return $hit[0].Directory.FullName }
    throw "Could not locate the trade-cockpit repo checkout (looked for card_system.js). Pass -RepoRoot explicitly."
}

# ------------------------------------------------------------- state file
# Paths under $Root are created only after the identity-probe self-test
# returns. That self-test must run without touching the production C: root,
# including on a host where that drive does not exist.

function Read-State {
    try {
        if (-not (Test-Path -LiteralPath $StateFile)) { return $null }
        return (Read-JsonUtf8 $StateFile)
    } catch { return $null }
}

function Save-State($state) {
    $tmp = $StateFile + "." + $PID + ".tmp"
    [IO.File]::WriteAllText($tmp, ($state | ConvertTo-Json -Depth 6), [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $tmp -Destination $StateFile -Force
}

function Test-OwnedPidIdentity([string]$Field,[int]$ProcessId) {
    $expected = switch ($Field) {
        "watcher_pid"      { "Kioxia_RSS_Live_Watcher.ps1" }
        "heartbeat_pid"    { "Kioxia_Safety_Heartbeat.ps1" }
        "collector_pid"    { "MS2_RSS_100_Collector.ps1" }
        "gateway_pid"      { "AI_COCKPIT_GATEWAY_V9.ps1" }
        "voice_bridge_pid" { "AI_COCKPIT_VOICE_BRIDGE_V9.ps1" }
        "sbv2_pid"         { "server_fastapi.py" }
        "shadow_supervisor_pid" { "ai_shadow_supervisor.py" }
        "controller_pid"   { "AI_COCKPIT_CONTROLLER_V9.ps1" }
        default            { "" }
    }
    if ([string]::IsNullOrWhiteSpace($expected)) { return $false }
    try {
        $wmi = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $ProcessId) -ErrorAction SilentlyContinue
        if ($null -eq $wmi) { return $false }
        $cmd = [string]$wmi.CommandLine
        return (-not [string]::IsNullOrWhiteSpace($cmd) -and $cmd -match [regex]::Escape($expected))
    } catch { return $false }
}

# Stop only PIDs recorded in OUR OWN previous state file - never a broad
# process-table scan. A PID that no longer exists, or that now belongs to
# a different process (recycled by Windows), is silently skipped.
function Stop-OwnedFromPreviousState {
    $prev = Read-State
    if ($null -eq $prev) { return }
    Stop-OwnedJobBridge $PORT_COLLECTOR ([int]$prev.collector_pid) "Collector JSON" | Out-Null
    Stop-OwnedJobBridge $PORT_WATCHER ([int]$prev.watcher_pid) "Watcher JSON" | Out-Null
    foreach ($field in @("watcher_pid", "heartbeat_pid", "collector_pid", "gateway_pid", "voice_bridge_pid", "sbv2_pid", "shadow_supervisor_pid", "controller_pid")) {
        $val = $prev.PSObject.Properties[$field]
        if ($null -eq $val -or [int]$val.Value -le 0) { continue }
        $procId = [int]$val.Value
        $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if ($null -ne $proc -and (Test-OwnedPidIdentity $field $procId)) {
            try { Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue } catch {}
            Write-Status ("  stopped previous {0} (PID {1})" -f $field, $procId) DarkGray
        } elseif ($null -ne $proc) {
            Write-Status ("  previous PID " + $procId + " no longer matches " + $field + "; leaving it untouched") Yellow
        }
    }
    # Excel is not stopped here. A PID in the previous state file is not
    # ownership, and this cleanup does not yet know the canonical path.
    # Leftover AI Cockpit /x Excel is classified at launch and is never adopted.
}

# A workbook title change does not establish ownership of the Excel process.
# Release the workers' COM references; never force-kill Excel, which may also
# host a user's other workbooks. A surviving Excel is reported for acceptance.
function Stop-ManagedWorkersOnWorkbookClose($SessionState) {
    foreach ($field in @("watcher_pid", "heartbeat_pid", "collector_pid", "gateway_pid", "voice_bridge_pid", "sbv2_pid", "shadow_supervisor_pid")) {
        $workerPid = [int]$SessionState.$field
        if ($workerPid -le 0 -or $workerPid -eq [int]$SessionState.excel_pid) { continue }
        $worker = Get-Process -Id $workerPid -ErrorAction SilentlyContinue
        if ($null -ne $worker -and (Test-OwnedPidIdentity $field $workerPid)) {
            Stop-Process -Id $workerPid -Force -ErrorAction SilentlyContinue
        }
    }
}
function Start-Worker([string]$Name, [string]$Script, [string]$WorkDir, [string]$ExtraArgs = "") {
    $stdout = Join-Path $LogDir ($Name + "_stdout.log")
    $stderr = Join-Path $LogDir ($Name + "_stderr.log")
    Remove-Item -LiteralPath $stdout, $stderr -Force -ErrorAction SilentlyContinue
    $args = '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "' + $Script + '"'
    if (-not [string]::IsNullOrWhiteSpace($ExtraArgs)) { $args += " " + $ExtraArgs }
    return Start-Process -FilePath "powershell.exe" -ArgumentList $args -WorkingDirectory $WorkDir `
        -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
}

function Write-ShadowStoppedStatus([string]$StatusPath, [string]$Reason) {
    $payload = [ordered]@{
        schema_version = "ai-shadow-supervisor-1"
        state = "STOPPED"
        reason = $Reason
        updated_at = (Get-Date).ToString("o")
        real_submit_allowed = $false
        ui_independent = $true
        open_observation_count = $null
        resume_blocked = $true
    }
    $parent = Split-Path -Parent $StatusPath
    if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $tmp = $StatusPath + ".tmp"
    [IO.File]::WriteAllText($tmp, ($payload | ConvertTo-Json -Depth 4), [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $tmp -Destination $StatusPath -Force
}

function Start-ShadowSupervisor([string]$RepoRootResolved, [string]$RuntimeDir) {
    $scriptPath = Join-Path $RepoRootResolved "scripts\ai_shadow_supervisor.py"
    $statusPath = Join-Path $RuntimeDir "ai_shadow_status.json"
    if (-not (Test-Path -LiteralPath $scriptPath)) {
        Write-ShadowStoppedStatus $statusPath "SUPERVISOR_SCRIPT_MISSING"
        Write-Status "  AI SHADOW supervisor script missing - STOPPED fail-closed. Excel/RSS were not touched." Yellow
        return $null
    }
    $python = $null
    foreach ($cand in @(
        (Join-Path $RepoRootResolved ".venv\Scripts\python.exe"),
        (Join-Path $RepoRootResolved "venv\Scripts\python.exe")
    )) {
        if (Test-Path -LiteralPath $cand) { $python = $cand; break }
    }
    if (-not $python) {
        $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($null -ne $cmd) { $python = $cmd.Source }
    }
    $prefix = @()
    if (-not $python) {
        $py = Get-Command py.exe -ErrorAction SilentlyContinue
        if ($null -ne $py) {
            $python = $py.Source
            $prefix = @("-3")
        }
    }
    $dataDir = Join-Path $LogDir "ai_shadow"
    if (-not (Test-Path -LiteralPath $dataDir)) { New-Item -ItemType Directory -Path $dataDir -Force | Out-Null }
    if (-not $python) {
        Write-ShadowStoppedStatus $statusPath "PYTHON_NOT_FOUND"
        Write-Status "  AI SHADOW python not found - STOPPED fail-closed. Excel/RSS were not touched." Yellow
        return $null
    }
    $stdout = Join-Path $LogDir "shadow_supervisor_stdout.log"
    $stderr = Join-Path $LogDir "shadow_supervisor_stderr.log"
    Remove-Item -LiteralPath $stdout, $stderr -Force -ErrorAction SilentlyContinue
    $argList = $prefix + @(
        "-u", $scriptPath,
        "--live", (Join-Path $RuntimeDir "live_ms2.json"),
        "--data-dir", $dataDir,
        "--status", $statusPath,
        "--interval", "5"
    )
    return Start-Process -FilePath $python -ArgumentList $argList -WorkingDirectory $RepoRootResolved `
        -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
}

function Start-Sbv2Managed {
    if (Test-Port 5000 350) { return $null }
    $sbvRoot = "C:\sbv2\Style-Bert-VITS2"
    $server = Join-Path $sbvRoot "server_fastapi.py"
    $python = Join-Path $sbvRoot "venv\Scripts\python.exe"
    $pythonw = Join-Path $sbvRoot "venv\Scripts\pythonw.exe"
    if (-not (Test-Path -LiteralPath $server)) {
        Write-Status ("  SBV2 server not installed: " + $server) Yellow
        return $null
    }
    $exe = if (Test-Path -LiteralPath $python) { $python } elseif (Test-Path -LiteralPath $pythonw) { $pythonw } else { $null }
    if ($null -eq $exe) {
        Write-Status "  SBV2 Python not found; voice will stay OFFLINE." Yellow
        return $null
    }
    $stdout = Join-Path $LogDir "sbv2_stdout.log"
    $stderr = Join-Path $LogDir "sbv2_stderr.log"
    Remove-Item -LiteralPath $stdout,$stderr -Force -ErrorAction SilentlyContinue
    return Start-Process -FilePath $exe -ArgumentList "server_fastapi.py" -WorkingDirectory $sbvRoot -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
}

function Stop-LegacyVoiceWorkers {
    foreach ($p in @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)) {
        $cmd = [string]$p.CommandLine
        if ([string]::IsNullOrWhiteSpace($cmd)) { continue }
        if ($cmd -match "SPEAK_TODAY_STRATEGY\.ps1|SPEAK_LIVE_EMOTION\.ps1") {
            try { Stop-Process -Id ([int]$p.ProcessId) -Force -ErrorAction SilentlyContinue } catch {}
            Write-Status ("  stopped legacy voice worker PID " + $p.ProcessId) DarkGray
        }
    }
}

function Tail-Log([string]$Path, [int]$Lines = 15) {
    if (Test-Path -LiteralPath $Path) {
        return ((Get-Content -LiteralPath $Path -Tail $Lines -ErrorAction SilentlyContinue) -join " | ")
    }
    return ""
}

# --------------------------------------------------------- Excel helpers

function Get-ExcelProcessForWorkbook([string]$WorkbookName) {
    return @(Get-Process EXCEL -ErrorAction SilentlyContinue | Where-Object {
        $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -like ("*" + $WorkbookName + "*")
    } | Select-Object -First 1)
}
function Get-CurrentSessionId {
    $self = Get-Process -Id $PID -ErrorAction Stop
    return [int]$self.SessionId
}

function Get-ForeignExcelProcesses([int[]]$AllowedPids = @(), [int]$SessionId = -1) {
    if ($SessionId -lt 0) { $SessionId = Get-CurrentSessionId }
    return @(
        Get-Process EXCEL -ErrorAction SilentlyContinue |
        Where-Object {
            $pidValue = [int]$_.Id
            [int]$_.SessionId -eq $SessionId -and
            -not ($AllowedPids -contains $pidValue)
        }
    )
}

function Get-CanonicalWorkbookConflicts([string]$WorkbookPath, [string]$WorkbookName, [int[]]$AllowedPids = @()) {
    $ordinalIgnoreCase = [StringComparison]::OrdinalIgnoreCase
    $hits = New-Object System.Collections.Generic.List[object]
    $seen = @{}
    foreach ($proc in @(Get-ExcelProcessForWorkbook $WorkbookName)) {
        if ($null -eq $proc) { continue }
        $pidValue = [int]$proc.Id
        if ($AllowedPids -contains $pidValue) { continue }
        if ($seen.ContainsKey($pidValue)) { continue }
        $seen[$pidValue] = $true
        [void]$hits.Add($proc)
    }
    foreach ($proc in @(Get-ForeignExcelProcesses $AllowedPids)) {
        if ($null -eq $proc) { continue }
        $pidValue = [int]$proc.Id
        if ($seen.ContainsKey($pidValue)) { continue }
        if ([string]::IsNullOrWhiteSpace($WorkbookPath)) { continue }
        $info = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $pidValue) -ErrorAction SilentlyContinue
        if ($null -eq $info) { continue }
        $cmd = [string]$info.CommandLine
        if ([string]::IsNullOrWhiteSpace($cmd)) { continue }
        if ($cmd.IndexOf($WorkbookPath, $ordinalIgnoreCase) -ge 0) {
            $seen[$pidValue] = $true
            [void]$hits.Add($proc)
        }
    }
    return @($hits.ToArray())
}

function Get-IsolatedExcelArguments([string]$WorkbookPath) {
    return '/x "' + $WorkbookPath + '"'
}

function Test-LeftoverCockpitExcel([int]$ExcelPid,[string]$WorkbookPath) {
    if ($ExcelPid -le 0) { return $false }
    $proc = Get-Process -Id $ExcelPid -ErrorAction SilentlyContinue
    if ($null -eq $proc) { return $false }
    if ($proc.ProcessName -ne "EXCEL") { return $false }
    if ([int]$proc.SessionId -ne (Get-CurrentSessionId)) { return $false }
    $info = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $ExcelPid) -ErrorAction SilentlyContinue
    if ($null -eq $info) { return $false }
    $cmd = [string]$info.CommandLine
    if ([string]::IsNullOrWhiteSpace($cmd)) { return $false }
    $ordinalIgnoreCase = [StringComparison]::OrdinalIgnoreCase
    $launchArg = Get-IsolatedExcelArguments $WorkbookPath
    if ($cmd.IndexOf($launchArg, $ordinalIgnoreCase) -lt 0) { return $false }
    $parentPid = 0
    try { $parentPid = [int]$info.ParentProcessId } catch { $parentPid = 0 }
    if ($parentPid -gt 0) {
        $parent = Get-Process -Id $parentPid -ErrorAction SilentlyContinue
        if ($null -ne $parent) { return $false }
    }
    return $true
}

function Stop-VerifiedLeftoverCockpitExcel([int]$ExcelPid,[string]$WorkbookPath) {
    if ($ExcelPid -le 0) { return $false }
    $proc = Get-Process -Id $ExcelPid -ErrorAction SilentlyContinue
    if ($null -eq $proc) { return $true }
    if (-not (Test-LeftoverCockpitExcel $ExcelPid $WorkbookPath)) { return $false }
    Stop-Process -Id $ExcelPid -Force -ErrorAction SilentlyContinue
    foreach ($attempt in 1..10) {
        Start-Sleep -Milliseconds 300
        if ($null -eq (Get-Process -Id $ExcelPid -ErrorAction SilentlyContinue)) { return $true }
    }
    return $false
}

function Test-LaunchedExcelOwnership([int]$ExcelPid,[string]$WorkbookPath,[int]$ControllerPid) {
    if ($ExcelPid -le 0) { return $false }
    $proc = Get-Process -Id $ExcelPid -ErrorAction SilentlyContinue
    if ($null -eq $proc) { return $false }
    $info = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $ExcelPid) -ErrorAction SilentlyContinue
    if ($null -eq $info) { return $false }
    $cmd = [string]$info.CommandLine
    $ordinalIgnoreCase = [StringComparison]::OrdinalIgnoreCase
    $isCanonicalWorkbook = (
        -not [string]::IsNullOrWhiteSpace($cmd) -and
        $cmd.IndexOf($WorkbookPath, $ordinalIgnoreCase) -ge 0
    )
    $isControllerChild = ([int]$info.ParentProcessId -eq $ControllerPid)
    $isSameSession = ([int]$proc.SessionId -eq (Get-CurrentSessionId))
    return ($isCanonicalWorkbook -and $isControllerChild -and $isSameSession)
}

function Stop-VerifiedOwnedExcel([int]$ExcelPid,[string]$WorkbookPath,[int]$ControllerPid) {
    if ($ExcelPid -le 0) { return $true }

    $proc = Get-Process -Id $ExcelPid -ErrorAction SilentlyContinue
    if ($null -eq $proc) { return $true }
    if (-not (Test-LaunchedExcelOwnership $ExcelPid $WorkbookPath $ControllerPid)) { return $false }

    Stop-Process -Id $ExcelPid -Force -ErrorAction SilentlyContinue
    foreach ($attempt in 1..10) {
        Start-Sleep -Milliseconds 300
        if ($null -eq (Get-Process -Id $ExcelPid -ErrorAction SilentlyContinue)) { return $true }
    }
    return $false
}

function Wait-OwnedHelperProcess {
    param(
        [System.Diagnostics.Process]$Process,
        [int]$TimeoutSeconds,
        [string]$ProgressPath
    )
    $started = Get-Date
    $seen = 0
    $lastBeat = -1
    $timedOut = $false
    while (-not $timedOut) {
        $elapsed = [int]((Get-Date) - $started).TotalSeconds
        if ($elapsed -ge $TimeoutSeconds) {
            # Kill this helper process only. WaitForExit(5000) returns even
            # when the process does not die, so a stuck COM call cannot
            # keep the Controller thread blocked.
            $timedOut = $true
            try { $Process.Kill() } catch {}
            try { [void]$Process.WaitForExit(5000) } catch {}
            break
        }
        if (-not [string]::IsNullOrWhiteSpace($ProgressPath) -and (Test-Path -LiteralPath $ProgressPath)) {
            try {
                $lines = @(Get-Content -LiteralPath $ProgressPath -ErrorAction SilentlyContinue)
                while ($seen -lt $lines.Count) {
                    Write-Status ("  " + $lines[$seen]) DarkGray
                    $seen++
                }
            } catch {}
        }
        if ($elapsed -ne $lastBeat -and (($elapsed % 2) -eq 0)) {
            Write-Status ("Excel identity probe attempt {0} / elapsed {1}s" -f ([Math]::Max(1, [int]($elapsed / 2)), $elapsed)) DarkGray
            $lastBeat = $elapsed
        }
        $sliceMs = [int](($TimeoutSeconds - $elapsed) * 1000)
        if ($sliceMs -lt 200) { $sliceMs = 200 }
        if ($sliceMs -gt 400) { $sliceMs = 400 }
        $exited = $false
        try { $exited = $Process.WaitForExit($sliceMs) } catch { $exited = $true }
        if ($exited) { break }
    }
    try { $Process.Refresh() } catch {}
    $exitCode = $null
    try { $exitCode = $Process.ExitCode } catch {}
    $reportedElapsed = [int]((Get-Date) - $started).TotalSeconds
    if ($timedOut) { $reportedElapsed = $TimeoutSeconds }
    return @{
        timed_out = $timedOut
        elapsed = $reportedElapsed
        exit_code = $exitCode
        helper_pid = [int]$Process.Id
    }
}

function Get-OperationsIncidentPath {
    return (Join-Path $LogDir "ai_shadow\incidents.jsonl")
}

function Read-OperationsIncidents([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return @() }
    $text = [IO.File]::ReadAllText($Path, [Text.UTF8Encoding]::new($false))
    $rows = @()
    foreach ($line in ($text -split '\r?\n')) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        $parsed = $line | ConvertFrom-Json
        if ($parsed.record_class -ne "operations_incident" -or $parsed.real_submit_allowed -ne $false) {
            throw "operations incident log is not a readable operations diary"
        }
        $rows += $parsed
    }
    return @($rows)
}

function Write-OperationsIncidentFile([string]$Path, $Rows) {
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $body = ""
    foreach ($row in @($Rows)) {
        $body += (($row | ConvertTo-Json -Compress -Depth 6) + "`n")
    }
    $tmp = $Path + ".tmp"
    [IO.File]::WriteAllText($tmp, $body, [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}

function Get-CanonicalWorkbookOpenDiagnostics([string]$WorkbookPath, [string]$LaunchArguments) {
    $name = [IO.Path]::GetFileName($WorkbookPath)
    $diag = [ordered]@{
        workbook_name = $name
        workbook_readable = $false
        has_vba_project = $false
        external_link_count = 0
        zip_error = ""
        document_recovery_match_count = 0
        disabled_item_count = 0
        startup_item_count = 0
        addin_leaf_names = @()
        marketspeed_addin_present = $false
        safe_mode_switch = ($LaunchArguments -match '(?i)(^|\s)/(safemode|s)(\s|$)')
        launch_switches = "/x"
        registry_error = ""
    }
    try {
        Add-Type -AssemblyName System.IO.Compression -ErrorAction SilentlyContinue
        Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction SilentlyContinue
        $stream = [IO.File]::Open($WorkbookPath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
        try {
            $zip = New-Object IO.Compression.ZipArchive($stream, [IO.Compression.ZipArchiveMode]::Read)
            try {
                $diag.workbook_readable = $true
                $links = 0
                foreach ($entry in $zip.Entries) {
                    $full = [string]$entry.FullName
                    if ($full -eq "xl/vbaProject.bin") { $diag.has_vba_project = $true }
                    if ($full.StartsWith("xl/externalLinks/")) { $links++ }
                }
                $diag.external_link_count = $links
            } finally { $zip.Dispose() }
        } finally { $stream.Dispose() }
    } catch {
        $diag.zip_error = $_.Exception.Message
    }
    $excelKey = "HKCU:\Software\Microsoft\Office\16.0\Excel"
    try {
        $recovery = Join-Path $excelKey "Resiliency\DocumentRecovery"
        if (Test-Path -LiteralPath $recovery) {
            $matches = 0
            $ordinalIgnoreCase = [StringComparison]::OrdinalIgnoreCase
            foreach ($child in @(Get-ChildItem -LiteralPath $recovery -ErrorAction SilentlyContinue)) {
                $props = Get-ItemProperty -LiteralPath $child.PSPath -ErrorAction SilentlyContinue
                if ($null -eq $props) { continue }
                foreach ($prop in $props.PSObject.Properties) {
                    if ($prop.Name -like "PS*") { continue }
                    $text = $null
                    if ($prop.Value -is [string]) { $text = [string]$prop.Value }
                    if (-not [string]::IsNullOrWhiteSpace($text) -and $text.IndexOf($name, $ordinalIgnoreCase) -ge 0) {
                        $matches++
                        break
                    }
                }
            }
            $diag.document_recovery_match_count = $matches
        }
        foreach ($pair in @(
            @{ Path = (Join-Path $excelKey "Resiliency\DisabledItems"); Field = "disabled_item_count" },
            @{ Path = (Join-Path $excelKey "Resiliency\StartupItems"); Field = "startup_item_count" }
        )) {
            if (-not (Test-Path -LiteralPath $pair.Path)) { continue }
            $count = @(Get-ChildItem -LiteralPath $pair.Path -ErrorAction SilentlyContinue).Count
            $props = Get-ItemProperty -LiteralPath $pair.Path -ErrorAction SilentlyContinue
            if ($null -ne $props) {
                foreach ($prop in $props.PSObject.Properties) {
                    if ($prop.Name -like "PS*") { continue }
                    $count++
                }
            }
            $diag[$pair.Field] = $count
        }
        $leaves = New-Object System.Collections.Generic.List[string]
        foreach ($keyPath in @(
            (Join-Path $excelKey "Add-in Manager"),
            (Join-Path $excelKey "Options")
        )) {
            if (-not (Test-Path -LiteralPath $keyPath)) { continue }
            $props = Get-ItemProperty -LiteralPath $keyPath -ErrorAction SilentlyContinue
            if ($null -eq $props) { continue }
            foreach ($prop in $props.PSObject.Properties) {
                if ($prop.Name -like "PS*") { continue }
                $raw = [string]$prop.Value
                if ([string]::IsNullOrWhiteSpace($raw)) { continue }
                $rakuten = -join @([char]0x697D, [char]0x5929)
                if ($raw -match ('MarketSpeed|RSS|' + $rakuten)) { $diag.marketspeed_addin_present = $true }
                $leaf = [IO.Path]::GetFileName($raw.Trim('"'))
                if ([string]::IsNullOrWhiteSpace($leaf) -or $leaf -notmatch '\.(xll|xlam|dll|exe)$') { continue }
                if (-not $leaves.Contains($leaf) -and $leaves.Count -lt 30) { [void]$leaves.Add($leaf) }
            }
        }
        $diag.addin_leaf_names = @($leaves)
    } catch {
        $diag.registry_error = $_.Exception.Message
    }
    return $diag
}

function Complete-ExcelProbeResult($Probe, $Process) {
    if ($null -eq $Probe.dialog_text) { $Probe.dialog_text = "" }
    $Probe.launched_excel_pid = 0
    $Probe.process_exited = $false
    $Probe.excel_exit_code = $null
    $Probe.excel_exit_at = ""
    if ($null -eq $Process) { return $Probe }
    $Probe.launched_excel_pid = [int]$Process.Id
    try { $Process.Refresh() } catch {}
    $exited = $false
    try { $exited = [bool]$Process.HasExited } catch { $exited = $true }
    $Probe.process_exited = $exited
    if (-not $exited) { return $Probe }
    try { $Probe.excel_exit_code = [int]$Process.ExitCode } catch {}
    try { $Probe.excel_exit_at = $Process.ExitTime.ToString("o") } catch {}
    if ($Probe.code -eq "EXCEL_IDENTITY_MISMATCH") { return $Probe }
    if ([bool]$Probe.ok) {
        $Probe.ok = $false
        $Probe.code = "EXCEL_PROCESS_EXITED"
        $Probe.last_error = "LAUNCHED_PID_EXITED"
        $Probe.detail = "Excel exited after the probe reported verification"
        return $Probe
    }
    if ($Probe.code -eq "EXCEL_SERIOUS_ERROR_PROMPT" -or -not [string]::IsNullOrWhiteSpace([string]$Probe.dialog_text)) {
        $Probe.code = "EXCEL_PROCESS_EXITED"
        $Probe.last_error = "PREVIOUS_SERIOUS_ERROR_DIALOG"
        return $Probe
    }
    $Probe.code = "EXCEL_PROCESS_EXITED"
    if ([string]::IsNullOrWhiteSpace([string]$Probe.last_error) -or [string]$Probe.last_error -in @("PROBE_TIMEOUT", "ROT_MONIKER_NOT_REGISTERED", "NOT_STARTED", "RESULT_MISSING")) {
        $Probe.last_error = "LAUNCHED_PID_EXITED"
    }
    return $Probe
}

function Add-ExcelIdentityIncident($Probe) {
    $path = Get-OperationsIncidentPath
    try {
        $existing = @(Read-OperationsIncidents $path)
    } catch {
        Write-Status ("  operations incident log unreadable; identity failure stays fail-closed. " + $_.Exception.Message) Red
        return
    }
    try {
    $code = [string]$Probe.code
    if ([string]::IsNullOrWhiteSpace($code)) { $code = "EXCEL_IDENTITY_PROBE_FAILED" }
    $component = "excel_identity"
    if ($code -eq "EXCEL_SERIOUS_ERROR_PROMPT" -or [string]$Probe.last_error -eq "PREVIOUS_SERIOUS_ERROR_DIALOG" -or -not [string]::IsNullOrWhiteSpace([string]$Probe.dialog_text)) {
        $component = "workbook_open"
    } elseif ($code -eq "EXCEL_PROCESS_EXITED") {
        $component = "excel_process_exit"
    }
    $key = $component + "|" + $code
    $prior = @($existing | Where-Object { [string]$_.recurrence_key -eq $key }).Count
    $seed = (Get-Date).ToString("o") + "|" + $key
    $sha = [Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($seed))
    $id = "inc-" + (([BitConverter]::ToString($sha) -replace "-","").ToLowerInvariant().Substring(0, 16))
    $diagnostics = $null
    try { $diagnostics = Get-CanonicalWorkbookOpenDiagnostics $WorkbookPath ('/x "' + $WorkbookPath + '"') } catch { $diagnostics = $null }
    try {
        $diagPath = Join-Path $LogDir "identity_probe\open_diagnostics.json"
        $diagDir = Split-Path -Parent $diagPath
        if (-not (Test-Path -LiteralPath $diagDir)) { New-Item -ItemType Directory -Path $diagDir -Force | Out-Null }
        if ($null -ne $diagnostics) {
            [IO.File]::WriteAllText($diagPath, ($diagnostics | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false))
        }
    } catch {}
    $incident = [ordered]@{
        record_class = "operations_incident"
        incident_id = $id
        occurrence_at = (Get-Date).ToString("o")
        recovery_at = $null
        duration_seconds = $null
        component = $component
        error_code = $code
        symptom = [string]$Probe.detail
        suspected_cause = [string]$Probe.last_error
        confirmed_cause = $null
        impact_scope = "startup"
        real_trade_impact = "NONE_REAL_SUBMIT_REMAINS_FALSE"
        shadow_impact = "STOPPED"
        fail_closed = $true
        invalidated_signal_count = $null
        recovery_mode = $null
        actions = @("startup aborted before AI SHADOW", "unrelated Excel was not stopped", "canonical workbook was not replaced", "the serious-error dialog was not clicked", "Excel was not relaunched")
        recurrence_key = $key
        recurrence_count = ($prior + 1)
        log_refs = @("Logs/V9/identity_probe/progress.log", "Logs/V9/identity_probe/result.json", "Logs/V9/identity_probe/open_diagnostics.json")
        identity_checks = [ordered]@{
            full_name = [string]$Probe.full_name
            hwnd = $Probe.hwnd
            excel_pid = $Probe.excel_pid
            launched_excel_pid = $Probe.launched_excel_pid
            process_exited = [bool]$Probe.process_exited
            excel_exit_code = $Probe.excel_exit_code
            excel_exit_at = [string]$Probe.excel_exit_at
            dialog_text = [string]$Probe.dialog_text
            parent_pid = $Probe.parent_pid
            command_line_match = [bool]$Probe.command_line_match
            parent_match = [bool]$Probe.parent_match
            session_match = [bool]$Probe.session_match
            rot_candidate_count = $Probe.rot_candidate_count
            attempts = $Probe.attempts
            last_error = [string]$Probe.last_error
        }
        open_diagnostics = $diagnostics
        real_submit_allowed = $false
    }
        Write-OperationsIncidentFile $path (@($existing) + @([pscustomobject]$incident))
        Write-Status ("  operations incident " + $id + " / " + $component + " / " + $code) Yellow
    } catch {
        Write-Status ("  operations incident was not recorded. " + $_.Exception.Message) Red
    }
}

function Close-OpenExcelIdentityIncidents {
    $path = Get-OperationsIncidentPath
    if (-not (Test-Path -LiteralPath $path)) { return }
    try {
        $existing = @(Read-OperationsIncidents $path)
    } catch {
        Write-Status ("  operations incident log unreadable after identity verification. " + $_.Exception.Message) Yellow
        return
    }
    $changed = $false
    $now = Get-Date
    foreach ($row in $existing) {
        if ([string]$row.component -in @("excel_identity", "workbook_open", "excel_process_exit") -and [string]::IsNullOrWhiteSpace([string]$row.recovery_at)) {
            $row.recovery_at = $now.ToString("o")
            try {
                $started = [datetime]$row.occurrence_at
                $row.duration_seconds = [int][Math]::Max(0, ($now - $started).TotalSeconds)
            } catch { $row.duration_seconds = $null }
            $row.recovery_mode = "MANUAL"
            $row.shadow_impact = "IDENTITY_VERIFIED_SHADOW_NOT_YET_STARTED"
            $changed = $true
        }
    }
    if ($changed) { Write-OperationsIncidentFile $path $existing }
}

function Invoke-ExcelIdentityProbe {
    param(
        [string]$WorkbookPath,
        [int]$ExpectedExcelPid,
        [int]$TimeoutSeconds,
        [string]$LogDirectory
    )
    if ($TimeoutSeconds -lt 30 -or $TimeoutSeconds -gt 40) {
        throw "Excel identity probe timeout must stay within 30-40 seconds."
    }
    $probeDir = Join-Path $LogDirectory "identity_probe"
    New-Item -ItemType Directory -Force -Path $probeDir | Out-Null
    $resultPath = Join-Path $probeDir "result.json"
    $progressPath = Join-Path $probeDir "progress.log"
    $stdoutPath = Join-Path $probeDir "stdout.log"
    $stderrPath = Join-Path $probeDir "stderr.log"
    foreach ($path in @($resultPath, $progressPath, $stdoutPath, $stderrPath)) {
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue }
    }
    $helper = Join-Path $PSScriptRoot "EXCEL_IDENTITY_PROBE_V9.ps1"
    if (-not (Test-Path -LiteralPath $helper)) {
        return @{ ok = $false; code = "EXCEL_IDENTITY_PROBE_FAILED"; elapsed = 0; helper_pid = 0; detail = "identity probe helper missing" }
    }
    $shell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    if (-not (Test-Path -LiteralPath $shell)) { $shell = "powershell.exe" }
    Write-Status "Excel identity probe started"
    # Windows PowerShell 5.1 does not quote an ArgumentList array. One
    # string keeps workbook paths that contain spaces intact.
    $helperArgs = '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "' + $helper + '"' +
        ' -WorkbookPath "' + $WorkbookPath + '"' +
        ' -ExpectedExcelPid ' + $ExpectedExcelPid +
        ' -ControllerPid ' + $PID +
        ' -ResultPath "' + $resultPath + '"' +
        ' -ProgressPath "' + $progressPath + '"' +
        ' -AttemptBudgetSeconds ' + $TimeoutSeconds
    $helperProc = Start-Process -FilePath $shell -ArgumentList $helperArgs -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru -WindowStyle Hidden
    Write-Status ("  helper PID " + $helperProc.Id + " / timeout " + $TimeoutSeconds + "s / started " + (Get-Date).ToString("HH:mm:ss")) DarkGray
    $wait = Wait-OwnedHelperProcess -Process $helperProc -TimeoutSeconds $TimeoutSeconds -ProgressPath $progressPath
    if ($wait.timed_out) {
        Write-Status ("EXCEL_IDENTITY_PROBE_TIMEOUT after " + $wait.elapsed + "s") Red
        $partial = $null
        if (Test-Path -LiteralPath $resultPath) {
            try { $partial = [IO.File]::ReadAllText($resultPath, [Text.Encoding]::UTF8) | ConvertFrom-Json } catch { $partial = $null }
        }
        $tail = Tail-Log $progressPath
        $detail = "helper PID $($wait.helper_pid) exceeded ${TimeoutSeconds}s"
        if ($null -ne $partial -and -not [string]::IsNullOrWhiteSpace([string]$partial.message)) { $detail = [string]$partial.message }
        elseif (-not [string]::IsNullOrWhiteSpace($tail)) { $detail = $tail }
        Write-Status ("  identity timeout detail: " + $detail) Red
        return @{
            ok = $false; code = "EXCEL_IDENTITY_PROBE_TIMEOUT"; elapsed = $wait.elapsed; helper_pid = $wait.helper_pid
            detail = $detail; last_error = "PROBE_TIMEOUT"; full_name = [string]$partial.full_name
            hwnd = $partial.hwnd; excel_pid = $partial.excel_pid; parent_pid = $partial.parent_pid
            command_line_match = [bool]$partial.command_line_match; parent_match = [bool]$partial.parent_match
            session_match = [bool]$partial.session_match; rot_candidate_count = $partial.rot_candidate_count
            attempts = $partial.attempts; dialog_text = [string]$partial.dialog_text
        }
    }
    if (-not (Test-Path -LiteralPath $resultPath)) {
        $err = Tail-Log $stderrPath
        $progress = Tail-Log $progressPath
        return @{
            ok = $false; code = "EXCEL_IDENTITY_PROBE_FAILED"; elapsed = $wait.elapsed; helper_pid = $wait.helper_pid
            exit_code = $wait.exit_code; detail = ($progress + " " + $err).Trim(); last_error = "RESULT_MISSING"
            full_name = ""; hwnd = 0; excel_pid = 0; parent_pid = 0
            command_line_match = $false; parent_match = $false; session_match = $false
            rot_candidate_count = 0; attempts = 0; dialog_text = ""
        }
    }
    $result = [IO.File]::ReadAllText($resultPath, [Text.Encoding]::UTF8) | ConvertFrom-Json
    $code = [string]$result.code
    if ($code -eq "EXCEL_IDENTITY_MISMATCH" -or -not [bool]$result.ok) {
        if ([string]::IsNullOrWhiteSpace($code)) { $code = "EXCEL_IDENTITY_PROBE_FAILED" }
        Write-Status ("  identity " + $code + " / " + [string]$result.message) Red
        return @{
            ok = $false; code = $code; elapsed = $wait.elapsed; helper_pid = $wait.helper_pid; exit_code = $wait.exit_code
            detail = [string]$result.message; last_error = [string]$result.last_error
            full_name = [string]$result.full_name; hwnd = $result.hwnd; excel_pid = $result.excel_pid
            parent_pid = $result.parent_pid; command_line_match = [bool]$result.command_line_match
            parent_match = [bool]$result.parent_match; session_match = [bool]$result.session_match
            rot_candidate_count = $result.rot_candidate_count; attempts = $result.attempts
            dialog_text = [string]$result.dialog_text
        }
    }
    $fullName = [string]$result.full_name
    $hwnd = 0L
    try { $hwnd = [Int64]$result.hwnd } catch { $hwnd = 0L }
    $reportedPid = 0
    try { $reportedPid = [int]$result.excel_pid } catch { $reportedPid = 0 }
    $fullNameIsLocal = $fullName -match '^[A-Za-z]:\\'
    if ($hwnd -eq 0 -or $reportedPid -ne $ExpectedExcelPid) {
        return @{ ok = $false; code = "EXCEL_IDENTITY_MISMATCH"; elapsed = $wait.elapsed; helper_pid = $wait.helper_pid; detail = "reported HWND or PID did not match the launched workbook"; last_error = "PID_OR_HWND_MISMATCH"; full_name = $fullName; hwnd = $hwnd; excel_pid = $reportedPid; parent_pid = $result.parent_pid; command_line_match = [bool]$result.command_line_match; parent_match = [bool]$result.parent_match; session_match = [bool]$result.session_match; rot_candidate_count = $result.rot_candidate_count; attempts = $result.attempts }
    }
    if ($fullNameIsLocal -and ($fullName -ine $WorkbookPath) -and -not [bool]$result.full_name_same_file) {
        return @{ ok = $false; code = "EXCEL_IDENTITY_MISMATCH"; elapsed = $wait.elapsed; helper_pid = $wait.helper_pid; detail = "reported local workbook is not the canonical file"; last_error = "FULL_NAME_DIFFERENT_FILE"; full_name = $fullName; hwnd = $hwnd; excel_pid = $reportedPid; parent_pid = $result.parent_pid; command_line_match = [bool]$result.command_line_match; parent_match = [bool]$result.parent_match; session_match = [bool]$result.session_match; rot_candidate_count = $result.rot_candidate_count; attempts = $result.attempts }
    }
    if (-not $fullNameIsLocal -and (-not [bool]$result.command_line_match -or -not [bool]$result.parent_match -or -not [bool]$result.session_match)) {
        return @{ ok = $false; code = "EXCEL_IDENTITY_MISMATCH"; elapsed = $wait.elapsed; helper_pid = $wait.helper_pid; detail = "cloud workbook moniker was not bound to the launched Excel"; last_error = "CLOUD_MONIKER_UNBOUND"; full_name = $fullName; hwnd = $hwnd; excel_pid = $reportedPid; parent_pid = $result.parent_pid; command_line_match = [bool]$result.command_line_match; parent_match = [bool]$result.parent_match; session_match = [bool]$result.session_match; rot_candidate_count = $result.rot_candidate_count; attempts = $result.attempts }
    }
    if (-not (Test-LaunchedExcelOwnership $ExpectedExcelPid $WorkbookPath $PID)) {
        return @{ ok = $false; code = "EXCEL_IDENTITY_MISMATCH"; elapsed = $wait.elapsed; helper_pid = $wait.helper_pid; detail = "canonical command line, parent PID, or session did not match"; last_error = "OWNERSHIP_MISMATCH"; full_name = $fullName; hwnd = $hwnd; excel_pid = $reportedPid; parent_pid = $result.parent_pid; command_line_match = [bool]$result.command_line_match; parent_match = [bool]$result.parent_match; session_match = [bool]$result.session_match; rot_candidate_count = $result.rot_candidate_count; attempts = $result.attempts }
    }
    Write-Status "Excel identity verified" Green
    return @{
        ok = $true
        code = "VERIFIED"
        elapsed = $wait.elapsed
        helper_pid = $wait.helper_pid
        full_name = $fullName
        hwnd = $hwnd
        excel_pid = $reportedPid
    }
}

function Invoke-ExcelIdentityProbeSelfTest {
    $helper = Join-Path $PSScriptRoot "EXCEL_IDENTITY_PROBE_V9.ps1"
    $progress = Join-Path ([IO.Path]::GetTempPath()) ("excel_identity_selftest_" + $PID + ".log")
    if (Test-Path -LiteralPath $progress) { Remove-Item -LiteralPath $progress -Force }
    $exe = (Get-Process -Id $PID).Path
    $helperArgs = '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "' + $helper + '" -SelfTestHang -ProgressPath "' + $progress + '"'
    $startParams = @{
        FilePath = $exe
        ArgumentList = $helperArgs
        PassThru = $true
    }
    if ($env:OS -eq "Windows_NT") { $startParams.WindowStyle = "Hidden" }
    $hung = Start-Process @startParams
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $wait = Wait-OwnedHelperProcess -Process $hung -TimeoutSeconds 3 -ProgressPath $progress
    $clock.Stop()
    if (-not $wait.timed_out) { throw "Identity probe selftest: hung helper exited before the hard timeout." }
    if ($clock.Elapsed.TotalSeconds -gt 20) { throw ("Identity probe selftest exceeded 20s: " + $clock.Elapsed.TotalSeconds) }
    $still = Get-Process -Id $hung.Id -ErrorAction SilentlyContinue
    if ($null -ne $still -and -not $still.HasExited) { throw "Identity probe selftest: helper PID $($hung.Id) was still running." }
    Write-Output ("EXCEL_IDENTITY_PROBE_TIMEOUT after " + $wait.elapsed + "s")
    Write-Output "AI Cockpit startup failed closed"
    Write-Output "Unrelated Excel processes were not touched"
    Write-Output "IDENTITY PROBE SELFTEST PASS"
}

# ======================================================================
# MAIN
# ======================================================================

if ($IdentityProbeSelfTest) {
    Invoke-ExcelIdentityProbeSelfTest
    exit 0
}

$StateFile = Join-Path $Root "V9_CONTROLLER_STATE.json"
$LogDir = Join-Path $Root "Logs\V9"
if (-not (Test-Path -LiteralPath $Root)) { New-Item -ItemType Directory -Path $Root -Force | Out-Null }
if (-not (Test-Path -LiteralPath $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

$state = [ordered]@{
    build                      = $Build
    controller_pid             = $PID
    session_id                 = (Get-CurrentSessionId)
    started_at                 = (Get-Date).ToString("o")
    repo_root                  = ""
    runtime_dir                = ""
    workbook_name              = ""
    workbook_path              = ""
    workbook_identity_verified = $null
    excel_identity_error       = ""
    excel_pid                  = 0
    watcher_pid                = 0
    watcher_status             = "NOT_STARTED"
    heartbeat_pid              = 0
    heartbeat_status           = "NOT_STARTED"
    collector_pid              = 0
    collector_status           = "NOT_STARTED"
    gateway_pid                = 0
    voice_bridge_pid           = 0
    voice_bridge_status        = "NOT_STARTED"
    sbv2_pid                   = 0
    sbv2_status                = "NOT_STARTED"
    shadow_supervisor_pid      = 0
    shadow_supervisor_status   = "NOT_STARTED"
}

try {
    Clear-Host
    Write-Host "==================================================" -ForegroundColor DarkCyan
    Write-Host " AI COCKPIT CONTROLLER V9" -ForegroundColor Cyan
    Write-Host (" " + $Build) -ForegroundColor DarkCyan
    Write-Host " Logs: $LogDir" -ForegroundColor DarkCyan
    Write-Host "==================================================" -ForegroundColor DarkCyan
    Write-Host ""

    Write-Status "Resolving repo checkout and MS2 runtime folder..."
    $RepoRootResolved = Resolve-RepoRoot $RepoRoot
    $RuntimeDir = Resolve-RuntimeDir $RuntimeDirOverride
    $state.repo_root = $RepoRootResolved
    $state.runtime_dir = $RuntimeDir
    Write-Status ("  repo:    " + $RepoRootResolved) Green
    Write-Status ("  runtime: " + $RuntimeDir) Green
    Write-Status ("  session: " + $state.session_id + " / user: " + [Environment]::UserName) Green

    if (-not [string]::IsNullOrWhiteSpace($ExpectedBranch)) {
        $actualBranch = ""
        try {
            Push-Location -LiteralPath $RepoRootResolved
            $actualBranch = (& git rev-parse --abbrev-ref HEAD 2>$null).Trim()
        } finally {
            Pop-Location -ErrorAction SilentlyContinue
        }
        if ($actualBranch -ne $ExpectedBranch) {
            throw "Repo checkout is on branch '$actualBranch', expected '$ExpectedBranch'. Refusing to start (fail-closed) - run RUN_AI_COCKPIT_V9.ps1, which pins and verifies the branch before ever reaching this point."
        }
        Write-Status ("  branch:  " + $actualBranch + " (matches expected)") Green
    }

    # 2026-09-25 P0 fix: repo-updated must never be assumed to mean
    # runtime-updated. RUN_AI_COCKPIT_V9.ps1 deploys Watcher/Heartbeat/
    # Collector into RuntimeDir and records their SHA256 in V9_RUNTIME.json;
    # this recomputes the hash of what's ACTUALLY sitting in RuntimeDir
    # right now and refuses to start if it doesn't match what was deployed
    # (missing manifest, stale runtime, or a file changed since deploy all
    # fail closed here rather than silently running mismatched code).
    $runtimeManifestPath = Join-Path $Root "V9_RUNTIME.json"
    if (-not (Test-Path -LiteralPath $runtimeManifestPath)) {
        throw "No V9_RUNTIME.json found - runtime scripts were never deployed to RuntimeDir. Run RUN_AI_COCKPIT_V9.ps1 (not this controller directly) so it deploys Watcher/Heartbeat/Collector before starting."
    }
    $runtimeManifest = Read-JsonUtf8 $runtimeManifestPath
    if ($runtimeManifest.runtime_dir -ne $RuntimeDir) {
        throw "V9_RUNTIME.json was deployed for a different RuntimeDir (" + $runtimeManifest.runtime_dir + ") than the one resolved now (" + $RuntimeDir + "). Re-run RUN_AI_COCKPIT_V9.ps1."
    }
    foreach ($name in @(
        "Kioxia_RSS_Live_Watcher.ps1",
        "Kioxia_Safety_Heartbeat.ps1",
        "MS2_RSS_100_Collector.ps1",
        "MS2_Common_Engine.ps1",
        "BUILD_KIOXIA_TIME_STATS.ps1",
        "watchlist_100.json",
        "SPEAK_TODAY_STRATEGY.ps1",
        "SPEAK_LIVE_EMOTION.ps1"
    )) {
        $expectedHash = $runtimeManifest.files.$name
        if ([string]::IsNullOrWhiteSpace($expectedHash)) {
            throw "V9_RUNTIME.json has no recorded hash for $name. Re-run RUN_AI_COCKPIT_V9.ps1."
        }
        $actualPath = Join-Path $RuntimeDir $name
        if (-not (Test-Path -LiteralPath $actualPath)) {
            throw "Runtime file missing: $actualPath. Re-run RUN_AI_COCKPIT_V9.ps1."
        }
        $actualHash = (Get-FileHash -LiteralPath $actualPath -Algorithm SHA256).Hash
        if ($actualHash -ne $expectedHash) {
            throw "Runtime file $name does not match the deployed manifest (RuntimeDir file was changed or reverted since deploy). Re-run RUN_AI_COCKPIT_V9.ps1 to redeploy - refusing to start against unverified runtime code."
        }
    }
    Write-Status ("  runtime files: verified against V9_RUNTIME.json (deployed " + $runtimeManifest.deployed_at + ")") Green

    $Watcher = Join-Path $RuntimeDir "Kioxia_RSS_Live_Watcher.ps1"
    $Heartbeat = Join-Path $RuntimeDir "Kioxia_Safety_Heartbeat.ps1"
    $Collector = Join-Path $RuntimeDir "MS2_RSS_100_Collector.ps1"
    $Gateway = Join-Path $PSScriptRoot "AI_COCKPIT_GATEWAY_V9.ps1"
    $VoiceBridge = Join-Path $PSScriptRoot "AI_COCKPIT_VOICE_BRIDGE_V9.ps1"
    $WorkbookPath = Join-Path $RuntimeDir "Kioxia_MS2_RSS_Live_Signals.xlsx"
    $WorkbookName = [IO.Path]::GetFileName($WorkbookPath)
    $state.workbook_name = $WorkbookName
    $state.workbook_path = $WorkbookPath

    foreach ($p in @($Watcher, $Heartbeat, $Collector, $Gateway, $VoiceBridge, $WorkbookPath)) {
        if (-not (Test-Path -LiteralPath $p)) { throw "Required file not found: $p" }
    }

    Write-Status "Stopping this controller's previously managed processes (own PIDs only)..."
    Stop-OwnedFromPreviousState
    Start-Sleep -Milliseconds 500

    Write-Status "Stopping obsolete voice-only workers so old SAPI cannot leak into V9..."
    Stop-LegacyVoiceWorkers

    Write-Status "Checking for foreign sessions on 28580/28581/28582/28583..."
    $ownedNow = @{
        watcher   = 0
        heartbeat = 0
        collector = 0
        gateway   = 0
        voice_bridge = 0
    }
    $foreignHits = Test-ForeignSession $ownedNow
    if ($foreignHits.Count -gt 0) {
        Write-Host ""
        Write-Host "==================================================" -ForegroundColor Red
        Write-Host " FOREIGN SESSION DETECTED" -ForegroundColor Red
        Write-Host "==================================================" -ForegroundColor Red
        foreach ($h in $foreignHits) { Write-Host ("  " + $h) -ForegroundColor Yellow }
        Write-Host ""
        Write-Host "Another process (an old V6/V7 session, a stale V8 run this" -ForegroundColor Cyan
        Write-Host "controller doesn't recognize, or something unrelated) already" -ForegroundColor Cyan
        Write-Host "owns one of these ports. Not killing it automatically - stop it" -ForegroundColor Cyan
        Write-Host "yourself (Task Manager, or the matching STOP_*.ps1 script) and" -ForegroundColor Cyan
        Write-Host "run this controller again." -ForegroundColor Cyan
        throw "Foreign session on a required port - refusing to start."
    }
    Write-Status "  No foreign session on 28580/28581/28582/28583." Green

    Write-Status "Checking MarketSpeed II in this Windows session..."
    $currentSessionId = Get-CurrentSessionId
    $ms2 = @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ProcessName -match "MarketSpeed|MARKETSPEED" -and
        [int]$_.SessionId -eq $currentSessionId
    })
    if ($ms2.Count -eq 0) {
        throw "MarketSpeed II is not running in this Windows session. Start/login MarketSpeed II inside the dedicated AI Cockpit session, then run again."
    }
    Write-Status ("  MarketSpeed II: READY / session " + $currentSessionId) Green

    # Foreign Excel may stay open. Isolation is the new /x process plus
    # canonical identity checks. Presence alone does not stop startup,
    # and this interlock never closes, kills, or clicks another Excel.
    $foreignExcelAtStartup = @(Get-ForeignExcelProcesses)
    if ($foreignExcelAtStartup.Count -gt 0) {
        Write-Host ""
        Write-Host "==================================================" -ForegroundColor Yellow
        Write-Host " EXCEL SAFETY INTERLOCK" -ForegroundColor Yellow
        Write-Host "==================================================" -ForegroundColor Yellow
        foreach ($foreignExcel in $foreignExcelAtStartup) {
            Write-Host ("  leaving foreign Excel untouched: PID " + $foreignExcel.Id + " / " + $foreignExcel.MainWindowTitle) -ForegroundColor Yellow
        }
        Write-Host ""
        Write-Host "Foreign Excel is present. It will not be closed, killed, or operated." -ForegroundColor Cyan
        Write-Host "AI Cockpit will launch a separate isolated Excel /x for the canonical workbook only." -ForegroundColor Cyan
    } else {
        Write-Status "  Excel safety interlock: no pre-existing Excel process." Green
    }

    Write-Status "Starting unified voice backend (Style-Bert-VITS2 only)..."
    if (Test-Port 5000 350) {
        $state.sbv2_status = "LIVE"
        Write-Status "  SBV2: READY / 5000" Green
    } else {
        $sbvProc = Start-Sbv2Managed
        if ($null -ne $sbvProc) {
            $state.sbv2_pid = [int]$sbvProc.Id
            $state.sbv2_status = "STARTING"
            Write-Status ("  SBV2: STARTING / PID " + $state.sbv2_pid + " (non-blocking)") Yellow
        } else {
            $state.sbv2_status = "OFFLINE"
        }
    }
    Save-State $state

    $voiceArgs = '-Port ' + $PORT_VOICE
    $voiceProc = Start-Worker -Name "voice_bridge" -Script $VoiceBridge -WorkDir $RepoRootResolved -ExtraArgs $voiceArgs
    $state.voice_bridge_pid = [int]$voiceProc.Id
    $ownedNow.voice_bridge = $state.voice_bridge_pid
    if (Wait-PortBounded $PORT_VOICE 10 "VoiceBridge") {
        $state.voice_bridge_status = "LIVE"
        Write-Status ("  VoiceBridge: LIVE / " + $PORT_VOICE) Green
    } else {
        $state.voice_bridge_status = if ($voiceProc.HasExited) { "CRASHED" } else { "STARTING" }
        Write-Status "  VoiceBridge not ready yet; cockpit continues with VOICE OFFLINE and no legacy fallback." Yellow
    }
    Save-State $state

    Write-Status "Starting Gateway first (fail-closed UI is viewable immediately)..."
    $gatewayArgs = '-RepoRoot "' + $RepoRootResolved + '" -RuntimeDir "' + $RuntimeDir + '" -Build "' + $Build + '" -Port ' + $PORT_GATEWAY
    $gatewayProc = Start-Worker -Name "gateway" -Script $Gateway -WorkDir $RepoRootResolved -ExtraArgs $gatewayArgs
    $state.gateway_pid = [int]$gatewayProc.Id
    Save-State $state
    if (-not (Wait-PortBounded $PORT_GATEWAY 20 "Gateway")) {
        $err = Tail-Log (Join-Path $LogDir "gateway_stderr.log")
        throw "Gateway did not open port $PORT_GATEWAY within 20s. $err"
    }
    Write-Status ("  Gateway: READY / http://127.0.0.1:" + $PORT_GATEWAY + "/?live=1") Green
    Start-Process ("http://127.0.0.1:" + $PORT_GATEWAY + "/?live=1")

    Write-Status "Opening MS2 RSS workbook (isolated Excel /x; canonical path only)..."
    Write-Status ("  canonical: " + $WorkbookPath) DarkGray

    $existingExcel = @(Get-CanonicalWorkbookConflicts $WorkbookPath $WorkbookName @())

    if ($existingExcel.Count -gt 0) {
        # A previous AI Cockpit /x process is not foreign work Excel, and it
        # is not an ownership candidate. Stop only an orphan whose command
        # line is exactly this controller's isolated launch. Any other
        # canonical holder stays untouched and startup fail-closes.
        $unknownCanonical = New-Object System.Collections.Generic.List[object]
        $leftoverPids = New-Object System.Collections.Generic.List[int]
        foreach ($proc in $existingExcel) {
            $pidValue = [int]$proc.Id
            if (Test-LeftoverCockpitExcel $pidValue $WorkbookPath) {
                if (-not $leftoverPids.Contains($pidValue)) { [void]$leftoverPids.Add($pidValue) }
            } else {
                [void]$unknownCanonical.Add($proc)
            }
        }
        if ($unknownCanonical.Count -gt 0) {
            $state.excel_pid = 0
            $state.workbook_identity_verified = $false
            Save-State $state
            throw (
                "RSS workbook is already open in Excel PID " +
                $unknownCanonical[0].Id +
                ". Refusing to take ownership. Foreign Excel was not touched."
            )
        }
        foreach ($pidValue in @($leftoverPids)) {
            Write-Status ("  leftover AI Cockpit /x Excel PID " + $pidValue + " is not adopted.") Yellow
            $leftoverStopped = Stop-VerifiedLeftoverCockpitExcel $pidValue $WorkbookPath
            if (-not $leftoverStopped) {
                $state.excel_pid = 0
                $state.workbook_identity_verified = $false
                Save-State $state
                throw (
                    "Leftover AI Cockpit Excel PID " +
                    $pidValue +
                    " could not be verified/stopped. Refusing to take ownership. Foreign Excel was not touched."
                )
            }
            Write-Status ("  stopped leftover AI Cockpit /x Excel PID " + $pidValue + ". It was not adopted.") Yellow
        }
        $stillOpen = @(Get-CanonicalWorkbookConflicts $WorkbookPath $WorkbookName @())
        if ($stillOpen.Count -gt 0) {
            $state.excel_pid = 0
            $state.workbook_identity_verified = $false
            Save-State $state
            throw (
                "RSS workbook is already open in Excel PID " +
                $stillOpen[0].Id +
                ". Refusing to take ownership. Foreign Excel was not touched."
            )
        }
    }

    $excelExe = @(
        "C:\Program Files\Microsoft Office\Root\Office16\EXCEL.EXE",
        "C:\Program Files (x86)\Microsoft Office\Root\Office16\EXCEL.EXE"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1

    if (-not $excelExe) {
        throw "EXCEL.EXE was not found."
    }

    # Windows PowerShell 5.1 re-quotes an ArgumentList array. A path that
    # already contains spaces (MarketSpeed II RSS) was being passed to
    # Excel with broken quotes, so the canonical workbook never reached
    # the ROT. ProcessStartInfo keeps one /x argument and the full path.
    if ($WorkbookPath.Contains('"')) { throw "Canonical workbook path contains a quote. Refusing to launch." }
    $excelStart = New-Object System.Diagnostics.ProcessStartInfo
    $excelStart.FileName = $excelExe
    $excelStart.UseShellExecute = $false
    $excelStart.Arguments = Get-IsolatedExcelArguments $WorkbookPath
    $launchedExcelProc = [Diagnostics.Process]::Start($excelStart)
    $state.excel_pid = [int]$launchedExcelProc.Id
    $state.workbook_identity_verified = $false
    Save-State $state

    Write-Status (
        "  isolated Excel launched / PID " +
        $launchedExcelProc.Id
    ) DarkGray

    $conflictAfterLaunch = @(Get-CanonicalWorkbookConflicts $WorkbookPath $WorkbookName @([int]$launchedExcelProc.Id))
    if ($conflictAfterLaunch.Count -gt 0) {
        $ownedStopped = Stop-VerifiedOwnedExcel ([int]$launchedExcelProc.Id) $WorkbookPath $PID
        if ($ownedStopped) {
            Write-Status "  verified owned Excel stopped after a canonical conflict. The other Excel was not touched." Yellow
        }
        $state.excel_pid = 0
        $state.workbook_identity_verified = $false
        Save-State $state
        throw (
            "RSS workbook is already open in Excel PID " +
            $conflictAfterLaunch[0].Id +
            ". Refusing to take ownership. Foreign Excel was not touched."
        )
    }

    $probe = Complete-ExcelProbeResult (Invoke-ExcelIdentityProbe `
        -WorkbookPath $WorkbookPath `
        -ExpectedExcelPid ([int]$launchedExcelProc.Id) `
        -TimeoutSeconds $ExcelIdentityProbeTimeoutSeconds `
        -LogDirectory $LogDir) $launchedExcelProc

    if (-not $probe.ok) {
        $state.excel_pid = 0
        $state.workbook_identity_verified = $false
        $state.excel_identity_error = [string]$probe.code
        Save-State $state

        $openCrash = $probe.code -in @("EXCEL_PROCESS_EXITED", "EXCEL_SERIOUS_ERROR_PROMPT") -or [bool]$probe.process_exited
        if ($openCrash) {
            Write-Status ("  launched Excel PID " + $probe.launched_excel_pid + " / process_exited " + [bool]$probe.process_exited + " / exit_code " + $probe.excel_exit_code + " / exit_at " + $probe.excel_exit_at) Yellow
            Write-Status "  launched Excel was not force-killed after workbook open failure. Work Excel was not touched. Startup does not reopen Excel." Yellow
        } else {
            $ownedStopped = Stop-VerifiedOwnedExcel ([int]$launchedExcelProc.Id) $WorkbookPath $PID
            if ($ownedStopped) {
                Write-Status "  verified owned Excel stopped after identity failure." Yellow
            }
        }
        Add-ExcelIdentityIncident $probe
        Write-Status "AI Cockpit startup failed closed" Red
        Write-Status "Unrelated Excel processes were not touched" Yellow
        if ($openCrash) {
            throw ("Excel workbook open failed closed: " + $probe.code + " / PID " + $probe.launched_excel_pid + " / exit_code " + $probe.excel_exit_code + " / " + [string]$probe.detail)
        }
        throw ("Excel identity probe failed closed: " + $probe.code + " / " + [string]$probe.detail)
    }

    $state.excel_pid = [int]$launchedExcelProc.Id
    $state.workbook_identity_verified = $true
    $state.excel_identity_error = ""
    Save-State $state
    Close-OpenExcelIdentityIncidents

    Write-Status (
        "  Excel PID: " +
        $state.excel_pid +
        " / identity verified: True / isolated: True"
    ) Green

    Write-Status "Starting Watcher..."
    $watcherProc = Start-Worker -Name "watcher" -Script $Watcher -WorkDir $RuntimeDir
    $state.watcher_pid = [int]$watcherProc.Id
    $ownedNow.watcher = $state.watcher_pid
    Save-State $state
    if (Wait-PortBounded $PORT_WATCHER 20 "Watcher") {
        $state.watcher_status = "LIVE"
        Write-Status ("  Watcher: LIVE / PID " + $state.watcher_pid + " / " + $PORT_WATCHER) Green
    } else {
        $state.watcher_status = if ($watcherProc.HasExited) { "CRASHED" } else { "SLOW_NOT_YET_READY" }
        $err = Tail-Log (Join-Path $LogDir "watcher_stderr.log")
        Write-Status ("  Watcher: " + $state.watcher_status + " (PID still tracked if alive; supervision loop will retry). " + $err) Yellow
    }
    Save-State $state

    Write-Status "Starting safety heartbeat..."
    $heartbeatProc = Start-Worker -Name "heartbeat" -Script $Heartbeat -WorkDir $RuntimeDir
    $state.heartbeat_pid = [int]$heartbeatProc.Id
    $state.heartbeat_status = if ($heartbeatProc.HasExited) { "CRASHED" } else { "RUNNING" }
    $ownedNow.heartbeat = $state.heartbeat_pid
    Save-State $state
    Write-Status ("  Heartbeat: PID " + $state.heartbeat_pid) Green

    Write-Status "Starting Collector (bounded wait; Controller/UI stay up either way)..."
    $collectorProc = Start-Worker -Name "collector" -Script $Collector -WorkDir $RuntimeDir
    $state.collector_pid = [int]$collectorProc.Id
    $state.collector_status = "STARTING"
    $ownedNow.collector = $state.collector_pid
    Save-State $state
    if (Wait-PortBounded $PORT_COLLECTOR 45 "Collector") {
        $state.collector_status = "LIVE"
        Write-Status ("  Collector: LIVE / " + $PORT_COLLECTOR) Green
    } else {
        $state.collector_status = if ($collectorProc.HasExited) { "CRASHED" } else { "SLOW_NOT_YET_READY" }
        $err = Tail-Log (Join-Path $LogDir "collector_stderr.log")
        Write-Status ("  Collector: " + $state.collector_status + " (Controller and UI continue; UI stays fail-closed). " + $err) Yellow
    }
    Save-State $state

    Write-Status "Starting AI SHADOW supervisor (UI-independent; it fail-closes until live data passes)..."
    $shadowProc = Start-ShadowSupervisor $RepoRootResolved $RuntimeDir
    if ($null -ne $shadowProc) {
        $state.shadow_supervisor_pid = [int]$shadowProc.Id
        $state.shadow_supervisor_status = if ($shadowProc.HasExited) { "CRASHED" } else { "STARTING" }
        Write-Status ("  AI SHADOW supervisor PID " + $state.shadow_supervisor_pid) Green
    } else {
        $state.shadow_supervisor_status = "STOPPED"
    }
    Save-State $state

    Write-Status "Startup complete. Entering supervision loop (Ctrl+C to stop everything)." Green
    Write-Host ""
    Write-Host "This window supervises the running session. Closing the MS2 workbook" -ForegroundColor Cyan
    Write-Host "will automatically stop the Watcher/Heartbeat/Collector/Gateway/VoiceBridge and" -ForegroundColor Cyan
    Write-Host "this Excel process - only the ones this controller started." -ForegroundColor Cyan
    Write-Host ""

    # ---------------------------------------------------- supervision loop
    $excelMisses = 0
    $collectorRestartAttempts = 0
    $lastCollectorRestartAt = Get-Date "2000-01-01"
    $watcherRestartAttempts = 0
    $lastWatcherRestartAt = Get-Date "2000-01-01"
    $heartbeatRestartAttempts = 0
    $lastHeartbeatRestartAt = Get-Date "2000-01-01"
    $voiceRestartAttempts = 0
    $lastVoiceRestartAt = Get-Date "2000-01-01"
    $sbv2RestartAttempts = 0
    $lastSbv2RestartAt = Get-Date "2000-01-01"
    $shadowRestartAttempts = 0
    $lastShadowRestartAt = Get-Date "2000-01-01"
    while ($true) {
        Start-Sleep -Seconds 2

        # A foreign Excel with some other workbook may keep running.
        # Fail closed only when another process already has the canonical
        # workbook. Never close, kill, or click that foreign process.
        $allowedExcelPids = @()
        if ([int]$state.excel_pid -gt 0) { $allowedExcelPids += [int]$state.excel_pid }
        $foreignExcelNow = @(Get-CanonicalWorkbookConflicts $WorkbookPath $WorkbookName $allowedExcelPids)
        if ($foreignExcelNow.Count -gt 0) {
            Write-Status "CANONICAL WORKBOOK CONFLICT - FAIL-CLOSED SAFETY STOP." Red
            foreach ($foreignExcel in $foreignExcelNow) {
                Write-Status ("  leaving foreign Excel untouched: PID " + $foreignExcel.Id + " / " + $foreignExcel.MainWindowTitle) Yellow
            }

            $state.collector_status = "BLOCKED_FOREIGN_EXCEL"
            $state.watcher_status = "BLOCKED_FOREIGN_EXCEL"
            $state.heartbeat_status = "BLOCKED_FOREIGN_EXCEL"
            Save-State $state

            Stop-OwnedJobBridge $PORT_COLLECTOR ([int]$state.collector_pid) "Collector JSON" | Out-Null
            Stop-OwnedJobBridge $PORT_WATCHER ([int]$state.watcher_pid) "Watcher JSON" | Out-Null
            Stop-ManagedWorkersOnWorkbookClose $state

            $ownedExcelStopped = Stop-VerifiedOwnedExcel ([int]$state.excel_pid) $WorkbookPath $PID
            if (-not $ownedExcelStopped) {
                Write-Status "ERROR: owned Excel could not be verified/stopped. Foreign Excel remains untouched." Red
            } else {
                Write-Status "  AI Cockpit Excel stopped; foreign Excel was not touched." Green
            }

            Save-State $state
            [Environment]::Exit(3)
        }

        # 1) Has the user closed the workbook?
        if ($state.excel_pid -gt 0) {
            $xp = Get-Process -Id $state.excel_pid -ErrorAction SilentlyContinue
            $stillOpen = $false
            if ($null -ne $xp) {
                if ($xp.MainWindowHandle -ne 0 -and $xp.MainWindowTitle -like ("*" + $WorkbookName + "*")) {
                    $stillOpen = $true
                    $excelMisses = 0
                } else {
                    $excelMisses++
                }
            } else {
                $excelMisses = 99
            }
            if (-not $stillOpen -and $excelMisses -ge 4) {
                Write-Status "Workbook close detected - stopping managed processes..." Yellow
                Stop-OwnedJobBridge $PORT_COLLECTOR ([int]$state.collector_pid) "Collector JSON" | Out-Null
                Stop-OwnedJobBridge $PORT_WATCHER ([int]$state.watcher_pid) "Watcher JSON" | Out-Null
                Stop-ManagedWorkersOnWorkbookClose $state
                Start-Sleep -Seconds 2

                # The workbook window is already closed at this point.
                # Do NOT preserve the tracked Excel blindly: that is what
                # left the hidden 300MB+ EXCEL.EXE orphan behind.
                #
                # Force-stop is permitted ONLY when all ownership checks
                # identify this exact process as the AI Cockpit workbook
                # launched by this Controller.
                $xp2 = Get-Process -Id ([int]$state.excel_pid) -ErrorAction SilentlyContinue

                if ($null -ne $xp2) {
                    $excelInfo = Get-CimInstance Win32_Process `
                        -Filter ("ProcessId = " + [int]$state.excel_pid) `
                        -ErrorAction SilentlyContinue

                    $excelCmd = if ($null -ne $excelInfo) {
                        [string]$excelInfo.CommandLine
                    } else {
                        ""
                    }

                    $isHidden = ($xp2.MainWindowHandle -eq 0)

                    $ordinalIgnoreCase = [StringComparison]::OrdinalIgnoreCase
                    $isCanonicalWorkbook = (
                        -not [string]::IsNullOrWhiteSpace($excelCmd) -and
                        $excelCmd.IndexOf($WorkbookPath, $ordinalIgnoreCase) -ge 0
                    )

                    $isControllerChild = (
                        $null -ne $excelInfo -and
                        [int]$excelInfo.ParentProcessId -eq $PID
                    )

                    if (
                        $isHidden -and
                        $isCanonicalWorkbook -and
                        $isControllerChild
                    ) {
                        Write-Status (
                            "  terminating verified hidden AI Cockpit Excel PID " +
                            $state.excel_pid
                        ) Yellow

                        Stop-Process `
                            -Id ([int]$state.excel_pid) `
                            -Force `
                            -ErrorAction Stop

                        # Bound the wait; never report clean shutdown until
                        # the tracked process is actually gone.
                        $excelGone = $false

                        foreach ($attempt in 1..10) {
                            Start-Sleep -Milliseconds 500

                            if (
                                $null -eq (
                                    Get-Process `
                                        -Id ([int]$state.excel_pid) `
                                        -ErrorAction SilentlyContinue
                                )
                            ) {
                                $excelGone = $true
                                break
                            }
                        }

                        if (-not $excelGone) {
                            Write-Status (
                                "ERROR: verified AI Cockpit Excel PID " +
                                $state.excel_pid +
                                " did not terminate."
                            ) Red

                            Save-State $state
                            [Environment]::Exit(2)
                        }

                        Write-Status (
                            "  verified AI Cockpit Excel PID " +
                            $state.excel_pid +
                            " terminated."
                        ) Green
                    }
                    else {
                        Write-Status (
                            "ERROR: remaining Excel PID " +
                            $state.excel_pid +
                            " failed ownership verification. " +
                            "hidden=" + $isHidden +
                            ", canonicalWorkbook=" + $isCanonicalWorkbook +
                            ", controllerChild=" + $isControllerChild +
                            ". It will NOT be force-stopped."
                        ) Red

                        # Keep state for diagnosis instead of deleting our
                        # only ownership evidence.
                        Save-State $state
                        [Environment]::Exit(2)
                    }
                }

                # Final tracked-PID verification before deleting state.
                $xp3 = Get-Process `
                    -Id ([int]$state.excel_pid) `
                    -ErrorAction SilentlyContinue

                if ($null -ne $xp3) {
                    Write-Status (
                        "ERROR: tracked Excel still exists; state retained."
                    ) Red

                    Save-State $state
                    [Environment]::Exit(2)
                }

                Write-Status "  Excel cleanup verified: tracked AI Cockpit Excel is gone." Green

                Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue
                Write-Status "Managed-worker shutdown requested. Review the process checks for any remaining processes." Green
                Start-Sleep -Seconds 2
                [Environment]::Exit(0)
            }
        }

        # Voice backend is presentation-only: failure never takes down market data,
        # but the UI must show VOICE OFFLINE and must never fall back to Windows SAPI.
        if (Test-Port 5000 250) {
            if ($state.sbv2_status -ne "LIVE") {
                $state.sbv2_status = "LIVE"
                $sbv2RestartAttempts = 0
                Write-Status "SBV2 recovered - LIVE / 5000" Green
            }
        } else {
            $state.sbv2_status = "OFFLINE"
            $since = ((Get-Date) - $lastSbv2RestartAt).TotalSeconds
            if ($sbv2RestartAttempts -lt 3 -and $since -gt 30) {
                $sbv2RestartAttempts++
                $lastSbv2RestartAt = Get-Date
                $sbvProc = Start-Sbv2Managed
                if ($null -ne $sbvProc) {
                    $state.sbv2_pid = [int]$sbvProc.Id
                    $state.sbv2_status = "STARTING"
                    Write-Status ("SBV2 restart attempt " + $sbv2RestartAttempts + "/3") Yellow
                }
            }
        }

        $vp = if ($state.voice_bridge_pid -gt 0) { Get-Process -Id $state.voice_bridge_pid -ErrorAction SilentlyContinue } else { $null }
        if ($null -eq $vp) {
            $state.voice_bridge_status = "DOWN"
            $since = ((Get-Date) - $lastVoiceRestartAt).TotalSeconds
            if ($voiceRestartAttempts -lt 5 -and $since -gt 20) {
                $voiceRestartAttempts++
                $lastVoiceRestartAt = Get-Date
                Write-Status ("VoiceBridge is down (attempt " + $voiceRestartAttempts + "/5) - restarting; no SAPI fallback.") Yellow
                $voiceProc = Start-Worker -Name ("voice_bridge_retry" + $voiceRestartAttempts) -Script $VoiceBridge -WorkDir $RepoRootResolved -ExtraArgs $voiceArgs
                $state.voice_bridge_pid = [int]$voiceProc.Id
                $state.voice_bridge_status = "STARTING"
            }
        } elseif (Test-Port $PORT_VOICE 250) {
            if ($state.voice_bridge_status -ne "LIVE") { Write-Status "VoiceBridge recovered - LIVE" Green }
            $state.voice_bridge_status = "LIVE"
            $voiceRestartAttempts = 0
        }
        Save-State $state

        # 2) Is Watcher still alive? Its death means the browser's Excel-
        #    sourced Kioxia data goes stale, so the UI must fail closed
        #    immediately rather than wait for the normal staleness timer -
        #    watcher_status is surfaced through /health for the frontend to
        #    check. Bounded restart, same as Collector; never takes down
        #    the Controller.
        $wp = if ($state.watcher_pid -gt 0) { Get-Process -Id $state.watcher_pid -ErrorAction SilentlyContinue } else { $null }
        if ($null -eq $wp) {
            if ($state.watcher_status -ne "DOWN") {
                Write-Status "Watcher is down - UI forced fail-closed via /health until it recovers." Red
            }
            $state.watcher_status = "DOWN"
            $secsSinceRestart = ((Get-Date) - $lastWatcherRestartAt).TotalSeconds
            if ($watcherRestartAttempts -lt 5 -and $secsSinceRestart -gt 20) {
                $watcherRestartAttempts++
                $lastWatcherRestartAt = Get-Date
                Write-Status ("Watcher is down (attempt " + $watcherRestartAttempts + "/5) - restarting.") Yellow
                Stop-OwnedJobBridge $PORT_WATCHER ([int]$state.watcher_pid) "Watcher JSON" | Out-Null
                $watcherProc = Start-Worker -Name ("watcher_retry" + $watcherRestartAttempts) -Script $Watcher -WorkDir $RuntimeDir
                $state.watcher_pid = [int]$watcherProc.Id
                $state.watcher_status = "STARTING"
            }
            Save-State $state
        } elseif ($state.watcher_status -ne "LIVE" -and (Test-Port $PORT_WATCHER 300)) {
            $state.watcher_status = "LIVE"
            $watcherRestartAttempts = 0
            Save-State $state
            Write-Status "Watcher recovered - LIVE" Green
        }

        # 3) Is Heartbeat still alive? Its death degrades the safety gate
        #    (Excel's own NOW()-based staleness formula keeps working
        #    without it, but the independent watchdog is gone) - surfaced
        #    as DEGRADED/BLOCK-worthy via /health, bounded restart.
        $hp = if ($state.heartbeat_pid -gt 0) { Get-Process -Id $state.heartbeat_pid -ErrorAction SilentlyContinue } else { $null }
        if ($null -eq $hp) {
            if ($state.heartbeat_status -ne "DOWN") {
                Write-Status "Heartbeat is down - safety status DEGRADED until it recovers." Red
            }
            $state.heartbeat_status = "DOWN"
            $secsSinceRestart = ((Get-Date) - $lastHeartbeatRestartAt).TotalSeconds
            if ($heartbeatRestartAttempts -lt 5 -and $secsSinceRestart -gt 20) {
                $heartbeatRestartAttempts++
                $lastHeartbeatRestartAt = Get-Date
                Write-Status ("Heartbeat is down (attempt " + $heartbeatRestartAttempts + "/5) - restarting.") Yellow
                $heartbeatProc = Start-Worker -Name ("heartbeat_retry" + $heartbeatRestartAttempts) -Script $Heartbeat -WorkDir $RuntimeDir
                $state.heartbeat_pid = [int]$heartbeatProc.Id
                $state.heartbeat_status = "STARTING"
            }
            Save-State $state
        } elseif ($state.heartbeat_status -ne "RUNNING") {
            $state.heartbeat_status = "RUNNING"
            $heartbeatRestartAttempts = 0
            Save-State $state
            Write-Status "Heartbeat recovered - RUNNING" Green
        }

        # 4) Is Collector still alive? Restart it with bounded backoff;
        #    never take down Gateway/UI because of this.
        $cp = if ($state.collector_pid -gt 0) { Get-Process -Id $state.collector_pid -ErrorAction SilentlyContinue } else { $null }
        if ($null -eq $cp) {
            $state.collector_status = "DOWN"
            $secsSinceRestart = ((Get-Date) - $lastCollectorRestartAt).TotalSeconds
            if ($collectorRestartAttempts -lt 5 -and $secsSinceRestart -gt 20) {
                $collectorRestartAttempts++
                $lastCollectorRestartAt = Get-Date
                Write-Status ("Collector is down (attempt " + $collectorRestartAttempts + "/5) - restarting; UI stays fail-closed meanwhile.") Yellow
                Stop-OwnedJobBridge $PORT_COLLECTOR ([int]$state.collector_pid) "Collector JSON" | Out-Null
                $collectorProc = Start-Worker -Name ("collector_retry" + $collectorRestartAttempts) -Script $Collector -WorkDir $RuntimeDir
                $state.collector_pid = [int]$collectorProc.Id
                $state.collector_status = "STARTING"
            }
            Save-State $state
        } elseif ($state.collector_status -ne "LIVE" -and (Test-Port $PORT_COLLECTOR 300)) {
            $state.collector_status = "LIVE"
            $collectorRestartAttempts = 0
            Save-State $state
            Write-Status ("Collector recovered - LIVE / " + $PORT_COLLECTOR) Green
        }

        # 4b) AI SHADOW is a background observer. Restart the process if it
        # dies, but never start a second copy while the recorded PID is alive,
        # and never let its failure stop Collector, Excel, or the Gateway.
        $sp = if ($state.shadow_supervisor_pid -gt 0) { Get-Process -Id $state.shadow_supervisor_pid -ErrorAction SilentlyContinue } else { $null }
        if ($null -eq $sp) {
            if ($state.shadow_supervisor_status -ne "STOPPED" -and $state.shadow_supervisor_status -ne "DOWN") {
                Write-Status "AI SHADOW supervisor is down - observations stay fail-closed until it restarts." Yellow
            }
            $state.shadow_supervisor_status = "DOWN"
            $secsSinceShadow = ((Get-Date) - $lastShadowRestartAt).TotalSeconds
            if ($shadowRestartAttempts -lt 5 -and $secsSinceShadow -gt 20) {
                $shadowRestartAttempts++
                $lastShadowRestartAt = Get-Date
                Write-Status ("AI SHADOW supervisor restart attempt " + $shadowRestartAttempts + "/5") Yellow
                $shadowProc = Start-ShadowSupervisor $RepoRootResolved $RuntimeDir
                if ($null -ne $shadowProc) {
                    $state.shadow_supervisor_pid = [int]$shadowProc.Id
                    $state.shadow_supervisor_status = "STARTING"
                } else {
                    $state.shadow_supervisor_status = "STOPPED"
                }
            }
            Save-State $state
        } elseif ($state.shadow_supervisor_status -ne "RUNNING") {
            $state.shadow_supervisor_status = "RUNNING"
            $shadowRestartAttempts = 0
            Save-State $state
            Write-Status "AI SHADOW supervisor process is alive. Engine state is published in ai_shadow_status.json." Green
        }

        # 5) Is Gateway still alive? This one we do treat as worth a clear
        #    warning (the UI itself becomes unreachable), but we still do
        #    not exit the Controller - the user can see this window.
        if ($state.gateway_pid -gt 0) {
            $gp = Get-Process -Id $state.gateway_pid -ErrorAction SilentlyContinue
            if ($null -eq $gp) {
                Write-Status "Gateway process is not running - UI is unreachable. Restarting it..." Red
                $gatewayProc = Start-Worker -Name "gateway_retry" -Script $Gateway -WorkDir $RepoRootResolved -ExtraArgs $gatewayArgs
                $state.gateway_pid = [int]$gatewayProc.Id
                Save-State $state
            }
        }
    }
} catch {
    Write-Host ""
    Write-Host "==================================================" -ForegroundColor Red
    Write-Host " AI COCKPIT CONTROLLER V9 - STOPPED ON ERROR" -ForegroundColor Red
    Write-Host "==================================================" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Yellow
    Write-Host ""
    Write-Host ("Logs: " + $LogDir) -ForegroundColor Cyan
    Write-Host ("State file: " + $StateFile) -ForegroundColor Cyan
    Write-Host ""
    Write-Host "This window is intentionally left open so you can read the cause above." -ForegroundColor Cyan
    Read-Host "Press Enter to close"
    [Environment]::Exit(1)
}
