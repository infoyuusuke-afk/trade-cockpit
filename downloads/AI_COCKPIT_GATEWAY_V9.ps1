param(
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [string]$RuntimeDir = "",
    [string]$Build = "unknown",
    [int]$Port = 28581
)

# AI Cockpit Gateway V9
#
# Rebuilt 2026-09-25. The previous Gateway (AI_Cockpit_Local_Gateway.ps1)
# proxied every page from the PUBLIC GitHub Pages site (main branch), so
# no local change - including the Card System PRs #258-#261 - could ever
# show up locally until it was merged to main. This version serves static
# files directly from $RepoRoot on disk instead: "git checkout <branch>"
# in that folder IS the deploy step, and /health reports exactly which
# branch/commit is currently being served, so "did the new UI actually
# load" is answerable from the browser, not assumed.
#
# /live_ms2.json and /health remain served from the local runtime data,
# exactly as before. Every response sends Cache-Control: no-store.

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RuntimeDir)) {
    $candidates = @(
        (Join-Path $env:USERPROFILE "Desktop\デイトレ\MarketSpeed II RSS\files"),
        (Join-Path ([Environment]::GetFolderPath("Desktop")) "デイトレ\MarketSpeed II RSS\files"),
        (Join-Path $env:USERPROFILE "OneDrive\Desktop\デイトレ\MarketSpeed II RSS\files")
    ) | Select-Object -Unique
    foreach ($c in $candidates) {
        if (Test-Path -LiteralPath (Join-Path $c "live_ms2.json")) { $RuntimeDir = $c; break }
    }
}
$liveJson = if ($RuntimeDir) { Join-Path $RuntimeDir "live_ms2.json" } else { "" }
$controllerStateFile = "C:\AI_Cockpit_OneClick_Starter\V9_CONTROLLER_STATE.json"

if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot "index.html"))) {
    throw "RepoRoot does not look like a trade-cockpit checkout (index.html not found): $RepoRoot"
}

$listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
$utf8 = [Text.UTF8Encoding]::new($false)

# 2026-09-25 fix: Get-Content -Raw does not reliably treat a BOM-less
# UTF-8 file as UTF-8 under Windows PowerShell 5.1 - it can fall back to
# the system ANSI codepage, corrupting the Japanese RuntimeDir path on
# read-back. Every JSON read in this script goes through this helper.
function Read-JsonUtf8([string]$Path) {
    $text = [IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8)
    return $text | ConvertFrom-Json
}

function Get-ShadowEnginePublication([string]$RuntimeDirectory) {
    $result = [ordered]@{
        shadow_engine_state = "STOPPED"
        shadow_engine_reason = "STATUS_NOT_PUBLISHED"
        shadow_engine_updated_at = $null
        shadow_open_observation_count = $null
        shadow_ops = $null
        shadow_latest_incident = $null
        shadow_ui_independent = $true
    }
    if ([string]::IsNullOrWhiteSpace($RuntimeDirectory)) { return $result }
    $path = Join-Path $RuntimeDirectory "ai_shadow_status.json"
    if (-not (Test-Path -LiteralPath $path)) { return $result }
    try {
        $status = Read-JsonUtf8 $path
        $written = (Get-Item -LiteralPath $path).LastWriteTime
        $age = ((Get-Date) - $written).TotalSeconds
        $publishedState = [string]$status.state
        if ($status.real_submit_allowed -ne $false -or [string]::IsNullOrWhiteSpace($publishedState)) {
            $result.shadow_engine_state = "PAUSED_FAIL_CLOSED"
            $result.shadow_engine_reason = "STATUS_UNTRUSTED"
            return $result
        }
        if ($age -lt 0 -or $age -gt 30) {
            if ($publishedState -eq "STOPPED") {
                $result.shadow_engine_state = "STOPPED"
                $result.shadow_engine_reason = "STATUS_STALE"
            } else {
                $result.shadow_engine_state = "PAUSED_FAIL_CLOSED"
                $result.shadow_engine_reason = "STATUS_STALE"
            }
            return $result
        }
        if (@("RUNNING", "PAUSED_FAIL_CLOSED", "RECOVERING", "STOPPED") -notcontains $publishedState) {
            $result.shadow_engine_state = "PAUSED_FAIL_CLOSED"
            $result.shadow_engine_reason = "UNKNOWN_STATE"
            return $result
        }
        $result.shadow_engine_state = $publishedState
        $result.shadow_engine_reason = [string]$status.reason
        $result.shadow_engine_updated_at = [string]$status.updated_at
        $result.shadow_open_observation_count = $status.open_observation_count
        $result.shadow_ops = $status.ops
        $result.shadow_latest_incident = $status.latest_incident
        return $result
    } catch {
        $result.shadow_engine_state = "PAUSED_FAIL_CLOSED"
        $result.shadow_engine_reason = "STATUS_UNREADABLE"
        return $result
    }
}

