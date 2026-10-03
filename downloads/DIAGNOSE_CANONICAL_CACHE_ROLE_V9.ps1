param(
    [switch]$SelfTest,
    [string]$Confirm = '',
    [int]$LaunchedPid = 0
)

# Read-only classification of the local Office files that already named the
# canonical workbook. The previous scan found the name and stopped inside
# exe_Rules and OfficeFileCache. This script asks whether those name hits
# also contain a crash marker. Rules folders are filename-only. It does not
# open the registry, the workbook zip, or the dialog.
# -SelfTest does not read processes or files.

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$script:Ordinal = [StringComparison]::Ordinal
$script:OrdinalIgnore = [StringComparison]::OrdinalIgnoreCase
$script:Leaf = 'Kioxia_MS2_RSS_Live_Signals.xlsx'
$script:PathTail = 'MarketSpeed II RSS\files\Kioxia_MS2_RSS_Live_Signals.xlsx'
$script:XllStem = 'MarketSpeed2_RSS'
$script:ConfirmToken = 'DIAGNOSE_CANONICAL_CACHE_ROLE_READONLY'
$script:CaseCount = 0
$script:GlobalFileCap = 4000
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

function Get-ScanMode {
    param([string]$Name)
    if ([string]::IsNullOrEmpty($Name)) { return 'other_content' }
    if ($Name.EndsWith('_Rules', $script:OrdinalIgnore)) { return 'rules_names' }
    if ($Name.IndexOf('OfficeFileCache', $script:OrdinalIgnore) -ge 0) { return 'cache_content' }
    if ($Name.IndexOf('mru', $script:OrdinalIgnore) -ge 0) { return 'recent_content' }
    if ($Name.IndexOf('Iris', $script:OrdinalIgnore) -ge 0) { return 'recent_content' }
    return 'other_content'
}

function Get-ModeRank {
    param([string]$Mode)
    if ($Mode -eq 'recent_content') { return 0 }
    if ($Mode -eq 'cache_content') { return 1 }
    if ($Mode -eq 'other_content') { return 2 }
    return 3
}

function Get-ModeBudget {
    param([string]$Mode)
    if ($Mode -eq 'rules_names') { return 500 }
    if ($Mode -eq 'cache_content') { return 2000 }
    if ($Mode -eq 'recent_content') { return 200 }
    return 80
}

function Get-DirOrder {
    param([string[]]$Names)
    $buckets = @(
        (New-Object System.Collections.Generic.List[string]),
        (New-Object System.Collections.Generic.List[string]),
        (New-Object System.Collections.Generic.List[string]),
        (New-Object System.Collections.Generic.List[string])
    )
    foreach ($name in $Names) {
        $text = [string]$name
        $rank = Get-ModeRank -Mode (Get-ScanMode -Name $text)
        [void]$buckets[$rank].Add($text)
    }
    $ordered = New-Object System.Collections.Generic.List[string]
    foreach ($bucket in $buckets) {
        foreach ($name in $bucket) { [void]$ordered.Add($name) }
    }
    return $ordered.ToArray()
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
    if ($lower.IndexOf('mru', $script:Ordinal) -ge 0) { return 'recent_name' }
    if ($lower.StartsWith('documents_', $script:Ordinal)) { return 'recent_name' }
    if ($lower.EndsWith('.c4', $script:Ordinal) -or $lower.EndsWith('.fsd', $script:Ordinal)) { return 'cache_blob' }
    return 'name_match'
}

function Get-RoleJudgment {
    param([string[]]$Roles, [string]$Truncated)
    $needle = 0
    $name = 0
    if ($null -ne $Roles) {
        foreach ($role in $Roles) {
            $text = [string]$role
            if ($text -eq 'crash_needle') { $needle = 1 }
            if ($text -eq 'recent_name' -or $text -eq 'cache_blob' -or $text -eq 'name_match') { $name = 1 }
        }
    }
    if ($needle -eq 1) { return 'located_crash_needle' }
    if ($name -eq 1 -and $Truncated -eq '1') { return 'name_only_cache_incomplete' }
    if ($name -eq 1) { return 'name_only_not_crash_marker' }
    if ($Truncated -eq '1') { return 'cache_incomplete' }
    return 'no_cache_name'
}

