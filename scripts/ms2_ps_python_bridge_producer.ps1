# Offline producer for one already-copied board record.
# The live watcher does not dot-source this file. Do not auto-start it.
# Submit copies 2048 bytes into an existing mapping and returns.
# It does not launch an interpreter, open a pipe, or take a file lock.

$script:Ms2PsBridgeCapacity = 8
$script:Ms2PsBridgeRecordSize = 2048
$script:Ms2PsBridgeSlotBase = 4096
$script:Ms2PsBridgeProto = 176

function New-Ms2PsBridgeRefusal([string]$Reason) {
    return @{ Ok = $false; Reason = $Reason; Record = $null }
}

function Write-Ms2PsBridgeText([byte[]]$Buffer, [int]$Offset, [int]$Size, [string]$Text) {
    if ([string]::IsNullOrEmpty($Text)) { return $true }
    if ($Text.Length -gt $Size) { return $false }
    $raw = [System.Text.Encoding]::UTF8.GetBytes($Text)
    if ($raw.Length -gt $Size) { return $false }
    [System.Array]::Copy($raw, 0, $Buffer, $Offset, $raw.Length)
    return $true
}

function Test-Ms2PsBridgeClock([string]$Text) {
    if ([string]::IsNullOrEmpty($Text)) { return $null }
    if ($Text.Length -gt 40) { return "TIMESTAMP_INVALID" }
    if ($Text.Contains("JST") -or $Text.Contains("Tokyo") -or $Text.Contains("Japan") -or $Text.EndsWith("Z")) {
        return "TIMEZONE_NOT_GUESSED"
    }
    if ($Text -notmatch '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}[+-]\d{2}:\d{2}$') {
        return "TIMEZONE_NOT_GUESSED"
    }
    return $null
}

function Add-Ms2PsBridgeDouble([byte[]]$Buffer, [int]$Offset, [double]$Value) {
    $raw = [System.BitConverter]::GetBytes($Value)
    [System.Array]::Copy($raw, 0, $Buffer, $Offset, 8)
}

