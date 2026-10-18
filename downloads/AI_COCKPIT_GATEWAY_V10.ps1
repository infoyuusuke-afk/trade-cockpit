param(
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [string]$RuntimeDir = "",
    [string]$Build = "unknown",
    [int]$Port = 28581,
    [switch]$SnapshotGuardSelfTest,
    [switch]$PublicationSelfTest,
    [switch]$ShadowHeartbeatSelfTest,
    [switch]$BrainObserverSelfTest
)

# AI Cockpit Gateway V10
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
    # Keep this file ASCII. Windows PowerShell 5.1 reads a BOM-less
    # script with the ANSI code page, and a UTF-8 character can swallow
    # the following quote. The parser then reports UnexpectedToken at a
    # later line, including Get-LivePriceRejection and Send-Response.
    $daytrade = -join @([char]0x30C7, [char]0x30A4, [char]0x30C8, [char]0x30EC)
    $candidates = @(
        (Join-Path $env:USERPROFILE ("Desktop\" + $daytrade + "\MarketSpeed II RSS\files")),
        (Join-Path ([Environment]::GetFolderPath("Desktop")) ($daytrade + "\MarketSpeed II RSS\files")),
        (Join-Path $env:USERPROFILE ("OneDrive\Desktop\" + $daytrade + "\MarketSpeed II RSS\files"))
    ) | Select-Object -Unique
    foreach ($c in $candidates) {
        if (Test-Path -LiteralPath (Join-Path $c "live_ms2.json")) { $RuntimeDir = $c; break }
    }
}
$liveJson = if ($RuntimeDir) { Join-Path $RuntimeDir "live_ms2.json" } else { "" }
$controllerStateFile = "C:\AI_Cockpit_OneClick_Starter\V10_CONTROLLER_STATE.json"
# Last quote times this Gateway served as LIVE (identity quote and each row).
# A later payload whose quote is older is a regression and is refused. The
# history is saved beside live_ms2.json after every LIVE response and read back
# at start, so a Gateway restart does not forget it. A missing history file is
# reported as a history-loss risk on /health; an unreadable one refuses LIVE.
$script:LastServedIdentityQuoteAt = $null
$script:LastServedRowQuoteAt = @{}
$script:ServedHistoryPath = if ($RuntimeDir) { Join-Path $RuntimeDir "v10_gateway_served_quotes.json" } else { "" }
$script:ServedHistoryState = "NOT_LOADED"

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


# A recent publication is NOT a recent market tick, source authentication, or
# a trading gate. Validate only the producer's exact timestamp contract.
function Get-V10PublicationState([string]$Stamp, [string]$TimezoneName,
    [bool]$ProcessVerified, [datetime]$LastWriteUtc) {
    if (-not $ProcessVerified) { return 'PROCESS_UNVERIFIED' }
    if ($TimezoneName -cne 'Asia/Tokyo') { return 'TIMEZONE_UNVERIFIED' }
    if ([string]::IsNullOrWhiteSpace($Stamp)) { return 'TIMESTAMP_MISSING' }
    $published = [datetimeoffset]::MinValue
    $valid = [datetimeoffset]::TryParseExact(
        $Stamp, 'yyyy-MM-ddTHH:mm:sszzz',
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::None, [ref]$published)
    if (-not $valid -or $published.Offset.TotalHours -ne 9) { return 'TIMESTAMP_INVALID' }
    $stampAge = ([datetimeoffset]::UtcNow - $published.ToUniversalTime()).TotalSeconds
    $fileAge = ([datetime]::UtcNow - $LastWriteUtc).TotalSeconds
    if ($stampAge -lt 0 -or $fileAge -lt 0) { return 'TIMESTAMP_FUTURE' }
    if ($stampAge -gt 60 -or $fileAge -gt 60) { return 'PUBLICATION_STALE' }
    return 'RECENT_PUBLICATION_ONLY'
}

# V10 RUN deploys Watcher into RuntimeDir, NOT RepoRoot/ms2_live.
# Watcher writes its JSON beside its deployed script under PSScriptRoot.
# Never read repo checkout snapshots or guess another directory.
function Get-V10WatcherPublication([string]$RuntimeDirectory, [bool]$ProcessVerified) {
    $result = [ordered]@{
        observed_at_offset = $null
        timestamp_timezone = $null
        publication_state = 'WATCHER_FILE_UNAVAILABLE'
    }
    if ([string]::IsNullOrWhiteSpace($RuntimeDirectory)) {
        $result.publication_state = 'WATCHER_RUNTIME_UNAVAILABLE'
        return $result
    }
    try {
        if (-not (Test-Path -LiteralPath $RuntimeDirectory -PathType Container)) {
            $result.publication_state = 'WATCHER_RUNTIME_UNAVAILABLE'
            return $result
        }
        $dir = Get-Item -LiteralPath $RuntimeDirectory -ErrorAction Stop
        if (($dir.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            $result.publication_state = 'WATCHER_RUNTIME_UNTRUSTED'
            return $result
        }
        $file = Join-Path $RuntimeDirectory 'kioxia_watcher_live.json'
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { return $result }
        $item = Get-Item -LiteralPath $file -ErrorAction Stop
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            $result.publication_state = 'WATCHER_FILE_UNTRUSTED'
            return $result
        }
        if ($item.Length -le 2 -or $item.Length -gt 65536) {
            $result.publication_state = 'WATCHER_FILE_SIZE_INVALID'
            return $result
        }
        $data = Read-JsonUtf8 $file
        if ([string]$data.schema_version -cne 'kioxia-watcher-1.0' -or
            [string]$data.source -cne 'Kioxia_RSS_Live_Watcher (Excel RSS)') {
            $result.publication_state = 'WATCHER_IDENTITY_UNVERIFIED'
            return $result
        }
        $stamp = [string]$data.observed_at_offset
        $zone = [string]$data.timestamp_timezone
        $state = Get-V10PublicationState $stamp $zone $ProcessVerified $item.LastWriteTimeUtc
        $result.publication_state = $state
        if ($state -eq 'RECENT_PUBLICATION_ONLY') {
            $result.observed_at_offset = $stamp
            $result.timestamp_timezone = $zone
        }
        return $result
    } catch {
        $result.publication_state = 'WATCHER_FILE_UNREADABLE'
        return $result
    }
}


# SHADOW is a separate observation supervisor, NOT the BRAIN strategy engine.
# This evidence is an authenticated process-publication heartbeat only.

# Controller-owned BRAIN observation worker is independent from port 28584
# (which is only another Gateway). This does NOT authenticate market ticks.
function Get-V10BrainObserverProof([string]$RuntimeDirectory, [int]$ExpectedPid, [bool]$ProcessVerified) {
    $result = [ordered]@{
        status = 'BRAIN_FILE_UNAVAILABLE'
        updated_at = $null
        watch_count = $null
        process_role = 'INDEPENDENT_BRAIN_OBSERVER_NOT_TRADE_ENGINE'
    }
    if ([string]::IsNullOrWhiteSpace($RuntimeDirectory)) {
        $result.status = 'BRAIN_RUNTIME_UNAVAILABLE'
        return $result
    }
    try {
        if (-not (Test-Path -LiteralPath $RuntimeDirectory -PathType Container)) {
            $result.status = 'BRAIN_RUNTIME_UNAVAILABLE'
            return $result
        }
        $dir = Get-Item -LiteralPath $RuntimeDirectory -ErrorAction Stop
        if (($dir.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            $result.status = 'BRAIN_RUNTIME_UNTRUSTED'
            return $result
        }
        $path = Join-Path $RuntimeDirectory 'ai_brain_observer_status_v1.json'
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $result }
        $item = Get-Item -LiteralPath $path -ErrorAction Stop
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
            $item.Length -le 2 -or $item.Length -gt 65536) {
            $result.status = 'BRAIN_FILE_UNTRUSTED'
            return $result
        }
        $data = Read-JsonUtf8 $path
        if ([string]$data.schema_version -cne 'ai-brain-observer-1' -or
            [string]$data.component_role -cne 'INDEPENDENT_BRAIN_OBSERVER_NOT_TRADE_ENGINE') {
            $result.status = 'BRAIN_SCHEMA_UNVERIFIED'
            return $result
        }
        if ($data.real_submit_allowed -ne $false -or
            $data.source_authenticated -ne $false -or
            $data.cross_source_join_allowed -ne $false -or
            $data.promotion_eligible -ne $false -or
            $null -ne $data.last_market_data_at -or
            $data.exchange_tick_date_verified -ne $false -or
            $data.signal_provenance_verified -ne $false -or
            $data.tested_expectancy_available -ne $false -or
            [string]$data.eligible_observed_n -cne '0') {
            $result.status = 'BRAIN_UNSAFE_EVIDENCE_CLAIM'
            return $result
        }
        if (-not $ProcessVerified -or $ExpectedPid -le 0) {
            $result.status = 'BRAIN_PROCESS_UNVERIFIED'
            return $result
        }
        $publishedPid = 0
        if (-not [int]::TryParse([string]$data.engine_pid, [ref]$publishedPid) -or
            $publishedPid -ne $ExpectedPid) {
            $result.status = 'BRAIN_PID_MISMATCH'
            return $result
        }
        $stamp = [string]$data.updated_at
        if ($stamp -cnotmatch '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,7})?(Z|[+-]\d{2}:\d{2})$') {
            $result.status = 'BRAIN_TIME_INVALID'
            return $result
        }
        $parsed = [datetimeoffset]::MinValue
        $valid = [datetimeoffset]::TryParse($stamp,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::None, [ref]$parsed)
        if (-not $valid) {
            $result.status = 'BRAIN_TIME_INVALID'
            return $result
        }
        $age = ([datetimeoffset]::UtcNow - $parsed.ToUniversalTime()).TotalSeconds
        $fileAge = ([datetime]::UtcNow - $item.LastWriteTimeUtc).TotalSeconds
        if ($age -lt 0 -or $fileAge -lt 0 -or $age -gt 30 -or $fileAge -gt 30) {
            $result.status = 'BRAIN_STALE_OR_FUTURE'
            return $result
        }
        $state = [string]$data.state
        if ($state -cnotin @('BLOCKED', 'OBSERVATION_ONLY')) {
            $result.status = 'BRAIN_STATE_INVALID'
            return $result
        }
        if ($state -ceq 'BLOCKED') {
            $result.status = 'BRAIN_INPUT_BLOCKED'
            $result.updated_at = $parsed.ToUniversalTime().ToString('o')
            return $result
        }
        # A recent BRAIN publication is not a dated exchange tick.
        $sourceStamp = [datetimeoffset]::MinValue
        $sourceRaw = [string]$data.source_publication_at
        $sourceOK = $sourceRaw -cmatch '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,7})?(Z|[+-]\d{2}:\d{2})$' -and
            [datetimeoffset]::TryParse($sourceRaw, [Globalization.CultureInfo]::InvariantCulture,
                [Globalization.DateTimeStyles]::None, [ref]$sourceStamp)
        if (-not $sourceOK) {
            $result.status = 'BRAIN_SOURCE_TIME_UNVERIFIED'
            return $result
        }
        $sourceAge = ([datetimeoffset]::UtcNow - $sourceStamp.ToUniversalTime()).TotalSeconds
        if ($sourceAge -lt 0 -or $sourceAge -gt 60) {
            $result.status = 'BRAIN_SOURCE_STALE'
            return $result
        }
        $watchCount = 0
        foreach ($key in @('OR15_ABOVE_VWAP_WATCH', 'OR15_BELOW_VWAP_WATCH')) {
            $count = $data.watch_counts.$key
            $parsedCount = 0
            if (-not [int]::TryParse([string]$count, [ref]$parsedCount) -or
                $parsedCount -lt 0 -or $parsedCount -gt 110) {
                $result.status = 'BRAIN_WATCH_COUNTS_INVALID'
                return $result
            }
            $watchCount += $parsedCount
        }
        if ($watchCount -gt 110) {
            $result.status = 'BRAIN_WATCH_COUNTS_INVALID'
            return $result
        }
        $result.status = 'BRAIN_OBSERVING_PUBLICATION_ONLY'
        $result.updated_at = $parsed.ToUniversalTime().ToString('o')
        $result.watch_count = $watchCount
        return $result
    } catch {
        $result.status = 'BRAIN_STATUS_UNREADABLE'
        return $result
    }
}

function Get-V10ShadowHeartbeatProof([string]$RuntimeDirectory, [int]$ExpectedPid,
    [bool]$ProcessVerified) {
    $result = [ordered]@{
        status = 'SHADOW_FILE_UNAVAILABLE'
        heartbeat_at = $null
        component_role = 'SHADOW_OBSERVER_NOT_BRAIN'
    }
    if ([string]::IsNullOrWhiteSpace($RuntimeDirectory)) {
        $result.status = 'SHADOW_RUNTIME_UNAVAILABLE'
        return $result
    }
    try {
        if (-not (Test-Path -LiteralPath $RuntimeDirectory -PathType Container)) {
            $result.status = 'SHADOW_RUNTIME_UNAVAILABLE'
            return $result
        }
        $dir = Get-Item -LiteralPath $RuntimeDirectory -ErrorAction Stop
        if (($dir.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            $result.status = 'SHADOW_RUNTIME_UNTRUSTED'
            return $result
        }
        $path = Join-Path $RuntimeDirectory 'ai_shadow_status.json'
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $result }
        $item = Get-Item -LiteralPath $path -ErrorAction Stop
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
            $item.Length -le 2 -or $item.Length -gt 65536) {
            $result.status = 'SHADOW_FILE_UNTRUSTED'
            return $result
        }
        $data = Read-JsonUtf8 $path
        if ([string]$data.schema_version -cne 'ai-shadow-supervisor-1' -or
            $data.ui_independent -ne $true) {
            $result.status = 'SHADOW_IDENTITY_UNVERIFIED'
            return $result
        }
        if ($data.real_submit_allowed -ne $false) {
            $result.status = 'SHADOW_ORDER_FLAG_UNSAFE'
            return $result
        }
        if ($ExpectedPid -le 0 -or -not $ProcessVerified) {
            $result.status = 'SHADOW_PROCESS_UNVERIFIED'
            return $result
        }
        $publishedPid = 0
        if (-not [int]::TryParse([string]$data.engine_pid, [ref]$publishedPid) -or
            $publishedPid -ne $ExpectedPid) {
            $result.status = 'SHADOW_PID_MISMATCH'
            return $result
        }
        $stamp = [string]$data.updated_at
        if ($stamp -cnotmatch '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,7})?(Z|[+-]\d{2}:\d{2})$') {
            $result.status = 'SHADOW_TIMESTAMP_INVALID'
            return $result
        }
        $parsed = [datetimeoffset]::MinValue
        $valid = [datetimeoffset]::TryParse($stamp,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::None, [ref]$parsed)
        if (-not $valid) {
            $result.status = 'SHADOW_TIMESTAMP_INVALID'
            return $result
        }
        $age = ([datetimeoffset]::UtcNow - $parsed.ToUniversalTime()).TotalSeconds
        $fileAge = ([datetime]::UtcNow - $item.LastWriteTimeUtc).TotalSeconds
        if ($age -lt 0 -or $fileAge -lt 0 -or $age -gt 30 -or $fileAge -gt 30) {
            $result.status = 'SHADOW_TIMESTAMP_STALE_OR_FUTURE'
            return $result
        }
        $publishedState = [string]$data.state
        if (@('RUNNING','PAUSED_FAIL_CLOSED','RECOVERING','STOPPED') -cnotcontains $publishedState) {
            $result.status = 'SHADOW_STATE_UNVERIFIED'
            return $result
        }
        if ($publishedState -eq 'RUNNING' -and $data.resume_blocked -ne $false) {
            $result.status = 'SHADOW_RESUME_UNVERIFIED'
            return $result
        }
        $result.status = 'SHADOW_' + $publishedState + '_HEARTBEAT_ONLY'
        $result.heartbeat_at = $parsed.ToUniversalTime().ToString('o')
        return $result
    } catch {
        $result.status = 'SHADOW_STATUS_UNREADABLE'
        return $result
    }
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
        shadow_quote_freshness = $null
        shadow_board_availability = $null
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
        $result.shadow_quote_freshness = $status.quote_freshness
        $result.shadow_board_availability = $status.board_availability
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

function Test-ControllerHealthProcess([int]$ProcessId, [datetime]$StateWrittenAt) {
    if ($ProcessId -le 0) { return $false }
    try {
        $process = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $ProcessId) -ErrorAction Stop
        if ($null -eq $process -or [string]::IsNullOrWhiteSpace([string]$process.CommandLine)) { return $false }
        if ([datetime]$process.CreationDate -gt $StateWrittenAt) { return $false }
        $cmd = [string]$process.CommandLine
        # RUN invokes Controller synchronously with &, so the State controller_pid
        # may legitimately be the RUN PowerShell host. Accept only these two
        # V10 identities; never treat an arbitrary powershell.exe as Controller.
        return (
            $cmd -match [regex]::Escape("AI_COCKPIT_CONTROLLER_V10.ps1") -or
            $cmd -match [regex]::Escape("RUN_AI_COCKPIT_V10.ps1")
        )
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
    $headers = "HTTP/1.1 $status`r`nContent-Type: $contentType`r`nContent-Length: $($body.Length)`r`nCache-Control: no-store`r`nX-Content-Type-Options: nosniff`r`nConnection: close`r`n`r`n"
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

function Get-NormalizedLocalWorkbookPath([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return "" }
    $trim = $Value.Trim()
    if ($trim -notmatch '^[A-Za-z]:\\' -and $trim -notmatch '^[A-Za-z]:/') { return "" }
    $slash = ($trim -replace '/', '\')
    while ($slash.Length -gt 3 -and $slash.EndsWith('\')) {
        $slash = $slash.Substring(0, $slash.Length - 1)
    }
    $parts = New-Object System.Collections.Generic.List[string]
    foreach ($part in ($slash -split '\\')) {
        if ($part -eq "" -or $part -eq ".") { continue }
        if ($part -eq "..") {
            if ($parts.Count -gt 1) { $parts.RemoveAt($parts.Count - 1) }
            continue
        }
        [void]$parts.Add($part)
    }
    if ($parts.Count -lt 2) { return "" }
    $root = [string]$parts[0]
    if ($root -notmatch '^[A-Za-z]:$') { return "" }
    $rest = @()
    for ($i = 1; $i -lt $parts.Count; $i++) { $rest += [string]$parts[$i] }
    return $root + '\' + ($rest -join '\')
}

function Get-CollectorFileIdentityType {
    foreach ($asm in [AppDomain]::CurrentDomain.GetAssemblies()) {
        $found = $asm.GetType("CollectorWorkbookFileIdentity")
        if ($null -ne $found) { return $found }
    }
    $code = @"
using System;
using System.IO;
using System.Runtime.InteropServices;
public class CollectorWorkbookFileIdentity {
    [StructLayout(LayoutKind.Sequential)]
    struct ByHandle {
        public uint FileAttributes;
        public uint CreationLow;
        public uint CreationHigh;
        public uint AccessLow;
        public uint AccessHigh;
        public uint WriteLow;
        public uint WriteHigh;
        public uint VolumeSerialNumber;
        public uint FileSizeHigh;
        public uint FileSizeLow;
        public uint NumberOfLinks;
        public uint FileIndexHigh;
        public uint FileIndexLow;
    }
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool GetFileInformationByHandle(IntPtr handle, out ByHandle info);
    public static string Key(string path) {
        using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete)) {
            ByHandle info;
            if (!GetFileInformationByHandle(stream.SafeFileHandle.DangerousGetHandle(), out info)) {
                throw new IOException("file identity unreadable");
            }
            return info.VolumeSerialNumber.ToString("X8") + ":" + info.FileIndexHigh.ToString("X8") + ":" + info.FileIndexLow.ToString("X8");
        }
    }
}
"@
    Add-Type -TypeDefinition $code
    foreach ($asm in [AppDomain]::CurrentDomain.GetAssemblies()) {
        $found = $asm.GetType("CollectorWorkbookFileIdentity")
        if ($null -ne $found) { return $found }
    }
    return $null
}

function Test-SameCanonicalWorkbookFile([string]$ActualFullName, [string]$ExpectedPath) {
    $left = Get-NormalizedLocalWorkbookPath $ActualFullName
    $right = Get-NormalizedLocalWorkbookPath $ExpectedPath
    if ($left -eq "" -or $right -eq "") { return $false }
    $cmp = [StringComparison]::OrdinalIgnoreCase
    if ([string]::Equals($left, $right, $cmp)) { return $true }
    if (-not (Test-Path -LiteralPath $left)) { return $false }
    if (-not (Test-Path -LiteralPath $right)) { return $false }
    try {
        $identityType = Get-CollectorFileIdentityType
        if ($null -eq $identityType) { return $false }
        $key = $identityType.GetMethod("Key")
        if ($null -eq $key) { return $false }
        $leftKey = [string]$key.Invoke($null, @($left))
        $rightKey = [string]$key.Invoke($null, @($right))
        return ($leftKey -eq $rightKey -and -not [string]::IsNullOrWhiteSpace($leftKey))
    } catch {
        return $false
    }
}

function Get-WorkbookPublicationId([string]$Value) {
    $path = Get-NormalizedLocalWorkbookPath $Value
    if ([string]::IsNullOrWhiteSpace($path)) { return '' }
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($path.ToUpperInvariant())))).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
}

