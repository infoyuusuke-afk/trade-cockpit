# MS2 CSV one-paste read-only diagnostic

Run this in an **interactive** Windows PowerShell window by pasting the whole command. Do not save or run any .ps1 or unsigned EXE. No ExecutionPolicy change, policy bypass, administrator access, network call, data upload, or write to the CSV is needed.

Default read-only input: D:\AI_Cockpit_Data\MS2_CSV\manual_backup\kioxia_ticks_20261016.csv. The diagnostic prints only aggregate status, SHA-256, counts and safety flags. It never prints price, volume values, absolute paths or CSV rows.

```powershell
$ErrorActionPreference = 'Stop'
$csv = if ($env:MS2_CSV_DIAG_PATH) { $env:MS2_CSV_DIAG_PATH } else { 'D:\AI_Cockpit_Data\MS2_CSV\manual_backup\kioxia_ticks_20261016.csv' }
try {
    $source = Get-Item -LiteralPath $csv -ErrorAction Stop
    if ($source.PSIsContainer -or ($source.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'UNSAFE_FILE' }
    if ($source.Length -lt 64 -or $source.Length -gt 8MB) { throw 'SIZE_INVALID' }
    $raw = [IO.File]::ReadAllBytes($source.FullName)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $digest = [BitConverter]::ToString($sha.ComputeHash($raw)).Replace('-','') } finally { $sha.Dispose() }
    $recheck = (Get-FileHash -LiteralPath $source.FullName -Algorithm SHA256).Hash
    if ($digest -ne $recheck -or $raw.Length -ne $source.Length) { throw 'CHANGED' }
    $match = [regex]::Match($source.Name, '^kioxia_ticks_(\d{8})\.csv$')
    if (-not $match.Success) { throw 'NAME_INVALID' }
    $utf8 = New-Object System.Text.UTF8Encoding($false, $true)
    $data = $utf8.GetString($raw).TrimStart([char]0xFEFF)
    if ($data.Contains([char]0) -or -not $data.EndsWith([string][char]10)) { throw 'PARTIAL_OR_BINARY' }
    $lines = $data.Split([char]10)
    if ($lines.Length -lt 3 -or $lines[0].TrimEnd([char]13) -cne 'recorded_at,tick_time,price,volume,poll_seq') { throw 'HEADER_INVALID' }
    $culture = [Globalization.CultureInfo]::InvariantCulture
    $rows = 0
    $clockReversals = 0
    $pollReversals = 0
    $lastTime = [datetime]::MinValue
    $lastPoll = [long]0
    for ($i = 1; $i -lt $lines.Length - 1; $i++) {
        $f = $lines[$i].TrimEnd([char]13).Split(',')
        if ($f.Length -ne 5) { throw 'FIELD_COUNT' }
        $dt = [datetime]::MinValue
        if (-not [datetime]::TryParseExact($f[0], 'yyyy-MM-dd HH:mm:ss', $culture, [Globalization.DateTimeStyles]::None, [ref]$dt) -or $dt.ToString('yyyyMMdd') -cne $match.Groups[1].Value) { throw 'DATE_INVALID' }
        $tick = [datetime]::MinValue
        if (-not [datetime]::TryParseExact($f[1], 'HH:mm:ss', $culture, [Globalization.DateTimeStyles]::None, [ref]$tick)) { throw 'TICK_TIME_INVALID' }
        $price = [double]0
        if (-not [double]::TryParse($f[2], [Globalization.NumberStyles]::Float, $culture, [ref]$price) -or [double]::IsInfinity($price) -or [double]::IsNaN($price) -or $price -le 0) { throw 'PRICE_INVALID' }
        $volume = [long]0
        $poll = [long]0
        if ($f[3] -cnotmatch '^\d+$' -or -not [long]::TryParse($f[3], [ref]$volume) -or $volume -le 0) { throw 'VOLUME_INVALID' }
        if ($f[4] -cnotmatch '^\d+$' -or -not [long]::TryParse($f[4], [ref]$poll) -or $poll -le 0) { throw 'POLL_INVALID' }
        if ($rows -gt 0 -and $dt -lt $lastTime) { $clockReversals++ }
        if ($rows -gt 0 -and $poll -lt $lastPoll) { $pollReversals++ }
        $lastTime = $dt
        $lastPoll = $poll
        $rows++
    }
    [pscustomobject]@{
        status = 'PASS_READONLY_FORMAT'
        rows = $rows
        bytes = $raw.Length
        sha256 = $digest
        recorded_time_reversals = $clockReversals
        poll_seq_reversals = $pollReversals
        suspected_gap = 'UNKNOWN_NO_DIAG'
        source_authenticated = $false
        eligible_observed_n = 0
        real_submit_allowed = $false
    } | Format-List
} catch {
    Write-Output 'BLOCKED: READONLY_FORMAT_OR_SOURCE'
}
```

PASS_READONLY_FORMAT checks file name, full five-column row format, strict UTF-8 including optional BOM, newline completion, date/time and positive numeric fields, and two separate SHA-256 reads. The counters recorded_time_reversals and poll_seq_reversals are warnings requiring separate analysis, not market provenance or proof of completeness. suspected_gap is UNKNOWN_NO_DIAG until the separate MS2 Watcher diagnostic is examined.

BLOCKED indicates that source contents or conditions could not pass. Never edit the source to force a pass. Neither outcome grants market eligibility or trading. Owner PC results remain UNVERIFIED until run. real_submit_allowed=false, source_authenticated=false, promotion_eligible=false, eligible_observed_n=0.