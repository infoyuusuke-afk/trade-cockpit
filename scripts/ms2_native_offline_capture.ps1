# Offline local MS2 preservation using built-in Windows PowerShell. No network/order.
param([switch]$SyntheticTest)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$limit = 8MB

function Assert-NoLink([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    $current = $full
    while ($current) {
        if (-not ([IO.File]::Exists($current) -or [IO.Directory]::Exists($current))) {
            throw 'MISSING_PATH'
        }
        if (([IO.File]::GetAttributes($current) -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw 'REPARSE_PATH'
        }
        $parent = [IO.Path]::GetDirectoryName($current)
        if (-not $parent -or $parent -ceq $current) { break }
        $current = $parent
    }
    return $full
}

function Ensure-Folder([string]$Folder) {
    $absolute = [IO.Path]::GetFullPath($Folder)
    $volume = [IO.Path]::GetPathRoot($absolute)
    $parent = Assert-NoLink $volume
    foreach ($segment in ($absolute.Substring($volume.Length) -split '[\\/]')) {
        if (-not $segment) { continue }
        $parent = [IO.Path]::Combine($parent, $segment)
        if (-not [IO.Directory]::Exists($parent)) {
            if ([IO.File]::Exists($parent)) { throw 'NOT_A_DIRECTORY' }
            [void][IO.Directory]::CreateDirectory($parent)
        }
        [void](Assert-NoLink $parent)
    }
    return (Assert-NoLink $parent)
}

function Sha([byte[]]$Bytes) {
    $hash = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($hash.ComputeHash($Bytes)).Replace('-', '').ToLowerInvariant() }
    finally { $hash.Dispose() }
}

function Read-Stable([string]$Path) {
    $full = Assert-NoLink $Path
    $meta = [IO.FileInfo]::new($full)
    if ($meta.Length -le 0 -or $meta.Length -gt $limit) { throw 'INVALID_SIZE' }
    $bytesize = [int]$meta.Length
    $modified = $meta.LastWriteTimeUtc
    $stream = [IO.FileStream]::new($full, [IO.FileMode]::Open,
                                  [IO.FileAccess]::Read, [IO.FileShare]::Read)
    try {
        $views = @()
        for ($pass = 0; $pass -lt 2; $pass++) {
            $stream.Position = 0
            $buffer = [byte[]]::new($bytesize)
            $offset = 0
            while ($offset -lt $bytesize) {
                $read = $stream.Read($buffer, $offset, $bytesize - $offset)
                if ($read -le 0) { throw 'SOURCE_CHANGED' }
                $offset += $read
            }
            if ($stream.Length -ne $bytesize) { throw 'SOURCE_CHANGED' }
            $views += ,$buffer
        }
        if ((Sha $views[0]) -cne (Sha $views[1])) { throw 'SOURCE_CHANGED' }
        $after = [IO.FileInfo]::new($full)
        if ($after.Length -ne $bytesize -or $after.LastWriteTimeUtc -ne $modified) {
            throw 'SOURCE_CHANGED'
        }
        return ,$views[0]
    } finally { $stream.Dispose() }
}

function Assert-Csv([byte[]]$Bytes, [string]$Day) {
    $utf8 = [Text.UTF8Encoding]::new($false, $true)
    $text = $utf8.GetString($Bytes)
    if ($text.StartsWith([string][char]0xFEFF)) { $text = $text.Substring(1) }
    if ($text.Contains([char]0) -or -not $text.EndsWith([string][char]10)) {
        throw 'INVALID_OR_PARTIAL_CSV'
    }
    $lines = $text.Split([char]10)
    if ($lines.Length -lt 3 -or
        $lines[0].TrimEnd([char]13) -cne 'recorded_at,tick_time,price,volume,poll_seq') {
        throw 'INVALID_HEADER'
    }
    $culture = [Globalization.CultureInfo]::InvariantCulture
    for ($i = 1; $i -lt $lines.Length - 1; $i++) {
        $fields = $lines[$i].TrimEnd([char]13).Split(',')
        if ($fields.Length -ne 5) { throw 'INVALID_FIELDS' }
        $dt = [datetime]::MinValue
        if (-not [datetime]::TryParseExact($fields[0], 'yyyy-MM-dd HH:mm:ss',
            $culture, [Globalization.DateTimeStyles]::None, [ref]$dt)) {
            throw 'INVALID_DATE'
        }
        if ($dt.ToString('yyyyMMdd') -cne $Day) { throw 'DATE_MISMATCH' }
        if (-not [datetime]::TryParseExact($fields[1], 'HH:mm:ss',
            $culture, [Globalization.DateTimeStyles]::None, [ref]$dt)) {
            throw 'INVALID_TICK_TIME'
        }
        $price = [decimal]0
        if (-not [decimal]::TryParse($fields[2],
            [Globalization.NumberStyles]::AllowDecimalPoint,
            $culture, [ref]$price) -or $price -le 0) {
            throw 'INVALID_PRICE'
        }
        foreach ($num in @($fields[3], $fields[4])) {
            $v = [long]0
            if ($num -cnotmatch '^\d+$' -or -not [long]::TryParse($num, [ref]$v) -or $v -le 0) {
                throw 'INVALID_VOLUME_OR_POLL'
            }
        }
    }
}

function Save-Csv([string]$Source, [string]$Root) {
    if (-not [IO.Path]::IsPathRooted($Source)) { throw 'SOURCE_NOT_ABSOLUTE' }
    $filename = [IO.Path]::GetFileName($Source)
    if ($filename -cnotmatch '^kioxia_ticks_(\d{8})\.csv$') { throw 'INVALID_NAME' }
    $day = $Matches[1]
    $valid = [datetime]::MinValue
    if (-not [datetime]::TryParseExact($day, 'yyyyMMdd',
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::None, [ref]$valid)) {
        throw 'INVALID_DAY'
    }
    $raw = Read-Stable $Source
    Assert-Csv $raw $day
    $digest = Sha $raw
    if ((Sha (Read-Stable $Source)) -cne $digest) { throw 'SOURCE_CHANGED' }
    $dir = Ensure-Folder $Root
    $final = [IO.Path]::Combine($dir, ($day + '_' + $digest))
    if ([IO.Directory]::Exists($final) -or [IO.File]::Exists($final)) {
        throw 'DUPLICATE_BLOCKED'
    }
    $stage = [IO.Path]::Combine($dir, ('stage_' + [guid]::NewGuid().ToString('N')))
    [void][IO.Directory]::CreateDirectory($stage)
    $published = $false
    try {
        $target = [IO.Path]::Combine($stage, $filename)
        $out = [IO.FileStream]::new($target, [IO.FileMode]::CreateNew,
                                   [IO.FileAccess]::Write, [IO.FileShare]::None)
        try {
            $out.Write($raw, 0, $raw.Length)
            $out.Flush($true)
        } finally { $out.Dispose() }
        if ((Sha ([IO.File]::ReadAllBytes($target))) -cne $digest) {
            throw 'READBACK_MISMATCH'
        }
        $receipt = [ordered]@{
            state = 'PRESERVED_UNAUTHENTICATED'
            source_authenticated = $false
            promotion_eligible = $false
            eligible_observed_n = 0
            real_submit_allowed = $false
            pair_atomic = $false
            size = $raw.Length
            sha256 = $digest
        } | ConvertTo-Json -Compress
        $manifest = [IO.Path]::Combine($stage, 'manifest.json')
        [IO.File]::WriteAllText($manifest, $receipt, [Text.UTF8Encoding]::new($false))
        if ([IO.File]::ReadAllText($manifest) -cne $receipt) { throw 'MANIFEST_MISMATCH' }
        if ((Sha (Read-Stable $Source)) -cne $digest) { throw 'SOURCE_CHANGED_BEFORE_PUBLISH' }
        [IO.Directory]::Move($stage, $final)
        $published = $true
        return 'PRESERVED_UNAUTHENTICATED'
    } finally {
        if (-not $published -and [IO.Directory]::Exists($stage)) {
            [IO.Directory]::Delete($stage, $true)
        }
    }
}

function Test-Synthetic {
    $temp = [IO.Path]::Combine([IO.Path]::GetTempPath(),
                               ('ms2_test_' + [guid]::NewGuid().ToString('N')))
    [void][IO.Directory]::CreateDirectory($temp)
    try {
        $file = [IO.Path]::Combine($temp, 'kioxia_ticks_20260102.csv')
        $lf = [string][char]13 + [string][char]10
        $csv = 'recorded_at,tick_time,price,volume,poll_seq' + $lf +
               '2026-01-02 09:00:00,09:00:00,1,1,1' + $lf
        [byte[]]$bytes = ([Text.UTF8Encoding]::new($true).GetPreamble() +
                           [Text.UTF8Encoding]::new($false).GetBytes($csv))
        [IO.File]::WriteAllBytes($file, $bytes)
        $storage = [IO.Path]::Combine($temp, 'private')
        if ((Save-Csv $file $storage) -cne 'PRESERVED_UNAUTHENTICATED') {
            throw 'SYNTHETIC_SAVE_FAILED'
        }
        $subdirs = @([IO.Directory]::GetDirectories($storage))
        if ($subdirs.Count -ne 1) { throw 'WRONG_SNAPSHOT_COUNT' }
        $copy = [IO.Path]::Combine($subdirs[0], 'kioxia_ticks_20260102.csv')
        if ((Sha ([IO.File]::ReadAllBytes($copy))) -cne (Sha $bytes)) {
            throw 'SYNTHETIC_HASH_MISMATCH'
        }
        if ((Sha ([IO.File]::ReadAllBytes($file))) -cne (Sha $bytes)) {
            throw 'SOURCE_CHANGED'
        }
        $duplicate = $false
        try { [void](Save-Csv $file $storage) } catch { $duplicate = $true }
        if (-not $duplicate) { throw 'DUPLICATE_ALLOWED' }
        [IO.File]::WriteAllText($file, 'invalid')
        $corrupt = $false
        try { [void](Save-Csv $file $storage) } catch { $corrupt = $true }
        if (-not $corrupt) { throw 'CORRUPT_ALLOWED' }
        if ([IO.Directory]::GetDirectories($storage).Count -ne 1) {
            throw 'EXTRA_SNAPSHOT'
        }
        return $true
    } finally { [IO.Directory]::Delete($temp, $true) }
}

if ($SyntheticTest) {
    try {
        if (-not (Test-Synthetic)) { throw 'SYNTHETIC_FAIL' }
        Write-Output 'PASS: SYNTHETIC_ONLY'
        exit 0
    } catch {
        Write-Output 'BLOCKED: SYNTHETIC_ONLY'
        exit 1
    }
}

try {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.Application]::EnableVisualStyles()
    $message = "MS2 WatcherのCSV書き込みを停止してください。" +
               [Environment]::NewLine + "CSV原本は変更しません。" +
               [Environment]::NewLine + "保全先：D:\AI_Cockpit_Data\MS2_CSV" +
               [Environment]::NewLine + "外部通信・実注文なし。続けますか？"
    if ([System.Windows.Forms.MessageBox]::Show($message, 'MS2 CSV保全',
        'OKCancel', 'Information') -ne 'OK') {
        Write-Output 'CANCELLED'
        exit 3
    }
    $picker = New-Object System.Windows.Forms.OpenFileDialog
    $picker.Filter = 'MS2 tick CSV|kioxia_ticks_*.csv'
    $picker.CheckFileExists = $true
    $picker.Multiselect = $false
    if ($picker.ShowDialog() -ne 'OK') {
        Write-Output 'CANCELLED'
        exit 3
    }
    $drive = [IO.DriveInfo]::new('D')
    if (-not $drive.IsReady) { throw 'D_DRIVE_NOT_READY' }
    $destination = 'D:\AI_Cockpit_Data\MS2_CSV\data\private\ms2_csv_snapshots'
    [void](Save-Csv $picker.FileName $destination)
    [void][System.Windows.Forms.MessageBox]::Show(
        'ローカル保全完了（未認証）。実注文は禁止です。',
        'MS2 CSV保全', 'OK', 'Information')
    Write-Output 'PRESERVED_UNAUTHENTICATED: LOCAL_ONLY'
    exit 0
} catch {
    try {
        [void][System.Windows.Forms.MessageBox]::Show(
            '安全検査で停止しました。原本は変更していません。',
            'MS2 CSV保全', 'OK', 'Warning')
    } catch {}
    Write-Output 'BLOCKED: LOCAL_CAPTURE_REFUSED'
    exit 1
}