function Get-PublishedWorkbookGate {
    param(
        [bool]$HasIdentityField,
        [bool]$IdentityVerified,
        [string]$FullName,
        [string]$ExpectedPath,
        [string]$Symbol,
        [bool]$ControllerVerified,
        [string]$PublicationId = ""
    )
    $reasons = New-Object System.Collections.Generic.List[string]
    $ordinal = [StringComparison]::Ordinal
    $identity = "285A.T"
    if (-not [string]::Equals([string]$Symbol, $identity, $ordinal)) {
        [void]$reasons.Add("WRONG_SYMBOL_MAPPING")
    }
    $expectedId = Get-WorkbookPublicationId $ExpectedPath
    $proved = $IdentityVerified -and -not [string]::IsNullOrWhiteSpace($expectedId) -and
        $PublicationId -ceq $expectedId -and $FullName -ceq [IO.Path]::GetFileName($ExpectedPath)
    if ($HasIdentityField) {
        if (-not $proved) { [void]$reasons.Add("WRONG_SOURCE_WORKBOOK") }
    } elseif (-not $ControllerVerified) {
        [void]$reasons.Add("WRONG_SOURCE_WORKBOOK")
    }
    return ($reasons -join ",")
}

# Quote freshness (P0-V10-ACCEPTANCE-FIX-20261019). Same rules and reason
# codes as assess_quote_freshness in scripts/ai_shadow_supervisor.py; the
# shared synthetic cases in tests/fixtures/v10_price_freshness_cases.json are
# run against both. Writer time (updated_at, mtime) is not quote time: a
# time-of-day without a dated, offset-carrying source_timestamp_at is never
# fresh. All clock arithmetic is explicit JST, not the PC's local zone.
function Get-JstNow {
    return [DateTimeOffset]::UtcNow.ToOffset([TimeSpan]::FromHours(9))
}

function ConvertFrom-OffsetTimestamp($Value) {
    if ($Value -isnot [string]) { return $null }
    $text = $Value.Trim()
    if ([string]::IsNullOrEmpty($text) -or $text -notmatch '(Z|[+-]\d{2}:?\d{2})$') { return $null }
    $parsed = [DateTimeOffset]::MinValue
    $styles = [Globalization.DateTimeStyles]::None
    if (-not [DateTimeOffset]::TryParse($text, [Globalization.CultureInfo]::InvariantCulture, $styles, [ref]$parsed)) { return $null }
    return $parsed.ToOffset([TimeSpan]::FromHours(9))
}

function Get-MarketSession([DateTimeOffset]$Moment) {
    $local = $Moment.ToOffset([TimeSpan]::FromHours(9))
    if ($local.DayOfWeek -eq [DayOfWeek]::Saturday -or $local.DayOfWeek -eq [DayOfWeek]::Sunday) { return "CLOSED_WEEKEND" }
    $clock = $local.TimeOfDay
    foreach ($window in @(@('09:00:00','11:30:00'), @('12:30:00','15:30:00'))) {
        if ($clock -ge [TimeSpan]::Parse($window[0]) -and $clock -le [TimeSpan]::Parse($window[1])) { return "OPEN_BY_CLOCK" }
    }
    return "CLOSED_OUTSIDE_HOURS"
}

function New-QuoteFreshnessVerdict([string]$State, [string[]]$Reasons, [DateTimeOffset]$Now, $QuoteAt, $Basis, [int]$MaxAge) {
    $list = New-Object System.Collections.Generic.List[string]
    foreach ($reason in @($Reasons)) { if (-not [string]::IsNullOrEmpty($reason) -and -not $list.Contains($reason)) { [void]$list.Add($reason) } }
    $sorted = $list.ToArray()
    [Array]::Sort($sorted, [StringComparer]::Ordinal)
    $fmt = "yyyy-MM-ddTHH:mm:sszzz"
    $inv = [Globalization.CultureInfo]::InvariantCulture
    $age = $null
    $quoteText = $null
    if ($null -ne $QuoteAt) {
        $age = [Math]::Round(($Now - $QuoteAt).TotalSeconds, 3)
        $quoteText = $QuoteAt.ToString($fmt, $inv)
    }
    return [ordered]@{
        schema_version = "price-freshness-1"
        state = $State
        fresh = ($State -eq "FRESH" -and $sorted.Count -eq 0)
        reasons = @($sorted)
        quote_at = $quoteText
        quote_basis = $(if ($Basis -is [string]) { $Basis } else { $null })
        quote_age_seconds = $age
        evaluated_at = $Now.ToString($fmt, $inv)
        max_quote_age_seconds = $MaxAge
        market_session = (Get-MarketSession $Now)
        timezone = "Asia/Tokyo"
        order_allowed = $false
        real_submit_allowed = $false
    }
}

