# Synthetic-only HTTP smoke test. Never requires a real Excel workbook,
# private market CSV, controller process, or OWNER machine.
$ErrorActionPreference='Stop'
$gateway=(Resolve-Path '.\downloads\AI_COCKPIT_GATEWAY_V10.ps1').Path
$scriptAsset=(Resolve-Path '.\v10_publication_status.js').Path
$base=Join-Path ([IO.Path]::GetTempPath()) ('v10_publication_smoke_'+[Guid]::NewGuid().ToString('N'))
$repoRoot=Join-Path $base 'repo'
$runtime=Join-Path $base 'runtime'
[void][IO.Directory]::CreateDirectory((Join-Path $repoRoot 'ms2_live'))
[void][IO.Directory]::CreateDirectory($runtime)
$listener=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,0)
$listener.Start()
$port=([Net.IPEndPoint]$listener.LocalEndpoint).Port
$listener.Stop()
$proc=$null
try {
    [IO.File]::WriteAllText((Join-Path $repoRoot 'index.html'),
        '<html><header><div>2026-09-25 10:41:50 JST</div></header><main>SYNTHETIC</main></html>')
    [IO.File]::Copy($scriptAsset,(Join-Path $repoRoot 'v10_publication_status.js'))
    [IO.File]::WriteAllText((Join-Path $runtime 'live_ms2.json'),
        '{"updated_at":"2026-01-01 09:00:00","price_source_status":"STALE","data_conflict":true,"real_submit_allowed":false}')
    $tokyo=[TimeZoneInfo]::FindSystemTimeZoneById('Tokyo Standard Time')
    $jst=[TimeZoneInfo]::ConvertTimeFromUtc([datetime]::UtcNow,$tokyo).ToString('yyyy-MM-ddTHH:mm:ss')+'+09:00'
    $watcher='{"schema_version":"kioxia-watcher-1.0","source":"Kioxia_RSS_Live_Watcher (Excel RSS)","observed_at_offset":"'+$jst+'","timestamp_timezone":"Asia/Tokyo"}'
    # Valid checkout decoy; the real Watcher is deployed under RuntimeDir.
    [IO.File]::WriteAllText((Join-Path $repoRoot 'ms2_live\kioxia_watcher_live.json'),$watcher)
    $runtimeWatcher=Join-Path $runtime 'kioxia_watcher_live.json'
    [IO.File]::WriteAllText($runtimeWatcher,'{"schema_version":"wrong"}')
    $shadowFile=Join-Path $runtime 'ai_shadow_status.json'
    $shadow='{"schema_version":"ai-shadow-supervisor-1","engine_pid":4242,"state":"RUNNING","updated_at":"'+([datetimeoffset]::UtcNow).ToString('o')+'","ui_independent":true,"real_submit_allowed":false,"resume_blocked":false}'
    [IO.File]::WriteAllText($shadowFile,$shadow)
    $args=@('-NoProfile','-NonInteractive','-File',('"' + $gateway + '"'),
        '-RepoRoot',('"' + $repoRoot + '"'),'-RuntimeDir',('"' + $runtime + '"'),
        '-Port',[string]$port)
    $proc=Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') -ArgumentList $args -PassThru -WindowStyle Hidden
    $baseUrl="http://127.0.0.1:$port"
    $resp=$null
    for($i=0;$i -lt 12;$i++){
        if($proc.HasExited){throw ('GATEWAY_PROCESS_EXITED_'+$proc.ExitCode)}
        try {
            $resp=Invoke-WebRequest -Uri "$baseUrl/health" -UseBasicParsing -TimeoutSec 1
            break
        } catch { Start-Sleep -Milliseconds 200 }
    }
    if($null -eq $resp){throw 'GATEWAY_HTTP_NOT_READY_WITHIN_15S'}
    $health=$resp.Content | ConvertFrom-Json
    if($health.status -ne 'ok'){throw 'GATEWAY_HEALTH_NOT_OK'}
    if($health.runtime.watcher_publication_state -ne 'WATCHER_IDENTITY_UNVERIFIED'){throw 'GATEWAY_USED_REPO_DECOY_OR_WRONG_RUNTIME'}
    [IO.File]::WriteAllText($runtimeWatcher,$watcher)
    $health=(Invoke-WebRequest -Uri "$baseUrl/health" -UseBasicParsing -TimeoutSec 5).Content | ConvertFrom-Json
    if($health.runtime.watcher_publication_state -ne 'PROCESS_UNVERIFIED'){throw 'UNVERIFIED_WATCHER_WAS_NOT_BLOCKED'}
    if($null -ne $health.runtime.watcher_observed_at_offset){throw 'UNVERIFIED_WATCHER_TIMESTAMP_EXPOSED'}
    if($health.runtime.brain_publication_state -ne 'UNKNOWN_NOT_PUBLISHED'){throw 'BRAIN_WAS_FABRICATED'}
    if($health.runtime.shadow_heartbeat_status -ne 'SHADOW_PROCESS_UNVERIFIED'){throw 'FAKE_SHADOW_PID_ACCEPTED'}
    if($null -ne $health.runtime.shadow_heartbeat_at){throw 'FAKE_SHADOW_HEARTBEAT_EXPOSED'}
    if($health.execution.real_submit_allowed -ne $false){throw 'REAL_ORDER_FLAG_UNSAFE'}
    if($health.runtime.fail_closed -ne $true){throw 'RUNTIME_FAIL_CLOSED_NOT_SET'}
    [IO.File]::Delete($runtimeWatcher)
    $health=(Invoke-WebRequest -Uri "$baseUrl/health" -UseBasicParsing -TimeoutSec 5).Content | ConvertFrom-Json
    if($health.runtime.watcher_publication_state -ne 'WATCHER_FILE_UNAVAILABLE'){throw 'GATEWAY_USED_REPO_DECOY_ON_MISSING_RUNTIME'}
    [IO.File]::Delete($shadowFile)
    $health=(Invoke-WebRequest -Uri "$baseUrl/health" -UseBasicParsing -TimeoutSec 5).Content | ConvertFrom-Json
    if($health.runtime.shadow_heartbeat_status -ne 'SHADOW_FILE_UNAVAILABLE'){throw 'SHADOW_MISSING_NOT_FAIL_CLOSED'}
    $page=Invoke-WebRequest -Uri "$baseUrl/" -UseBasicParsing -TimeoutSec 5
    if($page.Content -notmatch 'v10-static-snapshot-warning'){throw 'HISTORICAL_NOTICE_MISSING'}
    $asset=Invoke-WebRequest -Uri "$baseUrl/v10_publication_status.js" -UseBasicParsing -TimeoutSec 5
    if($asset.Content -notmatch 'summarizeHealth'){throw 'BROWSER_ASSET_NOT_SERVED'}
    Write-Output 'PASS: V10_GATEWAY_LOCAL_HTTP_SYNTHETIC'
}
finally {
    if($null -ne $proc){
        try {
            if(-not $proc.HasExited){
                Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
                [void]$proc.WaitForExit(4000)
            }
        } finally {$proc.Dispose()}
    }
    if([IO.Directory]::Exists($base)){[IO.Directory]::Delete($base,$true)}
}
