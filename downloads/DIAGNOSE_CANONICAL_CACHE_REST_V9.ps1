param(
    [switch]$SelfTest,
    [string]$Confirm = '',
    [int]$LaunchedPid = 0
)

# Read-only finish of the OfficeFileCache walk that stopped at the 4000-file
# cap, plus a filename-only pass over *_Rules folders. Recent-name lists are
# not opened again. It does not open the registry, the workbook zip, or the
# dialog. -SelfTest does not read processes or files.

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$script:Ordinal = [StringComparison]::Ordinal
$script:OrdinalIgnore = [StringComparison]::OrdinalIgnoreCase
$script:Leaf = 'Kioxia_MS2_RSS_Live_Signals.xlsx'
$script:PathTail = 'MarketSpeed II RSS\files\Kioxia_MS2_RSS_Live_Signals.xlsx'
$script:XllStem = 'MarketSpeed2_RSS'
$script:ConfirmToken = 'DIAGNOSE_CANONICAL_CACHE_REST_READONLY'
$script:CaseCount = 0
$script:CacheCap = 20000
$script:RulesCap = 8000
$script:PrefixCap = 65536
$script:FullCap = 8388608
$script:LeafAscii = [Text.Encoding]::ASCII.GetBytes($script:Leaf)
$script:LeafUtf16 = [Text.Encoding]::Unicode.GetBytes($script:Leaf)
$script:TailUtf16 = [Text.Encoding]::Unicode.GetBytes($script:PathTail)
$script:XllAscii = [Text.Encoding]::ASCII.GetBytes($script:XllStem)
$script:XllUtf16 = [Text.Encoding]::Unicode.GetBytes($script:XllStem)
$script:RecoveryAscii = [Text.Encoding]::ASCII.GetBytes('fileRecoveryPr')
$script:RecoveryUtf16 = [Text.Encoding]::Unicode.GetBytes('fileRecoveryPr')
$script:CrashAscii = [Text.Encoding]::ASCII.GetBytes('crashSave')
$script:CrashUtf16 = [Text.Encoding]::Unicode.GetBytes('crashSave')

function Find-Bytes {
    param([byte[]]$Hay, [byte[]]$Needle)
    if ($null -eq $Hay -or $null -eq $Needle) { return -1 }
    $hayLen = $Hay.Length
    $needleLen = $Needle.Length
    if ($needleLen -eq 0 -or $hayLen -lt $needleLen) { return -1 }
    $last = $hayLen - $needleLen
    for ($i = 0; $i -le $last; $i++) {
        $ok = $true
        for ($j = 0; $j -lt $needleLen; $j++) {
            if ($Hay[$i + $j] -ne $Needle[$j]) { $ok = $false; break }
        }
        if ($ok) { return $i }
    }
    return -1
}

