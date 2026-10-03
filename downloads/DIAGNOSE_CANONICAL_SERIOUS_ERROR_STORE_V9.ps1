param(
    [switch]$SelfTest,
    [string]$Confirm = '',
    [int]$LaunchedPid = 0
)

# Read-only search for where Excel could still mark the canonical workbook
# as a serious-error target. The package crashSave flag and the latest
# crash link are already ruled out. This script does not walk Resiliency,
# does not open the workbook zip, and does not touch the dialog.
# -SelfTest does not read HKCU, processes, or files.

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$script:Ordinal = [StringComparison]::Ordinal
$script:OrdinalIgnore = [StringComparison]::OrdinalIgnoreCase
$script:Leaf = 'Kioxia_MS2_RSS_Live_Signals.xlsx'
$script:Stem = 'Kioxia_MS2_RSS_Live_Signals'
$script:PathTail = 'MarketSpeed II RSS\files\Kioxia_MS2_RSS_Live_Signals.xlsx'
$script:ConfirmToken = 'DIAGNOSE_CANONICAL_SERIOUS_ERROR_STORE_READONLY'
$script:CaseCount = 0
$script:LeafAscii = [Text.Encoding]::ASCII.GetBytes($script:Leaf)
$script:LeafUtf16 = [Text.Encoding]::Unicode.GetBytes($script:Leaf)
$script:TailUtf16 = [Text.Encoding]::Unicode.GetBytes($script:PathTail)
$script:NeedleAscii = [Text.Encoding]::ASCII.GetBytes('fileRecoveryPr')
$script:NeedleUtf16 = [Text.Encoding]::Unicode.GetBytes('fileRecoveryPr')
$script:CrashAscii = [Text.Encoding]::ASCII.GetBytes('crashSave')
$script:CrashUtf16 = [Text.Encoding]::Unicode.GetBytes('crashSave')

