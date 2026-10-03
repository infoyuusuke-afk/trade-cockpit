param(
    [switch]$SelfTest,
    [string]$Confirm = '',
    [int]$LaunchedPid = 0
)

# Read-only continuation of the local Office cache scan. The disabled-item
# lists and the MRU bracket flags are already complete. The previous scan
# stopped at 80 files, so this script gives each Office folder its own
# budget and records the folder where a later cap stops. It does not open
# the registry, the workbook zip, or the dialog.
# -SelfTest does not read processes or files.

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$script:Ordinal = [StringComparison]::Ordinal
$script:OrdinalIgnore = [StringComparison]::OrdinalIgnoreCase
$script:Leaf = 'Kioxia_MS2_RSS_Live_Signals.xlsx'
$script:PathTail = 'MarketSpeed II RSS\files\Kioxia_MS2_RSS_Live_Signals.xlsx'
$script:XllStem = 'MarketSpeed2_RSS'
$script:ConfirmToken = 'DIAGNOSE_CANONICAL_LOCAL_CACHE_READONLY'
$script:CaseCount = 0
$script:GlobalFileCap = 2200
$script:LeafAscii = [Text.Encoding]::ASCII.GetBytes($script:Leaf)
$script:LeafUtf16 = [Text.Encoding]::Unicode.GetBytes($script:Leaf)
$script:TailUtf16 = [Text.Encoding]::Unicode.GetBytes($script:PathTail)
$script:XllAscii = [Text.Encoding]::ASCII.GetBytes($script:XllStem)
$script:XllUtf16 = [Text.Encoding]::Unicode.GetBytes($script:XllStem)

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
    $flags = New-Object psobject -Property @{ Leaf = 0; Path = 0; Xll = 0 }
    if (-not [string]::IsNullOrEmpty($Text)) {
        if ($Text.IndexOf($script:Leaf, $script:OrdinalIgnore) -ge 0) { $flags.Leaf = 1 }
        if ($Text.IndexOf($script:PathTail, $script:OrdinalIgnore) -ge 0) { $flags.Path = 1; $flags.Leaf = 1 }
        if ($Text.IndexOf($script:XllStem, $script:OrdinalIgnore) -ge 0) { $flags.Xll = 1 }
    }
    if ($null -ne $Binary -and $Binary.Length -gt 0) {
        if ((Find-Bytes -Hay $Binary -Needle $script:LeafAscii) -ge 0) { $flags.Leaf = 1 }
        if ((Find-Bytes -Hay $Binary -Needle $script:LeafUtf16) -ge 0) { $flags.Leaf = 1 }
        if ((Find-Bytes -Hay $Binary -Needle $script:TailUtf16) -ge 0) { $flags.Path = 1; $flags.Leaf = 1 }
        if ((Find-Bytes -Hay $Binary -Needle $script:XllAscii) -ge 0) { $flags.Xll = 1 }
        if ((Find-Bytes -Hay $Binary -Needle $script:XllUtf16) -ge 0) { $flags.Xll = 1 }
    }
    return $flags
}

function Get-DirClass {
    param([string]$Name)
    if ([string]::IsNullOrEmpty($Name)) { return 'other' }
    if ($Name.IndexOf('OfficeFileCache', $script:OrdinalIgnore) -ge 0) { return 'cache' }
    if ($Name.IndexOf('FileCache', $script:OrdinalIgnore) -ge 0) { return 'cache' }
    if ($Name.IndexOf('WebServiceCache', $script:OrdinalIgnore) -ge 0) { return 'cache' }
    if ($Name.IndexOf('Resiliency', $script:OrdinalIgnore) -ge 0) { return 'recovery' }
    if ($Name.IndexOf('Recovery', $script:OrdinalIgnore) -ge 0) { return 'recovery' }
    if ($Name.IndexOf('Unsaved', $script:OrdinalIgnore) -ge 0) { return 'recovery' }
    if ($Name.IndexOf('AutoRecover', $script:OrdinalIgnore) -ge 0) { return 'recovery' }
    return 'other'
}

function Get-DirBudget {
    param([string]$Class)
    if ($Class -eq 'recovery') { return 200 }
    if ($Class -eq 'cache') { return 800 }
    return 80
}

function Get-DirDepth {
    param([string]$Class)
    if ($Class -eq 'other') { return 3 }
    return 4
}

function Get-DirOrder {
    param([string[]]$Names)
    $recovery = New-Object System.Collections.Generic.List[string]
    $other = New-Object System.Collections.Generic.List[string]
    $cache = New-Object System.Collections.Generic.List[string]
    foreach ($name in $Names) {
        $text = [string]$name
        $class = Get-DirClass -Name $text
        if ($class -eq 'recovery') { [void]$recovery.Add($text) }
        elseif ($class -eq 'cache') { [void]$cache.Add($text) }
        else { [void]$other.Add($text) }
    }
    foreach ($name in $other) { [void]$recovery.Add($name) }
    foreach ($name in $cache) { [void]$recovery.Add($name) }
    return $recovery.ToArray()
}

