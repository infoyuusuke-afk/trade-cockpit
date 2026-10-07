param(
    [string]$StateRoot = "C:\AI_Cockpit_OneClick_Starter",
    [string]$BrainRoot = "C:\AI_Cockpit_Brain"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$logDir = Join-Path $StateRoot "Logs\Shutdown"
if (-not (Test-Path -LiteralPath $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}
$log = Join-Path $logDir ("shutdown_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".log")
Start-Transcript -LiteralPath $log -Force | Out-Null

function Write-Step([string]$Text, [ConsoleColor]$Color = [ConsoleColor]::Cyan) {
    Write-Host ("[" + (Get-Date -Format "HH:mm:ss") + "] " + $Text) -ForegroundColor $Color
}

function Test-Port([int]$Port, [int]$TimeoutMs = 300) {
    $client = New-Object Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) { return $false }
        $client.EndConnect($async)
        return $true
    } catch {
        return $false
    } finally {
        try { $client.Close() } catch {}
    }
}

function Wait-PortsClosed([int[]]$Ports, [int]$Seconds) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    do {
        $open = @($Ports | Where-Object { Test-Port $_ 250 })
        if ($open.Count -eq 0) { return $true }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    return $false
}

function Stop-BrainLane {
    $targets = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $cmd = [string]$_.CommandLine
        -not [string]::IsNullOrWhiteSpace($cmd) -and
        (
            $cmd -like "*C:\AI_Cockpit_Brain\downloads\AI_COCKPIT_GATEWAY_V9.ps1*" -or
            $cmd -like "*C:\AI_Cockpit_Brain\scripts\production_candidate_bridge.py*" -or
            $cmd -like "*C:\AI_Cockpit_Brain\scripts\ai_shadow_supervisor.py*"
        )
    })
    foreach ($proc in $targets) {
        try {
            Stop-Process -Id ([int]$proc.ProcessId) -Force -ErrorAction Stop
            Write-Step ("Stopped Brain lane PID " + $proc.ProcessId) DarkGray
        } catch {}
    }
}

function Get-State {
    $path = Join-Path $StateRoot "V9_CONTROLLER_STATE.json"
    if (-not (Test-Path -LiteralPath $path)) { return $null }
    try {
        return ([IO.File]::ReadAllText($path, [Text.Encoding]::UTF8) | ConvertFrom-Json)
    } catch {
        return $null
    }
}

function Test-ExpectedProcess([int]$Pid,[string]$Needle) {
    if ($Pid -le 0) { return $false }
    try {
        $p = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $Pid) -ErrorAction Stop
        if ($null -eq $p) { return $false }
        $cmd = [string]$p.CommandLine
        return (-not [string]::IsNullOrWhiteSpace($cmd) -and $cmd -like ("*" + $Needle + "*"))
    } catch {
        return $false
    }
}

function Stop-OwnedFallback($State) {
    $pairs = @(
        @("watcher_pid","Kioxia_RSS_Live_Watcher.ps1"),
        @("heartbeat_pid","Kioxia_Safety_Heartbeat.ps1"),
        @("collector_pid","MS2_RSS_100_Collector.ps1"),
        @("gateway_pid","AI_COCKPIT_GATEWAY_V9.ps1"),
        @("voice_bridge_pid","AI_COCKPIT_VOICE_BRIDGE_V9.ps1"),
        @("sbv2_pid","server_fastapi.py"),
        @("shadow_supervisor_pid","ai_shadow_supervisor.py"),
        @("controller_pid","AI_COCKPIT_CONTROLLER_V9.ps1")
    )
    foreach ($pair in $pairs) {
        $name = [string]$pair[0]
        $needle = [string]$pair[1]
        $prop = $State.PSObject.Properties[$name]
        if ($null -eq $prop) { continue }
        $pidValue = 0
        try { $pidValue = [int]$prop.Value } catch { $pidValue = 0 }
        if ($pidValue -le 0) { continue }
        if (Test-ExpectedProcess $pidValue $needle) {
            try {
                Stop-Process -Id $pidValue -Force -ErrorAction Stop
                Write-Step ("Fallback stopped owned " + $name + " PID " + $pidValue) Yellow
            } catch {}
        }
    }
}

