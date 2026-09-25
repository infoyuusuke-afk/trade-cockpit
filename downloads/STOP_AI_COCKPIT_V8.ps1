param(
    [string]$Root = "C:\AI_Cockpit_OneClick_Starter"
)

# Stops only the PIDs this Controller (AI_COCKPIT_CONTROLLER_V8.ps1) itself
# recorded in V8_CONTROLLER_STATE.json. Never scans the system process
# table by name/window-title pattern, so it cannot touch an unrelated
# Excel session or PowerShell window. Excel is stopped only if its PID
# still matches the tracked window title, same rule the Controller's own
# supervision loop uses.

$ErrorActionPreference = "SilentlyContinue"
$StateFile = Join-Path $Root "V8_CONTROLLER_STATE.json"

if (-not (Test-Path -LiteralPath $StateFile)) {
    Write-Host "No V8 state file found - nothing to stop." -ForegroundColor DarkGray
    exit 0
}

# Get-Content -Raw does not reliably treat a BOM-less UTF-8 file as UTF-8
# under Windows PowerShell 5.1 (can fall back to the system ANSI codepage,
# corrupting Japanese paths on read-back) - read explicitly as UTF-8.
$state = [IO.File]::ReadAllText($StateFile, [Text.Encoding]::UTF8) | ConvertFrom-Json

foreach ($field in @("watcher_pid", "heartbeat_pid", "collector_pid", "gateway_pid")) {
    $val = $state.PSObject.Properties[$field]
    if ($null -eq $val -or [int]$val.Value -le 0) { continue }
    $procId = [int]$val.Value
    $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if ($null -ne $p) {
        try { Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue } catch {}
        Write-Host ("Stopped " + $field + " (PID " + $procId + ")") -ForegroundColor Green
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
Write-Host "AI Cockpit V8 managed processes stopped." -ForegroundColor Green