function Get-LocalJudgment {
    param([string]$Match, [string]$Truncated, [string]$Unreadable, [string]$Roots)
    if ($Match -eq '1') { return 'local_file_names_workbook' }
    if ($Roots -eq 'absent') { return 'local_cache_absent' }
    if ($Truncated -eq '1' -or $Unreadable -eq '1') { return 'local_cache_incomplete' }
    return 'local_cache_clear'
}

function Get-LocalLimit {
    param([string]$Truncated, [string]$Unreadable, [string]$XllOnly)
    $flags = New-Object System.Collections.Generic.List[string]
    if ($Truncated -eq '1') { [void]$flags.Add('local_truncated') }
    if ($Unreadable -eq '1') { [void]$flags.Add('local_unreadable') }
    if ($XllOnly -eq '1') { [void]$flags.Add('local_names_xll_not_workbook') }
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

function Invoke-LocalCacheSelfTest {
    Assert-Case 'class_cache' ((Get-DirClass -Name 'OfficeFileCache') -eq 'cache')
    Assert-Case 'class_filecache' ((Get-DirClass -Name 'WebServiceCache') -eq 'cache')
    Assert-Case 'class_recovery' ((Get-DirClass -Name 'Resiliency') -eq 'recovery')
    Assert-Case 'class_unsaved' ((Get-DirClass -Name 'UnsavedFiles') -eq 'recovery')
    Assert-Case 'class_other' ((Get-DirClass -Name 'CustomXml') -eq 'other')
    $ordered = @(Get-DirOrder -Names @('OfficeFileCache', 'Resiliency', 'CustomXml', 'UnsavedFiles'))
    Assert-Case 'order_first' ([string]$ordered[0] -eq 'Resiliency')
    Assert-Case 'order_second' ([string]$ordered[1] -eq 'UnsavedFiles')
    Assert-Case 'order_other' ([string]$ordered[2] -eq 'CustomXml')
    Assert-Case 'order_cache' ([string]$ordered[3] -eq 'OfficeFileCache')
    Assert-Case 'budget_recovery' ((Get-DirBudget -Class 'recovery') -eq 200)
    Assert-Case 'budget_other' ((Get-DirBudget -Class 'other') -eq 80)
    Assert-Case 'budget_cache' ((Get-DirBudget -Class 'cache') -eq 800)
    Assert-Case 'depth_other' ((Get-DirDepth -Class 'other') -eq 3)
    Assert-Case 'depth_cache' ((Get-DirDepth -Class 'cache') -eq 4)
    Assert-Case 'judge_clear' ((Get-LocalJudgment -Match '0' -Truncated '0' -Unreadable '0' -Roots 'open') -eq 'local_cache_clear')
    Assert-Case 'judge_match' ((Get-LocalJudgment -Match '1' -Truncated '1' -Unreadable '0' -Roots 'open') -eq 'local_file_names_workbook')
    Assert-Case 'judge_incomplete' ((Get-LocalJudgment -Match '0' -Truncated '1' -Unreadable '0' -Roots 'open') -eq 'local_cache_incomplete')
    Assert-Case 'judge_absent' ((Get-LocalJudgment -Match '0' -Truncated '0' -Unreadable '0' -Roots 'absent') -eq 'local_cache_absent')
    Assert-Case 'limit_clear' ((Get-LocalLimit -Truncated '0' -Unreadable '0' -XllOnly '0') -eq 'none')
    Assert-Case 'limit_trunc' ((Get-LocalLimit -Truncated '1' -Unreadable '0' -XllOnly '0') -eq 'local_truncated')
    Assert-Case 'limit_xll' ((Get-LocalLimit -Truncated '0' -Unreadable '0' -XllOnly '1') -eq 'local_names_xll_not_workbook')
    $utfLeaf = [Text.Encoding]::Unicode.GetBytes('xx' + $script:Leaf)
    $byteHit = Get-ContentFlags -Text '' -Binary $utfLeaf
    Assert-Case 'byte_leaf' ([int]$byteHit.Leaf -eq 1)
    Assert-Case 'byte_path_off' ([int]$byteHit.Path -eq 0)
    $xllHit = Get-ContentFlags -Text $script:XllStem -Binary $null
    Assert-Case 'text_xll' ([int]$xllHit.Xll -eq 1)
    Assert-Case 'text_xll_leaf_off' ([int]$xllHit.Leaf -eq 0)
    Assert-Case 'skip_png' (Test-SkipExtension -Name 'tile.png')
    Assert-Case 'keep_bin' (-not (Test-SkipExtension -Name 'cache.bin'))
    Assert-Case 'leaf_name' ((Get-PathLeaf -Path ('C:\a\b\' + $script:Leaf)) -eq $script:Leaf)
    Assert-Case 'safe_cache' ((Get-SafeLeaf -Name 'OfficeFileCache') -eq 'OfficeFileCache')
    Assert-Case 'safe_redact' ((Get-SafeLeaf -Name 'Item 10') -eq 'len_7')
    Write-Output 'ACTION=diagnose_canonical_local_cache_readonly'
    Write-Output 'READ_ONLY=1'
    Write-Output 'REGISTRY_REREAD=0'
    Write-Output 'PACKAGE_REREAD=0'
    Write-Output 'DIALOG_QUERIED=0'
    Write-Output 'DISABLED_LIST_REREAD=0'
    Write-Output 'PROOF judgment=local_cache_clear'
    Write-Output 'PROOF judgment=local_file_names_workbook'
    Write-Output 'PROOF judgment=local_cache_incomplete'
    Write-Output 'PROOF order=recovery_before_cache'
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
    Write-Output 'ACTION=diagnose_canonical_local_cache_readonly'
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

function New-Bucket {
    param([string]$Label, [string]$Class, [int]$Budget)
    return (New-Object psobject -Property @{
        Label = $Label
        Class = $Class
        Budget = $Budget
        Seen = 0
        Match = 0
        Truncated = '0'
        Unreadable = '0'
    })
}

function Test-BucketFull {
    param($State, $Bucket)
    if ([int]$State.Seen -ge $script:GlobalFileCap) { return $true }
    if ([int]$Bucket.Seen -ge [int]$Bucket.Budget) { return $true }
    return $false
}

function Set-BucketStop {
    param($State, $Bucket)
    $State.Truncated = '1'
    $Bucket.Truncated = '1'
    if ([string]::IsNullOrEmpty([string]$State.StoppedAt)) { $State.StoppedAt = [string]$Bucket.Label }
}

function Add-FileHit {
    param([string]$FilePath, $State, $Bucket)
    $leafName = Get-PathLeaf -Path $FilePath
    $nameFlags = Get-ContentFlags -Text $leafName -Binary $null
    $binary = $null
    $skip = Test-SkipExtension -Name $leafName
    if (([int]$nameFlags.Leaf -ne 1) -and ([int]$nameFlags.Path -ne 1) -and (-not $skip)) {
        try { $binary = Read-CappedBytes -Path $FilePath -Cap 65536 } catch { $binary = $null }
    }
    $flags = Get-ContentFlags -Text $leafName -Binary $binary
    if ([int]$flags.Xll -eq 1) { $State.Xll = '1' }
    if ([int]$flags.Leaf -eq 1 -or [int]$flags.Path -eq 1) {
        $State.Match = '1'
        $Bucket.Match = [int]$Bucket.Match + 1
        if ($State.Hits.Count -lt 8) { [void]$State.Hits.Add((Get-SafeLeaf -Name $leafName)) }
    }
}

function Add-DirFiles {
    param([string]$Directory, $State, $Bucket, [int]$Depth, [int]$MaxDepth)
    if ($Depth -gt $MaxDepth) { return }
    if (Test-BucketFull -State $State -Bucket $Bucket) {
        Set-BucketStop -State $State -Bucket $Bucket
        return
    }
    try {
        foreach ($file in [IO.Directory]::EnumerateFiles($Directory)) {
            if (Test-BucketFull -State $State -Bucket $Bucket) {
                Set-BucketStop -State $State -Bucket $Bucket
                return
            }
            $State.Seen = [int]$State.Seen + 1
            $Bucket.Seen = [int]$Bucket.Seen + 1
            Add-FileHit -FilePath ([string]$file) -State $State -Bucket $Bucket
        }
        if ($Depth -ge $MaxDepth) { return }
        $names = New-Object System.Collections.Generic.List[string]
        foreach ($dir in [IO.Directory]::EnumerateDirectories($Directory)) {
            [void]$names.Add((Get-PathLeaf -Path ([string]$dir)))
        }
        $ordered = @(Get-DirOrder -Names $names.ToArray())
        foreach ($name in $ordered) {
            if (Test-BucketFull -State $State -Bucket $Bucket) {
                Set-BucketStop -State $State -Bucket $Bucket
                return
            }
            $childName = [string]$name
            if ([string]::IsNullOrEmpty($childName)) { continue }
            Add-DirFiles -Directory ($Directory + '\' + $childName) -State $State -Bucket $Bucket -Depth ($Depth + 1) -MaxDepth $MaxDepth
        }
    } catch {
        $State.Unreadable = '1'
        $Bucket.Unreadable = '1'
    }
}

function Get-ChildNames {
    param([string]$Directory)
    $names = New-Object System.Collections.Generic.List[string]
    foreach ($dir in [IO.Directory]::EnumerateDirectories($Directory)) {
        [void]$names.Add((Get-PathLeaf -Path ([string]$dir)))
    }
    return $names.ToArray()
}

function Invoke-LiveCache {
    param([int]$FocusPid)
    $launch = Get-LaunchStamp -ProcId $FocusPid
    Write-Output 'ACTION=diagnose_canonical_local_cache_readonly'
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
        NotScanned = 0
        StoppedAt = ''
        Hits = (New-Object System.Collections.Generic.List[string])
    }
    $buckets = New-Object System.Collections.Generic.List[object]
    $rootsOpen = 0
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
        $rootLabel = [string]$root.Label
        if (-not [IO.Directory]::Exists($rootPath)) { continue }
        $rootsOpen = $rootsOpen + 1
        $rootBucket = New-Bucket -Label $rootLabel -Class 'other' -Budget 40
        [void]$buckets.Add($rootBucket)
        Add-DirFiles -Directory $rootPath -State $state -Bucket $rootBucket -Depth 0 -MaxDepth 0
        $childNames = @()
        try { $childNames = @(Get-ChildNames -Directory $rootPath) } catch { $childNames = @(); $state.Unreadable = '1' }
        $ordered = @(Get-DirOrder -Names $childNames)
        foreach ($child in $ordered) {
            $childName = [string]$child
            if ([string]::IsNullOrEmpty($childName)) { continue }
            $class = Get-DirClass -Name $childName
            $label = Get-SafeLeaf -Name $childName
            $bucket = New-Bucket -Label $label -Class $class -Budget (Get-DirBudget -Class $class)
            [void]$buckets.Add($bucket)
            if ([int]$state.Seen -ge $script:GlobalFileCap) {
                $state.Truncated = '1'
                $bucket.Truncated = '1'
                $state.NotScanned = [int]$state.NotScanned + 1
                continue
            }
            Add-DirFiles -Directory ($rootPath + '\' + $childName) -State $state -Bucket $bucket -Depth 0 -MaxDepth (Get-DirDepth -Class $class)
        }
    }
    $rootState = 'absent'
    if ($rootsOpen -gt 0) { $rootState = 'open' }
    $printed = 0
    foreach ($bucket in $buckets) {
        if ($printed -ge 30) { continue }
        $printed = $printed + 1
        Write-Output ('DIR name=' + [string]$bucket.Label + ' class=' + [string]$bucket.Class + ' seen=' + ([int]$bucket.Seen).ToString() + ' match=' + ([int]$bucket.Match).ToString() + ' truncated=' + [string]$bucket.Truncated)
    }
    $xllOnly = '0'
    if (([string]$state.Xll -eq '1') -and ([string]$state.Match -ne '1')) { $xllOnly = '1' }
    $primary = Get-LocalJudgment -Match ([string]$state.Match) -Truncated ([string]$state.Truncated) -Unreadable ([string]$state.Unreadable) -Roots $rootState
    $limit = Get-LocalLimit -Truncated ([string]$state.Truncated) -Unreadable ([string]$state.Unreadable) -XllOnly $xllOnly
    Write-Output ('DIR_COUNT=' + $buckets.Count.ToString())
    Write-Output ('DIR_PRINTED=' + $printed.ToString())
    Write-Output ('LOCAL_SEEN=' + ([int]$state.Seen).ToString())
    Write-Output ('LOCAL_TRUNCATED=' + [string]$state.Truncated)
    Write-Output ('LOCAL_MATCH=' + [string]$state.Match)
    Write-Output ('LOCAL_XLL=' + [string]$state.Xll)
    Write-Output ('LOCAL_NOT_SCANNED=' + ([int]$state.NotScanned).ToString())
    Write-Output ('LOCAL_STOPPED_AT=' + [string]$state.StoppedAt)
    foreach ($hit in $state.Hits) {
        Write-Output ('LOCAL_HIT name=' + [string]$hit)
    }
    Write-Output ('JUDGMENT_LOCAL=' + $primary)
    Write-Output ('JUDGMENT_LIMIT=' + $limit)
    Write-Output 'NOTHING_TOUCHED=1'
    Write-Output 'REGISTRY_CHANGED=0'
    Write-Output 'WORKBOOK_CHANGED=0'
    Write-Output 'XLL_CHANGED=0'
    Write-Output 'DIALOG_CLICKED=0'
    Write-Output 'EXCEL_STOP_REQUESTED=0'
}

if ($SelfTest) {
    Invoke-LocalCacheSelfTest
    return
}
if (-not [string]::Equals($Confirm, $script:ConfirmToken, $script:Ordinal)) {
    Write-Refused -Reason 'confirm_token_missing'
    throw 'confirm_token_missing'
}
Invoke-LiveCache -FocusPid $LaunchedPid