function Test-HealthProcess([int]$ProcessId, [string]$ScriptName, [datetime]$StateWrittenAt) {
    if ($ProcessId -le 0) { return $false }
    try {
        $process = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $ProcessId) -ErrorAction Stop
        if ($null -eq $process -or [string]::IsNullOrWhiteSpace([string]$process.CommandLine)) { return $false }
        if ([datetime]$process.CreationDate -gt $StateWrittenAt) { return $false }
        return ([string]$process.CommandLine -match [regex]::Escape($ScriptName))
    } catch { return $false }
}
function Get-ContentType([string]$path) {
    switch -Regex ($path.ToLowerInvariant()) {
        '\.html?$' { return 'text/html; charset=utf-8' }
        '\.css$' { return 'text/css; charset=utf-8' }
        '\.js$' { return 'application/javascript; charset=utf-8' }
        '\.mjs$' { return 'application/javascript; charset=utf-8' }
        '\.json$' { return 'application/json; charset=utf-8' }
        '\.svg$' { return 'image/svg+xml' }
        '\.png$' { return 'image/png' }
        '\.jpe?g$' { return 'image/jpeg' }
        '\.webp$' { return 'image/webp' }
        '\.ico$' { return 'image/x-icon' }
        '\.woff2$' { return 'font/woff2' }
        default { return 'application/octet-stream' }
    }
}

function Send-Response($stream, [string]$status, [string]$contentType, [byte[]]$body) {
    $headers = "HTTP/1.1 $status`r`nContent-Type: $contentType`r`nContent-Length: $($body.Length)`r`nCache-Control: no-store`r`nAccess-Control-Allow-Origin: *`r`nConnection: close`r`n`r`n"
    $hb = [Text.Encoding]::ASCII.GetBytes($headers)
    $stream.Write($hb, 0, $hb.Length)
    if ($body.Length -gt 0) { $stream.Write($body, 0, $body.Length) }
    $stream.Flush()
}

function Get-GitInfo([string]$repoRoot) {
    $branch = "unknown"
    $sha = "unknown"
    try {
        Push-Location -LiteralPath $repoRoot
        $branch = (& git rev-parse --abbrev-ref HEAD 2>$null)
        $sha = (& git rev-parse HEAD 2>$null)
    } catch {
    } finally {
        Pop-Location -ErrorAction SilentlyContinue
    }
    if ([string]::IsNullOrWhiteSpace($branch)) { $branch = "unknown" }
    if ([string]::IsNullOrWhiteSpace($sha)) { $sha = "unknown" }
    return @{ branch = $branch.Trim(); sha = $sha.Trim() }
}

# Injects a small, fixed, bottom-right badge showing the branch/short-SHA
# this LOCAL gateway is serving. Only affects what this local gateway
# returns - the public GitHub Pages site (served separately by GitHub) is
# never touched by this script.
function Get-ProcessCommandCount([string]$ScriptName) {
    try {
        $procs = @(Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" -ErrorAction Stop | Where-Object {
            [string]$_.CommandLine -like ("*" + $ScriptName + "*")
        })
        return $procs.Count
    } catch {
        return $null
    }
}