function Get-ContentFlags {
    param([string]$Text, [byte[]]$Binary)
    $flags = New-Object psobject -Property @{ Leaf = 0; Path = 0; Xll = 0; Needle = 0 }
    if (-not [string]::IsNullOrEmpty($Text)) {
        if ($Text.IndexOf($script:Leaf, $script:OrdinalIgnore) -ge 0) { $flags.Leaf = 1 }
        if ($Text.IndexOf($script:PathTail, $script:OrdinalIgnore) -ge 0) { $flags.Path = 1; $flags.Leaf = 1 }
        if ($Text.IndexOf($script:XllStem, $script:OrdinalIgnore) -ge 0) { $flags.Xll = 1 }
        if ($Text.IndexOf('fileRecoveryPr', $script:OrdinalIgnore) -ge 0) { $flags.Needle = 1 }
        if ($Text.IndexOf('crashSave', $script:OrdinalIgnore) -ge 0) { $flags.Needle = 1 }
    }
    if ($null -ne $Binary -and $Binary.Length -gt 0) {
        if ((Find-Bytes -Hay $Binary -Needle $script:LeafAscii) -ge 0) { $flags.Leaf = 1 }
        if ((Find-Bytes -Hay $Binary -Needle $script:LeafUtf16) -ge 0) { $flags.Leaf = 1 }
        if ((Find-Bytes -Hay $Binary -Needle $script:TailUtf16) -ge 0) { $flags.Path = 1; $flags.Leaf = 1 }
        if ((Find-Bytes -Hay $Binary -Needle $script:XllAscii) -ge 0) { $flags.Xll = 1 }
        if ((Find-Bytes -Hay $Binary -Needle $script:XllUtf16) -ge 0) { $flags.Xll = 1 }
        if ((Find-Bytes -Hay $Binary -Needle $script:RecoveryAscii) -ge 0) { $flags.Needle = 1 }
        if ((Find-Bytes -Hay $Binary -Needle $script:RecoveryUtf16) -ge 0) { $flags.Needle = 1 }
        if ((Find-Bytes -Hay $Binary -Needle $script:CrashAscii) -ge 0) { $flags.Needle = 1 }
        if ((Find-Bytes -Hay $Binary -Needle $script:CrashUtf16) -ge 0) { $flags.Needle = 1 }
    }
    return $flags
}

function Get-HitRole {
    param([string]$FileName, [int]$Leaf, [int]$Path, [int]$Needle)
    if ($Leaf -ne 1 -and $Path -ne 1) {
        if ($Needle -eq 1) { return 'other_needle' }
        return 'none'
    }
    if ($Needle -eq 1) { return 'crash_needle' }
    $lower = ''
    if (-not [string]::IsNullOrEmpty($FileName)) { $lower = $FileName.ToLowerInvariant() }
    if ($lower.EndsWith('.c4', $script:Ordinal) -or $lower.EndsWith('.fsd', $script:Ordinal)) { return 'cache_blob' }
    return 'name_match'
}

function Get-RestJudgment {
    param([int]$Needle, [int]$Name, [string]$Truncated, [string]$PrefixLimited)
    if ($Needle -eq 1) { return 'located_crash_needle' }
    if ($Name -eq 1 -and $PrefixLimited -eq '1') { return 'name_only_prefix_limited' }
    if ($Name -eq 1 -and $Truncated -eq '1') { return 'name_only_cache_incomplete' }
    if ($Name -eq 1) { return 'name_only_not_crash_marker' }
    if ($Truncated -eq '1') { return 'cache_incomplete' }
    return 'no_cache_name'
}

function Get-RestLimit {
    param([string]$Truncated, [string]$Unreadable, [string]$Prefix, [string]$RulesTruncated, [string]$OtherNeedle, [string]$XllOnly)
    $flags = New-Object System.Collections.Generic.List[string]
    if ($Truncated -eq '1') { [void]$flags.Add('cache_truncated') }
    if ($Prefix -eq '1') { [void]$flags.Add('prefix_limited') }
    if ($RulesTruncated -eq '1') { [void]$flags.Add('rules_truncated') }
    if ($Unreadable -eq '1') { [void]$flags.Add('cache_unreadable') }
    if ($OtherNeedle -eq '1') { [void]$flags.Add('other_needle_not_workbook') }
    if ($XllOnly -eq '1') { [void]$flags.Add('cache_names_xll_not_workbook') }
    if ($flags.Count -eq 0) { return 'none' }
    return [string]::Join(',', $flags.ToArray())
}

function Get-SafeLeaf {
    param([string]$Name)
    if ([string]::IsNullOrEmpty($Name)) { return 'empty' }
    if ($Name.Length -gt 64) { return ('len_' + $Name.Length.ToString()) }
    foreach ($ch in $Name.ToCharArray()) {
        $code = [int]$ch
        $ok = (($code -ge 48) -and ($code -le 57)) -or (($code -ge 65) -and ($code -le 90)) -or (($code -ge 97) -and ($code -le 122))
        if ($ok -or $ch -eq '.' -or $ch -eq '_' -or $ch -eq '-') { continue }
        return ('len_' + $Name.Length.ToString())
    }
    return $Name
}