function Get-RoleLimit {
    param([string]$Truncated, [string]$Unreadable, [string]$OtherNeedle, [string]$XllOnly)
    $flags = New-Object System.Collections.Generic.List[string]
    if ($Truncated -eq '1') { [void]$flags.Add('cache_truncated') }
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

function Invoke-CacheRoleSelfTest {
    Assert-Case 'mode_rules' ((Get-ScanMode -Name 'excel.exe_Rules') -eq 'rules_names')
    Assert-Case 'mode_cache' ((Get-ScanMode -Name 'OfficeFileCache') -eq 'cache_content')
    Assert-Case 'mode_mru' ((Get-ScanMode -Name 'Agmru') -eq 'recent_content')
    Assert-Case 'mode_iris' ((Get-ScanMode -Name 'IrisServiceCache') -eq 'recent_content')
    Assert-Case 'mode_other' ((Get-ScanMode -Name 'WEF') -eq 'other_content')
    $ordered = @(Get-DirOrder -Names @('excel.exe_Rules', 'OfficeFileCache', 'WEF', 'IrisServiceCache'))
    Assert-Case 'order_iris' ([string]$ordered[0] -eq 'IrisServiceCache')
    Assert-Case 'order_cache' ([string]$ordered[1] -eq 'OfficeFileCache')
    Assert-Case 'order_other' ([string]$ordered[2] -eq 'WEF')
    Assert-Case 'order_rules' ([string]$ordered[3] -eq 'excel.exe_Rules')
    Assert-Case 'budget_cache' ((Get-ModeBudget -Mode 'cache_content') -eq 2000)
    Assert-Case 'budget_rules' ((Get-ModeBudget -Mode 'rules_names') -eq 500)
    Assert-Case 'role_recent' ((Get-HitRole -FileName 'mru4-ja-JP-sr.json' -Leaf 1 -Path 1 -Needle 0) -eq 'recent_name')
    Assert-Case 'role_docs' ((Get-HitRole -FileName 'Documents_ja-JP.json' -Leaf 1 -Path 0 -Needle 0) -eq 'recent_name')
    Assert-Case 'role_c4' ((Get-HitRole -FileName '1388790193167766279.C4' -Leaf 1 -Path 1 -Needle 0) -eq 'cache_blob')
    Assert-Case 'role_needle' ((Get-HitRole -FileName '1388790193167766279.C4' -Leaf 1 -Path 0 -Needle 1) -eq 'crash_needle')
    Assert-Case 'role_other_needle' ((Get-HitRole -FileName 'note.txt' -Leaf 0 -Path 0 -Needle 1) -eq 'other_needle')
    Assert-Case 'role_none' ((Get-HitRole -FileName 'note.txt' -Leaf 0 -Path 0 -Needle 0) -eq 'none')
    Assert-Case 'judge_name' ((Get-RoleJudgment -Roles @('recent_name', 'cache_blob') -Truncated '0') -eq 'name_only_not_crash_marker')
    Assert-Case 'judge_incomplete' ((Get-RoleJudgment -Roles @('cache_blob') -Truncated '1') -eq 'name_only_cache_incomplete')
    Assert-Case 'judge_needle' ((Get-RoleJudgment -Roles @('recent_name', 'crash_needle') -Truncated '1') -eq 'located_crash_needle')
    Assert-Case 'judge_empty' ((Get-RoleJudgment -Roles @('none') -Truncated '0') -eq 'no_cache_name')
    Assert-Case 'limit_trunc' ((Get-RoleLimit -Truncated '1' -Unreadable '0' -OtherNeedle '0' -XllOnly '0') -eq 'cache_truncated')
    Assert-Case 'limit_clear' ((Get-RoleLimit -Truncated '0' -Unreadable '0' -OtherNeedle '0' -XllOnly '0') -eq 'none')
    $utfNeedle = [Text.Encoding]::Unicode.GetBytes('<fileRecoveryPr crashSave="1"/>')
    $needleHit = Get-ContentFlags -Text '' -Binary $utfNeedle
    Assert-Case 'byte_needle' ([int]$needleHit.Needle -eq 1)
    $utfLeaf = [Text.Encoding]::Unicode.GetBytes('xx' + $script:Leaf)
    $leafHit = Get-ContentFlags -Text '' -Binary $utfLeaf
    Assert-Case 'byte_leaf' ([int]$leafHit.Leaf -eq 1)
    Assert-Case 'byte_leaf_needle_off' ([int]$leafHit.Needle -eq 0)
    Assert-Case 'safe_c4' ((Get-SafeLeaf -Name '1388790193167766279.C4') -eq '1388790193167766279.C4')
    Assert-Case 'safe_mru' ((Get-SafeLeaf -Name 'mru4-ja-JP-sr.json') -eq 'mru4-ja-JP-sr.json')
    Write-Output 'ACTION=diagnose_canonical_cache_role_readonly'
    Write-Output 'READ_ONLY=1'
    Write-Output 'REGISTRY_REREAD=0'
    Write-Output 'PACKAGE_REREAD=0'
    Write-Output 'DIALOG_QUERIED=0'
    Write-Output 'DISABLED_LIST_REREAD=0'
    Write-Output 'PROOF judgment=name_only_not_crash_marker'
    Write-Output 'PROOF judgment=located_crash_needle'
    Write-Output 'PROOF judgment=name_only_cache_incomplete'
    Write-Output 'PROOF role=recent_name'
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
    Write-Output 'ACTION=diagnose_canonical_cache_role_readonly'
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

function Add-RoleHit {
    param($State, [string]$DirLabel, [string]$FileName, $Flags)
    $role = Get-HitRole -FileName $FileName -Leaf ([int]$Flags.Leaf) -Path ([int]$Flags.Path) -Needle ([int]$Flags.Needle)
    if ($role -eq 'none') {
        if ([int]$Flags.Xll -eq 1) { $State.Xll = '1' }
        return
    }
    if ($role -eq 'other_needle') { $State.OtherNeedle = '1'; return }
    if ([int]$Flags.Xll -eq 1) { $State.Xll = '1' }
    if ($State.Roles.Count -lt 24) { [void]$State.Roles.Add($role) }
    $State.Match = '1'
    if ($State.Hits.Count -ge 12) { return }
    [void]$State.Hits.Add((New-Object psobject -Property @{
        Role = $role
        Dir = $DirLabel
        File = (Get-SafeLeaf -Name $FileName)
        Leaf = [int]$Flags.Leaf
        Path = [int]$Flags.Path
        Needle = [int]$Flags.Needle
    }))
}

function Add-RoleFiles {
    param([string]$Directory, [string]$DirLabel, [string]$Mode, $State, $Bucket, [int]$Depth, [int]$MaxDepth)
    if ($Depth -gt $MaxDepth) { return }
    if ([int]$State.Seen -ge $script:GlobalFileCap -or [int]$Bucket.Seen -ge [int]$Bucket.Budget) {
        $State.Truncated = '1'
        $Bucket.Truncated = '1'
        if ([string]::IsNullOrEmpty([string]$State.StoppedAt)) { $State.StoppedAt = $DirLabel }
        return
    }
    try {
        foreach ($file in [IO.Directory]::EnumerateFiles($Directory)) {
            if ([int]$State.Seen -ge $script:GlobalFileCap -or [int]$Bucket.Seen -ge [int]$Bucket.Budget) {
                $State.Truncated = '1'
                $Bucket.Truncated = '1'
                if ([string]::IsNullOrEmpty([string]$State.StoppedAt)) { $State.StoppedAt = $DirLabel }
                return
            }
            $State.Seen = [int]$State.Seen + 1
            $Bucket.Seen = [int]$Bucket.Seen + 1
            $fileText = [string]$file
            $leafName = Get-PathLeaf -Path $fileText
            $nameFlags = Get-ContentFlags -Text $leafName -Binary $null
            $readContent = $false
            if ($Mode -ne 'rules_names') { $readContent = -not (Test-SkipExtension -Name $leafName) }
            if (([int]$nameFlags.Leaf -eq 1) -or ([int]$nameFlags.Path -eq 1)) { $readContent = $true }
            $binary = $null
            if ($readContent) {
                try { $binary = Read-CappedBytes -Path $fileText -Cap 65536 } catch { $binary = $null }
            }
            $flags = Get-ContentFlags -Text $leafName -Binary $binary
            Add-RoleHit -State $State -DirLabel $DirLabel -FileName $leafName -Flags $flags
        }
        if ($Depth -ge $MaxDepth) { return }
        $names = New-Object System.Collections.Generic.List[string]
        foreach ($dir in [IO.Directory]::EnumerateDirectories($Directory)) {
            [void]$names.Add((Get-PathLeaf -Path ([string]$dir)))
        }
        $ordered = @(Get-DirOrder -Names $names.ToArray())
        foreach ($name in $ordered) {
            $childName = [string]$name
            if ([string]::IsNullOrEmpty($childName)) { continue }
            $childMode = Get-ScanMode -Name $childName
            $childLabel = Get-SafeLeaf -Name $childName
            Add-RoleFiles -Directory ($Directory + '\' + $childName) -DirLabel $childLabel -Mode $childMode -State $State -Bucket $Bucket -Depth ($Depth + 1) -MaxDepth $MaxDepth
        }
    } catch {
        $State.Unreadable = '1'
        $Bucket.Unreadable = '1'
    }
}

function Invoke-LiveRole {
    param([int]$FocusPid)
    $launch = Get-LaunchStamp -ProcId $FocusPid
    Write-Output 'ACTION=diagnose_canonical_cache_role_readonly'
    Write-Output 'READ_ONLY=1'
    Write-Output 'REGISTRY_REREAD=0'
    Write-Output 'PACKAGE_REREAD=0'
    Write-Output 'DIALOG_QUERIED=0'
    Write-Output 'DISABLED_LIST_REREAD=0'
    Write-Output ('LAUNCHED_PID=' + $FocusPid.ToString())
    Write-Output ('LAUNCHED_ALIVE=' + [string]$launch.Alive)
    Write-Output ('LAUNCHED_EXCEL=' + [string]$launch.Excel)
    Write-Output ('LAUNCHED_CANONICAL=' + [string]$launch.Canonical)
    Write-Output ('LAUNCHED_START_UTC=' + [string]$launch.StartUtc)
    $state = New-Object psobject -Property @{
        Seen = 0
        Truncated = '0'
        Unreadable = '0'
        Match = '0'
        Xll = '0'
        OtherNeedle = '0'
        StoppedAt = ''
        Roles = (New-Object System.Collections.Generic.List[string])
        Hits = (New-Object System.Collections.Generic.List[object])
    }
    $rulesSeen = 0
    $localRoot = ''
    try { $localRoot = [string][Environment]::GetFolderPath('LocalApplicationData') } catch { $localRoot = '' }
    $roots = @()
    if ($localRoot.Length -gt 0) {
        $roots = @(
            (New-Object psobject -Property @{ Label = 'office16'; Path = ($localRoot + '\Microsoft\Office\16.0') }),
            (New-Object psobject -Property @{ Label = 'office_excel'; Path = ($localRoot + '\Microsoft\Office\Excel') })
        )
    }
    foreach ($root in $roots) {
        $rootPath = [string]$root.Path
        if (-not [IO.Directory]::Exists($rootPath)) { continue }
        $rootBucket = New-Object psobject -Property @{ Seen = 0; Budget = 80; Truncated = '0'; Unreadable = '0' }
        Add-RoleFiles -Directory $rootPath -DirLabel ([string]$root.Label) -Mode 'other_content' -State $state -Bucket $rootBucket -Depth 0 -MaxDepth 0
        $names = New-Object System.Collections.Generic.List[string]
        try {
            foreach ($dir in [IO.Directory]::EnumerateDirectories($rootPath)) {
                [void]$names.Add((Get-PathLeaf -Path ([string]$dir)))
            }
        } catch {
            $state.Unreadable = '1'
        }
        $ordered = @(Get-DirOrder -Names $names.ToArray())
        foreach ($name in $ordered) {
            $childName = [string]$name
            if ([string]::IsNullOrEmpty($childName)) { continue }
            $mode = Get-ScanMode -Name $childName
            if ($mode -eq 'rules_names') { $rulesSeen = $rulesSeen + 1 }
            $label = Get-SafeLeaf -Name $childName
            $bucket = New-Object psobject -Property @{ Seen = 0; Budget = (Get-ModeBudget -Mode $mode); Truncated = '0'; Unreadable = '0' }
            if ([int]$state.Seen -ge $script:GlobalFileCap) {
                $state.Truncated = '1'
                if ([string]::IsNullOrEmpty([string]$state.StoppedAt)) { $state.StoppedAt = $label }
                continue
            }
            $depth = 3
            if ($mode -eq 'cache_content' -or $mode -eq 'recent_content') { $depth = 4 }
            Add-RoleFiles -Directory ($rootPath + '\' + $childName) -DirLabel $label -Mode $mode -State $state -Bucket $bucket -Depth 0 -MaxDepth $depth
        }
    }
    foreach ($hit in $state.Hits) {
        Write-Output ('HIT role=' + [string]$hit.Role + ' needle=' + ([int]$hit.Needle).ToString() + ' leaf=' + ([int]$hit.Leaf).ToString() + ' path=' + ([int]$hit.Path).ToString() + ' dir=' + [string]$hit.Dir + ' file=' + [string]$hit.File)
    }
    $roleArray = @()
    if ($state.Roles.Count -gt 0) { $roleArray = @($state.Roles.ToArray()) }
    $xllOnly = '0'
    if (([string]$state.Xll -eq '1') -and ([string]$state.Match -ne '1')) { $xllOnly = '1' }
    $primary = Get-RoleJudgment -Roles $roleArray -Truncated ([string]$state.Truncated)
    $limit = Get-RoleLimit -Truncated ([string]$state.Truncated) -Unreadable ([string]$state.Unreadable) -OtherNeedle ([string]$state.OtherNeedle) -XllOnly $xllOnly
    Write-Output ('RULES_DIRS=' + $rulesSeen.ToString())
    Write-Output 'RULES_MODE=filename_only'
    Write-Output ('LOCAL_SEEN=' + ([int]$state.Seen).ToString())
    Write-Output ('LOCAL_TRUNCATED=' + [string]$state.Truncated)
    Write-Output ('LOCAL_MATCH=' + [string]$state.Match)
    Write-Output ('LOCAL_STOPPED_AT=' + [string]$state.StoppedAt)
    Write-Output ('JUDGMENT_ROLE=' + $primary)
    Write-Output ('JUDGMENT_LIMIT=' + $limit)
    Write-Output 'NOTHING_TOUCHED=1'
    Write-Output 'REGISTRY_CHANGED=0'
    Write-Output 'WORKBOOK_CHANGED=0'
    Write-Output 'XLL_CHANGED=0'
    Write-Output 'DIALOG_CLICKED=0'
    Write-Output 'EXCEL_STOP_REQUESTED=0'
}

if ($SelfTest) {
    Invoke-CacheRoleSelfTest
    return
}
if (-not [string]::Equals($Confirm, $script:ConfirmToken, $script:Ordinal)) {
    Write-Refused -Reason 'confirm_token_missing'
    throw 'confirm_token_missing'
}
Invoke-LiveRole -FocusPid $LaunchedPid
