$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
. (Join-Path $repo "scripts\ms2_ps_python_bridge_producer.ps1")

$failures = @()
function Assert-Check([bool]$Condition, [string]$Name) {
    if ($Condition) {
        Write-Host "PASS $Name"
    } else {
        Write-Host "FAIL $Name"
        $script:failures += $Name
    }
}

function Read-ProcessLine($Process, [int]$TimeoutMs) {
    $task = $Process.StandardOutput.ReadLineAsync()
    if (-not $task.Wait($TimeoutMs)) { throw "STDOUT_TIMEOUT" }
    return $task.Result
}

function Start-Hold([string]$Preset) {
    $name = "b" + ([guid]::NewGuid().ToString("N").Substring(0, 11))
    $start = New-Object System.Diagnostics.ProcessStartInfo
    $start.FileName = "python"
    $start.Arguments = "-m scripts.ms2_ps_python_bridge hold --name $name --preset $Preset --timeout 20"
    $start.WorkingDirectory = $repo
    $start.RedirectStandardOutput = $true
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $start
    [void]$proc.Start()
    return @{ Process = $proc; Name = $name }
}

function Invoke-Probe([string]$Exe, [string]$Arguments, [int]$TimeoutMs) {
    if ($Exe -match '^[A-Za-z]:\\' -and -not (Test-Path -LiteralPath $Exe)) {
        return @{ Status = "PYTHON_ABSENT"; Attempts = 1; Retry = $false }
    }
    $start = New-Object System.Diagnostics.ProcessStartInfo
    $start.FileName = $Exe
    $start.Arguments = $Arguments
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $start
    try { [void]$proc.Start() } catch { return @{ Status = "PYTHON_START_FAILED"; Attempts = 1; Retry = $false } }
    if (-not $proc.WaitForExit($TimeoutMs)) {
        try { $proc.Kill() } catch {}
        $proc.WaitForExit(2000) | Out-Null
        return @{ Status = "PYTHON_UNRESPONSIVE"; Attempts = 1; Retry = $false }
    }
    if ($proc.ExitCode -ne 0) { return @{ Status = "PYTHON_START_FAILED"; Attempts = 1; Retry = $false } }
    return @{ Status = "PYTHON_PRESENT"; Attempts = 1; Retry = $false }
}

$fixturePath = Join-Path $env:TEMP ("ms2-bridge-" + [guid]::NewGuid().ToString("N") + ".json")
$fixtureText = @'
{
  "symbol": "285A.T",
  "market": "TSE",
  "poll_seq": 3,
  "source": "offline-harness",
  "data_freshness": "STALE",
  "watcher_observed_at": "2026-10-14T01:00:00.000+09:00",
  "levels": [
    {
      "Level": 1,
      "BidPrice": 100.0,
      "AskPrice": 101.0,
      "BidQty": null,
      "AskQty": 0,
      "read_at": "2026-10-14T01:00:00.010+09:00"
    },
    {
      "Level": 2,
      "BidPrice": 100.0,
      "AskPrice": 101.0,
      "read_at": "2026-10-14T01:00:00.050+09:00"
    }
  ],
  "gap": {
    "window_size": 300,
    "overlap_with_prev": 0,
    "prev_poll_nonempty": true,
    "new_appended": 20,
    "suspected_gap": true
  }
}
'@
[System.IO.File]::WriteAllText($fixturePath, $fixtureText)
$capture = @{
    symbol = "285A.T"
    market = "TSE"
    poll_seq = [int]3
    source = "offline-harness"
    data_freshness = "STALE"
    watcher_observed_at = "2026-10-14T01:00:00.000+09:00"
    levels = @(
        @{
            Level = [int]1
            BidPrice = [double]100.0
            AskPrice = [double]101.0
            BidQty = $null
            AskQty = [int]0
            read_at = "2026-10-14T01:00:00.010+09:00"
        },
        @{
            Level = [int]2
            BidPrice = [double]100.0
            AskPrice = [double]101.0
            read_at = "2026-10-14T01:00:00.050+09:00"
        }
    )
    gap = @{
        window_size = [int]300
        overlap_with_prev = [int]0
        prev_poll_nonempty = $true
        new_appended = [int]20
        suspected_gap = $true
    }
}