try {
    Write-Step "AI Cockpit validated shutdown beginning." Green

    # Stop the parallel Brain lane first. It is read-only and independent.
    Stop-BrainLane

    $state = Get-State
    if ($null -ne $state) {
        $excelPid = 0
        try { $excelPid = [int]$state.excel_pid } catch { $excelPid = 0 }
        $runtime = [string]$state.runtime_dir
        $book = if ([string]::IsNullOrWhiteSpace($runtime)) { "" } else { Join-Path $runtime "Kioxia_MS2_RSS_Live_Signals.xlsx" }

        if ($excelPid -gt 0) {
            try {
                $excel = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $excelPid) -ErrorAction Stop
            } catch {
                $excel = $null
            }

            if ($null -ne $excel) {
                $cmd = [string]$excel.CommandLine
                $safe = (
                    [string]$excel.Name -eq "EXCEL.EXE" -and
                    $cmd -match '(?i)(^|\s)/x(\s|$)' -and
                    -not [string]::IsNullOrWhiteSpace($book) -and
                    $cmd -like ("*" + $book + "*")
                )
                if (-not $safe) {
                    throw "EXCEL_SHUTDOWN_BLOCKED: recorded Excel PID is not the isolated cockpit workbook."
                }

                Write-Step ("Closing isolated cockpit Excel PID " + $excelPid + "...") Yellow
                Stop-Process -Id $excelPid -Force -ErrorAction Stop
            }
        }

        # The Controller is designed to detect workbook closure and stop
        # Watcher/Heartbeat/Collector/Gateway/Voice/Shadow itself.
        if (-not (Wait-PortsClosed @(28580,28581,28582,28583) 20)) {
            Write-Step "Controller did not finish shutdown in 20s; using exact owned-PID fallback." Yellow
            Stop-OwnedFallback $state
        }
    }

    # Re-run Brain stop in case a child was still exiting.
    Stop-BrainLane

    $sidecar = $null
    try {
        $manifestPath = Join-Path $StateRoot "V9_RUNTIME.json"
        if (Test-Path -LiteralPath $manifestPath) {
            $manifest = [IO.File]::ReadAllText($manifestPath, [Text.Encoding]::UTF8) | ConvertFrom-Json
            $runtimeDir = [string]$manifest.runtime_dir
            if (-not [string]::IsNullOrWhiteSpace($runtimeDir)) {
                $sidecar = Join-Path $runtimeDir "brain_candidate_live.json"
                Remove-Item -LiteralPath $sidecar -Force -ErrorAction SilentlyContinue
            }
        }
    } catch {}

    $closed = Wait-PortsClosed @(28580,28581,28582,28583,28584) 10
    if (-not $closed) {
        $stillOpen = @(28580,28581,28582,28583,28584 | Where-Object { Test-Port $_ 250 })
        throw ("PORTS_STILL_OPEN=" + ($stillOpen -join ","))
    }

    Write-Host ""
    Write-Host "==============================================" -ForegroundColor DarkGreen
    Write-Host " AI COCKPIT SHUTDOWN = PASS" -ForegroundColor Green
    Write-Host "==============================================" -ForegroundColor DarkGreen
    Write-Host "28580-28584=CLOSED" -ForegroundColor Green
    Write-Host "MarketSpeed II=UNTOUCHED" -ForegroundColor Green
    Write-Host "real_submit_allowed remains false." -ForegroundColor Green
    Write-Host ("SHUTDOWN_LOG=" + $log) -ForegroundColor DarkGray
}
catch {
    Write-Host ""
    Write-Host "==============================================" -ForegroundColor Red
    Write-Host " AI COCKPIT SHUTDOWN = CHECK REQUIRED" -ForegroundColor Red
    Write-Host "==============================================" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Yellow
    Write-Host "MarketSpeed II was not intentionally closed." -ForegroundColor Yellow
    Write-Host "real_submit_allowed remains false." -ForegroundColor Yellow
    Write-Host ("SHUTDOWN_LOG=" + $log) -ForegroundColor DarkGray
    [Environment]::ExitCode = 1
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
}