function ConvertTo-Ms2PsBridgeRecord($Capture) {
    if ($null -eq $Capture) { return New-Ms2PsBridgeRefusal "BOARD_INPUT_INVALID" }
    $symbol = $Capture["symbol"]
    if ($symbol -isnot [string] -or $symbol.Length -lt 1 -or $symbol.Length -gt 32) { return New-Ms2PsBridgeRefusal "SYMBOL_ABSENT" }
    $market = [string]$Capture.market
    if ($market -ne "TSE" -and $market -ne "JNX") { return New-Ms2PsBridgeRefusal "MARKET_INVALID" }
    $poll = $Capture.poll_seq
    if ($poll -is [bool] -or (($poll -isnot [int]) -and ($poll -isnot [long])) -or $poll -lt 1 -or $poll -gt 1000000000000) {
        return New-Ms2PsBridgeRefusal "POLL_SEQ_INVALID"
    }
    $source = [string]$Capture.source
    if ([string]::IsNullOrEmpty($source) -or $source.Length -gt 120) { return New-Ms2PsBridgeRefusal "SOURCE_ABSENT" }
    if ($source -eq "Kioxia_RSS_Live_Watcher.ps1") { return New-Ms2PsBridgeRefusal "WATCHER_SOURCE_HAS_NO_SIDECAR" }
    $levels = @($Capture.levels)
    if ($levels.Count -gt 10) { return New-Ms2PsBridgeRefusal "DEPTH_LIMIT" }
    $freshnessNames = @("UNKNOWN", "OK", "STALE", "MISSING", "FUTURE")
    $freshness = [string]$Capture.data_freshness
    if ([string]::IsNullOrEmpty($freshness)) { $freshness = "UNKNOWN" }
    $freshIndex = [array]::IndexOf($freshnessNames, $freshness)
    if ($freshIndex -lt 0) { return New-Ms2PsBridgeRefusal "FRESHNESS_INVALID" }
    $clockNames = @("event_time", "watcher_observed_at", "received_at", "read_started_at", "read_finished_at")
    foreach ($name in $clockNames) {
        if ($Capture.ContainsKey($name)) {
            $problem = Test-Ms2PsBridgeClock ([string]$Capture[$name])
            if ($problem) { return New-Ms2PsBridgeRefusal $problem }
        }
    }
    $parsed = @()
    $expected = 1
    foreach ($item in $levels) {
        $number = $item.Level
        if ($null -eq $number) { $number = $item.level }
        if ($number -is [bool] -or (($number -isnot [int]) -and ($number -isnot [long])) -or $number -ne $expected) {
            return New-Ms2PsBridgeRefusal "LEVEL_SEQUENCE_GAP"
        }
        $row = @{ level = [int]$number; ask = $null; bid = $null; ask_qty = $null; bid_qty = $null; ask_known = $false; bid_known = $false; ask_qty_known = $false; bid_qty_known = $false; read_at = "" }
        foreach ($pair in @(
            @{ Key = "AskPrice"; Out = "ask"; Known = "ask_known"; Positive = $true },
            @{ Key = "BidPrice"; Out = "bid"; Known = "bid_known"; Positive = $true },
            @{ Key = "AskQty"; Out = "ask_qty"; Known = "ask_qty_known"; Positive = $false },
            @{ Key = "BidQty"; Out = "bid_qty"; Known = "bid_qty_known"; Positive = $false }
        )) {
            if (-not $item.ContainsKey($pair.Key)) { continue }
            $raw = $item[$pair.Key]
            if ($null -eq $raw) { continue }
            if ($raw -is [bool] -or (($raw -isnot [int]) -and ($raw -isnot [long]) -and ($raw -isnot [double]) -and ($raw -isnot [decimal]))) {
                return New-Ms2PsBridgeRefusal "BOOK_VALUE_TYPE_INVALID"
            }
            $numberValue = [double]$raw
            if ([double]::IsNaN($numberValue) -or [double]::IsInfinity($numberValue)) { return New-Ms2PsBridgeRefusal "QTY_INVALID" }
            if ($pair.Positive -and $numberValue -le 0) { return New-Ms2PsBridgeRefusal "QTY_INVALID" }
            if (-not $pair.Positive -and $numberValue -lt 0) { return New-Ms2PsBridgeRefusal "QTY_INVALID" }
            $row[$pair.Out] = $numberValue
            $row[$pair.Known] = $true
        }
        $readAt = $null
        if ($item.ContainsKey("read_at")) { $readAt = $item["read_at"] }
        if ($null -ne $readAt -and -not [string]::IsNullOrEmpty([string]$readAt)) {
            $problem = Test-Ms2PsBridgeClock ([string]$readAt)
            if ($problem) { return New-Ms2PsBridgeRefusal $problem }
            if (([string]$readAt).Length -gt 40) { return New-Ms2PsBridgeRefusal "TIMESTAMP_INVALID" }
            $row["read_at"] = [string]$readAt
        }
        $parsed += $row
        $expected += 1
    }
    $buffer = New-Object byte[] 2048
    $buffer[0] = 78
    $buffer[1] = 66
    $buffer[2] = 72
    $buffer[3] = 49
    $buffer[4] = 1
    $buffer[5] = [byte]$parsed.Count
    $buffer[6] = [byte]$freshIndex
    $flags = 0
    if ($Capture.ContainsKey("available_at") -and $null -ne $Capture["available_at"]) { $flags = $flags -bor 1 }
    if ($Capture.ContainsKey("snapshot_atomic") -and $Capture["snapshot_atomic"] -eq $true) { $flags = $flags -bor 2 }
    $basis = ""
    if ($Capture.ContainsKey("sequence_basis")) { $basis = [string]$Capture["sequence_basis"] }
    if (($Capture.ContainsKey("exchange_sequence") -and $null -ne $Capture["exchange_sequence"]) -or $basis -eq "EXCHANGE") { $flags = $flags -bor 4 }
    if ($source.Contains("synthetic")) { $flags = $flags -bor 8 }
    $buffer[7] = [byte]$flags
    $pollRaw = [System.BitConverter]::GetBytes([int64]$poll)
    [System.Array]::Copy($pollRaw, 0, $buffer, 8, 8)
    if (-not (Write-Ms2PsBridgeText $buffer 16 32 $symbol)) { return New-Ms2PsBridgeRefusal "SYMBOL_ABSENT" }
    if (-not (Write-Ms2PsBridgeText $buffer 48 8 $market)) { return New-Ms2PsBridgeRefusal "MARKET_INVALID" }
    if ($Capture.ContainsKey("observation_id") -and -not [string]::IsNullOrEmpty([string]$Capture["observation_id"])) {
        if (-not (Write-Ms2PsBridgeText $buffer 56 80 ([string]$Capture["observation_id"]))) { return New-Ms2PsBridgeRefusal "OBSERVATION_ID_ABSENT" }
    }
    if (-not (Write-Ms2PsBridgeText $buffer 136 120 $source)) { return New-Ms2PsBridgeRefusal "SOURCE_ABSENT" }
    $clockAt = 256
    foreach ($name in $clockNames) {
        if ($Capture.ContainsKey($name) -and -not [string]::IsNullOrEmpty([string]$Capture[$name])) {
            if (-not (Write-Ms2PsBridgeText $buffer $clockAt 40 ([string]$Capture[$name]))) { return New-Ms2PsBridgeRefusal "TIMESTAMP_INVALID" }
        }
        $clockAt += 40
    }
    $levelAt = $clockAt
    foreach ($row in $parsed) {
        $buffer[$levelAt] = [byte]$row.level
        $mask = 0
        if ($row.ask_known) { $mask = $mask -bor 1 }
        if ($row.bid_known) { $mask = $mask -bor 2 }
        if ($row.ask_qty_known) { $mask = $mask -bor 4 }
        if ($row.bid_qty_known) { $mask = $mask -bor 8 }
        $buffer[$levelAt + 1] = [byte]$mask
        Add-Ms2PsBridgeDouble $buffer ($levelAt + 8) $(if ($row.ask_known) { [double]$row.ask } else { 0.0 })
        Add-Ms2PsBridgeDouble $buffer ($levelAt + 16) $(if ($row.bid_known) { [double]$row.bid } else { 0.0 })
        Add-Ms2PsBridgeDouble $buffer ($levelAt + 24) $(if ($row.ask_qty_known) { [double]$row.ask_qty } else { 0.0 })
        Add-Ms2PsBridgeDouble $buffer ($levelAt + 32) $(if ($row.bid_qty_known) { [double]$row.bid_qty } else { 0.0 })
        if (-not [string]::IsNullOrEmpty([string]$row.read_at)) {
            if (-not (Write-Ms2PsBridgeText $buffer ($levelAt + 40) 40 ([string]$row.read_at))) { return New-Ms2PsBridgeRefusal "TIMESTAMP_INVALID" }
        }
        $levelAt += 80
    }
    if ($levelAt -gt 1800) { return New-Ms2PsBridgeRefusal "RECORD_LAYOUT" }
    if ($Capture.ContainsKey("gap") -and $null -ne $Capture["gap"]) {
        $gap = $Capture["gap"]
        $buffer[1800] = 1
        $suspected = $gap["suspected_gap"]
        if ($null -eq $suspected) { $buffer[1801] = 0 }
        elseif ($suspected -eq $true) { $buffer[1801] = 1 }
        else { $buffer[1801] = 2 }
        if ($gap["prev_poll_nonempty"] -eq $true) { $buffer[1802] = 1 }
        $windowRaw = [System.BitConverter]::GetBytes([int]$gap["window_size"])
        $overlapRaw = [System.BitConverter]::GetBytes([int]$gap["overlap_with_prev"])
        $newRaw = [System.BitConverter]::GetBytes([int]$gap["new_appended"])
        [System.Array]::Copy($windowRaw, 0, $buffer, 1808, 4)
        [System.Array]::Copy($overlapRaw, 0, $buffer, 1812, 4)
        [System.Array]::Copy($newRaw, 0, $buffer, 1816, 4)
    }
    return @{ Ok = $true; Reason = "PACKED"; Record = $buffer }
}