function Get-QuoteFreshness {
    param(
        $LiveObj,
        [DateTimeOffset]$Now = (Get-JstNow),
        $PreviousQuoteAt = $null,
        [int]$MaxQuoteAgeSeconds = 120,
        [int]$FutureSkewSeconds = 5
    )
    $Now = $Now.ToOffset([TimeSpan]::FromHours(9))
    if ($null -eq $LiveObj) { return (New-QuoteFreshnessVerdict "UNKNOWN" @("MISSING_PAYLOAD") $Now $null $null $MaxQuoteAgeSeconds) }
    $diag = $LiveObj.live_price_diagnostics
    if ($null -eq $diag) { $diag = [pscustomobject]@{} }
    $rawTime = $diag.source_timestamp
    $rawAt = $diag.source_timestamp_at
    $basis = $diag.source_timestamp_basis
    $timeOnly = ($rawTime -is [string] -and $rawTime.Trim() -match '^\d{2}:\d{2}:\d{2}$')

    if ($null -eq $rawAt -or ($rawAt -is [string] -and $rawAt -eq "")) {
        $reason = if ($null -eq $rawTime -or ($rawTime -is [string] -and $rawTime -eq "")) { "SOURCE_TIMESTAMP_MISSING" } elseif ($timeOnly) { "SOURCE_DATE_UNKNOWN" } else { "SOURCE_TIMESTAMP_UNPARSEABLE" }
        return (New-QuoteFreshnessVerdict "UNKNOWN" @($reason) $Now $null $basis $MaxQuoteAgeSeconds)
    }
    $quoteAt = ConvertFrom-OffsetTimestamp $rawAt
    if ($null -eq $quoteAt) { return (New-QuoteFreshnessVerdict "UNKNOWN" @("SOURCE_TIMESTAMP_NO_OFFSET") $Now $null $basis $MaxQuoteAgeSeconds) }
    if (@("MS2_RSS_DATE_ITEM", "COLLECTOR_OBSERVED_CHANGE") -cnotcontains [string]$basis -or $basis -isnot [string]) {
        return (New-QuoteFreshnessVerdict "UNKNOWN" @("SOURCE_DATE_BASIS_UNVERIFIED") $Now $quoteAt $basis $MaxQuoteAgeSeconds)
    }

    $invalid = New-Object System.Collections.Generic.List[string]
    $inv = [Globalization.CultureInfo]::InvariantCulture
    if ($timeOnly) {
        if ($quoteAt.ToString("HH:mm:ss", $inv) -ne $rawTime.Trim()) { [void]$invalid.Add("SOURCE_TIMESTAMP_INCONSISTENT") }
    } elseif (-not ($null -eq $rawTime -or ($rawTime -is [string] -and $rawTime -eq ""))) {
        [void]$invalid.Add("SOURCE_TIMESTAMP_UNPARSEABLE")
    }
    $age = ($Now - $quoteAt).TotalSeconds
    if ($age -lt -$FutureSkewSeconds) { [void]$invalid.Add("SOURCE_TIMESTAMP_IN_FUTURE") }

    if ($basis -ceq "COLLECTOR_OBSERVED_CHANGE") {
        $observed = ConvertFrom-OffsetTimestamp $diag.source_timestamp_observed_at
        if ($null -eq $observed) { return (New-QuoteFreshnessVerdict "UNKNOWN" @("SOURCE_OBSERVATION_MISSING") $Now $quoteAt $basis $MaxQuoteAgeSeconds) }
        if (($observed - $Now).TotalSeconds -gt $FutureSkewSeconds) { [void]$invalid.Add("SOURCE_OBSERVATION_IN_FUTURE") }
        if (($quoteAt - $observed).TotalSeconds -gt $FutureSkewSeconds) { [void]$invalid.Add("SOURCE_TIMESTAMP_AFTER_OBSERVATION") }
    }

    $previous = ConvertFrom-OffsetTimestamp $PreviousQuoteAt
    if ($null -ne $previous -and $quoteAt -lt $previous) { [void]$invalid.Add("SOURCE_TIMESTAMP_REGRESSION") }

    $rowDates = New-Object System.Collections.Generic.HashSet[string]
    foreach ($row in @($LiveObj.all_targets)) {
        if ($null -eq $row) { continue }
        $rowAt = $row.source_timestamp_at
        if ($null -eq $rowAt -or ($rowAt -is [string] -and $rowAt -eq "")) { continue }
        $parsedRow = ConvertFrom-OffsetTimestamp $rowAt
        [void]$rowDates.Add($(if ($null -eq $parsedRow) { "INVALID" } else { $parsedRow.ToString("yyyy-MM-dd", $inv) }))
    }
    if ($rowDates.Count -gt 0 -and ($rowDates.Count -ne 1 -or -not $rowDates.Contains($quoteAt.ToString("yyyy-MM-dd", $inv)))) {
        [void]$invalid.Add("MIXED_SOURCE_DATES")
    }

    if ($invalid.Count -gt 0) { return (New-QuoteFreshnessVerdict "INVALID" $invalid.ToArray() $Now $quoteAt $basis $MaxQuoteAgeSeconds) }
    if ($age -gt $MaxQuoteAgeSeconds) { return (New-QuoteFreshnessVerdict "STALE" @("STALE_SOURCE_QUOTE") $Now $quoteAt $basis $MaxQuoteAgeSeconds) }
    return (New-QuoteFreshnessVerdict "FRESH" @() $Now $quoteAt $basis $MaxQuoteAgeSeconds)
}

function Get-RowQuoteFreshness {
    # One board row, judged by its own quote with the identity-quote rules.
    # Same rule as row_quote_freshness in scripts/ai_shadow_supervisor.py: a
    # fresh identity quote says nothing about another row's price, and a row
    # dated on another JST day than the identity quote is never fresh.
    # The Gateway also refuses a row whose quote went back in time against
    # the last quote it served for that ticker.
    param(
        $Row,
        [DateTimeOffset]$Now = (Get-JstNow),
        $BoardQuoteAt = $null,
        $PreviousQuoteAt = $null,
        [int]$MaxQuoteAgeSeconds = 120
    )
    $fields = [ordered]@{}
    $isObject = ($Row -is [System.Management.Automation.PSCustomObject]) -or ($Row -is [System.Collections.IDictionary])
    foreach ($key in @("source_timestamp", "source_timestamp_at", "source_timestamp_basis", "source_timestamp_observed_at")) {
        $fields[$key] = $(if ($isObject) { $Row.$key } else { $null })
    }
    $probe = [pscustomobject]@{ live_price_diagnostics = [pscustomobject]$fields; all_targets = @() }
    $verdict = Get-QuoteFreshness -LiveObj $probe -Now $Now -PreviousQuoteAt $PreviousQuoteAt -MaxQuoteAgeSeconds $MaxQuoteAgeSeconds
    if ($verdict.fresh -eq $true) {
        $board = ConvertFrom-OffsetTimestamp $BoardQuoteAt
        $rowAt = ConvertFrom-OffsetTimestamp $verdict.quote_at
        $inv = [Globalization.CultureInfo]::InvariantCulture
        if ($null -eq $board -or $null -eq $rowAt -or $rowAt.ToString("yyyy-MM-dd", $inv) -ne $board.ToString("yyyy-MM-dd", $inv)) {
            $reason = if ($null -eq $board) { "BOARD_QUOTE_DATE_UNKNOWN" } else { "MIXED_SOURCE_DATES" }
            $verdict = New-QuoteFreshnessVerdict "INVALID" @($reason) $Now $rowAt $verdict.quote_basis $MaxQuoteAgeSeconds
        }
    }
    return $verdict
}

function Get-BoardRowFreshness {
    # Every row of all_targets must carry its own fresh quote before
    # /live_ms2.json is served as LIVE. Masking single rows cannot be made
    # complete: market_state, breadth_pct, valid, kioxia, top5, hold_top5,
    # pts_top5, ir_pts_top5 and every row's market_state/breadth_pct are
    # computed over all rows. So one stale, undated, future or regressed row
    # rejects the whole response. Unknown is not fresh. Every row's verdict is
    # still returned (row_verdicts, state_counts) so the observation layer can
    # report fresh and missing rows without serving any derived value.
    param(
        $LiveObj,
        [DateTimeOffset]$Now = (Get-JstNow),
        $BoardQuoteAt = $null,
        $PreviousRowQuotes = $null,
        [int]$MaxQuoteAgeSeconds = 120
    )
    $reasons = New-Object System.Collections.Generic.List[string]
    $accepted = [ordered]@{}
    $notFresh = New-Object System.Collections.Generic.List[object]
    $verdictRows = New-Object System.Collections.Generic.List[object]
    $stateCounts = [ordered]@{ FRESH = 0; STALE = 0; UNKNOWN = 0; INVALID = 0 }
    $rowCount = 0
    $freshCount = 0
    $rows = $null
    if ($null -ne $LiveObj) { $rows = $LiveObj.all_targets }
    if ($null -eq $rows -or $rows -is [string] -or @($rows).Count -eq 0) {
        [void]$reasons.Add("BOARD_ROWS_MISSING")
    } else {
        $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
        foreach ($row in @($rows)) {
            $rowCount++
            $isObject = ($row -is [System.Management.Automation.PSCustomObject]) -or ($row -is [System.Collections.IDictionary])
            $ticker = $(if ($isObject) { $row.ticker } else { $null })
            if ($ticker -isnot [string] -or [string]::IsNullOrWhiteSpace($ticker)) {
                [void]$reasons.Add("ROW_TICKER_MISSING")
                $stateCounts.UNKNOWN++
                [void]$verdictRows.Add([ordered]@{ ticker = $null; state = "UNKNOWN"; reasons = @("ROW_TICKER_MISSING"); quote_at = $null; quote_age_seconds = $null })
                if ($notFresh.Count -lt 10) { [void]$notFresh.Add([ordered]@{ ticker = $null; state = "UNKNOWN"; reasons = @("ROW_TICKER_MISSING") }) }
                continue
            }
            if (-not $seen.Add($ticker)) {
                [void]$reasons.Add("ROW_TICKER_DUPLICATE")
                $stateCounts.INVALID++
                [void]$verdictRows.Add([ordered]@{ ticker = $ticker; state = "INVALID"; reasons = @("ROW_TICKER_DUPLICATE"); quote_at = $null; quote_age_seconds = $null })
                if ($notFresh.Count -lt 10) { [void]$notFresh.Add([ordered]@{ ticker = $ticker; state = "INVALID"; reasons = @("ROW_TICKER_DUPLICATE") }) }
                continue
            }
            $previous = $null
            if ($PreviousRowQuotes -is [System.Collections.IDictionary] -and $PreviousRowQuotes.Contains($ticker)) { $previous = $PreviousRowQuotes[$ticker] }
            $verdict = Get-RowQuoteFreshness -Row $row -Now $Now -BoardQuoteAt $BoardQuoteAt -PreviousQuoteAt $previous -MaxQuoteAgeSeconds $MaxQuoteAgeSeconds
            $stateName = [string]$verdict.state
            if ($stateCounts.Contains($stateName)) { $stateCounts[$stateName]++ } else { $stateCounts.INVALID++ }
            [void]$verdictRows.Add([ordered]@{ ticker = $ticker; state = $stateName; reasons = @($verdict.reasons); quote_at = $verdict.quote_at; quote_age_seconds = $verdict.quote_age_seconds })
            if ($verdict.fresh -eq $true) {
                $freshCount++
                $accepted[$ticker] = $verdict.quote_at
                continue
            }
            $own = @($verdict.reasons | Where-Object { -not [string]::IsNullOrEmpty([string]$_) })
            if ($own.Count -eq 0) { $own = @("FRESHNESS_NOT_FRESH") }
            foreach ($r in $own) { [void]$reasons.Add("ROW_" + [string]$r) }
            if ($notFresh.Count -lt 10) { [void]$notFresh.Add([ordered]@{ ticker = $ticker; state = [string]$verdict.state; reasons = @($own) }) }
        }
    }
    if ($reasons.Count -gt 0) { [void]$reasons.Add("ROW_QUOTE_NOT_FRESH") }
    $unique = @($reasons | Select-Object -Unique)
    $sorted = [string[]]$unique
    if ($null -eq $sorted) { $sorted = [string[]]@() }
    [Array]::Sort($sorted, [StringComparer]::Ordinal)
    return [ordered]@{
        schema_version = "board-row-freshness-1"
        fresh = ($sorted.Count -eq 0)
        reasons = @($sorted)
        row_count = $rowCount
        fresh_row_count = $freshCount
        not_fresh_row_count = ($rowCount - $freshCount)
        not_fresh_sample = $notFresh.ToArray()
        state_counts = $stateCounts
        row_verdicts = $verdictRows.ToArray()
        accepted_quote_at = $accepted
        board_quote_at = $(if ($BoardQuoteAt -is [string]) { $BoardQuoteAt } else { $null })
        max_quote_age_seconds = $MaxQuoteAgeSeconds
        order_allowed = $false
        real_submit_allowed = $false
    }
}