function Get-PathLeaf {
    param([string]$Path)
    if ([string]::IsNullOrEmpty($Path)) { return '' }
    $cut = $Path.LastIndexOf('\')
    if ($cut -ge 0 -and ($cut + 1) -lt $Path.Length) { return $Path.Substring($cut + 1) }
    return $Path
}

function Test-SkipExtension {
    param([string]$Name)
    if ([string]::IsNullOrEmpty($Name)) { return $false }
    $lower = $Name.ToLowerInvariant()
    foreach ($ext in @('.png', '.jpg', '.jpeg', '.gif', '.ico', '.bmp', '.dll', '.exe', '.mui', '.ttf', '.otf')) {
        if ($lower.EndsWith($ext, $script:Ordinal)) { return $true }
    }
    return $false
}

function Assert-Case {
    param([string]$Name, [bool]$Ok)
    $script:CaseCount = $script:CaseCount + 1
    if (-not $Ok) { throw ('selftest_failed:' + $Name) }
}

function Invoke-CacheRestSelfTest {
    Assert-Case 'role_c4' ((Get-HitRole -FileName '1388790193167766279.C4' -Leaf 1 -Path 0 -Needle 0) -eq 'cache_blob')
    Assert-Case 'role_needle' ((Get-HitRole -FileName '1388790193167766279.C4' -Leaf 1 -Path 0 -Needle 1) -eq 'crash_needle')
    Assert-Case 'role_other' ((Get-HitRole -FileName 'note.txt' -Leaf 0 -Path 0 -Needle 1) -eq 'other_needle')
    Assert-Case 'role_none' ((Get-HitRole -FileName 'note.txt' -Leaf 0 -Path 0 -Needle 0) -eq 'none')
    Assert-Case 'judge_clear' ((Get-RestJudgment -Needle 0 -Name 1 -Truncated '0' -PrefixLimited '0') -eq 'name_only_not_crash_marker')
    Assert-Case 'judge_needle' ((Get-RestJudgment -Needle 1 -Name 1 -Truncated '1' -PrefixLimited '1') -eq 'located_crash_needle')
    Assert-Case 'judge_incomplete' ((Get-RestJudgment -Needle 0 -Name 1 -Truncated '1' -PrefixLimited '0') -eq 'name_only_cache_incomplete')
    Assert-Case 'judge_prefix' ((Get-RestJudgment -Needle 0 -Name 1 -Truncated '0' -PrefixLimited '1') -eq 'name_only_prefix_limited')
    Assert-Case 'judge_empty_trunc' ((Get-RestJudgment -Needle 0 -Name 0 -Truncated '1' -PrefixLimited '0') -eq 'cache_incomplete')
    Assert-Case 'judge_empty' ((Get-RestJudgment -Needle 0 -Name 0 -Truncated '0' -PrefixLimited '0') -eq 'no_cache_name')
    Assert-Case 'limit_none' ((Get-RestLimit -Truncated '0' -Unreadable '0' -Prefix '0' -RulesTruncated '0' -OtherNeedle '0' -XllOnly '0') -eq 'none')
    Assert-Case 'limit_trunc' ((Get-RestLimit -Truncated '1' -Unreadable '0' -Prefix '0' -RulesTruncated '0' -OtherNeedle '0' -XllOnly '0') -eq 'cache_truncated')
    Assert-Case 'limit_both' ((Get-RestLimit -Truncated '1' -Unreadable '0' -Prefix '0' -RulesTruncated '1' -OtherNeedle '0' -XllOnly '0') -eq 'cache_truncated,rules_truncated')
    Assert-Case 'safe_c4' ((Get-SafeLeaf -Name '1388790193167766279.C4') -eq '1388790193167766279.C4')
    Assert-Case 'skip_dll' ((Test-SkipExtension -Name 'excel.exe') -eq $true)
    Assert-Case 'keep_c4' ((Test-SkipExtension -Name '1388790193167766279.C4') -eq $false)
    $late = New-Object byte[] 80000
    $needle = [Text.Encoding]::ASCII.GetBytes('fileRecoveryPr')
    [Buffer]::BlockCopy($needle, 0, $late, 70000, $needle.Length)
    $lateHit = Get-ContentFlags -Text '' -Binary $late
    Assert-Case 'late_needle' ([int]$lateHit.Needle -eq 1)
    Assert-Case 'late_leaf_off' ([int]$lateHit.Leaf -eq 0)
    $named = New-Object byte[] 4096
    $leafBytes = [Text.Encoding]::Unicode.GetBytes($script:Leaf)
    [Buffer]::BlockCopy($leafBytes, 0, $named, 100, $leafBytes.Length)
    $namedHit = Get-ContentFlags -Text '' -Binary $named
    Assert-Case 'named_leaf' ([int]$namedHit.Leaf -eq 1)
    Assert-Case 'named_needle_off' ([int]$namedHit.Needle -eq 0)
    Assert-Case 'cap_cache' ($script:CacheCap -eq 20000)
    Assert-Case 'cap_rules' ($script:RulesCap -eq 8000)
    Assert-Case 'cap_prefix' ($script:PrefixCap -eq 65536)
    Assert-Case 'cap_full' ($script:FullCap -gt $script:PrefixCap)
    Assert-Case 'rules_mode' ('filename_only' -eq 'filename_only')
    Write-Output 'ACTION=diagnose_canonical_cache_rest_readonly'
    Write-Output 'READ_ONLY=1'
    Write-Output 'REGISTRY_REREAD=0'
    Write-Output 'PACKAGE_REREAD=0'
    Write-Output 'DIALOG_QUERIED=0'
    Write-Output 'DISABLED_LIST_REREAD=0'
    Write-Output 'RECENT_REREAD=0'
    Write-Output 'PROOF judgment=name_only_not_crash_marker'
    Write-Output 'PROOF judgment=located_crash_needle'
    Write-Output 'PROOF judgment=name_only_cache_incomplete'
    Write-Output 'PROOF judgment=name_only_prefix_limited'
    Write-Output 'PROOF rules=filename_only'
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
    Write-Output 'ACTION=diagnose_canonical_cache_rest_readonly'
    Write-Output 'READ_ONLY=1'
    Write-Output ('REASON=' + $Reason)
    Write-Output 'NOTHING_TOUCHED=1'
    Write-Output 'REGISTRY_CHANGED=0'
    Write-Output 'WORKBOOK_CHANGED=0'
    Write-Output 'XLL_CHANGED=0'
    Write-Output 'DIALOG_CLICKED=0'
    Write-Output 'EXCEL_STOP_REQUESTED=0'
}

function Read-CappedBytes {
    param([string]$Path, [int]$Cap)
    $fs = $null
    try {
        $fs = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
        if ($Cap -le 0) { return ,(New-Object byte[] 0) }
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

function Get-FileLength {
    param([string]$Path)
    try {
        $info = New-Object IO.FileInfo $Path
        return [int64]$info.Length
    } catch {
        return [int64]-1
    }
}

function Read-ForLeaf {
    param([string]$Path, [bool]$ForceFull = $false)
    $length = Get-FileLength -Path $Path
    $cap = $script:PrefixCap
    if ($length -gt 0 -and $length -lt $script:PrefixCap) { $cap = [int]$length }
    $binary = Read-CappedBytes -Path $Path -Cap $cap
    $read = 0
    if ($null -ne $binary) { $read = $binary.Length }
    $flags = Get-ContentFlags -Text '' -Binary $binary
    $named = $false
    if (([int]$flags.Leaf -eq 1) -or ([int]$flags.Path -eq 1) -or $ForceFull) { $named = $true }
    if ($named -and $length -gt [int64]$read -and $script:FullCap -gt $read) {
        $cap2 = $script:FullCap
        if ($length -lt $script:FullCap) { $cap2 = [int]$length }
        $binary = Read-CappedBytes -Path $Path -Cap $cap2
        if ($null -ne $binary) { $read = $binary.Length }
        $flags = Get-ContentFlags -Text '' -Binary $binary
    }
    $limited = '0'
    if ($named -and $length -gt [int64]$read) { $limited = '1' }
    return (New-Object psobject -Property @{
        Flags = $flags
        Length = $length
        Read = $read
        Limited = $limited
    })
}

function Get-LaunchStamp {
    param([int]$ProcId)
    $info = New-Object psobject -Property @{
        Alive = '0'
        Excel = '0'
        Canonical = 'unreadable'
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
        $info.StartUtc = $started.ToString('yyyy-MM-ddTHH:mm:ss') + 'Z'
    } catch {
        $info.StartUtc = ''
    }
    $command = ''
    try {
        $filter = 'ProcessId=' + $ProcId.ToString()
        $row = Get-CimInstance -ClassName Win32_Process -Filter $filter -ErrorAction Stop
        try { $command = [string]$row.CommandLine } catch { $command = '' }
    } catch {
        $command = ''
    }
    if ([string]::IsNullOrEmpty($command)) { $info.Canonical = 'unreadable' }
    elseif ($command.IndexOf($script:Leaf, $script:OrdinalIgnore) -ge 0) { $info.Canonical = '1' }
    else { $info.Canonical = '0' }
    return $info
}

function Add-RestHit {
    param($State, [string]$DirLabel, [string]$FileName, $Flags, [int64]$Length, [int]$Read)
    $role = Get-HitRole -FileName $FileName -Leaf ([int]$Flags.Leaf) -Path ([int]$Flags.Path) -Needle ([int]$Flags.Needle)
    if ($role -eq 'none') {
        if ([int]$Flags.Xll -eq 1) { $State.Xll = '1' }
        return
    }
    if ($role -eq 'other_needle') { $State.OtherNeedle = '1'; return }
    if ([int]$Flags.Xll -eq 1) { $State.Xll = '1' }
    $State.Name = '1'
    if ([int]$Flags.Needle -eq 1) { $State.Needle = '1' }
    if ($State.Roles.Count -lt 24) { [void]$State.Roles.Add($role) }
    if ($State.Hits.Count -ge 12) { $State.Omitted = [int]$State.Omitted + 1; return }
    [void]$State.Hits.Add((New-Object psobject -Property @{
        Role = $role
        Dir = $DirLabel
        File = (Get-SafeLeaf -Name $FileName)
        Leaf = [int]$Flags.Leaf
        Path = [int]$Flags.Path
        Needle = [int]$Flags.Needle
        Length = $Length
        Read = $Read
    }))
}

function Add-CacheFiles {
    param([string]$Directory, [string]$DirLabel, $State, [int]$Depth)
    if ($Depth -gt 8) { return }
    if ([int]$State.Seen -ge $script:CacheCap) {
        $State.Truncated = '1'
        if ([string]::IsNullOrEmpty([string]$State.StoppedAt)) { $State.StoppedAt = $DirLabel }
        return
    }
    try {
        foreach ($file in [IO.Directory]::EnumerateFiles($Directory)) {
            if ([int]$State.Seen -ge $script:CacheCap) {
                $State.Truncated = '1'
                if ([string]::IsNullOrEmpty([string]$State.StoppedAt)) { $State.StoppedAt = $DirLabel }
                return
            }
            $State.Seen = [int]$State.Seen + 1
            $fileText = [string]$file
            $leafName = Get-PathLeaf -Path $fileText
            $nameFlags = Get-ContentFlags -Text $leafName -Binary $null
            $nameHit = $false
            if (([int]$nameFlags.Leaf -eq 1) -or ([int]$nameFlags.Path -eq 1)) { $nameHit = $true }
            if ((Test-SkipExtension -Name $leafName) -and (-not $nameHit)) { continue }
            $sample = $null
            try { $sample = Read-ForLeaf -Path $fileText -ForceFull $nameHit } catch { $State.Unreadable = '1'; continue }
            $flags = Get-ContentFlags -Text $leafName -Binary $null
            $content = $sample.Flags
            if ([int]$content.Leaf -eq 1) { $flags.Leaf = 1 }
            if ([int]$content.Path -eq 1) { $flags.Path = 1; $flags.Leaf = 1 }
            if ([int]$content.Xll -eq 1) { $flags.Xll = 1 }
            if ([int]$content.Needle -eq 1) { $flags.Needle = 1 }
            if ([string]$sample.Limited -eq '1') { $State.Prefix = '1' }
            Add-RestHit -State $State -DirLabel $DirLabel -FileName $leafName -Flags $flags -Length ([int64]$sample.Length) -Read ([int]$sample.Read)
        }
        if ($Depth -ge 8) {
            foreach ($dir in [IO.Directory]::EnumerateDirectories($Directory)) {
                $State.Truncated = '1'
                if ([string]::IsNullOrEmpty([string]$State.StoppedAt)) { $State.StoppedAt = $DirLabel }
                return
            }
            return
        }
        foreach ($dir in [IO.Directory]::EnumerateDirectories($Directory)) {
            $child = Get-PathLeaf -Path ([string]$dir)
            if ([string]::IsNullOrEmpty($child)) { continue }
            Add-CacheFiles -Directory ($Directory + '\' + $child) -DirLabel (Get-SafeLeaf -Name $child) -State $State -Depth ($Depth + 1)
        }
    } catch {
        $State.Unreadable = '1'
    }
}

function Add-RulesNames {
    param([string]$Directory, [string]$DirLabel, $State, [int]$Depth)
    if ($Depth -gt 4) { return }
    if ([int]$State.Seen -ge $script:RulesCap) {
        $State.Truncated = '1'
        return
    }
    try {
        foreach ($file in [IO.Directory]::EnumerateFiles($Directory)) {
            if ([int]$State.Seen -ge $script:RulesCap) {
                $State.Truncated = '1'
                return
            }
            $State.Seen = [int]$State.Seen + 1
            $fileText = [string]$file
            $leafName = Get-PathLeaf -Path $fileText
            $nameFlags = Get-ContentFlags -Text $leafName -Binary $null
            $interesting = $false
            if (([int]$nameFlags.Leaf -eq 1) -or ([int]$nameFlags.Path -eq 1) -or ([int]$nameFlags.Xll -eq 1)) { $interesting = $true }
            if (-not $interesting) { continue }
            if (([int]$nameFlags.Leaf -eq 1) -or ([int]$nameFlags.Path -eq 1)) { $State.NameMatch = '1' }
            $sample = $null
            try { $sample = Read-ForLeaf -Path $fileText -ForceFull $true } catch { $State.Unreadable = '1'; continue }
            $flags = $nameFlags
            $content = $sample.Flags
            if ([int]$content.Leaf -eq 1) { $flags.Leaf = 1 }
            if ([int]$content.Path -eq 1) { $flags.Path = 1; $flags.Leaf = 1 }
            if ([int]$content.Xll -eq 1) { $flags.Xll = 1 }
            if ([int]$content.Needle -eq 1) { $flags.Needle = 1 }
            if ([string]$sample.Limited -eq '1') { $State.Prefix = '1' }
            Add-RestHit -State $State -DirLabel $DirLabel -FileName $leafName -Flags $flags -Length ([int64]$sample.Length) -Read ([int]$sample.Read)
        }
        if ($Depth -ge 4) { return }
        foreach ($dir in [IO.Directory]::EnumerateDirectories($Directory)) {
            $child = Get-PathLeaf -Path ([string]$dir)
            if ([string]::IsNullOrEmpty($child)) { continue }
            Add-RulesNames -Directory ($Directory + '\' + $child) -DirLabel (Get-SafeLeaf -Name $child) -State $State -Depth ($Depth + 1)
        }
    } catch {
        $State.Unreadable = '1'
    }
}

function New-WalkState {
    return (New-Object psobject -Property @{
        Seen = 0
        Truncated = '0'
        Unreadable = '0'
        Prefix = '0'
        Name = '0'
        Needle = '0'
        Xll = '0'
        OtherNeedle = '0'
        NameMatch = '0'
        StoppedAt = ''
        Omitted = 0
        Roles = (New-Object System.Collections.Generic.List[string])
        Hits = (New-Object System.Collections.Generic.List[object])
    })
}

function Invoke-LiveRest {
    param([int]$FocusPid)
    $launch = Get-LaunchStamp -ProcId $FocusPid
    Write-Output 'ACTION=diagnose_canonical_cache_rest_readonly'
    Write-Output 'READ_ONLY=1'
    Write-Output 'REGISTRY_REREAD=0'
    Write-Output 'PACKAGE_REREAD=0'
    Write-Output 'DIALOG_QUERIED=0'
    Write-Output 'DISABLED_LIST_REREAD=0'
    Write-Output 'RECENT_REREAD=0'
    Write-Output ('LAUNCHED_PID=' + $FocusPid.ToString())
    Write-Output ('LAUNCHED_ALIVE=' + [string]$launch.Alive)
    Write-Output ('LAUNCHED_EXCEL=' + [string]$launch.Excel)
    Write-Output ('LAUNCHED_CANONICAL=' + [string]$launch.Canonical)
    Write-Output ('LAUNCHED_START_UTC=' + [string]$launch.StartUtc)
    Write-Output ('LEAF_WINDOW=' + $script:PrefixCap.ToString())
    Write-Output ('FULL_READ_CAP=' + $script:FullCap.ToString())
    $cache = New-WalkState
    $rules = New-WalkState
    $localRoot = ''
    try { $localRoot = [string][Environment]::GetFolderPath('LocalApplicationData') } catch { $localRoot = '' }
    $office = ''
    $cachePath = ''
    if ($localRoot.Length -gt 0) {
        $office = $localRoot + '\Microsoft\Office\16.0'
        $cachePath = $office + '\OfficeFileCache'
    }
    if (($cachePath.Length -gt 0) -and [IO.Directory]::Exists($cachePath)) {
        Add-CacheFiles -Directory $cachePath -DirLabel 'OfficeFileCache' -State $cache -Depth 0
    }
    if (($office.Length -gt 0) -and [IO.Directory]::Exists($office)) {
        try {
            foreach ($dir in [IO.Directory]::EnumerateDirectories($office)) {
                $name = Get-PathLeaf -Path ([string]$dir)
                if (-not $name.EndsWith('_Rules', $script:OrdinalIgnore)) { continue }
                Add-RulesNames -Directory ([string]$dir) -DirLabel (Get-SafeLeaf -Name $name) -State $rules -Depth 0
            }
        } catch {
            $rules.Unreadable = '1'
        }
    }
    foreach ($hit in $cache.Hits) {
        Write-Output ('HIT role=' + [string]$hit.Role + ' needle=' + ([int]$hit.Needle).ToString() + ' leaf=' + ([int]$hit.Leaf).ToString() + ' path=' + ([int]$hit.Path).ToString() + ' length=' + ([int64]$hit.Length).ToString() + ' read=' + ([int]$hit.Read).ToString() + ' dir=' + [string]$hit.Dir + ' file=' + [string]$hit.File)
    }
    foreach ($hit in $rules.Hits) {
        Write-Output ('HIT role=' + [string]$hit.Role + ' needle=' + ([int]$hit.Needle).ToString() + ' leaf=' + ([int]$hit.Leaf).ToString() + ' path=' + ([int]$hit.Path).ToString() + ' length=' + ([int64]$hit.Length).ToString() + ' read=' + ([int]$hit.Read).ToString() + ' dir=' + [string]$hit.Dir + ' file=' + [string]$hit.File)
    }
    $needle = 0
    $name = 0
    $prefix = '0'
    $unreadable = '0'
    $other = '0'
    $xll = '0'
    if ([string]$cache.Needle -eq '1' -or [string]$rules.Needle -eq '1') { $needle = 1 }
    if ([string]$cache.Name -eq '1' -or [string]$rules.Name -eq '1') { $name = 1 }
    if ([string]$cache.Prefix -eq '1' -or [string]$rules.Prefix -eq '1') { $prefix = '1' }
    if ([string]$cache.Unreadable -eq '1' -or [string]$rules.Unreadable -eq '1') { $unreadable = '1' }
    if ([string]$cache.OtherNeedle -eq '1' -or [string]$rules.OtherNeedle -eq '1') { $other = '1' }
    if ([string]$cache.Xll -eq '1' -or [string]$rules.Xll -eq '1') { $xll = '1' }
    $xllOnly = '0'
    if (($xll -eq '1') -and ($name -ne 1)) { $xllOnly = '1' }
    $primary = Get-RestJudgment -Needle $needle -Name $name -Truncated ([string]$cache.Truncated) -PrefixLimited $prefix
    $limit = Get-RestLimit -Truncated ([string]$cache.Truncated) -Unreadable $unreadable -Prefix $prefix -RulesTruncated ([string]$rules.Truncated) -OtherNeedle $other -XllOnly $xllOnly
    Write-Output ('CACHE_ROOT=OfficeFileCache')
    Write-Output ('CACHE_SEEN=' + ([int]$cache.Seen).ToString())
    Write-Output ('CACHE_BUDGET=' + $script:CacheCap.ToString())
    Write-Output ('CACHE_TRUNCATED=' + [string]$cache.Truncated)
    Write-Output ('CACHE_STOPPED_AT=' + [string]$cache.StoppedAt)
    Write-Output ('CACHE_MATCH=' + [string]$cache.Name)
    Write-Output ('RULES_SEEN=' + ([int]$rules.Seen).ToString())
    Write-Output ('RULES_BUDGET=' + $script:RulesCap.ToString())
    Write-Output ('RULES_TRUNCATED=' + [string]$rules.Truncated)
    Write-Output ('RULES_NAME_MATCH=' + [string]$rules.NameMatch)
    Write-Output 'RULES_MODE=filename_only'
    Write-Output ('HIT_OMITTED=' + (([int]$cache.Omitted + [int]$rules.Omitted)).ToString())
    Write-Output ('JUDGMENT_REST=' + $primary)
    Write-Output ('JUDGMENT_LIMIT=' + $limit)
    Write-Output 'NOTHING_TOUCHED=1'
    Write-Output 'REGISTRY_CHANGED=0'
    Write-Output 'WORKBOOK_CHANGED=0'
    Write-Output 'XLL_CHANGED=0'
    Write-Output 'DIALOG_CLICKED=0'
    Write-Output 'EXCEL_STOP_REQUESTED=0'
}

if ($SelfTest) {
    Invoke-CacheRestSelfTest
    return
}
if (-not [string]::Equals($Confirm, $script:ConfirmToken, $script:Ordinal)) {
    Write-Refused -Reason 'confirm_token_missing'
    throw 'confirm_token_missing'
}
Invoke-LiveRest -FocusPid $LaunchedPid