$huge = "x" * 1000000
$hugeCapture = @{ symbol = $huge; market = "TSE"; poll_seq = [int]1; source = "offline-harness"; levels = @() }
$clock = [System.Diagnostics.Stopwatch]::StartNew()
$refused = ConvertTo-Ms2PsBridgeRecord $hugeCapture
$clock.Stop()
$hugeMs = $clock.Elapsed.TotalMilliseconds
Write-Host ("huge_symbol reason=" + $refused["Reason"] + " ms=" + [math]::Round($hugeMs, 3))
Assert-Check ($refused["Reason"] -eq "SYMBOL_ABSENT") "huge_symbol_reason"
Assert-Check ($hugeMs -lt 200) "huge_symbol_bounded"

$packed = ConvertTo-Ms2PsBridgeRecord $capture
$pythonHex = (& python -m scripts.ms2_ps_python_bridge pack-fixture --fixture $fixturePath).Trim()
$localHex = -join ($packed.Record | ForEach-Object { $_.ToString("x2") })
Assert-Check ($packed.Ok -and $localHex -eq $pythonHex) "pack_matches_python_record"
Remove-Item -LiteralPath $fixturePath -Force

$absent = Invoke-Probe "C:\no\such\ms2-bridge-python.exe" "" 500
Assert-Check ($absent.Status -eq "PYTHON_ABSENT" -and $absent.Attempts -eq 1 -and -not $absent.Retry) "python_absent"

$failed = Invoke-Probe "python" '-c "import sys; raise SystemExit(9)"' 5000
Assert-Check ($failed.Status -eq "PYTHON_START_FAILED" -and $failed.Attempts -eq 1 -and -not $failed.Retry) "python_start_failed"

$hung = Invoke-Probe "python" '-c "import time; time.sleep(30)"' 400
Assert-Check ($hung.Status -eq "PYTHON_UNRESPONSIVE" -and $hung.Attempts -eq 1 -and -not $hung.Retry) "python_unresponsive"

$forkText = (& python -c "import multiprocessing as m`ntry:`n m.get_context('fork')`n print('FORK_AVAILABLE')`nexcept ValueError:`n print('FORK_ABSENT')").Trim()
Assert-Check ($forkText -eq "FORK_ABSENT") "windows_spawn_only"

$contract = (& python -m scripts.ms2_ps_python_bridge contract) | ConvertFrom-Json
Assert-Check ($contract.durable_writer_on_windows -eq "OFFLINE_IMPLEMENTED") "offline_durable_writer_implemented"
Assert-Check ($contract.durable_writer_via_handoff_worker -eq "OFFLINE_IMPLEMENTED") "handoff_durable_writer_blocked"
Assert-Check ($null -eq $contract.durable_writer_blocker) "handoff_blocker_exact"
Assert-Check ($contract.durable_writer_owner_pc -eq "NOT_VERIFIED") "durable_owner_pc_not_verified"
Assert-Check ($contract.power_loss_durability -eq "NOT_VERIFIED") "power_loss_not_verified"
Assert-Check ($contract.windows_sleep_resume -eq "NOT_VERIFIED") "sleep_resume_not_verified"
Assert-Check ($contract.windows_owner_pc -eq "NOT_VERIFIED") "owner_pc_not_verified"
Assert-Check ($contract.live_watcher_connection -eq "P0_BLOCKED") "watcher_connection_blocked"
Assert-Check ($contract.real_submit_allowed -eq $false) "real_submit_false"
Assert-Check ($contract.extra_com_reads -eq 0) "extra_com_zero"