function Get-ExpectedUniverse([string]$RuntimeDirectory) {
    # The Collector watches the first 100 stocks of watchlist_100.json in its
    # runtime directory (the Controller pins that file's hash at start-up).
    # The board is complete only against that set. When the set cannot be
    # read, has fewer than 100 tickers, or repeats one, completeness is not
    # verified and is never reported as passing.
    $expectedCount = 100
    $result = [ordered]@{ verified = $false; reason = "UNIVERSE_WATCHLIST_MISSING"; expected_count = $expectedCount; tickers = [string[]]@() }
    if ([string]::IsNullOrWhiteSpace($RuntimeDirectory)) { return $result }
    $path = Join-Path $RuntimeDirectory "watchlist_100.json"
    if (-not (Test-Path -LiteralPath $path)) { return $result }
    try {
        $watch = [IO.File]::ReadAllText($path, [Text.Encoding]::UTF8) | ConvertFrom-Json
        $list = New-Object System.Collections.Generic.List[string]
        $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
        $stocks = $null
        if ($null -ne $watch) { $stocks = $watch.stocks }
        if ($null -eq $stocks -or $stocks -isnot [System.Management.Automation.PSCustomObject]) { $result.reason = "UNIVERSE_WATCHLIST_INVALID"; return $result }
        foreach ($prop in @($stocks.PSObject.Properties)) {
            if ($list.Count -ge $expectedCount) { break }
            $ticker = $null
            if ($null -ne $prop.Value) { $ticker = $prop.Value.ticker }
            if ($ticker -isnot [string] -or [string]::IsNullOrWhiteSpace($ticker)) { $result.reason = "UNIVERSE_WATCHLIST_INVALID"; return $result }
            $ticker = $ticker.Trim()
            if (-not $seen.Add($ticker)) { $result.reason = "UNIVERSE_WATCHLIST_DUPLICATE"; return $result }
            [void]$list.Add($ticker)
        }
        if ($list.Count -ne $expectedCount) { $result.reason = "UNIVERSE_WATCHLIST_COUNT"; return $result }
        $result.verified = $true
        $result.reason = $null
        $result.tickers = $list.ToArray()
    } catch {
        $result.reason = "UNIVERSE_WATCHLIST_UNREADABLE"
    }
    return $result
}

function Get-BoardAvailability {
    # Decision availability of one live_ms2.json board, kept apart from the
    # health of the data source. The board may be used for signals, ranking
    # or any derived value only when the identity quote is fresh, every
    # all_targets row is fresh, and the rows are exactly the expected
    # universe. Missing rows are reported, never dropped: 99 present rows of
    # 100 are an incomplete board, not a 99-symbol board. The Collector's
    # valid>=90 quality count is reported separately and grants nothing.
    param($LiveObj, $QuoteFreshness, $RowFreshness, $Universe)
    $reasons = New-Object System.Collections.Generic.List[string]
    $identityFresh = ($null -ne $QuoteFreshness -and $QuoteFreshness.fresh -eq $true)
    if (-not $identityFresh) { [void]$reasons.Add("IDENTITY_QUOTE_NOT_FRESH") }
    $rowsFresh = ($null -ne $RowFreshness -and $RowFreshness.fresh -eq $true)
    if ($null -eq $RowFreshness) {
        [void]$reasons.Add("ROW_QUOTE_NOT_FRESH")
    } elseif (-not $rowsFresh) {
        foreach ($r in @($RowFreshness.reasons)) { if (-not [string]::IsNullOrEmpty([string]$r)) { [void]$reasons.Add([string]$r) } }
    }
    $present = New-Object System.Collections.Generic.List[string]
    $rows = $null
    if ($null -ne $LiveObj) { $rows = $LiveObj.all_targets }
    $rowCount = 0
    if ($null -ne $rows -and $rows -isnot [string]) {
        foreach ($row in @($rows)) {
            $rowCount++
            $isObject = ($row -is [System.Management.Automation.PSCustomObject]) -or ($row -is [System.Collections.IDictionary])
            $ticker = $(if ($isObject) { $row.ticker } else { $null })
            if ($ticker -is [string] -and -not [string]::IsNullOrWhiteSpace($ticker)) { [void]$present.Add($ticker.Trim()) }
        }
    }
    $declared = $null
    if ($null -ne $LiveObj) { $declared = $LiveObj.universe }
    $declaredOk = (($declared -is [int]) -or ($declared -is [long])) -and $declared -gt 0
    if (-not $declaredOk) { [void]$reasons.Add("UNIVERSE_DECLARED_MISSING") }
    elseif ($declared -ne $rowCount) { [void]$reasons.Add("UNIVERSE_DECLARED_MISMATCH") }
    $missing = New-Object System.Collections.Generic.List[string]
    $unexpected = New-Object System.Collections.Generic.List[string]
    $expectedCount = $null
    $universeVerified = ($null -ne $Universe -and $Universe.verified -eq $true)
    if (-not $universeVerified) {
        [void]$reasons.Add("UNIVERSE_UNVERIFIED")
        if ($null -ne $Universe -and -not [string]::IsNullOrEmpty([string]$Universe.reason)) { [void]$reasons.Add([string]$Universe.reason) }
    } else {
        $expected = @($Universe.tickers)
        $expectedCount = $expected.Count
        $expectedSet = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
        foreach ($t in $expected) { [void]$expectedSet.Add([string]$t) }
        $presentSet = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
        foreach ($t in $present) { [void]$presentSet.Add($t) }
        foreach ($t in $expected) { if (-not $presentSet.Contains([string]$t)) { [void]$missing.Add([string]$t) } }
        foreach ($t in $presentSet) { if (-not $expectedSet.Contains($t)) { [void]$unexpected.Add($t) } }
        if ($missing.Count -gt 0) { [void]$reasons.Add("UNIVERSE_ROW_MISSING") }
        if ($unexpected.Count -gt 0) { [void]$reasons.Add("UNIVERSE_ROW_UNEXPECTED") }
        if ($declaredOk -and $declared -ne $expectedCount) { [void]$reasons.Add("UNIVERSE_DECLARED_MISMATCH") }
    }
    $unique = @($reasons | Select-Object -Unique)
    $sorted = [string[]]$unique
    if ($null -eq $sorted) { $sorted = [string[]]@() }
    [Array]::Sort($sorted, [StringComparer]::Ordinal)
    $completenessReasons = @($sorted | Where-Object { $_ -like 'UNIVERSE_*' })
    $status = "AVAILABLE"
    if (-not $identityFresh) { $status = "BLOCKED_IDENTITY_QUOTE" }
    elseif ($completenessReasons.Count -gt 0) { $status = "BLOCKED_UNIVERSE_INCOMPLETE" }
    elseif (-not $rowsFresh) { $status = "BLOCKED_ROW_QUOTES" }
    $counts = [ordered]@{ FRESH = 0; STALE = 0; UNKNOWN = 0; INVALID = 0; MISSING = $missing.Count }
    if ($null -ne $RowFreshness -and $null -ne $RowFreshness.state_counts) {
        foreach ($k in @("FRESH", "STALE", "UNKNOWN", "INVALID")) { $counts[$k] = [int]$RowFreshness.state_counts[$k] }
    }
    $base = $(if ($null -ne $expectedCount) { $expectedCount } elseif ($declaredOk) { [int]$declared } else { $rowCount })
    $coverage = $null
    if ($base -gt 0) { $coverage = [Math]::Round(100.0 * $counts.FRESH / $base, 1) }
    $valid = $null
    if ($null -ne $LiveObj -and (($LiveObj.valid -is [int]) -or ($LiveObj.valid -is [long]))) { $valid = [int]$LiveObj.valid }
    $missingSample = @($missing | Select-Object -First 10)
    $unexpectedSample = @($unexpected | Select-Object -First 10)
    return [ordered]@{
        schema_version = "board-availability-1"
        decision_available = ($sorted.Count -eq 0)
        availability_status = $status
        reasons = @($sorted)
        identity_quote_fresh = $identityFresh
        universe_verified = $universeVerified
        universe_expected_count = $expectedCount
        universe_declared = $(if ($declaredOk) { [int]$declared } else { $null })
        row_count = $rowCount
        state_counts = $counts
        fresh_coverage_pct = $coverage
        missing_count = $missing.Count
        missing_sample = $missingSample
        unexpected_count = $unexpected.Count
        unexpected_sample = $unexpectedSample
        collector_valid_count = $valid
        collector_valid_quality_pass = ($null -ne $valid -and $valid -ge 90)
        order_allowed = $false
        real_submit_allowed = $false
    }
}

function Read-LiveSnapshot([string]$Path) {
    # Read live_ms2.json once. The bytes judged are the bytes served; reading
    # the file again after the check could serve a newer, unchecked payload.
    $item = Get-Item -LiteralPath $Path
    $snap = [ordered]@{
        bytes = [byte[]]@()
        obj = $null
        updated_at = $null
        payload_age_seconds = [double]::PositiveInfinity
        file_age_seconds = ((Get-Date) - $item.LastWriteTime).TotalSeconds
        file_mtime = $item.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss')
    }
    try {
        $snap.bytes = [IO.File]::ReadAllBytes($Path)
        $text = [Text.Encoding]::UTF8.GetString($snap.bytes)
        if ($text.Length -gt 0 -and $text[0] -eq [char]0xFEFF) { $text = $text.Substring(1) }
        $snap.obj = $text | ConvertFrom-Json
        $snap.updated_at = [string]$snap.obj.updated_at
        if (-not [string]::IsNullOrWhiteSpace($snap.updated_at)) {
            $clean = $snap.updated_at -replace '\s+JST\s*$',''
            $parsed = Get-Date $clean -ErrorAction Stop
            $snap.payload_age_seconds = ((Get-Date) - $parsed).TotalSeconds
        }
    } catch {
        $snap.payload_age_seconds = [double]::PositiveInfinity
        $snap.obj = $null
    }
    return $snap
}

function Get-AvailabilitySummary($Availability) {
    # The consumer-facing subset of Get-BoardAvailability (no ticker lists
    # beyond the 10-item samples).
    if ($null -eq $Availability) { return $null }
    return [ordered]@{
        decision_available = ($Availability.decision_available -eq $true)
        availability_status = [string]$Availability.availability_status
        reasons = @($Availability.reasons)
        universe_verified = ($Availability.universe_verified -eq $true)
        universe_expected_count = $Availability.universe_expected_count
        universe_declared = $Availability.universe_declared
        row_count = $Availability.row_count
        state_counts = $Availability.state_counts
        fresh_coverage_pct = $Availability.fresh_coverage_pct
        missing_count = $Availability.missing_count
        missing_sample = @($Availability.missing_sample)
        unexpected_count = $Availability.unexpected_count
        collector_valid_count = $Availability.collector_valid_count
        collector_valid_quality_pass = ($Availability.collector_valid_quality_pass -eq $true)
        order_allowed = $false
        real_submit_allowed = $false
    }
}

function Import-ServedHistory([string]$Path) {
    # Restore the served quote history saved by an earlier Gateway process.
    # NO_HISTORY_FILE: first start or the file was removed; the regression
    # check has nothing to compare against until the first LIVE response, and
    # /health says so. UNREADABLE: LIVE is refused until the file is readable
    # or removed by the OWNER; an unknown history is not an empty one.
    $result = [ordered]@{ state = "NO_HISTORY_FILE"; identity = $null; rows = @{} }
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path)) { return $result }
    try {
        $saved = [IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8) | ConvertFrom-Json
        if ($null -eq $saved -or [string]$saved.schema_version -cne "v10-served-quotes-1") { throw "SCHEMA" }
        $identity = $saved.identity_quote_at
        if ($null -ne $identity -and $null -eq (ConvertFrom-OffsetTimestamp $identity)) { throw "IDENTITY" }
        $rows = @{}
        if ($null -ne $saved.row_quote_at) {
            foreach ($prop in @($saved.row_quote_at.PSObject.Properties)) {
                if ($null -eq (ConvertFrom-OffsetTimestamp $prop.Value)) { throw "ROW" }
                $rows[[string]$prop.Name] = [string]$prop.Value
            }
        }
        $result.state = "RESTORED"
        $result.identity = $identity
        $result.rows = $rows
    } catch {
        $result.state = "UNREADABLE"
    }
    return $result
}

