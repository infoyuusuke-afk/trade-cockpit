param(
    [string]$Root = "C:\AI_Cockpit_OneClick_Starter"
)

# Stops only the PIDs this Controller (AI_COCKPIT_CONTROLLER_V9.ps1) itself
# recorded in V9_CONTROLLER_STATE.json. Never scans the system process
# table by name/window-title pattern, so it cannot touch an unrelated
# Excel session or PowerShell window. Excel is stopped only if its PID
# still matches the tracked window title, same rule the Controller's own
# supervision loop uses.

$ErrorActionPreference = "SilentlyContinue"
$StateFile = Join-Path $Root "V9_CONTROLLER_STATE.json"

if (-not (Test-Path -LiteralPath $StateFile)) {
    Write-Host "No V9 state file found - nothing to stop." -ForegroundColor DarkGray
    exit 0
}

# Get-Content -Raw does not reliably treat a BOM-less UTF-8 file as UTF-8
# under Windows PowerShell 5.1 (can fall back to the system ANSI codepage,
# corrupting Japanese paths on read-back) - read explicitly as UTF-8.
$state = [IO.File]::ReadAllText($StateFile, [Text.Encoding]::UTF8) | ConvertFrom-Json

function Test-OwnedPidIdentity([string]$Field,[int]$ProcessId) {
    $expected = switch ($Field) {
        "watcher_pid"      { "Kioxia_RSS_Live_Watcher.ps1" }
        "heartbeat_pid"    { "Kioxia_Safety_Heartbeat.ps1" }
        "collector_pid"    { "MS2_RSS_100_Collector.ps1" }
        "gateway_pid"      { "AI_COCKPIT_GATEWAY_V9.ps1" }
        "voice_bridge_pid" { "AI_COCKPIT_VOICE_BRIDGE_V9.ps1" }
        "sbv2_pid"         { "server_fastapi.py" }
        "controller_pid"   { "AI_COCKPIT_CONTROLLER_V9.ps1" }
        default            { "" }
    }
    if ([string]::IsNullOrWhiteSpace($expected)) { return $false }
    try {
        $wmi = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $ProcessId) -ErrorAction SilentlyContinue
        $cmd = if ($null -ne $wmi) { [string]$wmi.CommandLine } else { "" }
        return (-not [string]::IsNullOrWhiteSpace($cmd) -and $cmd -match [regex]::Escape($expected))
    } catch { return $false }
}

foreach ($field in @("watcher_pid", "heartbeat_pid", "collector_pid", "gateway_pid", "voice_bridge_pid", "sbv2_pid", "controller_pid")) {
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
if ($excelPid -gt 0 -and -not [string]::IsNullOrWhiteSpace($workbookName)) {
    $xp = Get-Process -Id $excelPid -ErrorAction SilentlyContinue
    if ($null -ne $xp -and $xp.MainWindowTitle -like ("*" + $workbookName + "*")) {
        Write-Host ("Excel PID " + $excelPid + " still shows the managed workbook - leaving it open (close it by hand if you want it closed).") -ForegroundColor Yellow
    }
}

Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue
Write-Host "AI Cockpit V9 managed processes stopped." -ForegroundColor Green
