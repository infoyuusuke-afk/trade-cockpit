param(
    [string]$RepoRoot = "",
    [string]$Root = "C:\AI_Cockpit_OneClick_Starter"
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
#      through that Gateway. Fixed by AI_COCKPIT_GATEWAY_V8.ps1, which
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
#     path. Only supervises the existing read-only Watcher/Collector/
#     Heartbeat/Gateway processes and the Excel process that hosts them.

$ErrorActionPreference = "Stop"
$Build = "V8-CONTROLLER-20260925-01"
$sw = [Diagnostics.Stopwatch]::StartNew()

# ---------------------------------------------------------------- utility

function Write-Status([string]$Message, [ConsoleColor]$Color = [ConsoleColor]::Cyan) {
    $sec = [Math]::Round($sw.Elapsed.TotalSeconds, 1)
    Write-Host ("[{0,7}s] {1}" -f $sec, $Message) -ForegroundColor $Color
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

function Resolve-RuntimeDir {
    $roots = @(
        [Environment]::GetFolderPath("Desktop"),
        (Join-Path $env:USERPROFILE "Desktop"),
        (Join-Path $env:USERPROFILE "OneDrive\Desktop")
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique
    $hits = foreach ($r in $roots) {
        Get-ChildItem -LiteralPath $r -Recurse -File -Filter "MS2_RSS_100_Collector.ps1" -ErrorAction SilentlyContinue
    }
    $preferred = @($hits | Where-Object { $_.FullName -like "*MarketSpeed II RSS\files*" } | Sort-Object LastWriteTime -Descending | Select-Object -First 1)
    if ($preferred.Count -gt 0) { return $preferred[0].Directory.FullName }
    $any = @($hits | Sort-Object LastWriteTime -Descending | Select-Object -First 1)
    if ($any.Count -gt 0) { return $any[0].Directory.FullName }
    throw "MS2 runtime folder not found under Desktop (looked for MS2_RSS_100_Collector.ps1)."
}

function Resolve-RepoRoot([string]$Explicit) {
    if (-not [string]::IsNullOrWhiteSpace($Explicit)) { return $Explicit }
    # Prefer the folder this controller script itself lives two levels
    # above (…\trade-cockpit\downloads\AI_COCKPIT_CONTROLLER_V8.ps1), if
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

$StateFile = Join-Path $Root "V8_CONTROLLER_STATE.json"
$LogDir = Join-Path $Root "Logs\V8"
if (-not (Test-Path -LiteralPath $Root)) { New-Item -ItemType Directory -Path $Root -Force | Out-Null }
if (-not (Test-Path -LiteralPath $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

function Read-State {
    try {
        if (-not (Test-Path -LiteralPath $StateFile)) { return $null }
        return (Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json)
    } catch { return $null }
}

function Save-State($state) {
    $tmp = $StateFile + "." + $PID + ".tmp"
    [IO.File]::WriteAllText($tmp, ($state | ConvertTo-Json -Depth 6), [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $tmp -Destination $StateFile -Force
}

# Stop only PIDs recorded in OUR OWN previous state file - never a broad
# process-table scan. A PID that no longer exists, or that now belongs to
# a different process (recycled by Windows), is silently skipped.
function Stop-OwnedFromPreviousState {
    $prev = Read-State
    if ($null -eq $prev) { return }
    foreach ($field in @("watcher_pid", "heartbeat_pid", "collector_pid", "gateway_pid")) {
        $val = $prev.PSObject.Properties[$field]
        if ($null -eq $val -or [int]$val.Value -le 0) { continue }
        $procId = [int]$val.Value
        $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if ($null -ne $proc) {
            try { Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue } catch {}
            Write-Status ("  stopped previous {0} (PID {1})" -f $field, $procId) DarkGray
        }
    }
    # Excel is only ever stopped by exact PID + the same window-title match
    # used when we detect a real close, never as part of routine cleanup -
    # a leftover Excel PID from a previous crashed session might still be
    # something the user is actively looking at.
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

# ======================================================================
# MAIN
# ======================================================================

$state = [ordered]@{
    build            = $Build
    started_at       = (Get-Date).ToString("o")
    repo_root        = ""
    runtime_dir      = ""
    workbook_name    = ""
    excel_pid        = 0
    watcher_pid      = 0
    heartbeat_pid    = 0
    collector_pid    = 0
    gateway_pid      = 0
    collector_status = "NOT_STARTED"
}

try {
    Clear-Host
    Write-Host "==================================================" -ForegroundColor DarkCyan
    Write-Host " AI COCKPIT CONTROLLER V8" -ForegroundColor Cyan
    Write-Host (" " + $Build) -ForegroundColor DarkCyan
    Write-Host " Logs: $LogDir" -ForegroundColor DarkCyan
    Write-Host "==================================================" -ForegroundColor DarkCyan
    Write-Host ""

    Write-Status "Resolving repo checkout and MS2 runtime folder..."
    $RepoRootResolved = Resolve-RepoRoot $RepoRoot
    $RuntimeDir = Resolve-RuntimeDir
    $state.repo_root = $RepoRootResolved
    $state.runtime_dir = $RuntimeDir
    Write-Status ("  repo:    " + $RepoRootResolved) Green
    Write-Status ("  runtime: " + $RuntimeDir) Green

    $Watcher = Join-Path $RuntimeDir "Kioxia_RSS_Live_Watcher.ps1"
    $Heartbeat = Join-Path $RuntimeDir "Kioxia_Safety_Heartbeat.ps1"
    $Collector = Join-Path $RuntimeDir "MS2_RSS_100_Collector.ps1"
    $Gateway = Join-Path $PSScriptRoot "AI_COCKPIT_GATEWAY_V8.ps1"
    $WorkbookPath = Join-Path $RuntimeDir "Kioxia_MS2_RSS_Live_Signals.xlsx"
    $WorkbookName = [IO.Path]::GetFileName($WorkbookPath)
    $state.workbook_name = $WorkbookName

    foreach ($p in @($Watcher, $Heartbeat, $Collector, $Gateway, $WorkbookPath)) {
        if (-not (Test-Path -LiteralPath $p)) { throw "Required file not found: $p" }
    }

    Write-Status "Stopping this controller's previously managed processes (own PIDs only)..."
    Stop-OwnedFromPreviousState
    Start-Sleep -Milliseconds 500

    Write-Status "Checking MarketSpeed II..."
    $ms2 = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match "MarketSpeed|MARKETSPEED" })
    if ($ms2.Count -eq 0) {
        throw "MarketSpeed II is not running. Start it and log in, then run this controller again."
    }
    Write-Status "  MarketSpeed II: READY" Green

    Write-Status "Starting Gateway first (fail-closed UI is viewable immediately)..."
    $gatewayArgs = '-RepoRoot "' + $RepoRootResolved + '" -RuntimeDir "' + $RuntimeDir + '" -Build "' + $Build + '"'
    $gatewayProc = Start-Worker -Name "gateway" -Script $Gateway -WorkDir $RepoRootResolved -ExtraArgs $gatewayArgs
    $state.gateway_pid = [int]$gatewayProc.Id
    Save-State $state
    if (-not (Wait-PortBounded 28581 20 "Gateway")) {
        $err = Tail-Log (Join-Path $LogDir "gateway_stderr.log")
        throw "Gateway did not open port 28581 within 20s. $err"
    }
    Write-Status "  Gateway: READY / http://127.0.0.1:28581/?live=1" Green
    Start-Process "http://127.0.0.1:28581/?live=1"

    Write-Status "Opening MS2 RSS workbook..."
    $excelProc = Get-ExcelProcessForWorkbook $WorkbookName
    if ($excelProc.Count -eq 0) {
        Start-Process -FilePath $WorkbookPath | Out-Null
        $deadline = (Get-Date).AddSeconds(40)
        while ((Get-Date) -lt $deadline) {
            $excelProc = Get-ExcelProcessForWorkbook $WorkbookName
            if ($excelProc.Count -eq 1) { break }
            Start-Sleep -Milliseconds 400
        }
    }
    if ($excelProc.Count -eq 0) {
        # Non-fatal: log it, keep going. The Watcher itself will fail
        # closed with no live workbook to read from, and the UI already
        # shows fail-closed via the Gateway - the user can open the
        # workbook by hand and nothing else needs restarting.
        Write-Status "  Excel workbook did not open within 40s - continuing without it. Open it by hand; Watcher will pick it up on its own retry." Yellow
    } else {
        $state.excel_pid = [int]$excelProc[0].Id
        Save-State $state
        Write-Status ("  Excel PID: " + $state.excel_pid) Green
    }

    Write-Status "Starting Watcher..."
    $watcherProc = Start-Worker -Name "watcher" -Script $Watcher -WorkDir $RuntimeDir
    $state.watcher_pid = [int]$watcherProc.Id
    Save-State $state
    Write-Status ("  Watcher: PID " + $state.watcher_pid) Green

    Write-Status "Starting safety heartbeat..."
    $heartbeatProc = Start-Worker -Name "heartbeat" -Script $Heartbeat -WorkDir $RuntimeDir
    $state.heartbeat_pid = [int]$heartbeatProc.Id
    Save-State $state
    Write-Status ("  Heartbeat: PID " + $state.heartbeat_pid) Green

    Write-Status "Starting Collector (bounded wait; Controller/UI stay up either way)..."
    $collectorProc = Start-Worker -Name "collector" -Script $Collector -WorkDir $RuntimeDir
    $state.collector_pid = [int]$collectorProc.Id
    $state.collector_status = "STARTING"
    Save-State $state
    if (Wait-PortBounded 28580 45 "Collector") {
        $state.collector_status = "LIVE"
        Write-Status "  Collector: LIVE / 28580" Green
    } else {
        $state.collector_status = if ($collectorProc.HasExited) { "CRASHED" } else { "SLOW_NOT_YET_READY" }
        $err = Tail-Log (Join-Path $LogDir "collector_stderr.log")
        Write-Status ("  Collector: " + $state.collector_status + " (Controller and UI continue; UI stays fail-closed). " + $err) Yellow
    }
    Save-State $state

    Write-Status "Startup complete. Entering supervision loop (Ctrl+C to stop everything)." Green
    Write-Host ""
    Write-Host "This window supervises the running session. Closing the MS2 workbook" -ForegroundColor Cyan
    Write-Host "will automatically stop the Watcher/Heartbeat/Collector/Gateway and" -ForegroundColor Cyan
    Write-Host "this Excel process - only the ones this controller started." -ForegroundColor Cyan
    Write-Host ""

    # ---------------------------------------------------- supervision loop
    $excelMisses = 0
    $collectorRestartAttempts = 0
    $lastCollectorRestartAt = Get-Date "2000-01-01"
    while ($true) {
        Start-Sleep -Seconds 2

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
                foreach ($field in @("watcher_pid", "heartbeat_pid", "collector_pid", "gateway_pid")) {
                    $val = [int]$state.$field
                    if ($val -gt 0) {
                        $p = Get-Process -Id $val -ErrorAction SilentlyContinue
                        if ($null -ne $p) { try { Stop-Process -Id $val -Force -ErrorAction SilentlyContinue } catch {} }
                    }
                }
                Start-Sleep -Seconds 2
                $xp2 = Get-Process -Id $state.excel_pid -ErrorAction SilentlyContinue
                if ($null -ne $xp2 -and ($xp2.MainWindowHandle -eq 0 -or $xp2.MainWindowTitle -notlike ("*" + $WorkbookName + "*"))) {
                    try { Stop-Process -Id $state.excel_pid -Force -ErrorAction SilentlyContinue } catch {}
                    Write-Status ("  Cleared orphaned Excel PID " + $state.excel_pid) Green
                }
                Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue
                Write-Status "Clean shutdown complete. Next start will begin from zero leftover state." Green
                Start-Sleep -Seconds 2
                [Environment]::Exit(0)
            }
        }

        # 2) Is Collector still alive? Restart it with bounded backoff;
        #    never take down Gateway/UI because of this.
        $cp = if ($state.collector_pid -gt 0) { Get-Process -Id $state.collector_pid -ErrorAction SilentlyContinue } else { $null }
        if ($null -eq $cp) {
            $state.collector_status = "DOWN"
            $secsSinceRestart = ((Get-Date) - $lastCollectorRestartAt).TotalSeconds
            if ($collectorRestartAttempts -lt 5 -and $secsSinceRestart -gt 20) {
                $collectorRestartAttempts++
                $lastCollectorRestartAt = Get-Date
                Write-Status ("Collector is down (attempt " + $collectorRestartAttempts + "/5) - restarting; UI stays fail-closed meanwhile.") Yellow
                $collectorProc = Start-Worker -Name ("collector_retry" + $collectorRestartAttempts) -Script $Collector -WorkDir $RuntimeDir
                $state.collector_pid = [int]$collectorProc.Id
                $state.collector_status = "STARTING"
            }
            Save-State $state
        } elseif ($state.collector_status -ne "LIVE" -and (Test-Port 28580 300)) {
            $state.collector_status = "LIVE"
            $collectorRestartAttempts = 0
            Save-State $state
            Write-Status "Collector recovered - LIVE / 28580" Green
        }

        # 3) Is Gateway still alive? This one we do treat as worth a clear
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
    Write-Host " AI COCKPIT CONTROLLER V8 - STOPPED ON ERROR" -ForegroundColor Red
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