function Save-ServedHistory([string]$Path, $IdentityQuoteAt, $RowQuotes) {
    if ([string]::IsNullOrWhiteSpace($Path)) { return $false }
    $sortedRows = [ordered]@{}
    foreach ($key in @($RowQuotes.Keys | Sort-Object)) { $sortedRows[[string]$key] = $RowQuotes[$key] }
    $body = [ordered]@{
        schema_version = "v10-served-quotes-1"
        identity_quote_at = $IdentityQuoteAt
        row_quote_at = $sortedRows
        real_submit_allowed = $false
    } | ConvertTo-Json -Depth 4
    $temporary = $Path + ".tmp"
    try {
        [IO.File]::WriteAllText($temporary, $body, [Text.UTF8Encoding]::new($false))
        if (Test-Path -LiteralPath $Path) { [IO.File]::Replace($temporary, $Path, $null) } else { [IO.File]::Move($temporary, $Path) }
        return $true
    } catch {
        return $false
    }
}

function Get-CombinedQuoteFreshness($GatewayVerdict, $ShadowVerdict) {
    # /health is fresh only when its own verdict and the Shadow supervisor's
    # published verdict are both FRESH. Either side missing, not fresh, or the
    # two disagreeing (one FRESH, one not) is fail-closed.
    $reasons = New-Object System.Collections.Generic.List[string]
    foreach ($verdict in @($GatewayVerdict, $ShadowVerdict)) {
        if ($null -eq $verdict) { [void]$reasons.Add("FRESHNESS_VERDICT_MISSING"); continue }
        if ($verdict.fresh -ne $true -or [string]$verdict.state -cne "FRESH") {
            $own = @($verdict.reasons | Where-Object { -not [string]::IsNullOrEmpty([string]$_) })
            if ($own.Count -eq 0) { [void]$reasons.Add("FRESHNESS_NOT_FRESH") } else { foreach ($r in $own) { [void]$reasons.Add([string]$r) } }
        }
        if ($verdict.real_submit_allowed -ne $false) { [void]$reasons.Add("REAL_SUBMIT_NOT_FALSE") }
    }
    if ($null -eq $GatewayVerdict -or $null -eq $ShadowVerdict -or
        [string]$GatewayVerdict.state -cne [string]$ShadowVerdict.state -or
        ($GatewayVerdict.fresh -eq $true) -ne ($ShadowVerdict.fresh -eq $true)) {
        [void]$reasons.Add("FRESHNESS_VERDICT_MISMATCH")
    }
    $unique = @($reasons | Select-Object -Unique)
    $sorted = [string[]]$unique
    if ($null -eq $sorted) { $sorted = [string[]]@() }
    [Array]::Sort($sorted, [StringComparer]::Ordinal)
    return [ordered]@{ fresh = ($sorted.Count -eq 0); reasons = @($sorted); real_submit_allowed = $false }
}