function Get-LivePriceRejection {
    param(
        $LiveObj,
        [double]$FileAgeSeconds,
        [double]$PayloadAgeSeconds,
        $UpdatedAtRaw,
        $FileMtime,
        [int]$MaxAgeSeconds = 60
    )
    $reasons = New-Object System.Collections.Generic.List[string]
    $canonicalSource = "MarketSpeed II RSS / local PC"
    $fresh = (
        $FileAgeSeconds -ge 0 -and $FileAgeSeconds -le $MaxAgeSeconds -and
        $PayloadAgeSeconds -ge 0 -and $PayloadAgeSeconds -le $MaxAgeSeconds
    )
    if (-not $fresh) { [void]$reasons.Add("STALE_OR_MISSING_TIMESTAMP") }
    $source = if ($null -ne $LiveObj) { [string]$LiveObj.source } else { "" }
    if ($source -ne $canonicalSource -or $source -match '(?i)sample|snapshot|cache|static|fixture|公開') {
        [void]$reasons.Add("CACHED_OR_SAMPLE_PAYLOAD")
    }
    $diag = if ($null -ne $LiveObj) { $LiveObj.live_price_diagnostics } else { $null }
    $sourceMode = ""
    $sourceTimestamp = $null
    $symbol = $null
    $currentPrice = $null
    $dataConflict = $false
    $collectorPid = $null
    $watcherCount = $null
    $collectorCount = $null
    if ($null -eq $diag) {
        [void]$reasons.Add("MISSING_PRICE_DIAGNOSTICS")
    } else {
        $sourceMode = [string]$diag.source_mode
        $sourceTimestamp = $diag.source_timestamp
        $symbol = $diag.symbol
        $currentPrice = $diag.current_price
        $collectorPid = $diag.collector_pid
        $dataConflict = ($diag.data_conflict -eq $true)
        if ([string]$diag.price_source_status -ne "OK") { [void]$reasons.Add("PRICE_SOURCE_MISMATCH") }
        if ($sourceMode -ne "MS2_RSS_WORKBOOK") { [void]$reasons.Add("WRONG_SOURCE_WORKBOOK") }
        if ($dataConflict) { [void]$reasons.Add("DATA_CONFLICT") }
        if ($diag.live_values_available -ne $true) { [void]$reasons.Add("LIVE_VALUES_UNAVAILABLE") }
        if ($diag.duplicate_collector -eq $true) { [void]$reasons.Add("DUPLICATE_COLLECTOR") }
        if ($diag.duplicate_watcher -eq $true) { [void]$reasons.Add("DUPLICATE_WATCHER") }
        if ([string]$diag.stale_reason -match 'WRONG_SYMBOL_MAPPING') { [void]$reasons.Add("WRONG_SYMBOL_MAPPING") }
    }
    if ($null -ne $LiveObj -and ($LiveObj.data_conflict -eq $true)) { [void]$reasons.Add("DATA_CONFLICT") }
    if ($null -ne $LiveObj -and [string]$LiveObj.price_source_status -eq "PRICE_SOURCE_MISMATCH") { [void]$reasons.Add("PRICE_SOURCE_MISMATCH") }
    $collectorCount = Get-ProcessCommandCount "MS2_RSS_100_Collector.ps1"
    $watcherCount = Get-ProcessCommandCount "Kioxia_RSS_Live_Watcher.ps1"
    if ($null -eq $collectorCount) { [void]$reasons.Add("DUPLICATE_PROCESS_CHECK_UNAVAILABLE") }
    elseif ($collectorCount -gt 1) { [void]$reasons.Add("DUPLICATE_COLLECTOR") }
    elseif ($collectorCount -lt 1) { [void]$reasons.Add("COLLECTOR_PROCESS_UNVERIFIED") }
    if ($null -eq $watcherCount) { [void]$reasons.Add("DUPLICATE_PROCESS_CHECK_UNAVAILABLE") }
    elseif ($watcherCount -gt 1) { [void]$reasons.Add("DUPLICATE_WATCHER") }
    $workbookVerified = $false
    try {
        if (Test-Path -LiteralPath $controllerStateFile) {
            $st = Read-JsonUtf8 $controllerStateFile
            $workbookVerified = ($st.workbook_identity_verified -eq $true)
        }
    } catch { $workbookVerified = $false }
    if (-not $workbookVerified) { [void]$reasons.Add("WRONG_SOURCE_WORKBOOK") }
    $unique = @($reasons | Select-Object -Unique)
    if ($unique.Count -eq 0) { return $null }
    $identity = @($unique | Where-Object { $_ -notin @("STALE_OR_MISSING_TIMESTAMP","LIVE_VALUES_UNAVAILABLE","INSUFFICIENT_COVERAGE") })
    $statusName = if ($identity.Count -gt 0) { "PRICE_SOURCE_MISMATCH" } else { "stale" }
    $reasonText = if ($unique -contains "STALE_OR_MISSING_TIMESTAMP" -and $identity.Count -eq 0) {
        "live_ms2.json freshness threshold exceeded"
    } else {
        ($unique -join ",")
    }
    return [ordered]@{
        status = $statusName
        reason = $reasonText
        stale_reason = ($unique -join ",")
        price_source_status = $(if ($identity.Count -gt 0) { "PRICE_SOURCE_MISMATCH" } else { "STALE" })
        source_mode = $sourceMode
        source_timestamp = $sourceTimestamp
        file_mtime = $FileMtime
        updated_at = $UpdatedAtRaw
        file_age_seconds = [Math]::Round($FileAgeSeconds, 1)
        payload_age_seconds = $(if ([double]::IsInfinity($PayloadAgeSeconds)) { $null } else { [Math]::Round($PayloadAgeSeconds, 1) })
        symbol = $symbol
        current_price = $currentPrice
        collector_pid = $collectorPid
        collector_count = $collectorCount
        watcher_count = $watcherCount
        data_conflict = [bool]($dataConflict -or ($identity.Count -gt 0))
        real_submit_allowed = $false
        live_values_available = $false
        max_age_seconds = $MaxAgeSeconds
    }
}

