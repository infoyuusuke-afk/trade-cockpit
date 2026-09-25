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
                }
                try {
                    if (Test-Path -LiteralPath $controllerStateFile) {
                        $st = Read-JsonUtf8 $controllerStateFile
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
                        # Fail-closed unless every safety-relevant worker is
                        # confirmed alive AND the collector has live data.
                        # Any unknown/missing state defaults to fail-closed.
                        $runtime.fail_closed = -not (
                            $st.watcher_status -eq "LIVE" -and
                            $st.heartbeat_status -eq "RUNNING" -and
                            $st.collector_status -eq "LIVE"
                        )
                    }
                } catch {}
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
                    now              = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
                } | ConvertTo-Json -Depth 5
                Send-Response $stream '200 OK' 'application/json; charset=utf-8' ($utf8.GetBytes($payload))
                continue
            }

            if ($path -eq '/live_ms2.json') {
                if ($liveJson -and (Test-Path -LiteralPath $liveJson)) {
                    $bytes = [IO.File]::ReadAllBytes($liveJson)
                    Send-Response $stream '200 OK' 'application/json; charset=utf-8' $bytes
                } else {
                    Send-Response $stream '503 Service Unavailable' 'application/json; charset=utf-8' ($utf8.GetBytes('{"status":"waiting","reason":"live_ms2.json not found"}'))
                }
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
