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
$job=$null
try {
    [IO.File]::WriteAllText((Join-Path $repoRoot 'index.html'),
        '<html><header><div>2026-09-25 10:41:50 JST</div></header><main>SYNTHETIC</main></html>')
    [IO.File]::Copy($scriptAsset,(Join-Path $repoRoot 'v10_publication_status.js'))
    [IO.File]::WriteAllText((Join-Path $runtime 'live_ms2.json'),
        '{"updated_at":"2026-01-01 09:00:00","price_source_status":"STALE","data_conflict":true,"real_submit_allowed":false}')
    $tokyo=[TimeZoneInfo]::FindSystemTimeZoneById('Tokyo Standard Time')
    $jst=[TimeZoneInfo]::ConvertTimeFromUtc([datetime]::UtcNow,$tokyo).ToString('yyyy-MM-ddTHH:mm:ss')+'+09:00'
    $watcher='{"schema_version":"kioxia-watcher-1.0","source":"Kioxia_RSS_Live_Watcher (Excel RSS)","observed_at_offset":"'+$jst+'","timestamp_timezone":"Asia/Tokyo"}'
    [IO.File]::WriteAllText((Join-Path $repoRoot 'ms2_live\kioxia_watcher_live.json'),$watcher)
    $job=Start-Job -ScriptBlock {
        param($path,$rr,$rd,$p)
        & $path -RepoRoot $rr -RuntimeDir $rd -Port $p
    } -ArgumentList $gateway,$repoRoot,$runtime,$port
    $baseUrl="http://127.0.0.1:$port"
    $resp=$null
    for($i=0;$i -lt 30;$i++){
        if($job.State -in @('Failed','Completed','Stopped')){break}
        try {
            $resp=Invoke-WebRequest -Uri "$baseUrl/health" -UseBasicParsing -TimeoutSec 2
            break
        } catch { Start-Sleep -Milliseconds 400 }
    }
    if($null -eq $resp){throw ('GATEWAY_HTTP_NOT_READY '+(Receive-Job -Job $job -Keep | Out-String))}
    $health=$resp.Content | ConvertFrom-Json
    if($health.status -ne 'ok'){throw 'GATEWAY_HEALTH_NOT_OK'}
    if($health.runtime.watcher_publication_state -ne 'PROCESS_UNVERIFIED'){throw 'UNVERIFIED_WATCHER_WAS_NOT_BLOCKED'}
    if($null -ne $health.runtime.watcher_observed_at_offset){throw 'UNVERIFIED_WATCHER_TIMESTAMP_EXPOSED'}
    if($health.runtime.brain_publication_state -ne 'UNKNOWN_NOT_PUBLISHED'){throw 'BRAIN_WAS_FABRICATED'}
    if($health.execution.real_submit_allowed -ne $false){throw 'REAL_ORDER_FLAG_UNSAFE'}
    if($health.runtime.fail_closed -ne $true){throw 'RUNTIME_FAIL_CLOSED_NOT_SET'}
    $page=Invoke-WebRequest -Uri "$baseUrl/" -UseBasicParsing -TimeoutSec 5
    if($page.Content -notmatch 'v10-static-snapshot-warning'){throw 'HISTORICAL_NOTICE_MISSING'}
    $asset=Invoke-WebRequest -Uri "$baseUrl/v10_publication_status.js" -UseBasicParsing -TimeoutSec 5
    if($asset.Content -notmatch 'summarizeHealth'){throw 'BROWSER_ASSET_NOT_SERVED'}
    Write-Output 'PASS: V10_GATEWAY_LOCAL_HTTP_SYNTHETIC'
}
finally {
    if($null -ne $job){
        Stop-Job -Job $job -ErrorAction SilentlyContinue
        Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
    }
    if([IO.Directory]::Exists($base)){[IO.Directory]::Delete($base,$true)}
}
