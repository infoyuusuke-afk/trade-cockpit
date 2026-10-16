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
            $data.exchange_tick_date_verified -eq $true -or
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

function Get-PublishedWorkbookGate {
    param(
        [bool]$HasIdentityField,
        [bool]$IdentityVerified,
        [string]$FullName,
        [string]$ExpectedPath,
        [string]$Symbol,
        [bool]$ControllerVerified
    )
    $reasons = New-Object System.Collections.Generic.List[string]
    $ordinal = [StringComparison]::Ordinal
    $identity = "285A.T"
    if (-not [string]::Equals([string]$Symbol, $identity, $ordinal)) {
        [void]$reasons.Add("WRONG_SYMBOL_MAPPING")
    }
    $proved = $IdentityVerified -and (Test-SameCanonicalWorkbookFile $FullName $ExpectedPath)
    if ($HasIdentityField) {
        if (-not $proved) { [void]$reasons.Add("WRONG_SOURCE_WORKBOOK") }
    } elseif (-not $ControllerVerified) {
        [void]$reasons.Add("WRONG_SOURCE_WORKBOOK")
    }
    return ($reasons -join ",")
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
    $gateText = Get-PublishedWorkbookGate $hasIdentityField $identityVerified $workbookFullName $canonicalWorkbookPath $identitySymbol $workbookVerified
    if (-not [string]::IsNullOrWhiteSpace($gateText)) {
        foreach ($gateReason in ($gateText -split ",")) {
            if (-not [string]::IsNullOrWhiteSpace($gateReason)) { [void]$reasons.Add($gateReason) }
        }
    }
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
            $ordinalIgnoreCase = [StringComparison]::OrdinalIgnoreCase
            if (-not $resolvedFull.StartsWith($resolvedRoot, $ordinalIgnoreCase)) {
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