$script:Ms2WriteArray = $null
foreach ($method in [System.IO.MemoryMappedFiles.MemoryMappedViewAccessor].GetMethods()) {
    if ($method.Name -eq "WriteArray" -and $method.IsGenericMethodDefinition) {
        $script:Ms2WriteArray = $method.MakeGenericMethod([byte])
        break
    }
}
$script:Ms2WriteInt64 = [System.IO.MemoryMappedFiles.MemoryMappedViewAccessor].GetMethod("Write", [type[]]@([int64], [int64]))
if ($null -eq $script:Ms2WriteInt64) { throw "WRITE_INT64_MISSING" }

function Write-Ms2PsBridgeInt64($Accessor, [int64]$Offset, [int64]$Value) {
    [void]$script:Ms2WriteInt64.Invoke($Accessor, @($Offset, $Value))
}

function Open-Ms2PsBridge([string]$MapName, [int]$Size) {
    $candidates = @($MapName)
    if ($MapName -notmatch '\\') {
        $candidates += ("Local\" + $MapName)
        $candidates += ("Global\" + $MapName)
    }
    $opened = $null
    $used = $null
    $tried = 0
    foreach ($candidate in $candidates) {
        $tried += 1
        try {
            $opened = [System.IO.MemoryMappedFiles.MemoryMappedFile]::OpenExisting($candidate, [System.IO.MemoryMappedFiles.MemoryMappedFileRights]::ReadWrite)
            $used = $candidate
            break
        } catch {
            $opened = $null
        }
    }
    if ($null -eq $opened) {
        return @{ Ok = $false; Reason = "ATTACH_FAILED"; Attempts = $tried; Retry = $false }
    }
    $accessor = $null
    try {
        if ($null -eq $script:Ms2WriteArray) { throw "WRITE_ARRAY_MISSING" }
        $accessor = $opened.CreateViewAccessor(0, $Size, [System.IO.MemoryMappedFiles.MemoryMappedFileAccess]::ReadWrite)
        $label = -join @(
            [char]$accessor.ReadByte($script:Ms2PsBridgeProto),
            [char]$accessor.ReadByte($script:Ms2PsBridgeProto + 1),
            [char]$accessor.ReadByte($script:Ms2PsBridgeProto + 2),
            [char]$accessor.ReadByte($script:Ms2PsBridgeProto + 3)
        )
        if ($label -ne "NBH1") {
            $accessor.Dispose()
            $opened.Dispose()
            return @{ Ok = $false; Reason = "PROTO_MISMATCH"; Attempts = $tried; Retry = $false }
        }
        $generation = $accessor.ReadInt64(112)
        return @{
            Ok = $true
            Reason = "ATTACHED"
            Attempts = $tried
            Retry = $false
            OpenedAs = $used
            Map = $opened
            Accessor = $accessor
            Generation = $generation
        }
    } catch {
        if ($null -ne $accessor) { $accessor.Dispose() }
        $opened.Dispose()
        return @{ Ok = $false; Reason = "VIEW_FAILED"; Attempts = $tried; Retry = $false }
    }
}

function Submit-Ms2PsBridgeRecord($Session, [byte[]]$Record) {
    $started = [System.Diagnostics.Stopwatch]::StartNew()
    if ($null -eq $Session -or -not $Session.Ok) {
        return @{ Status = "REFUSED"; Reason = "NOT_ATTACHED"; ElapsedMs = 0; Retry = $false; ComReadsAdded = 0 }
    }
    if ($null -eq $Record -or $Record.Length -ne $script:Ms2PsBridgeRecordSize) {
        return @{ Status = "REFUSED"; Reason = "RECORD_SIZE"; ElapsedMs = $started.Elapsed.TotalMilliseconds; Retry = $false; ComReadsAdded = 0 }
    }
    $accessor = $Session.Accessor
    $flags = $accessor.ReadInt64(32)
    if ((($flags -band 1) -ne 0) -or (($flags -band 2) -ne 0)) {
        Write-Ms2PsBridgeInt64 $accessor 144 ($accessor.ReadInt64(144) + 1)
        return @{ Status = "KILL_SWITCH"; Reason = "KILL_SWITCH"; ElapsedMs = $started.Elapsed.TotalMilliseconds; Retry = $false; ComReadsAdded = 0 }
    }
    $generation = $accessor.ReadInt64(112)
    if ($generation -ne $Session.Generation) {
        return @{ Status = "DROPPED"; Reason = "GENERATION_MISMATCH"; ElapsedMs = $started.Elapsed.TotalMilliseconds; Retry = $false; ComReadsAdded = 0 }
    }
    $write = $accessor.ReadInt64(0)
    $read = $accessor.ReadInt64(8)
    if (($write - $read) -ge $script:Ms2PsBridgeCapacity) {
        Write-Ms2PsBridgeInt64 $accessor 16 ($accessor.ReadInt64(16) + 1)
        return @{ Status = "DROPPED"; Reason = "DROP_NEWEST"; ElapsedMs = $started.Elapsed.TotalMilliseconds; Retry = $false; ComReadsAdded = 0 }
    }
    $slot = [int64]($script:Ms2PsBridgeSlotBase + (($write % $script:Ms2PsBridgeCapacity) * $script:Ms2PsBridgeRecordSize))
    $writeArgs = New-Object object[] 4
    $writeArgs[0] = $slot
    $writeArgs[1] = $Record
    $writeArgs[2] = [int]0
    $writeArgs[3] = [int]$script:Ms2PsBridgeRecordSize
    [void]$script:Ms2WriteArray.Invoke($accessor, $writeArgs)
    Write-Ms2PsBridgeInt64 $accessor 0 ($write + 1)
    Write-Ms2PsBridgeInt64 $accessor 48 ($accessor.ReadInt64(48) + 1)
    Write-Ms2PsBridgeInt64 $accessor 160 ($accessor.ReadInt64(160) + 1)
    return @{ Status = "ACCEPTED"; Reason = "QUEUED"; ElapsedMs = $started.Elapsed.TotalMilliseconds; Retry = $false; ComReadsAdded = 0 }
}

function Close-Ms2PsBridge($Session) {
    if ($null -eq $Session) { return }
    try { if ($Session.Accessor) { $Session.Accessor.Dispose() } } catch {}
    try { if ($Session.Map) { $Session.Map.Dispose() } } catch {}
}