function Get-LivePriceRejection {
    param(
        $LiveObj,
        [double]$FileAgeSeconds,
        [double]$PayloadAgeSeconds,
        $UpdatedAtRaw,
        $FileMtime,
        [int]$MaxAgeSeconds = 60,
        $QuoteFreshness = $null,
        $RowFreshness = $null,
        $Availability = $null
    )
    $reasons = New-Object System.Collections.Generic.List[string]
    # A recent write is not a recent quote. Without a fresh, dated quote the
    # payload is stale even when updated_at and mtime are seconds old.
    if ($null -eq $QuoteFreshness) { $QuoteFreshness = Get-QuoteFreshness -LiveObj $LiveObj }
    if ($QuoteFreshness.fresh -ne $true) {
        foreach ($r in @($QuoteFreshness.reasons)) { if (-not [string]::IsNullOrEmpty([string]$r)) { [void]$reasons.Add([string]$r) } }
        if (@($QuoteFreshness.reasons).Count -eq 0) { [void]$reasons.Add("FRESHNESS_NOT_FRESH") }
    }
    # A fresh identity quote does not make other rows fresh. Every row must
    # pass its own quote check and the rows must be exactly the expected
    # universe, or the whole response is refused.
    if ($null -eq $RowFreshness) { $RowFreshness = Get-BoardRowFreshness -LiveObj $LiveObj -BoardQuoteAt $QuoteFreshness.quote_at }
    if ($null -eq $Availability) { $Availability = Get-BoardAvailability -LiveObj $LiveObj -QuoteFreshness $QuoteFreshness -RowFreshness $RowFreshness -Universe (Get-ExpectedUniverse $RuntimeDir) }
    if ($Availability.decision_available -ne $true) {
        foreach ($r in @($Availability.reasons)) { if (-not [string]::IsNullOrEmpty([string]$r)) { [void]$reasons.Add([string]$r) } }
        if (@($Availability.reasons).Count -eq 0) { [void]$reasons.Add("BOARD_DECISION_UNAVAILABLE") }
    }
    $canonicalSource = "MarketSpeed II RSS / local PC"
    $fresh = (
        $FileAgeSeconds -ge 0 -and $FileAgeSeconds -le $MaxAgeSeconds -and
        $PayloadAgeSeconds -ge 0 -and $PayloadAgeSeconds -le $MaxAgeSeconds
    )
    if (-not $fresh) { [void]$reasons.Add("STALE_OR_MISSING_TIMESTAMP") }
    $source = if ($null -ne $LiveObj) { [string]$LiveObj.source } else { "" }
    $publicMarker = -join @([char]0x516C, [char]0x958B)
    $ordinal = [StringComparison]::Ordinal
    $cachedSource = (
        $source -ne $canonicalSource -or
        $source -match '(?i)sample|snapshot|cache|static|fixture' -or
        $source.IndexOf($publicMarker, $ordinal) -ge 0
    )
    if ($cachedSource) {
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
    $hasIdentityField = $false
    $identityVerified = $false
    $workbookFullName = ""
    $identitySymbol = [string]$symbol
    if ($null -ne $diag) {
        foreach ($prop in $diag.PSObject.Properties) {
            if ($prop.Name -eq "workbook_identity_verified") {
                $hasIdentityField = $true
                $identityVerified = ($prop.Value -eq $true)
            } elseif ($prop.Name -eq "workbook_full_name") {
                $workbookFullName = [string]$prop.Value
            }
        }
    }
    $canonicalWorkbookPath = ""
    if (-not [string]::IsNullOrWhiteSpace($RuntimeDir)) {
        $canonicalWorkbookPath = Join-Path $RuntimeDir "Kioxia_MS2_RSS_Live_Signals.xlsx"
    }
    $gateText = Get-PublishedWorkbookGate $hasIdentityField $identityVerified $workbookFullName $canonicalWorkbookPath $identitySymbol $workbookVerified ([string]$diag.workbook_identity_id)
    if (-not [string]::IsNullOrWhiteSpace($gateText)) {
        foreach ($gateReason in ($gateText -split ",")) {
            if (-not [string]::IsNullOrWhiteSpace($gateReason)) { [void]$reasons.Add($gateReason) }
        }
    }
    $unique = @($reasons | Select-Object -Unique)
    if ($unique.Count -eq 0) { return $null }
    $freshnessCodes = @("STALE_SOURCE_QUOTE","SOURCE_DATE_UNKNOWN","SOURCE_TIMESTAMP_MISSING","SOURCE_TIMESTAMP_UNPARSEABLE",
        "SOURCE_TIMESTAMP_NO_OFFSET","SOURCE_DATE_BASIS_UNVERIFIED","SOURCE_TIMESTAMP_INCONSISTENT","SOURCE_TIMESTAMP_IN_FUTURE",
        "SOURCE_OBSERVATION_MISSING","SOURCE_OBSERVATION_IN_FUTURE","SOURCE_TIMESTAMP_AFTER_OBSERVATION",
        "SOURCE_TIMESTAMP_REGRESSION","MIXED_SOURCE_DATES","FRESHNESS_NOT_FRESH","MISSING_PAYLOAD")
    $identity = @($unique | Where-Object { $_ -notin (@("STALE_OR_MISSING_TIMESTAMP","LIVE_VALUES_UNAVAILABLE","INSUFFICIENT_COVERAGE","IDENTITY_QUOTE_NOT_FRESH","BOARD_DECISION_UNAVAILABLE") + $freshnessCodes) -and $_ -notmatch '^(ROW_|UNIVERSE_|BOARD_ROWS_MISSING$)' })
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
        current_price = $null
        collector_pid = $collectorPid
        collector_count = $collectorCount
        watcher_count = $watcherCount
        data_conflict = [bool]($dataConflict -or ($identity.Count -gt 0))
        real_submit_allowed = $false
        live_values_available = $false
        max_age_seconds = $MaxAgeSeconds
        quote_freshness = $QuoteFreshness
        row_freshness = [ordered]@{
            fresh = ($RowFreshness.fresh -eq $true)
            reasons = @($RowFreshness.reasons)
            row_count = $RowFreshness.row_count
            fresh_row_count = $RowFreshness.fresh_row_count
            not_fresh_row_count = $RowFreshness.not_fresh_row_count
            not_fresh_sample = @($RowFreshness.not_fresh_sample)
        }
        availability = (Get-AvailabilitySummary $Availability)
        source_reasons = @($identity)
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


# P0 archival provenance: V10 checkout may lag behind generated main.
# Never rewrite historical numbers or make snapshot data appear live.
function Add-StaticSnapshotNotice([string]$Html, [datetime]$ReferenceDate) {
    if ([string]::IsNullOrEmpty($Html)) { return $Html }
    if ($Html.Contains('id="v10-static-snapshot-warning"')) { return $Html }
    $header = [regex]::Match($Html, '(?is)<header\b[^>]*>.*?</header>')
    $stamp = if ($header.Success) { [regex]::Match($header.Value, '\b\d{4}-\d{2}-\d{2}\b') } else { $null }
    $dateText = '&#19981;&#26126;'
    $status = 'DATE_UNVERIFIED'
    $detail = '&#22266;&#23450;&#20998;&#26512;&#12398;&#26356;&#26032;&#26085;&#12364;&#19981;&#26126;&#12414;&#12383;&#12399;&#26410;&#26469;&#12391;&#12377;&#12290;&#29694;&#22312;&#12398;&#24066;&#22580;&#12487;&#12540;&#12479;&#12392;&#12375;&#12390;&#20351;&#29992;&#31105;&#27490;&#12391;&#12377;&#12290;'
    if ($null -ne $stamp -and $stamp.Success) {
        $parsed = [datetime]::MinValue
        $ok = [datetime]::TryParseExact($stamp.Value, 'yyyy-MM-dd',
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::None, [ref]$parsed)
        if ($ok) {
            $dateText = [Net.WebUtility]::HtmlEncode($stamp.Value)
            if ($parsed.Date -lt $ReferenceDate.Date) {
                $status = 'HISTORICAL'
                $detail = '&#12371;&#12398;&#30011;&#38754;&#12398;&#22266;&#23450;&#20998;&#26512;&#12399;&#36942;&#21435;&#12398;&#26085;&#20184;&#12391;&#12377;&#12290;&#29694;&#22312;&#12398;&#24066;&#22580;&#21028;&#26029;&#12420;&#22770;&#36023;&#12469;&#12452;&#12531;&#12395;&#20351;&#29992;&#12375;&#12394;&#12356;&#12391;&#12367;&#12384;&#12373;&#12356;&#12290;'
            } elseif ($parsed.Date -eq $ReferenceDate.Date) {
                $status = 'SAME_DAY_STATIC'
                $detail = '&#26412;&#26085;&#12398;&#26085;&#20184;&#12391;&#12418;&#12289;&#22266;&#23450;&#20998;&#26512;&#12392;LIVE&#35251;&#28204;&#12399;&#21029;&#12391;&#12377;&#12290;Gateway&#12398;&#29694;&#22312;&#20516;&#12539;&#39854;&#24230;&#12539;&#20986;&#25152;&#12434;&#29420;&#31435;&#30906;&#35469;&#12377;&#12427;&#12414;&#12391;&#22770;&#36023;&#31105;&#27490;&#12391;&#12377;&#12290;'
            }
        }
    }
    $notice = '<aside id="v10-static-snapshot-warning" role="status" ' +
        'data-snapshot-status="' + $status + '" ' +
        'style="position:relative;z-index:10;margin:12px 20px;padding:14px 16px;' +
        'border:2px solid #d7a145;border-radius:8px;background:#191811;color:#f2deb8;' +
        'font:600 13px/1.6 system-ui,sans-serif;">' +
        '<strong>&#22266;&#23450;&#12473;&#12490;&#12483;&#12503;&#12471;&#12519;&#12483;&#12488;&#65372;LIVE&#24773;&#22577;&#12391;&#12399;&#12354;&#12426;&#12414;&#12379;&#12435;</strong><div>' + $detail + '</div>' +
        '<div>&#30011;&#38754;&#20869;&#12398;&#22522;&#28310;&#26085;: <time>' + $dateText + '</time> / &#23455;&#27880;&#25991;&#31105;&#27490;&#65295;&#22266;&#23450;&#12487;&#12540;&#12479;&#12399;&#26410;&#35469;&#35388;</div></aside>'
    $mainTag = [regex]::Match($Html, '(?i)<main\b')
    if ($mainTag.Success) { return $Html.Insert($mainTag.Index, $notice) }
    $closing = $Html.IndexOf('</body>', [StringComparison]::OrdinalIgnoreCase)
    if ($closing -ge 0) { return $Html.Insert($closing, $notice) }
    return $Html + $notice
}




if ($BrainObserverSelfTest) {
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ([IO.Path]::GetRandomFileName())
    [void][IO.Directory]::CreateDirectory($tmp)
    try {
        $file = Join-Path $tmp 'ai_brain_observer_status_v1.json'
        $stamp = ([datetimeoffset]::UtcNow).ToString('o')
        $fixture = [ordered]@{
            schema_version = 'ai-brain-observer-1'
            component_role = 'INDEPENDENT_BRAIN_OBSERVER_NOT_TRADE_ENGINE'
            engine_pid = 2222
            updated_at = $stamp
            state = 'OBSERVATION_ONLY'
            source_publication_at = $stamp
            last_market_data_at = $null
            exchange_tick_date_verified = $false
            signal_provenance_verified = $false
            real_submit_allowed = $false
            source_authenticated = $false
            cross_source_join_allowed = $false
            promotion_eligible = $false
            tested_expectancy_available = $false
            eligible_observed_n = 0
            watch_counts = @{ OR15_ABOVE_VWAP_WATCH = 3; OR15_BELOW_VWAP_WATCH = 4 }
        }
        [IO.File]::WriteAllText($file, ($fixture | ConvertTo-Json -Depth 4))
        $good = Get-V10BrainObserverProof $tmp 2222 $true
        if ($good.status -ne 'BRAIN_OBSERVING_PUBLICATION_ONLY' -or $good.watch_count -ne 7) { throw ('BRAIN_SYNTHETIC_FAILED ' + $good.status) }
        if ((Get-V10BrainObserverProof $tmp 2222 $false).status -ne 'BRAIN_PROCESS_UNVERIFIED') { throw 'BRAIN_PROCESS_GUARD_FAILED' }
        if ((Get-V10BrainObserverProof $tmp 2223 $true).status -ne 'BRAIN_PID_MISMATCH') { throw 'BRAIN_PID_GUARD_FAILED' }
        $fixture.source_authenticated = $true
        [IO.File]::WriteAllText($file, ($fixture | ConvertTo-Json -Depth 4))
        if ((Get-V10BrainObserverProof $tmp 2222 $true).status -ne 'BRAIN_UNSAFE_EVIDENCE_CLAIM') { throw 'BRAIN_TRUST_CLAIM_GUARD_FAILED' }
        $fixture.source_authenticated = $false
        $fixture.updated_at = '2026-01-01T00:00:00+00:00'
        [IO.File]::WriteAllText($file, ($fixture | ConvertTo-Json -Depth 4))
        if ((Get-V10BrainObserverProof $tmp 2222 $true).status -ne 'BRAIN_STALE_OR_FUTURE') { throw 'BRAIN_STALE_GUARD_FAILED' }
        $fixture.updated_at = $stamp
        $fixture.state = 'BLOCKED'
        [IO.File]::WriteAllText($file, ($fixture | ConvertTo-Json -Depth 4))
        if ((Get-V10BrainObserverProof $tmp 2222 $true).status -ne 'BRAIN_INPUT_BLOCKED') { throw 'BRAIN_BLOCKED_INPUT_GUARD_FAILED' }
        [IO.File]::Delete($file)
        if ((Get-V10BrainObserverProof $tmp 2222 $true).status -ne 'BRAIN_FILE_UNAVAILABLE') { throw 'BRAIN_MISSING_GUARD_FAILED' }
    } finally {
        if ([IO.Directory]::Exists($tmp)) { [IO.Directory]::Delete($tmp, $true) }
    }
    Write-Output 'PASS: V10_INDEPENDENT_BRAIN_OBSERVER_SYNTHETIC'
    exit 0
}

if ($ShadowHeartbeatSelfTest) {
    # Synthetic ProcessVerified=true is a fixture, not real process attestation.
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ([IO.Path]::GetRandomFileName())
    [void][IO.Directory]::CreateDirectory($tmp)
    try {
        $path = Join-Path $tmp 'ai_shadow_status.json'
        $stamp = ([datetimeoffset]::UtcNow).ToString('o')
        $fixture = [ordered]@{
            schema_version = 'ai-shadow-supervisor-1'
            engine_pid = 4242
            state = 'RUNNING'
            updated_at = $stamp
            ui_independent = $true
            real_submit_allowed = $false
            resume_blocked = $false
        }
        [IO.File]::WriteAllText($path, ($fixture | ConvertTo-Json -Depth 4))
        $ok = Get-V10ShadowHeartbeatProof $tmp 4242 $true
        if ($ok.status -ne 'SHADOW_RUNNING_HEARTBEAT_ONLY' -or $null -eq $ok.heartbeat_at) { throw ('SHADOW_SYNTHETIC_HEARTBEAT_FAILED: ' + $ok.status) }
        $mismatch = Get-V10ShadowHeartbeatProof $tmp 4243 $true
        if ($mismatch.status -ne 'SHADOW_PID_MISMATCH' -or $null -ne $mismatch.heartbeat_at) { throw 'SHADOW_PID_GUARD_FAILED' }
        if ((Get-V10ShadowHeartbeatProof $tmp 4242 $false).status -ne 'SHADOW_PROCESS_UNVERIFIED') { throw 'SHADOW_PROCESS_GUARD_FAILED' }
        $fixture.real_submit_allowed = $true
        [IO.File]::WriteAllText($path, ($fixture | ConvertTo-Json -Depth 4))
        if ((Get-V10ShadowHeartbeatProof $tmp 4242 $true).status -ne 'SHADOW_ORDER_FLAG_UNSAFE') { throw 'SHADOW_ORDER_GUARD_FAILED' }
        $fixture.real_submit_allowed = $false
        $fixture.updated_at = '2026-01-01T00:00:00+00:00'
        [IO.File]::WriteAllText($path, ($fixture | ConvertTo-Json -Depth 4))
        if ((Get-V10ShadowHeartbeatProof $tmp 4242 $true).status -ne 'SHADOW_TIMESTAMP_STALE_OR_FUTURE') { throw 'SHADOW_STALE_GUARD_FAILED' }
        $fixture.updated_at = '2026-10-01 09:00:00'
        [IO.File]::WriteAllText($path, ($fixture | ConvertTo-Json -Depth 4))
        if ((Get-V10ShadowHeartbeatProof $tmp 4242 $true).status -ne 'SHADOW_TIMESTAMP_INVALID') { throw 'SHADOW_TIMEZONE_GUARD_FAILED' }
        $fixture.updated_at = $stamp
        $fixture.resume_blocked = $true
        [IO.File]::WriteAllText($path, ($fixture | ConvertTo-Json -Depth 4))
        if ((Get-V10ShadowHeartbeatProof $tmp 4242 $true).status -ne 'SHADOW_RESUME_UNVERIFIED') { throw 'SHADOW_RESUME_GUARD_FAILED' }
        [IO.File]::Delete($path)
        if ((Get-V10ShadowHeartbeatProof $tmp 4242 $true).status -ne 'SHADOW_FILE_UNAVAILABLE') { throw 'SHADOW_MISSING_GUARD_FAILED' }
    } finally {
        if ([IO.Directory]::Exists($tmp)) { [IO.Directory]::Delete($tmp, $true) }
    }
    Write-Output 'PASS: V10_SHADOW_HEARTBEAT_SYNTHETIC'
    exit 0
}

if ($PublicationSelfTest) {
    $now = Get-Date
    $stamp = $now.ToString('yyyy-MM-ddTHH:mm:sszzz')
    # Synthetic fixture uses the explicit Asia/Tokyo contract independently of
    # runner machine timezone. A writer in JST would publish +09:00.
    $tokyo = [TimeZoneInfo]::FindSystemTimeZoneById('Tokyo Standard Time')
    $tokyoNow = [TimeZoneInfo]::ConvertTimeFromUtc([datetime]::UtcNow, $tokyo)
    $jstStamp = $tokyoNow.ToString('yyyy-MM-ddTHH:mm:ss') + '+09:00'
    $recent = Get-V10PublicationState $jstStamp 'Asia/Tokyo' $true ([datetime]::UtcNow)
    if ($recent -ne 'RECENT_PUBLICATION_ONLY') { throw "RECENT_PUBLICATION_FAILED: $recent" }
    if ((Get-V10PublicationState $jstStamp 'Asia/Tokyo' $false ([datetime]::UtcNow)) -ne 'PROCESS_UNVERIFIED') { throw 'PROCESS_GUARD_FAILED' }
    if ((Get-V10PublicationState $jstStamp 'UNKNOWN' $true ([datetime]::UtcNow)) -ne 'TIMEZONE_UNVERIFIED') { throw 'ZONE_GUARD_FAILED' }
    $oldStamp = ([datetime]::ParseExact('2026-01-01T09:00:00', 'yyyy-MM-ddTHH:mm:ss',
        [Globalization.CultureInfo]::InvariantCulture)).ToString('yyyy-MM-ddTHH:mm:ss') + '+09:00'
    if ((Get-V10PublicationState $oldStamp 'Asia/Tokyo' $true ([datetime]::UtcNow)) -ne 'PUBLICATION_STALE') { throw 'STALE_GUARD_FAILED' }
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ([IO.Path]::GetRandomFileName())
    $runtimeFixture = Join-Path $tmp 'files'
    $repoFixture = Join-Path (Join-Path $tmp 'repo') 'ms2_live'
    [void][IO.Directory]::CreateDirectory($runtimeFixture)
    [void][IO.Directory]::CreateDirectory($repoFixture)
    try {
        $file = Join-Path $runtimeFixture 'kioxia_watcher_live.json'
        $fixture = '{"schema_version":"kioxia-watcher-1.0","source":"Kioxia_RSS_Live_Watcher (Excel RSS)","observed_at_offset":"' + $jstStamp + '","timestamp_timezone":"Asia/Tokyo"}'
        # Repo checkout has a deliberately valid decoy. It must be ignored.
        [IO.File]::WriteAllText((Join-Path $repoFixture 'kioxia_watcher_live.json'), $fixture)
        [IO.File]::WriteAllText($file, '{"schema_version":"not-a-watcher"}')
        $untrusted = Get-V10WatcherPublication $runtimeFixture $true
        if ($untrusted.publication_state -ne 'WATCHER_IDENTITY_UNVERIFIED') { throw 'WATCHER_REPO_DECOY_WAS_USED' }
        [IO.File]::WriteAllText($file, $fixture, [Text.UTF8Encoding]::new($false))
        $verified = Get-V10WatcherPublication $runtimeFixture $true
        if ($verified.publication_state -ne 'RECENT_PUBLICATION_ONLY') { throw 'WATCHER_LOCAL_FILE_NOT_READ' }
        $denied = Get-V10WatcherPublication $runtimeFixture $false
        if ($denied.publication_state -ne 'PROCESS_UNVERIFIED' -or $null -ne $denied.observed_at_offset) { throw 'UNVERIFIED_FILE_EXPOSED' }
        [IO.File]::WriteAllText($file, '{"schema_version":"wrong"}')
        if ((Get-V10WatcherPublication $runtimeFixture $true).publication_state -ne 'WATCHER_IDENTITY_UNVERIFIED') { throw 'WATCHER_SCHEMA_GUARD_FAILED' }
        [IO.File]::Delete($file)
        if ((Get-V10WatcherPublication $runtimeFixture $true).publication_state -ne 'WATCHER_FILE_UNAVAILABLE') { throw 'MISSING_WATCHER_NOT_BLOCKED' }
        if ((Get-V10WatcherPublication '' $true).publication_state -ne 'WATCHER_RUNTIME_UNAVAILABLE') { throw 'MISSING_RUNTIME_NOT_BLOCKED' }
    } finally { if ([IO.Directory]::Exists($tmp)) { [IO.Directory]::Delete($tmp, $true) } }
    Write-Output 'PASS: V10_WATCHER_PUBLICATION_SYNTHETIC'
    exit 0
}

if ($SnapshotGuardSelfTest) {
    $fixture = '<html><header><div class="sub">2026-09-25 10:41:50 JST</div></header><main>OLD</main></html>'
    $fixed = Add-StaticSnapshotNotice $fixture ([datetime]'2026-10-16')
    if (-not $fixed.Contains('data-snapshot-status="HISTORICAL"')) { throw 'STATIC_HISTORICAL_NOT_FLAGGED' }
    if (-not $fixed.Contains('2026-09-25 10:41:50')) { throw 'HISTORICAL_BYTES_REWRITTEN' }
    if ([regex]::Matches($fixed, 'id="v10-static-snapshot-warning"').Count -ne 1) { throw 'MISSING_OR_DUPLICATE_WARNING' }
    if ((Add-StaticSnapshotNotice $fixed ([datetime]'2026-10-16')) -cne $fixed) { throw 'NOTICE_NOT_IDEMPOTENT' }
    $same = Add-StaticSnapshotNotice $fixture ([datetime]'2026-09-25')
    if (-not $same.Contains('data-snapshot-status="SAME_DAY_STATIC"')) { throw 'SAME_DAY_SNAPSHOT_NOT_FLAGGED' }
    $unknown = Add-StaticSnapshotNotice '<html><main>UNKNOWN</main></html>' ([datetime]'2026-10-16')
    if (-not $unknown.Contains('data-snapshot-status="DATE_UNVERIFIED"')) { throw 'MISSING_DATE_NOT_BLOCKED' }
    $future = Add-StaticSnapshotNotice $fixture ([datetime]'2026-09-24')
    if (-not $future.Contains('data-snapshot-status="DATE_UNVERIFIED"')) { throw 'FUTURE_DATE_NOT_BLOCKED' }
    Write-Output 'PASS: V10_STATIC_SNAPSHOT_GUARD_SYNTHETIC'
    exit 0
}

$restoredHistory = Import-ServedHistory $script:ServedHistoryPath
$script:ServedHistoryState = $restoredHistory.state
$script:LastServedIdentityQuoteAt = $restoredHistory.identity
$script:LastServedRowQuoteAt = $restoredHistory.rows

try {
    $listener.Start()
    Write-Host ("AI Cockpit Gateway V10: http://127.0.0.1:{0}/?live=1" -f $Port) -ForegroundColor Green
    Write-Host ("Serving from: " + $RepoRoot) -ForegroundColor Cyan
    Write-Host ("Runtime dir:  " + $RuntimeDir) -ForegroundColor Cyan

    while ($true) {
        $client = $listener.AcceptTcpClient()
        try {
            $stream = $client.GetStream()
            $reader = [IO.StreamReader]::new($stream, [Text.Encoding]::ASCII, $false, 4096, $true)
            $requestLine = $reader.ReadLine()
            $requestHeaders = @{}
            $headerCount = 0
            while (($line = $reader.ReadLine()) -ne $null -and $line -ne "") {
                $headerCount++
                if ($headerCount -gt 64 -or $line.Length -gt 8192) { throw "V10_HTTP_HEADERS_TOO_LARGE" }
                $splitAt = $line.IndexOf(':')
                if ($splitAt -le 0) { throw "V10_HTTP_HEADER_MALFORMED" }
                $key = $line.Substring(0, $splitAt).Trim().ToLowerInvariant()
                if ($requestHeaders.ContainsKey($key)) { throw "V10_HTTP_DUPLICATE_HEADER" }
                $requestHeaders[$key] = $line.Substring($splitAt + 1).Trim()
            }
            if ([string]::IsNullOrWhiteSpace($requestLine)) { continue }
            $parts = $requestLine -split ' '
            $method = $parts[0]
            $rawPath = if ($parts.Count -ge 2) { $parts[1] } else { '/' }

            # Browser navigation and localhost are not an authorization boundary.
            # Reject forged Host/Origin, cross-site browser requests and bad PNA preflights.
            $expectedHost = "127.0.0.1:" + [string]$Port
            $expectedOrigin = "http://" + $expectedHost
            $hostOk = $requestHeaders.ContainsKey('host') -and
                ($requestHeaders['host'] -ceq $expectedHost -or
                 ($requestHeaders['host'] -ceq '127.0.0.1' -and
                  -not $requestHeaders.ContainsKey('origin') -and
                  -not $requestHeaders.ContainsKey('sec-fetch-site')))
            $originOk = -not $requestHeaders.ContainsKey('origin') -or $requestHeaders['origin'] -ceq $expectedOrigin
            $fetchSiteOk = -not $requestHeaders.ContainsKey('sec-fetch-site') -or $requestHeaders['sec-fetch-site'] -cne 'cross-site'
            if (-not ($hostOk -and $originOk -and $fetchSiteOk)) {
                Send-Response $stream '403 Forbidden' 'text/plain; charset=utf-8' ($utf8.GetBytes('V10_HTTP_ORIGIN_BLOCKED'))
                continue
            }
            if ($method -eq 'OPTIONS') {
                # Same-origin UI needs no browser cross-origin grants.
                Send-Response $stream '403 Forbidden' 'text/plain' ([byte[]]@())
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
                    collector_observed_at_offset = $null
                    collector_timestamp_timezone = $null
                    collector_publication_state   = 'UNKNOWN'
                    watcher_observed_at_offset   = $null
                    watcher_timestamp_timezone   = $null
                    watcher_publication_state    = 'UNKNOWN'
                    brain_publication_state      = 'UNKNOWN_NOT_PUBLISHED'
                    brain_observer_state         = 'BRAIN_NOT_VERIFIED'
                    brain_observer_updated_at    = $null
                    brain_observer_watch_count   = $null
                    brain_observer_role          = 'INDEPENDENT_BRAIN_OBSERVER_NOT_TRADE_ENGINE'
                    shadow_heartbeat_status      = 'SHADOW_NOT_VERIFIED'
                    shadow_heartbeat_at          = $null
                    shadow_component_role        = 'SHADOW_OBSERVER_NOT_BRAIN'
                    source_timestamp           = $null
                    live_symbol                = $null
                    live_current_price         = $null
                }
                $shadowExpectedPid = 0
                $shadowProcessVerified = $false
                $brainExpectedPid = 0
                $brainProcessVerified = $false
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
                        $controllerAlive = Test-ControllerHealthProcess ([int]$st.controller_pid) $stateWrittenAt
                        $sessionFresh = $controllerAlive -and $stateAge -ge 0 -and $stateAge -le 30
                        $shadowExpectedPid = [int]$st.shadow_supervisor_pid
                        $shadowProcessVerified = $sessionFresh -and (Test-HealthProcess $shadowExpectedPid 'ai_shadow_supervisor.py' $stateWrittenAt)
                        $brainExpectedPid = [int]$st.brain_observer_pid
                        $brainProcessVerified = $sessionFresh -and (Test-HealthProcess $brainExpectedPid 'ai_brain_observer.py' $stateWrittenAt)
                        foreach ($check in @(
                            @{field='watcher'; script='Kioxia_RSS_Live_Watcher.ps1'},
                            @{field='heartbeat'; script='Kioxia_Safety_Heartbeat.ps1'},
                            @{field='collector'; script='MS2_RSS_100_Collector.ps1'},
                            @{field='voice_bridge'; script='AI_COCKPIT_VOICE_BRIDGE_V10.ps1'},
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
                $healthLive = $null
                if ($liveExists) {
                    try {
                        $healthLive = Read-JsonUtf8 $liveJson
                        $healthDiag = $healthLive.live_price_diagnostics
                        $runtime.live_updated_at = [string]$healthLive.updated_at
                        $runtime.collector_observed_at_offset = [string]$healthLive.observed_at_offset
                        $runtime.collector_timestamp_timezone = [string]$healthLive.timestamp_timezone
                        $collectorFileItem = Get-Item -LiteralPath $liveJson -ErrorAction Stop
                        $runtime.collector_publication_state = Get-V10PublicationState `
                            $runtime.collector_observed_at_offset `
                            $runtime.collector_timestamp_timezone `
                            ($runtime.collector_status -eq 'LIVE') `
                            $collectorFileItem.LastWriteTimeUtc

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
                # Quote freshness: /health agrees with the Shadow supervisor or
                # fails closed. A recent live_ms2.json write is not enough.
                $gatewayFreshness = Get-QuoteFreshness -LiveObj $healthLive
                $shadowFreshness = (Get-ShadowEnginePublication $RuntimeDir).shadow_quote_freshness
                $freshnessCombined = Get-CombinedQuoteFreshness $gatewayFreshness $shadowFreshness
                $runtime['quote_freshness'] = $gatewayFreshness
                $runtime['shadow_quote_freshness'] = $shadowFreshness
                $runtime['quote_freshness_combined'] = $freshnessCombined
                # Same row and universe gate as /live_ms2.json (without the
                # served-history regression check, which only /live_ms2.json
                # records). source_status keeps what the Collector reported
                # about its source; availability says whether the board may be
                # used. A healthy source does not make a stale board usable.
                $runtime['source_status'] = $(if ([string]::IsNullOrWhiteSpace([string]$runtime.price_source_status)) { 'UNKNOWN' } else { [string]$runtime.price_source_status })
                $healthRows = Get-BoardRowFreshness -LiveObj $healthLive -BoardQuoteAt $gatewayFreshness.quote_at
                $runtime['board_row_freshness'] = [ordered]@{
                    fresh = ($healthRows.fresh -eq $true)
                    reasons = @($healthRows.reasons)
                    row_count = $healthRows.row_count
                    fresh_row_count = $healthRows.fresh_row_count
                    not_fresh_row_count = $healthRows.not_fresh_row_count
                    not_fresh_sample = @($healthRows.not_fresh_sample)
                }
                $healthAvailability = Get-BoardAvailability -LiveObj $healthLive -QuoteFreshness $gatewayFreshness -RowFreshness $healthRows -Universe (Get-ExpectedUniverse $RuntimeDir)
                $runtime['availability'] = Get-AvailabilitySummary $healthAvailability
                # The Shadow supervisor publishes its own availability verdict.
                # Missing, or disagreeing on decision_available, is fail-closed.
                $shadowAvailability = (Get-ShadowEnginePublication $RuntimeDir).shadow_board_availability
                $runtime['shadow_board_availability'] = $shadowAvailability
                $runtime['served_history'] = [ordered]@{
                    state = $script:ServedHistoryState
                    identity_quote_at = $script:LastServedIdentityQuoteAt
                    row_count = $script:LastServedRowQuoteAt.Count
                    history_loss_risk = (@("RESTORED", "SAVED") -cnotcontains $script:ServedHistoryState)
                }
                $availabilityReasons = @()
                if ($healthAvailability.decision_available -ne $true) { $availabilityReasons += @($healthAvailability.reasons) }
                if ($null -eq $shadowAvailability) { $availabilityReasons += "SHADOW_BOARD_AVAILABILITY_MISSING" }
                elseif (($shadowAvailability.decision_available -eq $true) -ne ($healthAvailability.decision_available -eq $true)) { $availabilityReasons += "BOARD_AVAILABILITY_MISMATCH" }
                elseif ($shadowAvailability.real_submit_allowed -ne $false) { $availabilityReasons += "REAL_SUBMIT_NOT_FALSE" }
                $runtime['decision_available'] = ($availabilityReasons.Count -eq 0 -and $healthAvailability.decision_available -eq $true)
                $runtime['availability_status'] = $(if ($runtime['decision_available']) { 'AVAILABLE' } elseif ($healthAvailability.decision_available -ne $true) { [string]$healthAvailability.availability_status } else { 'BLOCKED_SHADOW_DISAGREES' })
                if ($availabilityReasons.Count -gt 0) {
                    $runtime.fail_closed = $true
                    if ([string]$runtime.price_source_status -eq "OK" -or [string]::IsNullOrWhiteSpace([string]$runtime.price_source_status)) {
                        $runtime.price_source_status = "STALE"
                    }
                    $runtime.stale_reason = (@((@(([string]$runtime.stale_reason) -split ',' | Where-Object { $_ }) + $availabilityReasons) | Select-Object -Unique) -join ',')
                }
                if ($freshnessCombined.fresh -ne $true) {
                    $runtime.fail_closed = $true
                    if ([string]$runtime.price_source_status -eq "OK" -or [string]::IsNullOrWhiteSpace([string]$runtime.price_source_status)) {
                        $runtime.price_source_status = "STALE"
                    }
                    $staleParts = @(([string]$runtime.stale_reason) -split ',' | Where-Object { $_ }) + @($freshnessCombined.reasons)
                    $runtime.stale_reason = (@($staleParts | Select-Object -Unique) -join ',')
                }
                if ($runtime.fail_closed -eq $true) {
                    # Fail-closed /health presents no LIVE price. price_source_status
                    # is never left OK beside fail_closed; the Collector's own
                    # report stays in source_status.
                    $runtime['decision_available'] = $false
                    if ($runtime['availability_status'] -eq 'AVAILABLE') { $runtime['availability_status'] = 'BLOCKED_FAIL_CLOSED' }
                    if ([string]$runtime.price_source_status -eq "OK" -or [string]::IsNullOrWhiteSpace([string]$runtime.price_source_status)) {
                        $runtime.price_source_status = "FAIL_CLOSED"
                    }
                    $runtime.live_current_price = $null
                    $runtime.source_timestamp = $null
                }
                # Read only the Watcher-owned local JSON. It may live in a
                # different working tree; in that case state stays UNKNOWN.
                $watcherProof = Get-V10WatcherPublication $RuntimeDir ($runtime.watcher_status -eq 'LIVE')
                $runtime.watcher_observed_at_offset = $watcherProof.observed_at_offset
                $runtime.watcher_timestamp_timezone = $watcherProof.timestamp_timezone
                $runtime.watcher_publication_state = $watcherProof.publication_state
                $shadowProof = Get-V10ShadowHeartbeatProof $RuntimeDir $shadowExpectedPid $shadowProcessVerified
                $runtime.shadow_heartbeat_status = $shadowProof.status
                $runtime.shadow_heartbeat_at = $shadowProof.heartbeat_at
                $runtime.shadow_component_role = $shadowProof.component_role
                $brainProof = Get-V10BrainObserverProof $RuntimeDir $brainExpectedPid $brainProcessVerified
                $runtime.brain_observer_state = $brainProof.status
                $runtime.brain_observer_updated_at = $brainProof.updated_at
                $runtime.brain_observer_watch_count = $brainProof.watch_count
                $runtime.brain_observer_role = $brainProof.process_role
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
                # Legacy SHADOW state used only file mtime; never allow it to
                # claim RUNNING, RECOVERING, or expose old counts unless the
                # independently verified PID + heartbeat proof also passes.
                $shadowProven = @(
                    'SHADOW_RUNNING_HEARTBEAT_ONLY',
                    'SHADOW_PAUSED_FAIL_CLOSED_HEARTBEAT_ONLY',
                    'SHADOW_RECOVERING_HEARTBEAT_ONLY',
                    'SHADOW_STOPPED_HEARTBEAT_ONLY'
                ) -ccontains $shadowProof.status
                if (-not $shadowProven) {
                    if (@('RUNNING', 'RECOVERING') -ccontains [string]$execution.shadow_engine_state) {
                        $execution.shadow_engine_state = 'PAUSED_FAIL_CLOSED'
                        $execution.shadow_engine_reason = 'SHADOW_IDENTITY_OR_HEARTBEAT_UNVERIFIED'
                    }
                    $execution.shadow_engine_updated_at = $null
                    $execution.shadow_open_observation_count = $null
                    $execution.shadow_ops = $null
                    $execution.shadow_latest_incident = $null
                }

                $payload = [ordered]@{
                    status           = 'ok'
                    port             = $Port
                    ui_branch        = $git.branch
                    ui_sha           = $git.sha
                    ui_build         = $Build
                    # Do not disclose absolute local paths or Windows usernames.
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

                $snap = Read-LiveSnapshot $liveJson
                $bytes = $snap.bytes
                $liveObj = $snap.obj
                $liveNow = Get-JstNow
                $liveQuoteFreshness = Get-QuoteFreshness -LiveObj $liveObj -Now $liveNow -PreviousQuoteAt $script:LastServedIdentityQuoteAt
                $liveRowFreshness = Get-BoardRowFreshness -LiveObj $liveObj -Now $liveNow -BoardQuoteAt $liveQuoteFreshness.quote_at -PreviousRowQuotes $script:LastServedRowQuoteAt
                $liveAvailability = Get-BoardAvailability -LiveObj $liveObj -QuoteFreshness $liveQuoteFreshness -RowFreshness $liveRowFreshness -Universe (Get-ExpectedUniverse $RuntimeDir)
                $rejection = Get-LivePriceRejection -LiveObj $liveObj -FileAgeSeconds $snap.file_age_seconds -PayloadAgeSeconds $snap.payload_age_seconds -UpdatedAtRaw $snap.updated_at -FileMtime $snap.file_mtime -MaxAgeSeconds 60 -QuoteFreshness $liveQuoteFreshness -RowFreshness $liveRowFreshness -Availability $liveAvailability
                if ($null -eq $rejection -and $script:ServedHistoryState -ceq "UNREADABLE") {
                    $rejection = [ordered]@{ status = "stale"; reason = "SERVED_HISTORY_UNREADABLE"; stale_reason = "SERVED_HISTORY_UNREADABLE"; price_source_status = "STALE"; current_price = $null; real_submit_allowed = $false; live_values_available = $false; data_conflict = $false }
                }
                if ($null -ne $rejection -or $null -eq $liveObj -or $bytes.Length -eq 0) {
                    if ($null -eq $rejection) { $rejection = [ordered]@{ status = "stale"; stale_reason = "MISSING_PAYLOAD"; real_submit_allowed = $false; live_values_available = $false; data_conflict = $true } }
                    $stalePayload = $rejection | ConvertTo-Json -Depth 6
                    Send-Response $stream '503 Service Unavailable' 'application/json; charset=utf-8' ($utf8.GetBytes($stalePayload))
                    continue
                }

                $script:LastServedIdentityQuoteAt = $liveQuoteFreshness.quote_at
                foreach ($servedTicker in @($liveRowFreshness.accepted_quote_at.Keys)) {
                    $script:LastServedRowQuoteAt[$servedTicker] = $liveRowFreshness.accepted_quote_at[$servedTicker]
                }
                if (Save-ServedHistory $script:ServedHistoryPath $script:LastServedIdentityQuoteAt $script:LastServedRowQuoteAt) {
                    $script:ServedHistoryState = "SAVED"
                } else {
                    $script:ServedHistoryState = "SAVE_FAILED"
                }
                Send-Response $stream '200 OK' 'application/json; charset=utf-8' $bytes
                continue
            }
            if ($path -eq '/observation_ms2.json') {
                # Observation layer. Reports every expected ticker's quote state
                # and, for FRESH rows only, the observed price. It never carries
                # signals, scores, entry/stop/targets, indicators, top5/hold/pts
                # lists or market aggregates, and it never makes the board
                # usable for decisions: decision_available comes from the same
                # Get-BoardAvailability as /live_ms2.json. A payload that fails
                # a source, identity or writer-time check is refused whole.
                if (-not $liveJson -or -not (Test-Path -LiteralPath $liveJson)) {
                    Send-Response $stream '503 Service Unavailable' 'application/json; charset=utf-8' ($utf8.GetBytes('{"status":"waiting","observation_available":false,"stale_reason":"MISSING_PAYLOAD","real_submit_allowed":false,"order_allowed":false}'))
                    continue
                }
                $obsSnap = Read-LiveSnapshot $liveJson
                $obsObj = $obsSnap.obj
                $obsNow = Get-JstNow
                $obsQuote = Get-QuoteFreshness -LiveObj $obsObj -Now $obsNow -PreviousQuoteAt $script:LastServedIdentityQuoteAt
                $obsRows = Get-BoardRowFreshness -LiveObj $obsObj -Now $obsNow -BoardQuoteAt $obsQuote.quote_at -PreviousRowQuotes $script:LastServedRowQuoteAt
                $obsAvailability = Get-BoardAvailability -LiveObj $obsObj -QuoteFreshness $obsQuote -RowFreshness $obsRows -Universe (Get-ExpectedUniverse $RuntimeDir)
                $obsRejection = Get-LivePriceRejection -LiveObj $obsObj -FileAgeSeconds $obsSnap.file_age_seconds -PayloadAgeSeconds $obsSnap.payload_age_seconds -UpdatedAtRaw $obsSnap.updated_at -FileMtime $obsSnap.file_mtime -MaxAgeSeconds 60 -QuoteFreshness $obsQuote -RowFreshness $obsRows -Availability $obsAvailability
                $obsBlockers = @()
                if ($null -eq $obsObj) { $obsBlockers += "MISSING_PAYLOAD" }
                if ($null -ne $obsRejection) {
                    $obsBlockers += @($obsRejection.source_reasons)
                    foreach ($writerReason in @("STALE_OR_MISSING_TIMESTAMP", "LIVE_VALUES_UNAVAILABLE")) {
                        if ((([string]$obsRejection.stale_reason) -split ',') -contains $writerReason) { $obsBlockers += $writerReason }
                    }
                }
                $obsBlockers = @($obsBlockers | Where-Object { -not [string]::IsNullOrEmpty([string]$_) } | Select-Object -Unique)
                if ($obsBlockers.Count -gt 0) {
                    $obsBody = [ordered]@{ status = "blocked"; observation_available = $false; stale_reason = ($obsBlockers -join ","); decision_available = $false; real_submit_allowed = $false; order_allowed = $false } | ConvertTo-Json -Depth 4
                    Send-Response $stream '503 Service Unavailable' 'application/json; charset=utf-8' ($utf8.GetBytes($obsBody))
                    continue
                }
                $priceByTicker = @{}
                foreach ($row in @($obsObj.all_targets)) {
                    if ($null -ne $row -and $row.ticker -is [string] -and -not $priceByTicker.ContainsKey($row.ticker)) { $priceByTicker[$row.ticker] = $row.price }
                }
                $obsList = New-Object System.Collections.Generic.List[object]
                foreach ($v in @($obsRows.row_verdicts)) {
                    $isFresh = ([string]$v.state -ceq "FRESH")
                    $obsPrice = $null
                    if ($isFresh -and $null -ne $v.ticker -and $priceByTicker.ContainsKey($v.ticker)) { $obsPrice = $priceByTicker[$v.ticker] }
                    [void]$obsList.Add([ordered]@{ ticker = $v.ticker; state = [string]$v.state; reasons = @($v.reasons); quote_at = $v.quote_at; quote_age_seconds = $v.quote_age_seconds; observed_price = $obsPrice })
                }
                $obsPayload = [ordered]@{
                    schema_version = "v10-observation-1"
                    status = "observing"
                    observation_available = $true
                    evaluated_at = $obsNow.ToString("yyyy-MM-ddTHH:mm:sszzz", [Globalization.CultureInfo]::InvariantCulture)
                    collector_updated_at = $obsSnap.updated_at
                    decision_available = ($obsAvailability.decision_available -eq $true)
                    availability = (Get-AvailabilitySummary $obsAvailability)
                    identity_quote_freshness = $obsQuote
                    missing_tickers = @($obsAvailability.missing_sample)
                    rows = $obsList.ToArray()
                    derived_fields = "WITHHELD"
                    order_allowed = $false
                    real_submit_allowed = $false
                } | ConvertTo-Json -Depth 6
                Send-Response $stream '200 OK' 'application/json; charset=utf-8' ($utf8.GetBytes($obsPayload))
                continue
            }
            # Serve ONLY the explicit public UI files. Never serve arbitrary files
            # from the local Git checkout (e.g. .git/config, secrets or private data).
            $relative = if ($path -eq '/') { 'index.html' } else { $path.TrimStart('/') }
            $relative = [Uri]::UnescapeDataString($relative)
            $allowedUiFiles = @('index.html', 'card_system.css', 'card_system.js', 'card_table_adapter.css', 'card_table_adapter.js', 'correlations.json', 'credit_supply.json', 'earnings-calendar.js', 'event_calendar.json', 'focus.css', 'kioxia_5m_calendar.json', 'kioxia_breaking_radar.json', 'kioxia_catalysts.json', 'kioxia_prediction_history.json', 'live_focus.json', 'paper_trade_history.json', 'weekly_review.json', 'earnings_calendar.json', 'next-theme-radar.css', 'next-theme-radar.js', 'next_theme_radar.json', 'opportunity_radar.js', 'signals.json', 'theme.css', 'trade_control.js', 'v10_publication_status.js', 'voice_client.js', 'world_market.json')
            if ($allowedUiFiles -cnotcontains $relative) {
                Send-Response $stream '404 Not Found' 'text/plain; charset=utf-8' ($utf8.GetBytes('V10_PUBLIC_PATH_NOT_ALLOWED'))
                continue
            }
            # Reject any path that escapes RepoRoot (no "..", no absolute
            # drive references) before touching the filesystem.
            if ($relative -match '\.\.' -or $relative -match '^[A-Za-z]:' -or $relative.StartsWith('\\')) {
                Send-Response $stream '400 Bad Request' 'text/plain; charset=utf-8' ($utf8.GetBytes('Bad path'))
                continue
            }
            $fullPath = Join-Path $RepoRoot $relative
            $resolvedFull = [IO.Path]::GetFullPath($fullPath)
            $resolvedRoot = [IO.Path]::GetFullPath($RepoRoot)
            $ordinalIgnoreCase = [StringComparison]::OrdinalIgnoreCase
            if (-not $resolvedFull.StartsWith($resolvedRoot, $ordinalIgnoreCase)) {
                Send-Response $stream '400 Bad Request' 'text/plain; charset=utf-8' ($utf8.GetBytes('Bad path'))
                continue
            }

            if (-not (Test-Path -LiteralPath $resolvedFull -PathType Leaf)) {
                Send-Response $stream '404 Not Found' 'text/plain; charset=utf-8' ($utf8.GetBytes('Not found: ' + $relative))
                continue
            }
            $publicItem = Get-Item -LiteralPath $resolvedFull -Force
            if (($publicItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                Send-Response $stream '403 Forbidden' 'text/plain; charset=utf-8' ($utf8.GetBytes('V10_REPARSE_PUBLIC_FILE_BLOCKED'))
                continue
            }

            $ct = Get-ContentType $resolvedFull
            if ($resolvedFull -match '(?i)index\.html$') {
                $git = Get-GitInfo $RepoRoot
                $html = Get-Content -LiteralPath $resolvedFull -Raw -Encoding UTF8
                $html = Add-StaticSnapshotNotice $html (Get-Date)
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
