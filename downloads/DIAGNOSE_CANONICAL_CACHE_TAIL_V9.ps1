param(
    [switch]$SelfTest,
    [string]$Confirm = '',
    [int]$LaunchedPid = 0
)

# Read-only tail of OfficeFileCache files larger than 64KB. The finished
# cache walk already read every shorter file, and every file that named the
# workbook in that prefix. This script does not open those short files, the
# rules folders, the registry, the workbook zip, or the dialog.
# -SelfTest does not read processes or files.

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$script:Ordinal = [StringComparison]::Ordinal
$script:OrdinalIgnore = [StringComparison]::OrdinalIgnoreCase
$script:Leaf = 'Kioxia_MS2_RSS_Live_Signals.xlsx'
$script:PathTail = 'MarketSpeed II RSS\files\Kioxia_MS2_RSS_Live_Signals.xlsx'
$script:XllStem = 'MarketSpeed2_RSS'
$script:ConfirmToken = 'DIAGNOSE_CANONICAL_CACHE_TAIL_READONLY'
$script:CaseCount = 0
$script:PrefixCap = 65536
$script:Overlap = 128
$script:TailCap = 8388608
$script:LargeBudget = 4000
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

function Get-TailStart {
    return ($script:PrefixCap - $script:Overlap)
}