$holders = @()
try {
    $normal = Start-Hold "empty"
    $holders += $normal.Process
    $ready = Read-ProcessLine $normal.Process 15000
    Assert-Check ($ready -eq ("READY " + $normal.Name + " 20480")) "mapping_ready"
    $second = & python -c "from multiprocessing import shared_memory`nimport sys`ntry:`n shared_memory.SharedMemory(name='$($normal.Name)', create=True, size=20480)`nexcept FileExistsError:`n raise SystemExit(2)`nraise SystemExit(0)"
    Assert-Check ($LASTEXITCODE -eq 2) "duplicate_mapping_refused"
    $opened = Open-Ms2PsBridge -MapName $normal.Name -Size 20480
    Write-Host ("ATTACHED_AS attempts=" + $opened.Attempts + " name=" + $opened.OpenedAs)
    Assert-Check ($opened.Ok -and $opened.Retry -eq $false -and $opened.Attempts -le 3) "attach_existing_mapping"
    $submitted = Submit-Ms2PsBridgeRecord -Session $opened -Record $packed.Record
    Write-Host ("submit status=" + $submitted.Status + " ms=" + [math]::Round($submitted.ElapsedMs, 3))
    Assert-Check ($submitted.Status -eq "ACCEPTED" -and $submitted.ComReadsAdded -eq 0 -and $submitted.ElapsedMs -lt 200) "submit_accepted"
    Close-Ms2PsBridge $opened
    $resultLine = Read-ProcessLine $normal.Process 15000
    $result = ($resultLine.Substring(7)) | ConvertFrom-Json
    Assert-Check ($result.symbol -eq "285A.T" -and $result.poll_seq -eq 3 -and $result.sequence_basis -eq "POLL" -and $result.snapshot_atomic -eq $false) "roundtrip_fields"
    Assert-Check ($null -eq $result.event_time -and $null -eq $result.bid_qty -and $result.ask_qty -eq 0 -and $result.suspected_gap -eq $true -and $result.freshness -eq "STALE") "roundtrip_nulls_and_gap"
    if (-not $normal.Process.WaitForExit(5000)) { $normal.Process.Kill() }
    $after = Open-Ms2PsBridge -MapName $normal.Name -Size 20480
    Assert-Check (-not $after.Ok -and $after.Reason -eq "ATTACH_FAILED" -and -not $after.Retry) "mapping_released"

    $full = Start-Hold "full"
    $holders += $full.Process
    $fullReady = Read-ProcessLine $full.Process 15000
    Assert-Check ($fullReady.StartsWith("READY ")) "full_ready"
    $fullOpen = Open-Ms2PsBridge -MapName $full.Name -Size 20480
    $fullSubmit = Submit-Ms2PsBridgeRecord -Session $fullOpen -Record $packed.Record
    Assert-Check ($fullSubmit.Status -eq "DROPPED" -and $fullSubmit.Reason -eq "DROP_NEWEST") "queue_full_drops_newest"
    Close-Ms2PsBridge $fullOpen
    $fullResult = ((Read-ProcessLine $full.Process 15000).Substring(7)) | ConvertFrom-Json
    Assert-Check ($fullResult.dropped -eq 1 -and $fullResult.write -eq 8) "queue_full_counter"

    $killed = Start-Hold "kill"
    $holders += $killed.Process
    Read-ProcessLine $killed.Process 15000 | Out-Null
    $killOpen = Open-Ms2PsBridge -MapName $killed.Name -Size 20480
    $killSubmit = Submit-Ms2PsBridgeRecord -Session $killOpen -Record $packed.Record
    Assert-Check ($killSubmit.Status -eq "KILL_SWITCH" -and $killSubmit.ElapsedMs -lt 200) "kill_switch"
    Close-Ms2PsBridge $killOpen
    $killResult = ((Read-ProcessLine $killed.Process 15000).Substring(7)) | ConvertFrom-Json
    Assert-Check ($killResult.kill_drops -eq 1 -and $killResult.write -eq 0) "kill_switch_counter"
} finally {
    foreach ($proc in $holders) {
        if ($proc -and -not $proc.HasExited) {
            try { $proc.Kill() } catch {}
        }
    }
}

Write-Host "NOT_VERIFIED windows_sleep_resume"
Write-Host "NOT_VERIFIED windows_owner_pc"
Write-Host "OFFLINE_IMPLEMENTED durable_writer_on_windows"
Write-Host "OFFLINE_IMPLEMENTED durable_writer_via_handoff_worker"
Write-Host "P0_BLOCKED live_watcher_connection"
if ($failures.Count -gt 0) {
    Write-Host ("FAILED " + ($failures -join ","))
    exit 1
}
Write-Host "WINDOWS_RUNNER_SYNTHETIC_PASS"
exit 0
