param(
    [switch]$SelfTest,
    [string]$Confirm = '',
    [int]$LaunchedPid = 0
)

# Read-only check for disabled-item lists outside the completed Excel store
# walk. That walk finished and its only hit was a recent-file MRU record.
# This script reads resiliency lists, policy and machine copies, the MRU
# bracket flags, and the local Office 16 file cache. It does not open the
# workbook zip, query the dialog, or write anything.
# -SelfTest does not read HKCU, processes, or files.

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$script:Ordinal = [StringComparison]::Ordinal
$script:OrdinalIgnore = [StringComparison]::OrdinalIgnoreCase
$script:Leaf = 'Kioxia_MS2_RSS_Live_Signals.xlsx'
$script:PathTail = 'MarketSpeed II RSS\files\Kioxia_MS2_RSS_Live_Signals.xlsx'
$script:XllStem = 'MarketSpeed2_RSS'
$script:ConfirmToken = 'DIAGNOSE_CANONICAL_DISABLED_SCOPE_READONLY'
$script:CaseCount = 0
$script:LeafAscii = [Text.Encoding]::ASCII.GetBytes($script:Leaf)
$script:LeafUtf16 = [Text.Encoding]::Unicode.GetBytes($script:Leaf)
$script:TailUtf16 = [Text.Encoding]::Unicode.GetBytes($script:PathTail)
$script:XllAscii = [Text.Encoding]::ASCII.GetBytes($script:XllStem)
$script:XllUtf16 = [Text.Encoding]::Unicode.GetBytes($script:XllStem)