function Add-BuildBadge([string]$html, [string]$branch, [string]$sha, [string]$build) {
    $shortSha = if ($sha.Length -ge 8) { $sha.Substring(0, 8) } else { $sha }
    $safeBranch = [System.Net.WebUtility]::HtmlEncode($branch)
    $badge = "<div id=`"cc-build-badge`" style=`"position:fixed;right:6px;bottom:6px;z-index:99999;font:10px/1.4 -apple-system,sans-serif;background:#090A0C;color:#9AA0AA;border:1px solid #22252A;border-radius:6px;padding:4px 8px;opacity:.85;pointer-events:none`">local gateway &middot; $safeBranch @ $shortSha &middot; $build</div>"
    if ($html -match '(?i)</body>') {
        return $html -replace '(?i)</body>', ($badge + '</body>')
    }
    return $html + $badge
}

try {
    $listener.Start()
    Write-Host ("AI Cockpit Gateway V9: http://127.0.0.1:{0}/?live=1" -f $Port) -ForegroundColor Green
    Write-Host ("Serving from: " + $RepoRoot) -ForegroundColor Cyan
    Write-Host ("Runtime dir:  " + $RuntimeDir) -ForegroundColor Cyan

    while ($true) {
        $client = $listener.AcceptTcpClient()
        try {
            $stream = $client.GetStream()
            $reader = [IO.StreamReader]::new($stream, [Text.Encoding]::ASCII, $false, 4096, $true)
            $requestLine = $reader.ReadLine()
            while (($line = $reader.ReadLine()) -ne $null -and $line -ne "") {}
            if ([string]::IsNullOrWhiteSpace($requestLine)) { continue }
            $parts = $requestLine -split ' '
            $method = $parts[0]
            $rawPath = if ($parts.Count -ge 2) { $parts[1] } else { '/' }

            if ($method -eq 'OPTIONS') {
                Send-Response $stream '204 No Content' 'text/plain' ([byte[]]@())
                continue
            }
            if ($method -ne 'GET') {
                Send-Response $stream '405 Method Not Allowed' 'text/plain; charset=utf-8' ($utf8.GetBytes('GET only'))
                continue
            }

            $uri = [Uri]("http://127.0.0.1:" + $Port + $rawPath)
            $path = $uri.AbsolutePath

            if ($path -eq '/health') {
                $git = Get-GitInfo $RepoRoot
                $liveExists = if ($liveJson) { Test-Path -LiteralPath $liveJson } else { $false }
                $liveMtime = if ($liveExists) { (Get-Item -LiteralPath $liveJson).LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss') } else { $null }
                $runtime = [ordered]@{
                    controller_pid             = $null
                    collector_status           = $null
                    watcher_status             = $null
                    heartbeat_status           = $null
                    voice_bridge_status        = $null
                    sbv2_status                = $null
                    watcher_pid                = $null
                    heartbeat_pid              = $null
                    collector_pid              = $null
                    voice_bridge_pid           = $null
                    sbv2_pid                   = $null
                    excel_pid                  = $null
                    workbook_identity_verified = $null
                    voice_backend              = "Style-Bert-VITS2"
                    fail_closed                = $true
                    price_source_status        = $null
                    source_mode                = $null
                    data_conflict              = $null
                    stale_reason               = $null
                    live_updated_at            = $null
                    source_timestamp           = $null
                    live_symbol                = $null
                    live_current_price         = $null
                }
                try {
                    if (Test-Path -LiteralPath $controllerStateFile) {
                        $st = Read-JsonUtf8 $controllerStateFile
                        $runtime.controller_pid = $st.controller_pid
                        $runtime.collector_status = $st.collector_status
                        $runtime.watcher_status = $st.watcher_status
                        $runtime.heartbeat_status = $st.heartbeat_status
                        $runtime.voice_bridge_status = $st.voice_bridge_status
                        $runtime.sbv2_status = $st.sbv2_status
                        $runtime.watcher_pid = $st.watcher_pid
                        $runtime.heartbeat_pid = $st.heartbeat_pid
                        $runtime.collector_pid = $st.collector_pid
                        $runtime.voice_bridge_pid = $st.voice_bridge_pid
                        $runtime.sbv2_pid = $st.sbv2_pid
                        $runtime.excel_pid = $st.excel_pid
                        $runtime.workbook_identity_verified = $st.workbook_identity_verified
                        $stateWrittenAt = (Get-Item -LiteralPath $controllerStateFile).LastWriteTime
                        $stateAge = ((Get-Date) - $stateWrittenAt).TotalSeconds
                        $liveAge = if ($liveExists) { ((Get-Date) - (Get-Item -LiteralPath $liveJson).LastWriteTime).TotalSeconds } else { [double]::PositiveInfinity }
                        $controllerAlive = Test-HealthProcess ([int]$st.controller_pid) 'AI_COCKPIT_CONTROLLER_V9.ps1' $stateWrittenAt
                        $sessionFresh = $controllerAlive -and $stateAge -ge 0 -and $stateAge -le 30
                        foreach ($check in @(
                            @{field='watcher'; script='Kioxia_RSS_Live_Watcher.ps1'},
                            @{field='heartbeat'; script='Kioxia_Safety_Heartbeat.ps1'},
                            @{field='collector'; script='MS2_RSS_100_Collector.ps1'},
                            @{field='voice_bridge'; script='AI_COCKPIT_VOICE_BRIDGE_V9.ps1'},
                            @{field='sbv2'; script='server_fastapi.py'}
                        )) {
                            $pidField = $check.field + '_pid'
                            $statusField = $check.field + '_status'
                            if (-not $sessionFresh -or -not (Test-HealthProcess ([int]$st.$pidField) $check.script $stateWrittenAt)) {
                                $runtime[$statusField] = 'UNVERIFIED_OR_OFFLINE'
                            }
                        }
                        # Fail-closed unless every safety-relevant worker is
                        # confirmed alive AND the collector has live data.
                        # Any unknown/missing state defaults to fail-closed.
                        $runtime.fail_closed = -not (
                            $sessionFresh -and $liveAge -ge 0 -and $liveAge -le 60 -and
                            $runtime.watcher_status -eq "LIVE" -and
                            $runtime.heartbeat_status -eq "RUNNING" -and
                            $runtime.collector_status -eq "LIVE"
                        )
                    }
                } catch {}
                if ($liveExists) {
                    try {
                        $healthLive = Read-JsonUtf8 $liveJson
                        $healthDiag = $healthLive.live_price_diagnostics
                        $runtime.live_updated_at = [string]$healthLive.updated_at
                        $runtime.price_source_status = [string]$healthLive.price_source_status
                        $runtime.data_conflict = ($healthLive.data_conflict -eq $true)
                        $runtime.stale_reason = [string]$healthLive.stale_reason
                        if ($null -ne $healthDiag) {
                            if ([string]::IsNullOrWhiteSpace([string]$runtime.price_source_status)) { $runtime.price_source_status = [string]$healthDiag.price_source_status }
                            $runtime.source_mode = [string]$healthDiag.source_mode
                            $runtime.source_timestamp = $healthDiag.source_timestamp
                            $runtime.live_symbol = $healthDiag.symbol
                            $runtime.live_current_price = $healthDiag.current_price
                            if ($healthDiag.data_conflict -eq $true) { $runtime.data_conflict = $true }
                            if (-not [string]::IsNullOrWhiteSpace([string]$healthDiag.stale_reason)) { $runtime.stale_reason = [string]$healthDiag.stale_reason }
                        }
                    } catch {}
                }
                $execution = [ordered]@{
                    real_submit_allowed        = $false
                    real_order_route            = 'DISABLED'
                    auto_trading_real           = 'OFF_LOCKED'
                    broker_positions_connected  = $false
                    broker_position_count       = $null
                    broker_position_status      = 'NOT_CONNECTED_UNKNOWN_NOT_ZERO'
                    shadow_positions_connected  = $false
                    shadow_open_position_count  = $null
                    shadow_position_status      = 'NOT_PUBLISHED'
                    owner_control               = 'REAL_ORDER_UNLOCK_NOT_AVAILABLE'
                }
                $shadowPub = Get-ShadowEnginePublication $RuntimeDir
                foreach ($shadowKey in @(
                    "shadow_engine_state", "shadow_engine_reason", "shadow_engine_updated_at",
                    "shadow_open_observation_count", "shadow_ops", "shadow_latest_incident",
                    "shadow_ui_independent"
                )) {
                    $execution[$shadowKey] = $shadowPub[$shadowKey]
                }

                $payload = [ordered]@{
                    status           = 'ok'
                    port             = $Port
                    ui_branch        = $git.branch
                    ui_sha           = $git.sha
                    ui_build         = $Build
                    repo_root        = $RepoRoot
                    live_json_exists = $liveExists
                    live_json_mtime  = $liveMtime
                    runtime          = $runtime
                    execution        = $execution
                    now              = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
                } | ConvertTo-Json -Depth 8
                Send-Response $stream '200 OK' 'application/json; charset=utf-8' ($utf8.GetBytes($payload))
                continue
            }

            if ($path -eq '/live_ms2.json') {
                if (-not $liveJson -or -not (Test-Path -LiteralPath $liveJson)) {
                    Send-Response $stream '503 Service Unavailable' 'application/json; charset=utf-8' ($utf8.GetBytes('{"status":"waiting","reason":"live_ms2.json not found","stale_reason":"MISSING_PAYLOAD","real_submit_allowed":false,"live_values_available":false,"data_conflict":true}'))
                    continue
                }

                $LIVE_JSON_MAX_AGE_SECONDS = 60
                $liveItem = Get-Item -LiteralPath $liveJson
                $fileAgeSeconds = ((Get-Date) - $liveItem.LastWriteTime).TotalSeconds
                $payloadAgeSeconds = [double]::PositiveInfinity
                $updatedAtRaw = $null
                $liveObj = $null
                try {
                    $liveObj = Read-JsonUtf8 $liveJson
                    $updatedAtRaw = [string]$liveObj.updated_at
                    if (-not [string]::IsNullOrWhiteSpace($updatedAtRaw)) {
                        $cleanUpdatedAt = $updatedAtRaw -replace '\s+JST\s*$',''
                        $parsedUpdatedAt = Get-Date $cleanUpdatedAt -ErrorAction Stop
                        $payloadAgeSeconds = ((Get-Date) - $parsedUpdatedAt).TotalSeconds
                    }
                } catch {
                    $payloadAgeSeconds = [double]::PositiveInfinity
                    $liveObj = $null
                }

                $rejection = Get-LivePriceRejection -LiveObj $liveObj -FileAgeSeconds $fileAgeSeconds -PayloadAgeSeconds $payloadAgeSeconds -UpdatedAtRaw $updatedAtRaw -FileMtime $liveItem.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss') -MaxAgeSeconds $LIVE_JSON_MAX_AGE_SECONDS
                if ($null -ne $rejection) {
                    $stalePayload = $rejection | ConvertTo-Json -Depth 6
                    Send-Response $stream '503 Service Unavailable' 'application/json; charset=utf-8' ($utf8.GetBytes($stalePayload))
                    continue
                }

                $bytes = [IO.File]::ReadAllBytes($liveJson)
                Send-Response $stream '200 OK' 'application/json; charset=utf-8' $bytes
                continue
            }
            # Static file, served directly from the local repo checkout.
            $relative = if ($path -eq '/') { 'index.html' } else { $path.TrimStart('/') }
            $relative = [Uri]::UnescapeDataString($relative)
            # Reject any path that escapes RepoRoot (no "..", no absolute
            # drive references) before touching the filesystem.
            if ($relative -match '\.\.' -or $relative -match '^[A-Za-z]:' -or $relative.StartsWith('\\')) {
                Send-Response $stream '400 Bad Request' 'text/plain; charset=utf-8' ($utf8.GetBytes('Bad path'))
                continue
            }
            $fullPath = Join-Path $RepoRoot $relative
            $resolvedFull = [IO.Path]::GetFullPath($fullPath)
            $resolvedRoot = [IO.Path]::GetFullPath($RepoRoot)
            if (-not $resolvedFull.StartsWith($resolvedRoot, [StringComparison]::OrdinalIgnoreCase)) {
                Send-Response $stream '400 Bad Request' 'text/plain; charset=utf-8' ($utf8.GetBytes('Bad path'))
                continue
            }

            if (-not (Test-Path -LiteralPath $resolvedFull -PathType Leaf)) {
                Send-Response $stream '404 Not Found' 'text/plain; charset=utf-8' ($utf8.GetBytes('Not found: ' + $relative))
                continue
            }

            $ct = Get-ContentType $resolvedFull
            if ($resolvedFull -match '(?i)index\.html$') {
                $git = Get-GitInfo $RepoRoot
                $html = Get-Content -LiteralPath $resolvedFull -Raw -Encoding UTF8
                $html = Add-BuildBadge $html $git.branch $git.sha $Build
                Send-Response $stream '200 OK' $ct ($utf8.GetBytes($html))
            } else {
                $bytes = [IO.File]::ReadAllBytes($resolvedFull)
                Send-Response $stream '200 OK' $ct $bytes
            }
        } catch {
        } finally {
            $client.Close()
        }
    }
} finally {
    $listener.Stop()
}