function Test-ShortFile {
    param([int64]$Length)
    if ($Length -lt 0) { return $false }
    if ($Length -le $script:PrefixCap) { return $true }
    return $false
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

function Get-TailJudgment {
    param([int]$Needle, [int]$Name, [string]$Truncated, [string]$Limited)
    if ($Needle -eq 1) { return 'located_crash_needle' }
    if ($Name -eq 1 -and $Limited -eq '1') { return 'name_only_tail_limited' }
    if ($Name -eq 1 -and $Truncated -eq '1') { return 'name_only_cache_incomplete' }
    if ($Name -eq 1) { return 'name_only_not_crash_marker' }
    if ($Truncated -eq '1') { return 'cache_incomplete' }
    if ($Limited -eq '1') { return 'cache_incomplete' }
    return 'no_tail_name'
}

function Get-TailLimit {
    param([string]$Truncated, [string]$Unreadable, [string]$Limited, [string]$OtherNeedle, [string]$XllOnly)
    $flags = New-Object System.Collections.Generic.List[string]
    if ($Truncated -eq '1') { [void]$flags.Add('cache_truncated') }
    if ($Limited -eq '1') { [void]$flags.Add('tail_limited') }
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

function Invoke-CacheTailSelfTest {
    Assert-Case 'short_32k' ((Test-ShortFile -Length 32768) -eq $true)
    Assert-Case 'short_64k' ((Test-ShortFile -Length 65536) -eq $true)
    Assert-Case 'large_144k' ((Test-ShortFile -Length 147456) -eq $false)
    Assert-Case 'tail_start' ((Get-TailStart) -eq 65408)
    Assert-Case 'role_tail_blob' ((Get-HitRole -FileName '1388790193167766279.C4' -Leaf 1 -Path 0 -Needle 0) -eq 'cache_blob')
    Assert-Case 'role_tail_needle' ((Get-HitRole -FileName '1388790193167766279.C4' -Leaf 1 -Path 0 -Needle 1) -eq 'crash_needle')
    Assert-Case 'role_other' ((Get-HitRole -FileName 'note.bin' -Leaf 0 -Path 0 -Needle 1) -eq 'other_needle')
    Assert-Case 'judge_clear' ((Get-TailJudgment -Needle 0 -Name 1 -Truncated '0' -Limited '0') -eq 'name_only_not_crash_marker')
    Assert-Case 'judge_needle' ((Get-TailJudgment -Needle 1 -Name 1 -Truncated '1' -Limited '1') -eq 'located_crash_needle')
    Assert-Case 'judge_incomplete' ((Get-TailJudgment -Needle 0 -Name 1 -Truncated '1' -Limited '0') -eq 'name_only_cache_incomplete')
    Assert-Case 'judge_limited' ((Get-TailJudgment -Needle 0 -Name 1 -Truncated '0' -Limited '1') -eq 'name_only_tail_limited')
    Assert-Case 'judge_empty' ((Get-TailJudgment -Needle 0 -Name 0 -Truncated '0' -Limited '0') -eq 'no_tail_name')
    Assert-Case 'judge_trunc' ((Get-TailJudgment -Needle 0 -Name 0 -Truncated '1' -Limited '0') -eq 'cache_incomplete')
    Assert-Case 'limit_none' ((Get-TailLimit -Truncated '0' -Unreadable '0' -Limited '0' -OtherNeedle '0' -XllOnly '0') -eq 'none')
    Assert-Case 'limit_tail' ((Get-TailLimit -Truncated '0' -Unreadable '0' -Limited '1' -OtherNeedle '0' -XllOnly '0') -eq 'tail_limited')
    $late = New-Object byte[] 200
    $leafBytes = [Text.Encoding]::ASCII.GetBytes($script:Leaf)
    [Buffer]::BlockCopy($leafBytes, 0, $late, 20, $leafBytes.Length)
    $lateHit = Get-ContentFlags -Text '' -Binary $late
    Assert-Case 'tail_leaf' ([int]$lateHit.Leaf -eq 1)
    Assert-Case 'tail_leaf_needle_off' ([int]$lateHit.Needle -eq 0)
    $span = New-Object byte[] 160
    $needle = [Text.Encoding]::Unicode.GetBytes('crashSave')
    [Buffer]::BlockCopy($needle, 0, $span, 40, $needle.Length)
    $spanHit = Get-ContentFlags -Text '' -Binary $span
    Assert-Case 'overlap_needle' ([int]$spanHit.Needle -eq 1)
    Assert-Case 'budget' ($script:LargeBudget -eq 4000)
    Assert-Case 'skip_dll' ((Test-SkipExtension -Name 'cache.dll') -eq $true)
    Assert-Case 'keep_c4' ((Test-SkipExtension -Name '1388790193167766279.C4') -eq $false)
    Write-Output 'ACTION=diagnose_canonical_cache_tail_readonly'
    Write-Output 'READ_ONLY=1'
    Write-Output 'REGISTRY_REREAD=0'
    Write-Output 'PACKAGE_REREAD=0'
    Write-Output 'DIALOG_QUERIED=0'
    Write-Output 'DISABLED_LIST_REREAD=0'
    Write-Output 'SHORT_REREAD=0'
    Write-Output 'RULES_REREAD=0'
    Write-Output 'PROOF judgment=name_only_not_crash_marker'
    Write-Output 'PROOF judgment=located_crash_needle'
    Write-Output 'PROOF judgment=no_tail_name'
    Write-Output 'PROOF short=65536'
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
    Write-Output 'ACTION=diagnose_canonical_cache_tail_readonly'
    Write-Output 'READ_ONLY=1'
    Write-Output ('REASON=' + $Reason)
    Write-Output 'NOTHING_TOUCHED=1'
    Write-Output 'REGISTRY_CHANGED=0'
    Write-Output 'WORKBOOK_CHANGED=0'
    Write-Output 'XLL_CHANGED=0'
    Write-Output 'DIALOG_CLICKED=0'
    Write-Output 'EXCEL_STOP_REQUESTED=0'
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

function Read-TailBytes {
    param([string]$Path, [int64]$Offset, [int]$Cap)
    $fs = $null
    try {
        $fs = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
        if ($Cap -le 0) { return ,(New-Object byte[] 0) }
        if ($Offset -gt 0) { [void]$fs.Seek($Offset, [IO.SeekOrigin]::Begin) }
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

function Add-TailHit {
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

function Add-TailFiles {
    param([string]$Directory, [string]$DirLabel, $State, [int]$Depth)
    if ($Depth -gt 8) { return }
    if ([int]$State.Large -ge $script:LargeBudget) {
        $State.Truncated = '1'
        if ([string]::IsNullOrEmpty([string]$State.StoppedAt)) { $State.StoppedAt = $DirLabel }
        return
    }
    try {
        foreach ($file in [IO.Directory]::EnumerateFiles($Directory)) {
            if ([int]$State.Large -ge $script:LargeBudget) {
                $State.Truncated = '1'
                if ([string]::IsNullOrEmpty([string]$State.StoppedAt)) { $State.StoppedAt = $DirLabel }
                return
            }
            $fileText = [string]$file
            $leafName = Get-PathLeaf -Path $fileText
            $length = Get-FileLength -Path $fileText
            if ($length -lt 0) { $State.Unreadable = '1'; continue }
            if (Test-ShortFile -Length $length) { $State.Short = [int]$State.Short + 1; continue }
            $nameFlags = Get-ContentFlags -Text $leafName -Binary $null
            $nameHit = $false
            if (([int]$nameFlags.Leaf -eq 1) -or ([int]$nameFlags.Path -eq 1)) { $nameHit = $true }
            if ((Test-SkipExtension -Name $leafName) -and (-not $nameHit)) { $State.SkipExt = [int]$State.SkipExt + 1; continue }
            $State.Large = [int]$State.Large + 1
            $offset = [int64](Get-TailStart)
            $remain = $length - $offset
            $cap = $script:TailCap
            $limited = $false
            if ($remain -gt $script:TailCap) { $limited = $true; $State.Limited = '1' }
            if ($remain -gt 0 -and $remain -lt $cap) { $cap = [int]$remain }
            $binary = $null
            try { $binary = Read-TailBytes -Path $fileText -Offset $offset -Cap $cap } catch { $State.Unreadable = '1'; continue }
            $read = 0
            if ($null -ne $binary) { $read = $binary.Length }
            $flags = Get-ContentFlags -Text $leafName -Binary $binary
            Add-TailHit -State $State -DirLabel $DirLabel -FileName $leafName -Flags $flags -Length $length -Read $read
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
            Add-TailFiles -Directory ($Directory + '\' + $child) -DirLabel (Get-SafeLeaf -Name $child) -State $State -Depth ($Depth + 1)
        }
    } catch {
        $State.Unreadable = '1'
    }
}

function Invoke-LiveTail {
    param([int]$FocusPid)
    $launch = Get-LaunchStamp -ProcId $FocusPid
    Write-Output 'ACTION=diagnose_canonical_cache_tail_readonly'
    Write-Output 'READ_ONLY=1'
    Write-Output 'REGISTRY_REREAD=0'
    Write-Output 'PACKAGE_REREAD=0'
    Write-Output 'DIALOG_QUERIED=0'
    Write-Output 'DISABLED_LIST_REREAD=0'
    Write-Output 'SHORT_REREAD=0'
    Write-Output 'RULES_REREAD=0'
    Write-Output ('LAUNCHED_PID=' + $FocusPid.ToString())
    Write-Output ('LAUNCHED_ALIVE=' + [string]$launch.Alive)
    Write-Output ('LAUNCHED_EXCEL=' + [string]$launch.Excel)
    Write-Output ('LAUNCHED_CANONICAL=' + [string]$launch.Canonical)
    Write-Output ('LAUNCHED_START_UTC=' + [string]$launch.StartUtc)
    Write-Output ('TAIL_START=' + (Get-TailStart).ToString())
    Write-Output ('TAIL_CAP=' + $script:TailCap.ToString())
    $state = New-Object psobject -Property @{
        Short = 0
        Large = 0
        SkipExt = 0
        Truncated = '0'
        Unreadable = '0'
        Limited = '0'
        Name = '0'
        Needle = '0'
        Xll = '0'
        OtherNeedle = '0'
        StoppedAt = ''
        Omitted = 0
        Hits = (New-Object System.Collections.Generic.List[object])
    }
    $localRoot = ''
    try { $localRoot = [string][Environment]::GetFolderPath('LocalApplicationData') } catch { $localRoot = '' }
    $cachePath = ''
    if ($localRoot.Length -gt 0) { $cachePath = $localRoot + '\Microsoft\Office\16.0\OfficeFileCache' }
    if (($cachePath.Length -gt 0) -and [IO.Directory]::Exists($cachePath)) {
        Add-TailFiles -Directory $cachePath -DirLabel 'OfficeFileCache' -State $state -Depth 0
    }
    foreach ($hit in $state.Hits) {
        Write-Output ('HIT role=' + [string]$hit.Role + ' needle=' + ([int]$hit.Needle).ToString() + ' leaf=' + ([int]$hit.Leaf).ToString() + ' path=' + ([int]$hit.Path).ToString() + ' length=' + ([int64]$hit.Length).ToString() + ' read=' + ([int]$hit.Read).ToString() + ' dir=' + [string]$hit.Dir + ' file=' + [string]$hit.File)
    }
    $needle = 0
    $name = 0
    if ([string]$state.Needle -eq '1') { $needle = 1 }
    if ([string]$state.Name -eq '1') { $name = 1 }
    $xllOnly = '0'
    if (([string]$state.Xll -eq '1') -and ($name -ne 1)) { $xllOnly = '1' }
    $primary = Get-TailJudgment -Needle $needle -Name $name -Truncated ([string]$state.Truncated) -Limited ([string]$state.Limited)
    $limit = Get-TailLimit -Truncated ([string]$state.Truncated) -Unreadable ([string]$state.Unreadable) -Limited ([string]$state.Limited) -OtherNeedle ([string]$state.OtherNeedle) -XllOnly $xllOnly
    Write-Output 'CACHE_ROOT=OfficeFileCache'
    Write-Output ('SHORT_SEEN=' + ([int]$state.Short).ToString())
    Write-Output ('LARGE_SEEN=' + ([int]$state.Large).ToString())
    Write-Output ('LARGE_BUDGET=' + $script:LargeBudget.ToString())
    Write-Output ('LARGE_TRUNCATED=' + [string]$state.Truncated)
    Write-Output ('LARGE_STOPPED_AT=' + [string]$state.StoppedAt)
    Write-Output ('SKIP_EXT=' + ([int]$state.SkipExt).ToString())
    Write-Output ('TAIL_MATCH=' + [string]$state.Name)
    Write-Output ('HIT_OMITTED=' + ([int]$state.Omitted).ToString())
    Write-Output ('JUDGMENT_TAIL=' + $primary)
    Write-Output ('JUDGMENT_LIMIT=' + $limit)
    Write-Output 'NOTHING_TOUCHED=1'
    Write-Output 'REGISTRY_CHANGED=0'
    Write-Output 'WORKBOOK_CHANGED=0'
    Write-Output 'XLL_CHANGED=0'
    Write-Output 'DIALOG_CLICKED=0'
    Write-Output 'EXCEL_STOP_REQUESTED=0'
}

if ($SelfTest) {
    Invoke-CacheTailSelfTest
    return
}
if (-not [string]::Equals($Confirm, $script:ConfirmToken, $script:Ordinal)) {
    Write-Refused -Reason 'confirm_token_missing'
    throw 'confirm_token_missing'
}
Invoke-LiveTail -FocusPid $LaunchedPid