function Get-CanonicalFullPath {
    $day = -join @(
        [char]0x30C7,
        [char]0x30A4,
        [char]0x30C8,
        [char]0x30EC
    )
    return ('C:\Users\yusuk\Desktop\' + $day + '\MarketSpeed II RSS\files\' + $script:Leaf)
}

function Find-PatternOffset {
    param([byte[]]$Hay, [byte[]]$Needle, [int]$Start)
    if ($null -eq $Hay -or $null -eq $Needle) { return -1 }
    $limit = $Hay.Length - $Needle.Length
    if ($Needle.Length -eq 0 -or $limit -lt 0) { return -1 }
    if ($Start -lt 0) { $Start = 0 }
    for ($i = $Start; $i -le $limit; $i++) {
        $matched = $true
        for ($j = 0; $j -lt $Needle.Length; $j++) {
            if ($Hay[$i + $j] -ne $Needle[$j]) { $matched = $false; break }
        }
        if ($matched) { return $i }
    }
    return -1
}

function Test-BytesContain {
    param([byte[]]$Hay, [byte[]]$Needle)
    return ((Find-PatternOffset -Hay $Hay -Needle $Needle -Start 0) -ge 0)
}

function Get-ByteHit {
    param([byte[]]$Hay)
    $hit = New-Object psobject -Property @{ Leaf = 0; Path = 0; Needle = 0 }
    if ($null -eq $Hay -or $Hay.Length -eq 0) { return $hit }
    if ((Test-BytesContain -Hay $Hay -Needle $script:LeafAscii) -or (Test-BytesContain -Hay $Hay -Needle $script:LeafUtf16)) { $hit.Leaf = 1 }
    if (Test-BytesContain -Hay $Hay -Needle $script:TailUtf16) { $hit.Path = 1; $hit.Leaf = 1 }
    $needle = (Test-BytesContain -Hay $Hay -Needle $script:NeedleAscii) -or (Test-BytesContain -Hay $Hay -Needle $script:NeedleUtf16)
    $crash = (Test-BytesContain -Hay $Hay -Needle $script:CrashAscii) -or (Test-BytesContain -Hay $Hay -Needle $script:CrashUtf16)
    if ($needle -or $crash) { $hit.Needle = 1 }
    return $hit
}

function Get-TextHit {
    param([string]$Text, [string]$FullPath)
    $hit = New-Object psobject -Property @{ Leaf = 0; Path = 0; Needle = 0 }
    if ([string]::IsNullOrEmpty($Text)) { return $hit }
    if ($Text.IndexOf($script:Leaf, $script:OrdinalIgnore) -ge 0) { $hit.Leaf = 1 }
    if ($Text.IndexOf($script:PathTail, $script:OrdinalIgnore) -ge 0) { $hit.Path = 1; $hit.Leaf = 1 }
    if ((-not [string]::IsNullOrEmpty($FullPath)) -and ($Text.IndexOf($FullPath, $script:OrdinalIgnore) -ge 0)) { $hit.Path = 1; $hit.Leaf = 1 }
    if ($Text.IndexOf('fileRecoveryPr', $script:OrdinalIgnore) -ge 0) { $hit.Needle = 1 }
    if ($Text.IndexOf('crashSave', $script:OrdinalIgnore) -ge 0) { $hit.Needle = 1 }
    return $hit
}

function Get-SafeLabel {
    param([string]$Name)
    if ([string]::IsNullOrEmpty($Name)) { return 'empty' }
    if ($Name.Length -gt 64) { return ('len_' + $Name.Length.ToString()) }
    foreach ($ch in $Name.ToCharArray()) {
        $code = [int]$ch
        if ($code -lt 33 -or $code -gt 126) { return ('len_' + $Name.Length.ToString()) }
        if ($ch -eq '=' -or $ch -eq ' ' -or $ch -eq ':' -or $ch -eq '/' -or $ch -eq '\') {
            return ('len_' + $Name.Length.ToString())
        }
    }
    return $Name
}

function Get-StoreLabel {
    param([string]$Name)
    if ([string]::IsNullOrEmpty($Name)) { return 'empty' }
    $slash = $Name.Replace('\', '/')
    if ($slash.Length -gt 80) { return ('len_' + $Name.Length.ToString()) }
    foreach ($ch in $slash.ToCharArray()) {
        $code = [int]$ch
        $ok = (($code -ge 48) -and ($code -le 57)) -or (($code -ge 65) -and ($code -le 90)) -or (($code -ge 97) -and ($code -le 122))
        if ($ok -or $ch -eq '/' -or $ch -eq '_' -or $ch -eq '-' -or $ch -eq '.') { continue }
        return ('len_' + $Name.Length.ToString())
    }
    return $slash
}

function Get-RegistryArea {
    param([string]$Relative)
    if ([string]::IsNullOrEmpty($Relative)) { return 'registry' }
    $norm = $Relative.Replace('/', '\')
    if ($norm.StartsWith('File MRU', $script:OrdinalIgnore)) { return 'mru' }
    if ($norm.StartsWith('User MRU', $script:OrdinalIgnore)) { return 'mru' }
    if ($norm.StartsWith('Place MRU', $script:OrdinalIgnore)) { return 'mru' }
    if ($norm.IndexOf('\File MRU', $script:OrdinalIgnore) -ge 0) { return 'mru' }
    if ($norm.IndexOf('\User MRU', $script:OrdinalIgnore) -ge 0) { return 'mru' }
    if ($norm.IndexOf('\Place MRU', $script:OrdinalIgnore) -ge 0) { return 'mru' }
    return 'registry'
}

function Test-SkippedRegistry {
    param([string]$Relative)
    if ([string]::IsNullOrEmpty($Relative)) { return $false }
    $norm = $Relative.Replace('/', '\')
    if ($norm.Equals('Resiliency', $script:OrdinalIgnore) -or $norm.StartsWith('Resiliency\', $script:OrdinalIgnore)) { return $true }
    $trust = 'Security\Trusted Documents'
    if ($norm.Equals($trust, $script:OrdinalIgnore) -or $norm.StartsWith($trust + '\', $script:OrdinalIgnore)) { return $true }
    return $false
}

function Get-StoreRole {
    param([string]$Area, [int]$Leaf, [int]$Needle)
    if ($Needle -eq 1) {
        if ($Area -eq 'ads') { return 'ads_crash_needle' }
        return 'crash_needle'
    }
    if ($Leaf -ne 1) { return 'none' }
    if ($Area -eq 'mru') { return 'recent_list' }
    if ($Area -eq 'xlb') { return 'session_list' }
    if ($Area -eq 'excel_appdata') { return 'excel_appdata' }
    if ($Area -eq 'autorecover') { return 'autorecover_file' }
    if ($Area -eq 'unsaved') { return 'unsaved_file' }
    if ($Area -eq 'xlstart') { return 'xlstart_file' }
    if ($Area -eq 'registry') { return 'registry_name_match' }
    if ($Area -eq 'ads') { return 'ads_name_match' }
    return 'name_match'
}

function Test-RolePresent {
    param($Roles, [string]$Role)
    foreach ($item in $Roles) {
        if ([string]::Equals([string]$item, $Role, $script:Ordinal)) { return $true }
    }
    return $false
}

function Get-JudgmentPrimary {
    param($Roles)
    $order = @(
        'ads_crash_needle',
        'crash_needle',
        'session_list',
        'excel_appdata',
        'autorecover_file',
        'unsaved_file',
        'registry_name_match',
        'xlstart_file',
        'ads_name_match',
        'recent_list'
    )
    foreach ($role in $order) {
        if (Test-RolePresent -Roles $Roles -Role $role) {
            if ($role -eq 'ads_crash_needle' -or $role -eq 'crash_needle') { return 'located_crash_needle' }
            if ($role -eq 'recent_list') { return 'recent_list_not_crash_marker' }
            return $role
        }
    }
    return 'not_located'
}

function Get-JudgmentAlso {
    param($Roles, [string]$Primary)
    $list = New-Object System.Collections.Generic.List[string]
    foreach ($item in $Roles) {
        $role = [string]$item
        if ($role.Length -eq 0 -or $role -eq 'none') { continue }
        $shown = $role
        if ($role -eq 'ads_crash_needle' -or $role -eq 'crash_needle') { $shown = 'located_crash_needle' }
        if ($role -eq 'recent_list') { $shown = 'recent_list_not_crash_marker' }
        if ($shown -eq $Primary) { continue }
        if (-not $list.Contains($shown)) { [void]$list.Add($shown) }
    }
    if ($list.Count -eq 0) { return 'none' }
    return [string]::Join(',', $list.ToArray())
}

function Get-JudgmentLimit {
    param([string]$Primary, [string]$AdsState, [string]$RegistryTruncated, [string]$ValuePartial)
    $flags = New-Object System.Collections.Generic.List[string]
    if (($Primary -eq 'recent_list_not_crash_marker') -or ($Primary -eq 'not_located')) {
        if ($AdsState -eq 'unavailable') { [void]$flags.Add('ads_unreadable') }
    }
    if ($Primary -eq 'recent_list_not_crash_marker') { [void]$flags.Add('recent_list_is_not_crash_marker') }
    if ($RegistryTruncated -eq '1') { [void]$flags.Add('registry_truncated') }
    if ($ValuePartial -eq '1') { [void]$flags.Add('registry_value_partial') }
    if ($flags.Count -eq 0) { return 'none' }
    return [string]::Join(',', $flags.ToArray())
}

function Get-WriteRelation {
    param([long]$WriteTicks, [bool]$WriteKnown, [long]$StartTicks, [bool]$StartKnown)
    if (-not $WriteKnown -or $WriteTicks -le 0) { return 'unreadable' }
    if (-not $StartKnown -or $StartTicks -le 0) { return 'start_unreadable' }
    if ($WriteTicks -lt $StartTicks) { return 'before_excel_start' }
    if ($WriteTicks -gt $StartTicks) { return 'after_excel_start' }
    return 'same_second'
}

function Get-StreamSuffix {
    param([string]$Name)
    if ([string]::IsNullOrEmpty($Name)) { return '' }
    $marker = ':$DATA'
    if ($Name.EndsWith($marker, $script:OrdinalIgnore)) {
        return $Name.Substring(0, $Name.Length - $marker.Length)
    }
    return $Name
}

function Assert-Case {
    param([string]$Name, [bool]$Ok)
    $script:CaseCount = $script:CaseCount + 1
    if (-not $Ok) { throw ('selftest_failed:' + $Name) }
}

function Invoke-StoreSelfTest {
    $asciiLeaf = [Text.Encoding]::ASCII.GetBytes('xx ' + $script:Leaf + ' yy')
    $asciiHit = Get-ByteHit -Hay $asciiLeaf
    Assert-Case 'byte_leaf' ([int]$asciiHit.Leaf -eq 1)
    Assert-Case 'byte_no_needle' ([int]$asciiHit.Needle -eq 0)
    $utfNeedle = [Text.Encoding]::Unicode.GetBytes('<fileRecoveryPr crashSave="1"/>')
    $needleHit = Get-ByteHit -Hay $utfNeedle
    Assert-Case 'utf16_needle' ([int]$needleHit.Needle -eq 1)
    $plain = Get-TextHit -Text ('C:\temp\' + $script:Leaf) -FullPath (Get-CanonicalFullPath)
    Assert-Case 'text_leaf' ([int]$plain.Leaf -eq 1)
    Assert-Case 'text_path_off' ([int]$plain.Path -eq 0)
    $full = Get-TextHit -Text (Get-CanonicalFullPath) -FullPath (Get-CanonicalFullPath)
    Assert-Case 'text_path_on' ([int]$full.Path -eq 1)
    Assert-Case 'area_mru' ((Get-RegistryArea -Relative 'User MRU\Live\File MRU') -eq 'mru')
    Assert-Case 'area_options' ((Get-RegistryArea -Relative 'Options') -eq 'registry')
    Assert-Case 'skip_resiliency' (Test-SkippedRegistry -Relative 'Resiliency\DisabledItems')
    Assert-Case 'skip_trust' (Test-SkippedRegistry -Relative 'Security\Trusted Documents\TrustRecords')
    Assert-Case 'keep_options' (-not (Test-SkippedRegistry -Relative 'Options'))
    Assert-Case 'role_mru' ((Get-StoreRole -Area 'mru' -Leaf 1 -Needle 0) -eq 'recent_list')
    Assert-Case 'role_xlb' ((Get-StoreRole -Area 'xlb' -Leaf 1 -Needle 0) -eq 'session_list')
    Assert-Case 'role_appdata' ((Get-StoreRole -Area 'excel_appdata' -Leaf 1 -Needle 0) -eq 'excel_appdata')
    Assert-Case 'role_ads' ((Get-StoreRole -Area 'ads' -Leaf 0 -Needle 1) -eq 'ads_crash_needle')
    Assert-Case 'role_reg' ((Get-StoreRole -Area 'registry' -Leaf 1 -Needle 0) -eq 'registry_name_match')
    Assert-Case 'role_none' ((Get-StoreRole -Area 'xlb' -Leaf 0 -Needle 0) -eq 'none')
    $noneRoles = @()
    Assert-Case 'judge_none' ((Get-JudgmentPrimary -Roles $noneRoles) -eq 'not_located')
    $mruRoles = @('recent_list')
    Assert-Case 'judge_mru' ((Get-JudgmentPrimary -Roles $mruRoles) -eq 'recent_list_not_crash_marker')
    $mixed = @('recent_list', 'session_list')
    Assert-Case 'judge_session' ((Get-JudgmentPrimary -Roles $mixed) -eq 'session_list')
    Assert-Case 'judge_also' ((Get-JudgmentAlso -Roles $mixed -Primary 'session_list') -eq 'recent_list_not_crash_marker')
    $needleRoles = @('recent_list', 'crash_needle')
    Assert-Case 'judge_needle' ((Get-JudgmentPrimary -Roles $needleRoles) -eq 'located_crash_needle')
    Assert-Case 'limit_mru' ((Get-JudgmentLimit -Primary 'recent_list_not_crash_marker' -AdsState 'none' -RegistryTruncated '0' -ValuePartial '0') -eq 'recent_list_is_not_crash_marker')
    Assert-Case 'limit_ads' ((Get-JudgmentLimit -Primary 'not_located' -AdsState 'unavailable' -RegistryTruncated '0' -ValuePartial '0') -eq 'ads_unreadable')
    Assert-Case 'limit_clear' ((Get-JudgmentLimit -Primary 'session_list' -AdsState 'ok' -RegistryTruncated '0' -ValuePartial '0') -eq 'none')
    Assert-Case 'stream_main' ((Get-StreamSuffix -Name '::$DATA') -eq ':')
    Assert-Case 'stream_zone' ((Get-StreamSuffix -Name ':Zone.Identifier:$DATA') -eq ':Zone.Identifier')
    $before = Get-WriteRelation -WriteTicks 10 -WriteKnown $true -StartTicks 20 -StartKnown $true
    Assert-Case 'rel_before' ($before -eq 'before_excel_start')
    $after = Get-WriteRelation -WriteTicks 30 -WriteKnown $true -StartTicks 20 -StartKnown $true
    Assert-Case 'rel_after' ($after -eq 'after_excel_start')
    Assert-Case 'label_plain' ((Get-StoreLabel -Name 'Excel15.xlb') -eq 'Excel15.xlb')
    Assert-Case 'label_redact' ((Get-SafeLabel -Name 'Item 1') -eq 'len_6')
    Write-Output 'ACTION=diagnose_canonical_serious_error_store_readonly'
    Write-Output 'READ_ONLY=1'
    Write-Output 'RESILIENCY_SKIPPED=1'
    Write-Output 'TRUST_SKIPPED=1'
    Write-Output 'PACKAGE_REREAD=0'
    Write-Output 'DIALOG_QUERIED=0'
    Write-Output 'PROOF judgment=not_located'
    Write-Output 'PROOF judgment=located_crash_needle'
    Write-Output 'PROOF judgment=recent_list_not_crash_marker'
    Write-Output 'PROOF judgment=session_list'
    Write-Output ('CASE_COUNT=' + $script:CaseCount.ToString())
    Write-Output 'SELFTEST PASS'
    Write-Output 'NOTHING_TOUCHED=1'
    Write-Output 'REGISTRY_CHANGED=0'
    Write-Output 'WORKBOOK_CHANGED=0'
    Write-Output 'XLL_CHANGED=0'
    Write-Output 'DIALOG_CLICKED=0'
}

function Write-Refused {
    param([string]$Reason)
    Write-Output 'ACTION=diagnose_canonical_serious_error_store_readonly'
    Write-Output 'READ_ONLY=1'
    Write-Output 'NOTHING_TOUCHED=1'
    Write-Output ('REASON=' + $Reason)
    Write-Output 'REGISTRY_CHANGED=0'
    Write-Output 'WORKBOOK_CHANGED=0'
    Write-Output 'XLL_CHANGED=0'
    Write-Output 'DIALOG_CLICKED=0'
}

function Read-CappedBytes {
    param([string]$Path, [int]$Cap)
    $fs = $null
    try {
        $fs = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
        $buf = New-Object byte[] $Cap
        $read = 0
        while ($read -lt $Cap) {
            $n = $fs.Read($buf, $read, ($Cap - $read))
            if ($n -le 0) { break }
            $read = $read + $n
        }
        if ($read -le 0) { return ,(New-Object byte[] 0) }
        if ($read -eq $Cap) { return ,$buf }
        $exact = New-Object byte[] $read
        [Buffer]::BlockCopy($buf, 0, $exact, 0, $read)
        return ,$exact
    } finally {
        if ($null -ne $fs) { $fs.Dispose() }
    }
}

function Add-StreamType {
    try {
        [void][CanonicalStreamList]
        return
    } catch {}
    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

public class CanonicalStreamName {
    public string Name;
    public long Size;
}

public class CanonicalStreamList {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct WIN32_FIND_STREAM_DATA {
        public long StreamSize;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 296)]
        public string StreamName;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern IntPtr FindFirstStreamW(string path, int infoLevel, out WIN32_FIND_STREAM_DATA data, int flags);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern bool FindNextStreamW(IntPtr handle, out WIN32_FIND_STREAM_DATA data);

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool FindClose(IntPtr handle);

    public static List<CanonicalStreamName> List(string path) {
        List<CanonicalStreamName> list = new List<CanonicalStreamName>();
        WIN32_FIND_STREAM_DATA data;
        IntPtr handle = FindFirstStreamW(path, 0, out data, 0);
        if (handle == new IntPtr(-1)) { return list; }
        try {
            do {
                CanonicalStreamName row = new CanonicalStreamName();
                row.Name = data.StreamName;
                row.Size = data.StreamSize;
                list.Add(row);
                if (list.Count >= 16) { break; }
            } while (FindNextStreamW(handle, out data));
        } finally {
            FindClose(handle);
        }
        return list;
    }
}
'@
}

function Get-LaunchStamp {
    param([int]$ProcId)
    $info = New-Object psobject -Property @{
        Alive = '0'
        Excel = '0'
        Canonical = 'unreadable'
        StartKnown = $false
        StartTicks = [int64]0
        StartUtc = ''
    }
    if ($ProcId -le 0) { return $info }
    $proc = $null
    try { $proc = Get-Process -Id $ProcId -ErrorAction Stop } catch { return $info }
    $info.Alive = '1'
    $name = ''
    try { $name = [string]$proc.ProcessName } catch { $name = '' }
    if ($name.Equals('EXCEL', $script:OrdinalIgnore) -or $name.Equals('EXCEL.EXE', $script:OrdinalIgnore)) { $info.Excel = '1' }
    try {
        $started = $proc.StartTime.ToUniversalTime()
        $info.StartTicks = [int64]$started.Ticks
        $info.StartUtc = $started.ToString('yyyy-MM-ddTHH:mm:ss') + 'Z'
        $info.StartKnown = $true
    } catch {
        $info.StartKnown = $false
    }
    $command = ''
    try {
        $filter = 'ProcessId=' + $ProcId.ToString()
        $row = Get-CimInstance -ClassName Win32_Process -Filter $filter -ErrorAction Stop
        try { $command = [string]$row.CommandLine } catch { $command = '' }
    } catch {
        try {
            $filter = 'ProcessId=' + $ProcId.ToString()
            $row = Get-WmiObject -Class Win32_Process -Filter $filter -ErrorAction Stop
            try { $command = [string]$row.CommandLine } catch { $command = '' }
        } catch {
            $command = ''
        }
    }
    if ([string]::IsNullOrEmpty($command)) { $info.Canonical = 'unreadable' }
    elseif ($command.IndexOf($script:Leaf, $script:OrdinalIgnore) -ge 0) { $info.Canonical = '1' }
    else { $info.Canonical = '0' }
    if ($info.Excel -ne '1') { $info.StartKnown = $false }
    return $info
}

function New-StoreHit {
    param([string]$Area, [string]$Name, [int]$Leaf, [int]$Path, [int]$Needle, [string]$Relation, [string]$Role)
    return (New-Object psobject -Property @{
        Area = $Area
        Name = $Name
        Leaf = $Leaf
        Path = $Path
        Needle = $Needle
        Relation = $Relation
        Role = $Role
    })
}

function Add-FileHit {
    param($Hits, [string]$Area, [string]$Path, [string]$FullPath, [long]$StartTicks, [bool]$StartKnown, [bool]$ScanContent)
    if ($null -eq $Hits) { return }
    if ($Hits.Count -ge 40) { return }
    $leafName = $Path
    $cut = $Path.LastIndexOf('\')
    if (($cut -ge 0) -and ($cut -lt ($Path.Length - 1))) { $leafName = $Path.Substring($cut + 1) }
    $nameHit = Get-TextHit -Text $leafName -FullPath $FullPath
    $content = $nameHit
    $relation = 'unreadable'
    $writeKnown = $false
    $writeTicks = [int64]0
    try {
        $item = Get-Item -LiteralPath $Path -ErrorAction Stop
        $writeTicks = [int64]$item.LastWriteTimeUtc.Ticks
        $writeKnown = $true
    } catch {}
    $relation = Get-WriteRelation -WriteTicks $writeTicks -WriteKnown $writeKnown -StartTicks $StartTicks -StartKnown $StartKnown
    if ($ScanContent) {
        $length = [int64]0
        try { $length = [int64](Get-Item -LiteralPath $Path).Length } catch { $length = -1 }
        if (($length -ge 0) -and ($length -le 2000000)) {
            try {
                $raw = Read-CappedBytes -Path $Path -Cap 65536
                $byteHit = Get-ByteHit -Hay $raw
                if ([int]$byteHit.Leaf -eq 1) { $content.Leaf = 1 }
                if ([int]$byteHit.Path -eq 1) { $content.Path = 1; $content.Leaf = 1 }
                if ([int]$byteHit.Needle -eq 1) { $content.Needle = 1 }
            } catch {}
        }
    }
    $role = Get-StoreRole -Area $Area -Leaf ([int]$content.Leaf) -Needle ([int]$content.Needle)
    if ($role -eq 'none') { return }
    [void]$Hits.Add((New-StoreHit -Area $Area -Name (Get-SafeLabel -Name $leafName) -Leaf ([int]$content.Leaf) -Path ([int]$content.Path) -Needle ([int]$content.Needle) -Relation $relation -Role $role))
}

function Add-DirectoryHits {
    param($Hits, [string]$Area, [string]$Directory, [string]$FullPath, [long]$StartTicks, [bool]$StartKnown, [int]$Budget)
    if ([string]::IsNullOrEmpty($Directory)) { return 0 }
    if (-not [IO.Directory]::Exists($Directory)) { return 0 }
    $seen = 0
    try {
        foreach ($file in [IO.Directory]::EnumerateFiles($Directory)) {
            if ($seen -ge $Budget) { return $seen }
            $seen = $seen + 1
            $useArea = $Area
            if ([string]$file.EndsWith('.xlb', $script:OrdinalIgnore)) { $useArea = 'xlb' }
            Add-FileHit -Hits $Hits -Area $useArea -Path ([string]$file) -FullPath $FullPath -StartTicks $StartTicks -StartKnown $StartKnown -ScanContent $true
        }
    } catch {}
    return $seen
}

function Get-AutoRecoverClass {
    param([string]$Value, [string]$DefaultDir)
    if ([string]::IsNullOrEmpty($Value)) { return 'absent' }
    $expanded = $Value
    try { $expanded = [Environment]::ExpandEnvironmentVariables($Value) } catch { $expanded = $Value }
    $left = $expanded.TrimEnd('\')
    $right = ''
    if (-not [string]::IsNullOrEmpty($DefaultDir)) { $right = $DefaultDir.TrimEnd('\') }
    if ((-not [string]::IsNullOrEmpty($right)) -and $left.Equals($right, $script:OrdinalIgnore)) { return 'default' }
    return 'custom'
}

function Add-ExcelRegistryStores {
    param($Opened, [string]$Relative, $Hits, $State, [string]$FullPath, [int]$Depth)
    if ($null -eq $Opened) { return }
    if ($Depth -gt 5) { return }
    if ([int]$State.Values -ge 400 -or [int]$State.Keys -ge 80) { $State.Truncated = '1'; return }
    if (Test-SkippedRegistry -Relative $Relative) { return }
    $State.Keys = [int]$State.Keys + 1
    $names = @()
    try { $names = @($Opened.GetValueNames()) } catch { return }
    foreach ($name in $names) {
        if ([int]$State.Values -ge 400) { $State.Truncated = '1'; return }
        $State.Values = [int]$State.Values + 1
        $valueName = [string]$name
        if ($valueName.IndexOf('Password', $script:OrdinalIgnore) -ge 0) { continue }
        $kindName = ''
        try { $kindName = [string]$Opened.GetValueKind($valueName) } catch { $kindName = '' }
        $text = ''
        $binary = $null
        if (($kindName -eq 'String') -or ($kindName -eq 'ExpandString')) {
            try { $text = [string]$Opened.GetValue($valueName, '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames) } catch { $text = '' }
        } elseif ($kindName -eq 'MultiString') {
            try {
                $parts = @($Opened.GetValue($valueName))
                $text = [string]::Join("`n", $parts)
            } catch { $text = '' }
        } elseif ($kindName -eq 'Binary') {
            try {
                $raw = $Opened.GetValue($valueName)
                if ($raw -is [byte[]]) {
                    $take = $raw.Length
                    if ($take -gt 65536) { $take = 65536; $State.Partial = '1' }
                    $binary = New-Object byte[] $take
                    [Buffer]::BlockCopy($raw, 0, $binary, 0, $take)
                }
            } catch { $binary = $null }
        } else {
            continue
        }
        $hit = Get-TextHit -Text ($valueName + ' ' + $text) -FullPath $FullPath
        if ($null -ne $binary) {
            $byteHit = Get-ByteHit -Hay $binary
            if ([int]$byteHit.Leaf -eq 1) { $hit.Leaf = 1 }
            if ([int]$byteHit.Path -eq 1) { $hit.Path = 1; $hit.Leaf = 1 }
            if ([int]$byteHit.Needle -eq 1) { $hit.Needle = 1 }
        }
        $area = Get-RegistryArea -Relative $Relative
        $role = Get-StoreRole -Area $area -Leaf ([int]$hit.Leaf) -Needle ([int]$hit.Needle)
        if ($role -eq 'none') { continue }
        if ($Hits.Count -ge 40) { $State.Truncated = '1'; return }
        $label = (Get-StoreLabel -Name $Relative) + '/' + (Get-SafeLabel -Name $valueName)
        [void]$Hits.Add((New-StoreHit -Area $area -Name $label -Leaf ([int]$hit.Leaf) -Path ([int]$hit.Path) -Needle ([int]$hit.Needle) -Relation 'registry' -Role $role))
    }
    $children = @()
    try { $children = @($Opened.GetSubKeyNames()) } catch { return }
    foreach ($child in $children) {
        $childName = [string]$child
        $next = $childName
        if ($Relative.Length -gt 0) { $next = $Relative + '\' + $childName }
        if (Test-SkippedRegistry -Relative $next) { continue }
        $sub = $null
        try { $sub = $Opened.OpenSubKey($childName, $false) } catch { $sub = $null }
        if ($null -eq $sub) { continue }
        try {
            Add-ExcelRegistryStores -Opened $sub -Relative $next -Hits $Hits -State $State -FullPath $FullPath -Depth ($Depth + 1)
        } finally {
            $sub.Dispose()
        }
    }
}

function Invoke-LiveStore {
    param([int]$FocusPid)
    $fullPath = Get-CanonicalFullPath
    $launch = Get-LaunchStamp -ProcId $FocusPid
    $startKnown = [bool]$launch.StartKnown
    $startTicks = [int64]$launch.StartTicks
    Write-Output 'ACTION=diagnose_canonical_serious_error_store_readonly'
    Write-Output 'READ_ONLY=1'
    Write-Output 'RESILIENCY_SKIPPED=1'
    Write-Output 'TRUST_SKIPPED=1'
    Write-Output 'PACKAGE_REREAD=0'
    Write-Output 'DIALOG_QUERIED=0'
    Write-Output ('LAUNCHED_PID=' + $FocusPid.ToString())
    Write-Output ('LAUNCHED_ALIVE=' + [string]$launch.Alive)
    Write-Output ('LAUNCHED_EXCEL=' + [string]$launch.Excel)
    Write-Output ('LAUNCHED_CANONICAL=' + [string]$launch.Canonical)
    Write-Output ('LAUNCHED_START_UTC=' + [string]$launch.StartUtc)
    $hits = New-Object System.Collections.Generic.List[object]
    $adsState = 'unavailable'
    if ([IO.File]::Exists($fullPath)) {
        try {
            Add-StreamType
            $streams = [CanonicalStreamList]::List($fullPath)
            $adsState = 'unavailable'
            $sawMain = $false
            foreach ($stream in $streams) {
                $rawName = ''
                try { $rawName = [string]$stream.Name } catch { $rawName = '' }
                $suffix = Get-StreamSuffix -Name $rawName
                if ([string]::IsNullOrEmpty($suffix) -or $suffix -eq ':') {
                    if ($suffix -eq ':') { $sawMain = $true }
                    continue
                }
                $adsState = 'ok'
                $openPath = $fullPath + $suffix
                $leafFlag = 0
                $pathFlag = 0
                $needleFlag = 0
                try {
                    $raw = Read-CappedBytes -Path $openPath -Cap 65536
                    $byteHit = Get-ByteHit -Hay $raw
                    $leafFlag = [int]$byteHit.Leaf
                    $pathFlag = [int]$byteHit.Path
                    $needleFlag = [int]$byteHit.Needle
                } catch {}
                $role = Get-StoreRole -Area 'ads' -Leaf $leafFlag -Needle $needleFlag
                if ($role -eq 'none') { continue }
                if ($hits.Count -lt 40) {
                    [void]$hits.Add((New-StoreHit -Area 'ads' -Name (Get-SafeLabel -Name $suffix) -Leaf $leafFlag -Path $pathFlag -Needle $needleFlag -Relation 'stream' -Role $role))
                }
            }
            if (($adsState -ne 'ok') -and $sawMain) { $adsState = 'none' }
        } catch {
            $adsState = 'unavailable'
        }
    } else {
        $adsState = 'workbook_absent'
    }
    $roaming = ''
    $local = ''
    try { $roaming = [string][Environment]::GetFolderPath('ApplicationData') } catch { $roaming = '' }
    try { $local = [string][Environment]::GetFolderPath('LocalApplicationData') } catch { $local = '' }
    $excelDir = ''
    if ($roaming.Length -gt 0) { $excelDir = $roaming + '\Microsoft\Excel' }
    if ($excelDir.Length -gt 0) {
        [void](Add-DirectoryHits -Hits $hits -Area 'excel_appdata' -Directory $excelDir -FullPath $fullPath -StartTicks $startTicks -StartKnown $startKnown -Budget 80)
        [void](Add-DirectoryHits -Hits $hits -Area 'xlstart' -Directory ($excelDir + '\XLSTART') -FullPath $fullPath -StartTicks $startTicks -StartKnown $startKnown -Budget 40)
        [void](Add-DirectoryHits -Hits $hits -Area 'autorecover' -Directory ($excelDir + '\AutoRecover') -FullPath $fullPath -StartTicks $startTicks -StartKnown $startKnown -Budget 40)
    }
    if ($local.Length -gt 0) {
        [void](Add-DirectoryHits -Hits $hits -Area 'unsaved' -Directory ($local + '\Microsoft\Office\UnsavedFiles') -FullPath $fullPath -StartTicks $startTicks -StartKnown $startKnown -Budget 40)
    }
    $autoClass = 'unreadable'
    $registryState = New-Object psobject -Property @{ Values = 0; Keys = 0; Truncated = '0'; Partial = '0' }
    $excelKey = $null
    try {
        $excelKey = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Software\Microsoft\Office\16.0\Excel', $false)
        if ($null -eq $excelKey) { $autoClass = 'absent' }
        else {
            $autoRaw = ''
            $optionsKey = $null
            try {
                $optionsKey = $excelKey.OpenSubKey('Options', $false)
                if ($null -ne $optionsKey) {
                    $autoRaw = [string]$optionsKey.GetValue('AutoRecoverPath', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
                }
            } catch {
                $autoRaw = ''
            } finally {
                if ($null -ne $optionsKey) { $optionsKey.Dispose() }
            }
            $autoClass = Get-AutoRecoverClass -Value $autoRaw -DefaultDir $excelDir
            if ($autoClass -eq 'custom') {
                $customDir = $autoRaw
                try { $customDir = [Environment]::ExpandEnvironmentVariables($autoRaw) } catch { $customDir = $autoRaw }
                [void](Add-DirectoryHits -Hits $hits -Area 'autorecover' -Directory $customDir -FullPath $fullPath -StartTicks $startTicks -StartKnown $startKnown -Budget 40)
            }
            Add-ExcelRegistryStores -Opened $excelKey -Relative '' -Hits $hits -State $registryState -FullPath $fullPath -Depth 0
        }
    } catch {
        $autoClass = 'unreadable'
        $registryState.Truncated = '1'
    } finally {
        if ($null -ne $excelKey) { $excelKey.Dispose() }
    }
    $roles = New-Object System.Collections.Generic.List[string]
    $printed = 0
    foreach ($hit in $hits) {
        if ($null -eq $hit) { continue }
        $role = [string]$hit.Role
        if ((-not [string]::IsNullOrEmpty($role)) -and ($role -ne 'none') -and (-not $roles.Contains($role))) { [void]$roles.Add($role) }
        if ($printed -ge 12) { continue }
        $printed = $printed + 1
        Write-Output ('STORE area=' + [string]$hit.Area + ' name=' + [string]$hit.Name + ' leaf=' + ([int]$hit.Leaf).ToString() + ' path=' + ([int]$hit.Path).ToString() + ' needle=' + ([int]$hit.Needle).ToString() + ' relation=' + [string]$hit.Relation + ' role=' + $role)
    }
    $primary = Get-JudgmentPrimary -Roles $roles
    $also = Get-JudgmentAlso -Roles $roles -Primary $primary
    $limit = Get-JudgmentLimit -Primary $primary -AdsState $adsState -RegistryTruncated ([string]$registryState.Truncated) -ValuePartial ([string]$registryState.Partial)
    Write-Output ('ADS_STATUS=' + $adsState)
    Write-Output ('AUTORECOVER_PATH=' + $autoClass)
    Write-Output ('REGISTRY_VALUES=' + ([int]$registryState.Values).ToString())
    Write-Output ('REGISTRY_TRUNCATED=' + [string]$registryState.Truncated)
    Write-Output ('STORE_HIT_COUNT=' + $hits.Count.ToString())
    Write-Output ('STORE_PRINTED=' + $printed.ToString())
    Write-Output ('JUDGMENT_STORE=' + $primary)
    Write-Output ('JUDGMENT_ALSO=' + $also)
    Write-Output ('JUDGMENT_LIMIT=' + $limit)
    Write-Output 'NOTHING_TOUCHED=1'
    Write-Output 'REGISTRY_CHANGED=0'
    Write-Output 'WORKBOOK_CHANGED=0'
    Write-Output 'XLL_CHANGED=0'
    Write-Output 'DIALOG_CLICKED=0'
    Write-Output 'EXCEL_STOP_REQUESTED=0'
}

if ($SelfTest) {
    Invoke-StoreSelfTest
    return
}
if (-not [string]::Equals($Confirm, $script:ConfirmToken, $script:Ordinal)) {
    Write-Refused -Reason 'confirm_token_missing'
    throw 'confirm_token_missing'
}
Invoke-LiveStore -FocusPid $LaunchedPid
