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
$state = [IO.File]::ReadAllText($StateFile, [Text.Encoding]::UTF8) | ConvertFrom-Json

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
        "controller_pid"   { "AI_COCKPIT_CONTROLLER_V10.ps1" }
        default            { "" }
    }
    if ([string]::IsNullOrWhiteSpace($expected)) { return $false }
    try {
        $wmi = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $ProcessId) -ErrorAction SilentlyContinue
        $cmd = if ($null -ne $wmi) { [string]$wmi.CommandLine } else { "" }
        return (-not [string]::IsNullOrWhiteSpace($cmd) -and $cmd -match [regex]::Escape($expected))
    } catch { return $false }
}

Stop-OwnedJobBridge 28580 ([int]$state.collector_pid) "Collector JSON"
Stop-OwnedJobBridge 28582 ([int]$state.watcher_pid) "Watcher JSON"

foreach ($field in @("watcher_pid", "heartbeat_pid", "collector_pid", "gateway_pid", "brain_gateway_pid", "voice_bridge_pid", "sbv2_pid", "shadow_supervisor_pid", "controller_pid")) {
    $val = $state.PSObject.Properties[$field]
    if ($null -eq $val -or [int]$val.Value -le 0) { continue }
    $procId = [int]$val.Value
    $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
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
            Write-Host ("Requesting normal close of verified V10 Excel PID " + $excelPid + " ...") -ForegroundColor Yellow
            $closeRequested = $false
            try { $closeRequested = [bool]$xp.CloseMainWindow() } catch {}
            if ($closeRequested) {
                foreach ($attempt in 1..30) {
                    Start-Sleep -Milliseconds 500
                    if ($null -eq (Get-Process -Id $excelPid -ErrorAction SilentlyContinue)) {
                        $excelCleanupOk = $true
                        break
                    }
                }
            }
            if ($excelCleanupOk) {
                Write-Host ("Verified V10 Excel PID " + $excelPid + " closed normally.") -ForegroundColor Green
            } else {
                Write-Host ("Verified V10 Excel PID " + $excelPid + " did not close normally. It was NOT force-killed; state is retained.") -ForegroundColor Red
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

Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue
Write-Host "AI Cockpit V10 managed processes and verified managed Excel stopped." -ForegroundColor Green