function Get-CanonicalFullPath {
    $day = -join @(
        [char]0x30C7,
        [char]0x30A4,
        [char]0x30C8,
        [char]0x30EC
    )
    return ('C:\Users\yusuk\Desktop\' + $day + '\MarketSpeed II RSS\files\' + $script:Leaf)
}

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

function Test-Hex8 {
    param([string]$Text)
    if ([string]::IsNullOrEmpty($Text) -or $Text.Length -ne 8) { return $false }
    foreach ($ch in $Text.ToCharArray()) {
        $code = [int]$ch
        $digit = (($code -ge 48) -and ($code -le 57))
        $lower = (($code -ge 97) -and ($code -le 102))
        $upper = (($code -ge 65) -and ($code -le 70))
        if (-not ($digit -or $lower -or $upper)) { return $false }
    }
    return $true
}

function Get-BracketHex {
    param([string]$Text, [string]$Mark)
    if ([string]::IsNullOrEmpty($Text)) { return '' }
    $token = '[' + $Mark
    $at = $Text.IndexOf($token, $script:Ordinal)
    if ($at -lt 0) { return '' }
    $start = $at + $token.Length
    if (($start + 9) -gt $Text.Length) { return '' }
    $hex = $Text.Substring($start, 8)
    if (-not (Test-Hex8 -Text $hex)) { return '' }
    if ($Text.Substring($start + 8, 1) -ne ']') { return '' }
    return $hex.ToLowerInvariant()
}

function Get-MruRecord {
    param([string]$Text)
    $rec = New-Object psobject -Property @{
        Form = 'unparsed'
        F = ''
        O = ''
        T = '0'
        Star = '0'
        Leaf = 0
        Path = 0
    }
    if ([string]::IsNullOrEmpty($Text)) { return $rec }
    $flags = Get-ContentFlags -Text $Text -Binary $null
    $rec.Leaf = [int]$flags.Leaf
    $rec.Path = [int]$flags.Path
    if ($Text.IndexOf('[T', $script:Ordinal) -ge 0) { $rec.T = '1' }
    if ($Text.IndexOf(']*', $script:Ordinal) -ge 0) { $rec.Star = '1' }
    $f = Get-BracketHex -Text $Text -Mark 'F'
    $o = Get-BracketHex -Text $Text -Mark 'O'
    if ($Text.StartsWith('[F', $script:Ordinal) -and ($f.Length -eq 8) -and ($o.Length -eq 8) -and ($rec.Star -eq '1')) {
        $rec.Form = 'bracket'
        $rec.F = $f
        $rec.O = $o
    }
    return $rec
}

function Get-MruFlagClass {
    param([string]$Form, [string]$F, [string]$O)
    if ($Form -ne 'bracket') { return 'unparsed' }
    if ($F.Equals('00000000', $script:Ordinal) -and $O.Equals('00000000', $script:Ordinal)) { return 'flags_clear' }
    return 'flags_set'
}

function Get-ResiliencyArea {
    param([string]$Name)
    if ([string]::IsNullOrEmpty($Name)) { return 'other' }
    if ($Name.Equals('DisabledItems', $script:OrdinalIgnore)) { return 'disabled_items' }
    if ($Name.Equals('DocumentRecovery', $script:OrdinalIgnore)) { return 'document_recovery' }
    if ($Name.Equals('StartupItems', $script:OrdinalIgnore)) { return 'startup_items' }
    if ($Name.Equals('CrashingAddinList', $script:OrdinalIgnore)) { return 'crashing_list' }
    return 'other'
}

function Get-DisabledJudgment {
    param($Rows, [string]$LocalMatch)
    $disabled = 0
    $other = 0
    $xll = 0
    if ($null -ne $Rows) {
        foreach ($row in $Rows) {
            if ($null -eq $row) { continue }
            $leaf = [int]$row.MatchLeaf
            $path = [int]$row.MatchPath
            $hasXll = [int]$row.MatchXll
            if ($hasXll -eq 1) { $xll = 1 }
            if ($leaf -ne 1 -and $path -ne 1) { continue }
            $area = [string]$row.Area
            if ($area.Equals('disabled_items', $script:Ordinal) -or $area.Equals('document_recovery', $script:Ordinal)) { $disabled = 1 }
            else { $other = 1 }
        }
    }
    if ($disabled -eq 1) { return 'located_disabled_list' }
    if ($other -eq 1) { return 'located_other_list' }
    if ($LocalMatch -eq '1') { return 'local_file_names_workbook' }
    if ($xll -eq 1) { return 'xll_list_not_workbook' }
    return 'not_in_disabled_lists'
}

function Get-DisabledLimit {
    param([string]$Primary, [string]$MruClass, [string]$ScopeTruncated, [string]$ScopeUnreadable, [string]$LocalTruncated, [string]$LocalUnreadable, [string]$ValuePartial)
    $flags = New-Object System.Collections.Generic.List[string]
    if ($MruClass -eq 'flags_clear') { [void]$flags.Add('mru_flags_clear') }
    elseif ($MruClass -eq 'flags_set') { [void]$flags.Add('mru_flags_set') }
    elseif ($MruClass -eq 'unparsed') { [void]$flags.Add('mru_unparsed') }
    elseif ($MruClass -eq 'none') { [void]$flags.Add('mru_not_seen') }
    if ($ScopeTruncated -eq '1') { [void]$flags.Add('scope_truncated') }
    if ($ScopeUnreadable -eq '1') { [void]$flags.Add('scope_unreadable') }
    if ($LocalTruncated -eq '1') { [void]$flags.Add('local_truncated') }
    if ($LocalUnreadable -eq '1') { [void]$flags.Add('local_unreadable') }
    if ($ValuePartial -eq '1') { [void]$flags.Add('value_partial') }
    if ($Primary -eq 'xll_list_not_workbook') { [void]$flags.Add('xll_is_not_workbook_dialog') }
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

function Assert-Case {
    param([string]$Name, [bool]$Ok)
    $script:CaseCount = $script:CaseCount + 1
    if (-not $Ok) { throw ('selftest_failed:' + $Name) }
}

function Invoke-DisabledSelfTest {
    $clearText = '[F00000000][T01D0A1B2C3D4E5F6][O00000000]*C:\x\' + $script:PathTail
    $clear = Get-MruRecord -Text $clearText
    Assert-Case 'mru_form' ($clear.Form -eq 'bracket')
    Assert-Case 'mru_f0' ($clear.F -eq '00000000')
    Assert-Case 'mru_o0' ($clear.O -eq '00000000')
    Assert-Case 'mru_t' ($clear.T -eq '1')
    Assert-Case 'mru_leaf' ([int]$clear.Leaf -eq 1)
    Assert-Case 'mru_path' ([int]$clear.Path -eq 1)
    Assert-Case 'mru_clear' ((Get-MruFlagClass -Form $clear.Form -F $clear.F -O $clear.O) -eq 'flags_clear')
    $setText = '[F00000001][T01D0A1B2C3D4E5F6][O00000000]*C:\x\' + $script:Leaf
    $set = Get-MruRecord -Text $setText
    Assert-Case 'mru_set' ((Get-MruFlagClass -Form $set.Form -F $set.F -O $set.O) -eq 'flags_set')
    $bad = Get-MruRecord -Text ('C:\x\' + $script:Leaf)
    Assert-Case 'mru_bad' ($bad.Form -eq 'unparsed')
    Assert-Case 'mru_bad_class' ((Get-MruFlagClass -Form $bad.Form -F $bad.F -O $bad.O) -eq 'unparsed')
    Assert-Case 'hex_ok' (Test-Hex8 -Text '0000000A')
    Assert-Case 'hex_no' (-not (Test-Hex8 -Text '0000000G'))
    Assert-Case 'area_disabled' ((Get-ResiliencyArea -Name 'DisabledItems') -eq 'disabled_items')
    Assert-Case 'area_doc' ((Get-ResiliencyArea -Name 'DocumentRecovery') -eq 'document_recovery')
    Assert-Case 'area_other' ((Get-ResiliencyArea -Name '1664DDA6') -eq 'other')
    $disabledRow = New-Object psobject -Property @{ Area = 'disabled_items'; MatchLeaf = 1; MatchPath = 1; MatchXll = 0 }
    $noneRow = New-Object psobject -Property @{ Area = 'disabled_items'; MatchLeaf = 0; MatchPath = 0; MatchXll = 0 }
    $otherRow = New-Object psobject -Property @{ Area = 'startup_items'; MatchLeaf = 1; MatchPath = 0; MatchXll = 0 }
    $xllRow = New-Object psobject -Property @{ Area = 'crashing_list'; MatchLeaf = 0; MatchPath = 0; MatchXll = 1 }
    Assert-Case 'judge_disabled' ((Get-DisabledJudgment -Rows @($disabledRow) -LocalMatch '0') -eq 'located_disabled_list')
    Assert-Case 'judge_other' ((Get-DisabledJudgment -Rows @($otherRow) -LocalMatch '0') -eq 'located_other_list')
    Assert-Case 'judge_local' ((Get-DisabledJudgment -Rows @($noneRow) -LocalMatch '1') -eq 'local_file_names_workbook')
    Assert-Case 'judge_xll' ((Get-DisabledJudgment -Rows @($xllRow) -LocalMatch '0') -eq 'xll_list_not_workbook')
    Assert-Case 'judge_clear' ((Get-DisabledJudgment -Rows @($noneRow) -LocalMatch '0') -eq 'not_in_disabled_lists')
    $limitClear = Get-DisabledLimit -Primary 'not_in_disabled_lists' -MruClass 'flags_clear' -ScopeTruncated '0' -ScopeUnreadable '0' -LocalTruncated '0' -LocalUnreadable '0' -ValuePartial '0'
    Assert-Case 'limit_mru' ($limitClear -eq 'mru_flags_clear')
    $limitTrunc = Get-DisabledLimit -Primary 'not_in_disabled_lists' -MruClass 'flags_clear' -ScopeTruncated '1' -ScopeUnreadable '0' -LocalTruncated '0' -LocalUnreadable '0' -ValuePartial '0'
    Assert-Case 'limit_trunc' ($limitTrunc -eq 'mru_flags_clear,scope_truncated')
    $utfLeaf = [Text.Encoding]::Unicode.GetBytes('xx' + $script:Leaf)
    $byteHit = Get-ContentFlags -Text '' -Binary $utfLeaf
    Assert-Case 'byte_leaf' ([int]$byteHit.Leaf -eq 1)
    Assert-Case 'byte_path_off' ([int]$byteHit.Path -eq 0)
    $xllHit = Get-ContentFlags -Text $script:XllStem -Binary $null
    Assert-Case 'text_xll' ([int]$xllHit.Xll -eq 1)
    Assert-Case 'text_xll_leaf_off' ([int]$xllHit.Leaf -eq 0)
    Assert-Case 'leaf_name' ((Get-PathLeaf -Path ('C:\a\b\' + $script:Leaf)) -eq $script:Leaf)
    Assert-Case 'safe_leaf' ((Get-SafeLeaf -Name 'Excel16.xlb') -eq 'Excel16.xlb')
    Assert-Case 'safe_redact' ((Get-SafeLeaf -Name 'Item 10') -eq 'len_7')
    $areaMap = @{}
    $disabledFlags = New-Object psobject -Property @{ Leaf = 1; Path = 1; Xll = 0 }
    Add-AreaMatch -Areas $areaMap -Area 'disabled_items' -Flags $disabledFlags -ValueCount 1
    $built = @(New-ScopeRows -ScopeId 'hkcu16' -StateName 'open' -Areas $areaMap)
    Assert-Case 'scope_rows' (@($built).Count -eq 1)
    Assert-Case 'scope_leaf' ([int]$built[0].MatchLeaf -eq 1)
    Assert-Case 'scope_values' ([int]$built[0].Values -eq 1)
    $mruItem = New-Object psobject -Property @{ Form = 'bracket'; F = '00000000'; O = '00000000'; Head = 'User_MRU'; ValueLen = 7; Class = 'flags_clear' }
    $mruSum = Get-MruSummary -Found @($mruItem)
    Assert-Case 'mru_sum_class' ([string]$mruSum.Class -eq 'flags_clear')
    Assert-Case 'mru_sum_len' ([string]$mruSum.ValueLen -eq '7')
    Assert-Case 'mru_sum_head' ([string]$mruSum.Head -eq 'User_MRU')
    Write-Output 'ACTION=diagnose_canonical_disabled_scope_readonly'
    Write-Output 'READ_ONLY=1'
    Write-Output 'PACKAGE_REREAD=0'
    Write-Output 'DIALOG_QUERIED=0'
    Write-Output 'STORE_WALK_REPEATED=0'
    Write-Output 'PROOF judgment=not_in_disabled_lists'
    Write-Output 'PROOF judgment=located_disabled_list'
    Write-Output 'PROOF mru=flags_clear'
    Write-Output 'PROOF mru=flags_set'
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
    Write-Output 'ACTION=diagnose_canonical_disabled_scope_readonly'
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

function New-AreaCount {
    return (New-Object psobject -Property @{
        Values = 0
        MatchLeaf = 0
        MatchPath = 0
        MatchXll = 0
        Seen = 0
    })
}

function Add-AreaMatch {
    param($Areas, [string]$Area, $Flags, [int]$ValueCount)
    if (-not $Areas.Contains($Area)) { $Areas[$Area] = New-AreaCount }
    $count = $Areas[$Area]
    $count.Seen = 1
    $count.Values = [int]$count.Values + $ValueCount
    if ($null -eq $Flags) { return }
    if ([int]$Flags.Leaf -eq 1) { $count.MatchLeaf = [int]$count.MatchLeaf + 1 }
    if ([int]$Flags.Path -eq 1) { $count.MatchPath = [int]$count.MatchPath + 1 }
    if ([int]$Flags.Xll -eq 1) { $count.MatchXll = [int]$count.MatchXll + 1 }
}

function Add-KeyValues {
    param($Opened, [string]$Area, $Areas, $State)
    if ($null -eq $Opened) { return }
    $names = @()
    try {
        $rawNames = $Opened.GetValueNames()
        if ($null -ne $rawNames) { $names = @($rawNames) }
    } catch {
        $State.Unreadable = '1'
        return
    }
    if (-not $Areas.Contains($Area)) { Add-AreaMatch -Areas $Areas -Area $Area -Flags $null -ValueCount 0 }
    foreach ($name in $names) {
        if ([int]$State.Values -ge 200) { $State.Truncated = '1'; return }
        $State.Values = [int]$State.Values + 1
        $valueName = [string]$name
        if ($valueName.IndexOf('Password', $script:OrdinalIgnore) -ge 0) {
            Add-AreaMatch -Areas $Areas -Area $Area -Flags $null -ValueCount 1
            continue
        }
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
            Add-AreaMatch -Areas $Areas -Area $Area -Flags $null -ValueCount 1
            continue
        }
        $flags = Get-ContentFlags -Text ($valueName + ' ' + $text) -Binary $binary
        Add-AreaMatch -Areas $Areas -Area $Area -Flags $flags -ValueCount 1
    }
}

function Add-ScopeTree {
    param($Opened, [string]$Area, $Areas, $State, [int]$Depth)
    if ($null -eq $Opened) { return }
    if ($Depth -gt 3) { $State.Truncated = '1'; return }
    Add-KeyValues -Opened $Opened -Area $Area -Areas $Areas -State $State
    if ([int]$State.Values -ge 200) { $State.Truncated = '1'; return }
    if ($Depth -ge 3) { return }
    $children = @()
    try {
        $rawChildren = $Opened.GetSubKeyNames()
        if ($null -ne $rawChildren) { $children = @($rawChildren) }
    } catch {
        $State.Unreadable = '1'
        return
    }
    foreach ($child in $children) {
        if ([int]$State.Keys -ge 40) { $State.Truncated = '1'; return }
        $State.Keys = [int]$State.Keys + 1
        $childName = [string]$child
        $nextArea = $Area
        if ($Depth -eq 0) { $nextArea = Get-ResiliencyArea -Name $childName }
        $sub = $null
        try { $sub = $Opened.OpenSubKey($childName, $false) } catch { $sub = $null; $State.Unreadable = '1' }
        if ($null -eq $sub) { continue }
        try {
            Add-ScopeTree -Opened $sub -Area $nextArea -Areas $Areas -State $State -Depth ($Depth + 1)
        } finally {
            $sub.Dispose()
        }
    }
}

function Open-ReadKey {
    param($Hive, [string]$Path)
    $info = New-Object psobject -Property @{ Key = $null; State = 'absent' }
    if ($null -eq $Hive) { $info.State = 'unreadable'; return $info }
    try {
        $key = $Hive.OpenSubKey($Path, $false)
        if ($null -eq $key) { $info.State = 'absent' }
        else { $info.Key = $key; $info.State = 'open' }
    } catch {
        $info.State = 'unreadable'
    }
    return $info
}

function New-ScopeRows {
    param([string]$ScopeId, [string]$StateName, $Areas)
    $rows = New-Object System.Collections.Generic.List[object]
    if ($StateName -ne 'open') {
        [void]$rows.Add((New-Object psobject -Property @{
            Scope = $ScopeId
            State = $StateName
            Area = 'none'
            Values = 0
            MatchLeaf = 0
            MatchPath = 0
            MatchXll = 0
        }))
        return $rows
    }
    $order = @('root', 'disabled_items', 'document_recovery', 'startup_items', 'crashing_list', 'other')
    foreach ($area in $order) {
        if (-not $Areas.Contains($area)) { continue }
        $count = $Areas[$area]
        [void]$rows.Add((New-Object psobject -Property @{
            Scope = $ScopeId
            State = 'open'
            Area = $area
            Values = [int]$count.Values
            MatchLeaf = [int]$count.MatchLeaf
            MatchPath = [int]$count.MatchPath
            MatchXll = [int]$count.MatchXll
        }))
    }
    if ($rows.Count -eq 0) {
        [void]$rows.Add((New-Object psobject -Property @{
            Scope = $ScopeId
            State = 'open'
            Area = 'root'
            Values = 0
            MatchLeaf = 0
            MatchPath = 0
            MatchXll = 0
        }))
    }
    return $rows
}

function Read-ResiliencyScope {
    param($Hive, [string]$Path, [string]$ScopeId, $Rows, $Cap)
    $opened = Open-ReadKey -Hive $Hive -Path $Path
    if ([string]$opened.State -ne 'open') {
        $empty = New-ScopeRows -ScopeId $ScopeId -StateName ([string]$opened.State) -Areas @{}
        foreach ($row in $empty) { [void]$Rows.Add($row) }
        if ([string]$opened.State -eq 'unreadable') { $Cap.Unreadable = '1' }
        return
    }
    $areas = @{}
    $state = New-Object psobject -Property @{ Values = 0; Keys = 0; Truncated = '0'; Partial = '0'; Unreadable = '0' }
    try {
        Add-ScopeTree -Opened $opened.Key -Area 'root' -Areas $areas -State $state -Depth 0
    } finally {
        if ($null -ne $opened.Key) { $opened.Key.Dispose() }
    }
    if ($state.Truncated -eq '1') { $Cap.Truncated = '1' }
    if ($state.Partial -eq '1') { $Cap.Partial = '1' }
    if ($state.Unreadable -eq '1') { $Cap.Unreadable = '1' }
    $built = New-ScopeRows -ScopeId $ScopeId -StateName 'open' -Areas $areas
    foreach ($row in $built) { [void]$Rows.Add($row) }
    Write-Output ('SCOPE_CAP id=' + $ScopeId + ' truncated=' + [string]$state.Truncated + ' partial=' + [string]$state.Partial + ' unreadable=' + [string]$state.Unreadable)
}

function Add-MruValue {
    param([string]$Text, [string]$Head, [string]$ValueName, $Found)
    if ([string]::IsNullOrEmpty($Text)) { return }
    $rec = Get-MruRecord -Text $Text
    if ([int]$rec.Leaf -ne 1 -and [int]$rec.Path -ne 1) { return }
    if ($Found.Count -ge 8) { return }
    [void]$Found.Add((New-Object psobject -Property @{
        Form = [string]$rec.Form
        F = [string]$rec.F
        O = [string]$rec.O
        Head = $Head
        ValueLen = $ValueName.Length
        Class = (Get-MruFlagClass -Form ([string]$rec.Form) -F ([string]$rec.F) -O ([string]$rec.O))
    }))
}

function Read-MruKey {
    param($Opened, [string]$Head, $Found, $Cap)
    if ($null -eq $Opened) { return }
    $names = @()
    try {
        $rawNames = $Opened.GetValueNames()
        if ($null -ne $rawNames) { $names = @($rawNames) }
    } catch {
        $Cap.Unreadable = '1'
        return
    }
    foreach ($name in $names) {
        if ([int]$Cap.Examined -ge 120) { $Cap.Truncated = '1'; return }
        $Cap.Examined = [int]$Cap.Examined + 1
        $valueName = [string]$name
        if ($valueName.IndexOf('Password', $script:OrdinalIgnore) -ge 0) { continue }
        $kindName = ''
        try { $kindName = [string]$Opened.GetValueKind($valueName) } catch { continue }
        if (($kindName -ne 'String') -and ($kindName -ne 'ExpandString')) { continue }
        $text = ''
        try { $text = [string]$Opened.GetValue($valueName, '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames) } catch { $text = '' }
        Add-MruValue -Text $text -Head $Head -ValueName $valueName -Found $Found
    }
}

function Read-UserMru {
    param($ExcelKey, $Found, $Cap)
    $user = $null
    try { $user = $ExcelKey.OpenSubKey('User MRU', $false) } catch { $user = $null; $Cap.Unreadable = '1' }
    if ($null -eq $user) { return }
    try {
        $children = @()
        try {
            $rawChildren = $user.GetSubKeyNames()
            if ($null -ne $rawChildren) { $children = @($rawChildren) }
        } catch {
            $Cap.Unreadable = '1'
            return
        }
        foreach ($child in $children) {
            if ([int]$Cap.Examined -ge 120) { $Cap.Truncated = '1'; return }
            $sub = $null
            try { $sub = $user.OpenSubKey([string]$child, $false) } catch { $sub = $null }
            if ($null -eq $sub) { continue }
            $fileMru = $null
            try { $fileMru = $sub.OpenSubKey('File MRU', $false) } catch { $fileMru = $null }
            try {
                if ($null -ne $fileMru) { Read-MruKey -Opened $fileMru -Head 'User_MRU' -Found $Found -Cap $Cap }
            } finally {
                if ($null -ne $fileMru) { $fileMru.Dispose() }
                $sub.Dispose()
            }
        }
    } finally {
        $user.Dispose()
    }
}

function Read-MruFlags {
    $cap = New-Object psobject -Property @{ Examined = 0; Truncated = '0'; Unreadable = '0' }
    $found = New-Object System.Collections.Generic.List[object]
    $excel = Open-ReadKey -Hive ([Microsoft.Win32.Registry]::CurrentUser) -Path 'Software\Microsoft\Office\16.0\Excel'
    if ([string]$excel.State -ne 'open') {
        if ([string]$excel.State -eq 'unreadable') { $cap.Unreadable = '1' }
        return (New-Object psobject -Property @{ Cap = $cap; Found = $found })
    }
    try {
        $fileMru = $null
        $place = $null
        try { $fileMru = $excel.Key.OpenSubKey('File MRU', $false) } catch { $fileMru = $null }
        try { $place = $excel.Key.OpenSubKey('Place MRU', $false) } catch { $place = $null }
        try {
            if ($null -ne $fileMru) { Read-MruKey -Opened $fileMru -Head 'File_MRU' -Found $found -Cap $cap }
            if ($null -ne $place) { Read-MruKey -Opened $place -Head 'Place_MRU' -Found $found -Cap $cap }
            Read-UserMru -ExcelKey $excel.Key -Found $found -Cap $cap
        } finally {
            if ($null -ne $fileMru) { $fileMru.Dispose() }
            if ($null -ne $place) { $place.Dispose() }
        }
    } finally {
        if ($null -ne $excel.Key) { $excel.Key.Dispose() }
    }
    return (New-Object psobject -Property @{ Cap = $cap; Found = $found })
}

function Get-MruSummary {
    param($Found)
    $summary = New-Object psobject -Property @{
        Count = 0
        Form = 'none'
        F = ''
        O = ''
        Head = 'none'
        ValueLen = ''
        Class = 'none'
    }
    if ($null -eq $Found) { return $summary }
    if ($Found.Count -eq 0) { return $summary }
    $summary.Count = $Found.Count
    $form = ''
    $f = ''
    $o = ''
    $head = ''
    $valueLen = ''
    $class = ''
    foreach ($item in $Found) {
        $itemForm = [string]$item.Form
        $itemF = [string]$item.F
        $itemO = [string]$item.O
        $itemHead = [string]$item.Head
        $itemLen = [int]$item.ValueLen
        $itemClass = [string]$item.Class
        if ($form.Length -eq 0) { $form = $itemForm } elseif ($form -ne $itemForm) { $form = 'mixed' }
        if ($f.Length -eq 0) { $f = $itemF } elseif ($f -ne $itemF) { $f = 'mixed' }
        if ($o.Length -eq 0) { $o = $itemO } elseif ($o -ne $itemO) { $o = 'mixed' }
        if ($head.Length -eq 0) { $head = $itemHead } elseif ($head -ne $itemHead) { $head = 'mixed' }
        $lenText = $itemLen.ToString()
        if ($valueLen.Length -eq 0) { $valueLen = $lenText } elseif ($valueLen -ne $lenText) { $valueLen = 'mixed' }
        if ($class.Length -eq 0) { $class = $itemClass }
        elseif ($class -ne $itemClass) {
            if ($itemClass -eq 'unparsed' -or $class -eq 'unparsed') { $class = 'unparsed' }
            elseif ($itemClass -eq 'flags_set' -or $class -eq 'flags_set') { $class = 'flags_set' }
        }
    }
    $summary.Form = $form
    $summary.F = $f
    $summary.O = $o
    $summary.Head = $head
    $summary.ValueLen = $valueLen
    $summary.Class = $class
    return $summary
}

function Add-OfficeFiles {
    param([string]$Directory, $State, [int]$Depth)
    if ($Depth -gt 1) { return }
    if ([string]::IsNullOrEmpty($Directory)) { return }
    if (-not [IO.Directory]::Exists($Directory)) { return }
    try {
        foreach ($file in [IO.Directory]::EnumerateFiles($Directory)) {
            if ([int]$State.Seen -ge 80) { $State.Truncated = '1'; return }
            $State.Seen = [int]$State.Seen + 1
            $fileText = [string]$file
            $leafName = Get-PathLeaf -Path $fileText
            $nameFlags = Get-ContentFlags -Text $leafName -Binary $null
            $binary = $null
            if ([int]$nameFlags.Leaf -ne 1 -and [int]$nameFlags.Path -ne 1) {
                try { $binary = Read-CappedBytes -Path $fileText -Cap 65536 } catch { $binary = $null }
            }
            $flags = Get-ContentFlags -Text $leafName -Binary $binary
            if ([int]$flags.Leaf -eq 1 -or [int]$flags.Path -eq 1) {
                $State.Match = '1'
                if ($State.Hits.Count -lt 8) {
                    [void]$State.Hits.Add((Get-SafeLeaf -Name $leafName))
                }
            }
        }
        if ($Depth -ge 1) { return }
        foreach ($dir in [IO.Directory]::EnumerateDirectories($Directory)) {
            if ([int]$State.Seen -ge 80) { $State.Truncated = '1'; return }
            Add-OfficeFiles -Directory ([string]$dir) -State $State -Depth ($Depth + 1)
        }
    } catch {
        $State.Unreadable = '1'
    }
}

function Invoke-LiveScope {
    param([int]$FocusPid)
    $launch = Get-LaunchStamp -ProcId $FocusPid
    Write-Output 'ACTION=diagnose_canonical_disabled_scope_readonly'
    Write-Output 'READ_ONLY=1'
    Write-Output 'PACKAGE_REREAD=0'
    Write-Output 'DIALOG_QUERIED=0'
    Write-Output 'STORE_WALK_REPEATED=0'
    Write-Output ('LAUNCHED_PID=' + $FocusPid.ToString())
    Write-Output ('LAUNCHED_ALIVE=' + [string]$launch.Alive)
    Write-Output ('LAUNCHED_EXCEL=' + [string]$launch.Excel)
    Write-Output ('LAUNCHED_CANONICAL=' + [string]$launch.Canonical)
    Write-Output ('LAUNCHED_START_UTC=' + [string]$launch.StartUtc)
    $rows = New-Object System.Collections.Generic.List[object]
    $cap = New-Object psobject -Property @{ Truncated = '0'; Partial = '0'; Unreadable = '0' }
    $hkcu = [Microsoft.Win32.Registry]::CurrentUser
    $hklm = [Microsoft.Win32.Registry]::LocalMachine
    Read-ResiliencyScope -Hive $hkcu -Path 'Software\Microsoft\Office\16.0\Excel\Resiliency' -ScopeId 'hkcu16' -Rows $rows -Cap $cap
    Read-ResiliencyScope -Hive $hkcu -Path 'Software\Microsoft\Office\15.0\Excel\Resiliency' -ScopeId 'hkcu15' -Rows $rows -Cap $cap
    Read-ResiliencyScope -Hive $hkcu -Path 'Software\Policies\Microsoft\Office\16.0\Excel\Resiliency' -ScopeId 'policy16' -Rows $rows -Cap $cap
    Read-ResiliencyScope -Hive $hklm -Path 'Software\Microsoft\Office\16.0\Excel\Resiliency' -ScopeId 'hklm16' -Rows $rows -Cap $cap
    Read-ResiliencyScope -Hive $hklm -Path 'Software\WOW6432Node\Microsoft\Office\16.0\Excel\Resiliency' -ScopeId 'hklm_wow64' -Rows $rows -Cap $cap
    Read-ResiliencyScope -Hive $hkcu -Path 'Software\Microsoft\Office\16.0\Common\Resiliency' -ScopeId 'common16' -Rows $rows -Cap $cap
    $mru = Read-MruFlags
    $summary = Get-MruSummary -Found $mru.Found
    $local = New-Object psobject -Property @{
        Seen = 0
        Truncated = '0'
        Unreadable = '0'
        Match = '0'
        Hits = (New-Object System.Collections.Generic.List[string])
    }
    $localRoot = ''
    try { $localRoot = [string][Environment]::GetFolderPath('LocalApplicationData') } catch { $localRoot = '' }
    if ($localRoot.Length -gt 0) {
        Add-OfficeFiles -Directory ($localRoot + '\Microsoft\Office\16.0') -State $local -Depth 0
        Add-OfficeFiles -Directory ($localRoot + '\Microsoft\Office\Excel') -State $local -Depth 0
    }
    foreach ($row in $rows) {
        Write-Output ('SCOPE id=' + [string]$row.Scope + ' state=' + [string]$row.State + ' area=' + [string]$row.Area + ' values=' + ([int]$row.Values).ToString() + ' match_leaf=' + ([int]$row.MatchLeaf).ToString() + ' match_path=' + ([int]$row.MatchPath).ToString() + ' match_xll=' + ([int]$row.MatchXll).ToString())
    }
    Write-Output ('MRU_MATCH_COUNT=' + ([int]$summary.Count).ToString())
    Write-Output ('MRU_FORM=' + [string]$summary.Form)
    Write-Output ('MRU_F=' + [string]$summary.F)
    Write-Output ('MRU_O=' + [string]$summary.O)
    Write-Output ('MRU_HEAD=' + [string]$summary.Head)
    Write-Output ('MRU_VALUE_LEN=' + [string]$summary.ValueLen)
    Write-Output ('MRU_CLASS=' + [string]$summary.Class)
    Write-Output ('MRU_EXAMINED=' + ([int]$mru.Cap.Examined).ToString())
    Write-Output ('MRU_TRUNCATED=' + [string]$mru.Cap.Truncated)
    Write-Output ('LOCAL_SEEN=' + ([int]$local.Seen).ToString())
    Write-Output ('LOCAL_TRUNCATED=' + [string]$local.Truncated)
    Write-Output ('LOCAL_MATCH=' + [string]$local.Match)
    foreach ($hit in $local.Hits) {
        Write-Output ('LOCAL_HIT name=' + [string]$hit)
    }
    $primary = Get-DisabledJudgment -Rows $rows -LocalMatch ([string]$local.Match)
    $scopeUnreadable = [string]$cap.Unreadable
    if ([string]$mru.Cap.Unreadable -eq '1' -or [string]$local.Unreadable -eq '1') { $scopeUnreadable = '1' }
    $limit = Get-DisabledLimit -Primary $primary -MruClass ([string]$summary.Class) -ScopeTruncated ([string]$cap.Truncated) -ScopeUnreadable $scopeUnreadable -LocalTruncated ([string]$local.Truncated) -LocalUnreadable ([string]$local.Unreadable) -ValuePartial ([string]$cap.Partial)
    if ([string]$mru.Cap.Truncated -eq '1' -and $limit.IndexOf('scope_truncated', $script:Ordinal) -lt 0) {
        if ($limit -eq 'none') { $limit = 'scope_truncated' }
        else { $limit = $limit + ',scope_truncated' }
    }
    Write-Output ('JUDGMENT_SCOPE=' + $primary)
    Write-Output ('JUDGMENT_LIMIT=' + $limit)
    Write-Output 'NOTHING_TOUCHED=1'
    Write-Output 'REGISTRY_CHANGED=0'
    Write-Output 'WORKBOOK_CHANGED=0'
    Write-Output 'XLL_CHANGED=0'
    Write-Output 'DIALOG_CLICKED=0'
    Write-Output 'EXCEL_STOP_REQUESTED=0'
}

if ($SelfTest) {
    Invoke-DisabledSelfTest
    return
}
if (-not [string]::Equals($Confirm, $script:ConfirmToken, $script:Ordinal)) {
    Write-Refused -Reason 'confirm_token_missing'
    throw 'confirm_token_missing'
}
Invoke-LiveScope -FocusPid $LaunchedPid
