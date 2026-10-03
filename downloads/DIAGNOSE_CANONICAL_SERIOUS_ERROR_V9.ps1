param(
    [switch]$SelfTest,
    [string]$Confirm = '',
    [int]$LaunchedPid = 0
)

# Read-only diagnosis for the canonical workbook serious-error prompt.
# Dialog text is already confirmed. crashSave is reported only after the
# whole workbook part is scanned. Prior Excel crashes stay correlation
# until an event names the canonical workbook or the RSS xll.
# It does not delete registry values, stop Excel, click a dialog, or
# modify the workbook or the RSS xll. -SelfTest does not read HKCU,
# processes, or the workbook.

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$script:Ordinal = [StringComparison]::Ordinal
$script:OrdinalIgnore = [StringComparison]::OrdinalIgnoreCase
$script:Leaf = 'Kioxia_MS2_RSS_Live_Signals.xlsx'
$script:PathTail = 'MarketSpeed II RSS\files\Kioxia_MS2_RSS_Live_Signals.xlsx'
$script:XllStem = 'MarketSpeed2_RSS'
$script:XllLeaf = 'MarketSpeed2_RSS_64bit.xll'
$script:ResiliencyRoot = 'Software\Microsoft\Office\16.0\Excel\Resiliency'
$script:ConfirmToken = 'DIAGNOSE_CANONICAL_SERIOUS_ERROR_READONLY'
$script:CaseCount = 0
$script:SeriousErrorJa = -join @(
    [char]0x91CD, [char]0x5927, [char]0x306A, [char]0x30A8, [char]0x30E9, [char]0x30FC
)
$script:ReopenDocumentJa = -join @(
    [char]0x3053, [char]0x306E, [char]0x30C9, [char]0x30AD, [char]0x30E5, [char]0x30E1, [char]0x30F3, [char]0x30C8, [char]0x3092, [char]0x958B, [char]0x304D, [char]0x307E, [char]0x3059, [char]0x304B
)

function Get-CanonicalFullPath {
    $day = -join @(
        [char]0x30C7,
        [char]0x30A4,
        [char]0x30C8,
        [char]0x30EC
    )
    return ('C:\Users\yusuk\Desktop\' + $day + '\MarketSpeed II RSS\files\' + $script:Leaf)
}

function Get-BackupRoot {
    return 'C:\AI_Cockpit_OneClick_Starter\Logs\V9\canonical_workbook_recovery_backup'
}

function ConvertTo-CanonicalRegistryPath {
    param([string]$Key)
    if ([string]::IsNullOrWhiteSpace($Key)) { return '' }
    $text = $Key.Trim()
    $marker = 'Registry::'
    $markerAt = $text.IndexOf($marker, $script:OrdinalIgnore)
    if ($markerAt -ge 0) { $text = $text.Substring($markerAt + $marker.Length) }
    foreach ($hive in @('HKEY_CURRENT_USER\', 'HKCU:\', 'HKCU\')) {
        if ($text.StartsWith($hive, $script:OrdinalIgnore)) {
            $text = $text.Substring($hive.Length)
            break
        }
    }
    while ($text.IndexOf('\\', $script:Ordinal) -ge 0) { $text = $text.Replace('\\', '\') }
    $text = $text.Trim('\')
    if ($text.IndexOf('..', $script:Ordinal) -ge 0) { return '' }
    if ($text.IndexOf('/', $script:Ordinal) -ge 0) { return '' }
    if ($text.StartsWith('HKCU', $script:OrdinalIgnore)) { return '' }
    if ($text.StartsWith('HKEY_', $script:OrdinalIgnore)) { return '' }
    return $text
}

function Get-RecoveryArea {
    param([string]$Key)
    $canon = ConvertTo-CanonicalRegistryPath -Key $Key
    if ([string]::IsNullOrWhiteSpace($canon)) { return 'other' }
    $prefix = $script:ResiliencyRoot + '\'
    if (-not $canon.StartsWith($prefix, $script:OrdinalIgnore)) { return 'other' }
    $rel = $canon.Substring($prefix.Length)
    if ($rel.Length -eq 0) { return 'other' }
    $parts = @($rel.Split('\'))
    if ($parts.Count -lt 1 -or $parts.Count -gt 2) { return 'other' }
    foreach ($part in $parts) {
        if ([string]::IsNullOrWhiteSpace([string]$part)) { return 'other' }
        if ([string]$part -eq '.' -or [string]$part -eq '..') { return 'other' }
    }
    $head = [string]$parts[0]
    if ([string]::Equals($head, 'DocumentRecovery', $script:OrdinalIgnore)) { return 'document_recovery' }
    if ([string]::Equals($head, 'DisabledItems', $script:OrdinalIgnore)) { return 'disabled_items' }
    return 'other'
}

function Get-ResiliencyHead {
    param([string]$Key)
    $canon = ConvertTo-CanonicalRegistryPath -Key $Key
    $prefix = $script:ResiliencyRoot + '\'
    if ([string]::IsNullOrWhiteSpace($canon) -or -not $canon.StartsWith($prefix, $script:OrdinalIgnore)) { return 'none' }
    $rel = $canon.Substring($prefix.Length)
    $cut = $rel.IndexOf('\', $script:Ordinal)
    if ($cut -lt 0) { return $rel }
    if ($cut -eq 0) { return 'none' }
    return $rel.Substring(0, $cut)
}

function Get-ResiliencyRelative {
    param([string]$Key)
    $canon = ConvertTo-CanonicalRegistryPath -Key $Key
    $prefix = $script:ResiliencyRoot + '\'
    if ([string]::IsNullOrWhiteSpace($canon)) { return '' }
    if ($canon.StartsWith($prefix, $script:OrdinalIgnore)) { return $canon.Substring($prefix.Length) }
    return $canon
}

function Test-BackupDirAllowed {
    param([string]$Root, [string]$Candidate)
    if ([string]::IsNullOrWhiteSpace($Root) -or [string]::IsNullOrWhiteSpace($Candidate)) { return $false }
    if ($Candidate.IndexOf('..', $script:Ordinal) -ge 0) { return $false }
    if ($Candidate.IndexOf('/', $script:Ordinal) -ge 0) { return $false }
    $prefix = $Root.TrimEnd('\') + '\'
    if (-not $Candidate.StartsWith($prefix, $script:OrdinalIgnore)) { return $false }
    $leaf = $Candidate.Substring($prefix.Length)
    if ($leaf.IndexOf('\', $script:Ordinal) -ge 0) { return $false }
    return ($leaf -match '^[0-9]{8}T[0-9]{6}Z$')
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

function Test-AsciiNameByte {
    param([int]$Value)
    if ($Value -ge 48 -and $Value -le 57) { return $true }
    if ($Value -ge 65 -and $Value -le 90) { return $true }
    if ($Value -ge 97 -and $Value -le 122) { return $true }
    if ($Value -eq 46 -or $Value -eq 95 -or $Value -eq 45) { return $true }
    return $false
}

function Test-BoundedNeedle {
    param([byte[]]$Hay, [byte[]]$Needle, [bool]$Utf16)
    if ($null -eq $Needle -or $Needle.Length -eq 0) { return $false }
    if ($Utf16 -and (($Needle.Length % 2) -ne 0)) { return $false }
    $start = 0
    while ($start -ge 0) {
        $at = Find-PatternOffset -Hay $Hay -Needle $Needle -Start $start
        if ($at -lt 0) { return $false }
        $bounded = $true
        if ($Utf16) {
            if (($at % 2) -ne 0) { $bounded = $false }
            elseif ($at -ge 2) {
                $hi = [int]$Hay[$at - 1]
                $lo = [int]$Hay[$at - 2]
                if ($hi -eq 0 -and (Test-AsciiNameByte -Value $lo)) { $bounded = $false }
            }
        } elseif ($at -gt 0) {
            if (Test-AsciiNameByte -Value ([int]$Hay[$at - 1])) { $bounded = $false }
        }
        if ($bounded) { return $true }
        $start = $at + 1
    }
    return $false
}

function Test-OddUtf16Hit {
    param([byte[]]$Hay, [byte[]]$Needle)
    if ($null -eq $Needle -or $Needle.Length -eq 0 -or (($Needle.Length % 2) -ne 0)) { return $false }
    $start = 1
    while ($start -ge 1) {
        $at = Find-PatternOffset -Hay $Hay -Needle $Needle -Start $start
        if ($at -lt 0) { return $false }
        if (($at % 2) -eq 1) { return $true }
        $start = $at + 1
    }
    return $false
}

function Get-AsciiStrings {
    param([byte[]]$Hay, [int]$MinChars)
    $found = New-Object System.Collections.Generic.List[string]
    if ($null -eq $Hay) { return ,$found.ToArray() }
    $sb = New-Object System.Text.StringBuilder
    foreach ($b in $Hay) {
        $code = [int]$b
        if ($code -ge 32 -and $code -le 126) {
            [void]$sb.Append([char]$code)
        } else {
            if ($sb.Length -ge $MinChars) { [void]$found.Add($sb.ToString()) }
            [void]$sb.Clear()
        }
    }
    if ($sb.Length -ge $MinChars) { [void]$found.Add($sb.ToString()) }
    return ,$found.ToArray()
}

function Get-Utf16Strings {
    param([byte[]]$Hay, [int]$MinChars)
    $found = New-Object System.Collections.Generic.List[string]
    if ($null -eq $Hay) { return ,$found.ToArray() }
    $sb = New-Object System.Text.StringBuilder
    $i = 0
    while ($i -le ($Hay.Length - 2)) {
        $code = [int]$Hay[$i] + (256 * [int]$Hay[$i + 1])
        $printable = (($code -ge 32) -and ($code -le 126)) -or (($code -ge 0x3000) -and ($code -le 0x30FF)) -or (($code -ge 0x4E00) -and ($code -le 0x9FFF)) -or (($code -ge 0xFF00) -and ($code -le 0xFFEF))
        if ($printable) {
            [void]$sb.Append([char]$code)
            $i += 2
        } else {
            if ($sb.Length -ge $MinChars) { [void]$found.Add($sb.ToString()) }
            [void]$sb.Clear()
            $i += 2
        }
    }
    if ($sb.Length -ge $MinChars) { [void]$found.Add($sb.ToString()) }
    return ,$found.ToArray()
}

function Get-SpreadsheetLeaves {
    param([byte[]]$Hay)
    $leaves = New-Object System.Collections.Generic.List[string]
    $seen = New-Object System.Collections.Generic.List[string]
    $texts = New-Object System.Collections.Generic.List[string]
    foreach ($s in @(Get-AsciiStrings -Hay $Hay -MinChars 6)) {
        if (-not [string]::IsNullOrWhiteSpace($s)) { [void]$texts.Add([string]$s) }
    }
    foreach ($s in @(Get-Utf16Strings -Hay $Hay -MinChars 6)) {
        if (-not [string]::IsNullOrWhiteSpace($s)) { [void]$texts.Add([string]$s) }
    }
    $pattern = '(?i)(?<leaf>[A-Za-z0-9][A-Za-z0-9 ._-]{0,160}\.(?:xlsx|xlsm|xlsb|xltx|xltm|xls))(?![A-Za-z0-9])'
    $regex = New-Object System.Text.RegularExpressions.Regex($pattern)
    foreach ($text in $texts) {
        foreach ($m in @($regex.Matches([string]$text))) {
            $leaf = $m.Groups['leaf'].Value.Trim()
            $key = $leaf.ToLowerInvariant()
            if (-not $seen.Contains($key)) {
                [void]$seen.Add($key)
                [void]$leaves.Add($leaf)
            }
        }
    }
    return ,$leaves.ToArray()
}

function New-PrefixedUtf16 {
    param([string]$Text)
    $utf = [Text.Encoding]::Unicode.GetBytes($Text)
    $blob = New-Object byte[] (6 + $utf.Length)
    $blob[0] = 1
    $blob[1] = 2
    $blob[2] = 3
    $blob[3] = 4
    $blob[4] = 5
    $blob[5] = 6
    [Buffer]::BlockCopy($utf, 0, $blob, 6, $utf.Length)
    return ,$blob
}

function New-OddUtf16 {
    param([string]$Text)
    $utf = [Text.Encoding]::Unicode.GetBytes($Text)
    $blob = New-Object byte[] (1 + $utf.Length)
    $blob[0] = 9
    [Buffer]::BlockCopy($utf, 0, $blob, 1, $utf.Length)
    return ,$blob
}

function New-OfficeDisabledItemBytes {
    param([string]$Path, [string]$Description)
    $pathBytes = [Text.Encoding]::Unicode.GetBytes($Path + [char]0)
    $descBytes = New-Object byte[] 0
    if (-not [string]::IsNullOrEmpty($Description)) {
        $descBytes = [Text.Encoding]::Unicode.GetBytes($Description + [char]0)
    }
    $blob = New-Object byte[] (12 + $pathBytes.Length + $descBytes.Length)
    $blob[0] = 1
    $pathLen = [BitConverter]::GetBytes([int]$pathBytes.Length)
    $descLen = [BitConverter]::GetBytes([int]$descBytes.Length)
    [Buffer]::BlockCopy($pathLen, 0, $blob, 4, 4)
    [Buffer]::BlockCopy($descLen, 0, $blob, 8, 4)
    [Buffer]::BlockCopy($pathBytes, 0, $blob, 12, $pathBytes.Length)
    if ($descBytes.Length -gt 0) {
        [Buffer]::BlockCopy($descBytes, 0, $blob, (12 + $pathBytes.Length), $descBytes.Length)
    }
    return ,$blob
}

function Get-Sha256Hex {
    param([byte[]]$Bytes)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $hash = $sha.ComputeHash($Bytes)
    } finally {
        $sha.Dispose()
    }
    $sb = New-Object System.Text.StringBuilder
    foreach ($b in $hash) {
        [void]$sb.Append($b.ToString('x2'))
    }
    return $sb.ToString()
}

function Get-BlobVerdict {
    param([byte[]]$Bytes)
    if ($null -eq $Bytes -or $Bytes.Length -lt 32) { return 'none' }
    $leafAscii = [Text.Encoding]::ASCII.GetBytes($script:Leaf)
    $leafUtf16 = [Text.Encoding]::Unicode.GetBytes($script:Leaf)
    $tailAscii = [Text.Encoding]::ASCII.GetBytes($script:PathTail)
    $tailUtf16 = [Text.Encoding]::Unicode.GetBytes($script:PathTail)
    $fullUtf16 = [Text.Encoding]::Unicode.GetBytes((Get-CanonicalFullPath))
    $hit = $false
    if (Test-BoundedNeedle -Hay $Bytes -Needle $leafAscii -Utf16 $false) { $hit = $true }
    if (Test-BoundedNeedle -Hay $Bytes -Needle $leafUtf16 -Utf16 $true) { $hit = $true }
    if (Test-BoundedNeedle -Hay $Bytes -Needle $tailAscii -Utf16 $false) { $hit = $true }
    if (Test-BoundedNeedle -Hay $Bytes -Needle $tailUtf16 -Utf16 $true) { $hit = $true }
    if (Test-BoundedNeedle -Hay $Bytes -Needle $fullUtf16 -Utf16 $true) { $hit = $true }
    $odd = (Test-OddUtf16Hit -Hay $Bytes -Needle $leafUtf16) -or (Test-OddUtf16Hit -Hay $Bytes -Needle $tailUtf16) -or (Test-OddUtf16Hit -Hay $Bytes -Needle $fullUtf16)
    if (-not $hit -and -not $odd) { return 'none' }
    if ($odd -and -not $hit) { return 'impure' }
    $xllAscii = [Text.Encoding]::ASCII.GetBytes($script:XllStem)
    $xllUtf16 = [Text.Encoding]::Unicode.GetBytes($script:XllStem)
    $hasXll = ((Find-PatternOffset -Hay $Bytes -Needle $xllAscii -Start 0) -ge 0) -or ((Find-PatternOffset -Hay $Bytes -Needle $xllUtf16 -Start 0) -ge 0)
    $foreign = $false
    foreach ($leaf in @(Get-SpreadsheetLeaves -Hay $Bytes)) {
        if (-not [string]::Equals([string]$leaf, $script:Leaf, $script:OrdinalIgnore)) { $foreign = $true }
    }
    $hasModule = $false
    foreach ($suffix in @('.xll', '.dll', '.ocx')) {
        $suffixAscii = [Text.Encoding]::ASCII.GetBytes($suffix)
        $suffixUtf16 = [Text.Encoding]::Unicode.GetBytes($suffix)
        if (((Find-PatternOffset -Hay $Bytes -Needle $suffixAscii -Start 0) -ge 0) -or ((Find-PatternOffset -Hay $Bytes -Needle $suffixUtf16 -Start 0) -ge 0)) {
            $hasModule = $true
        }
    }
    if ($hasXll -or $foreign -or $odd -or $hasModule) { return 'impure' }
    return 'pure'
}

function Test-BlobHasXllStem {
    param([byte[]]$Bytes)
    if ($null -eq $Bytes) { return $false }
    $xllAscii = [Text.Encoding]::ASCII.GetBytes($script:XllStem)
    $xllUtf16 = [Text.Encoding]::Unicode.GetBytes($script:XllStem)
    if ((Find-PatternOffset -Hay $Bytes -Needle $xllAscii -Start 0) -ge 0) { return $true }
    if ((Find-PatternOffset -Hay $Bytes -Needle $xllUtf16 -Start 0) -ge 0) { return $true }
    return $false
}

function Get-FlatRows {
    param($Rows)
    $items = New-Object System.Collections.Generic.List[object]
    if ($null -eq $Rows) { return $items.ToArray() }
    $current = $Rows
    if (($current -is [System.Array]) -and ($current.Length -eq 1) -and ($null -ne $current[0]) -and ($current[0] -is [System.Array])) {
        $current = $current[0]
    }
    foreach ($entry in $current) {
        if ($null -eq $entry) { continue }
        if ($entry -is [System.Array]) { throw 'diagnostic rows were nested' }
        [void]$items.Add($entry)
    }
    return $items.ToArray()
}

function Get-MatchCounts {
    param($Rows)
    $pure = 0
    $impure = 0
    $outside = 0
    $none = 0
    foreach ($row in @(Get-FlatRows -Rows $Rows)) {
        $verdict = [string]$row.Verdict
        $area = [string]$row.Area
        if ($verdict -eq 'none') {
            $none = $none + 1
            continue
        }
        $allowed = ($area -eq 'document_recovery') -or ($area -eq 'disabled_items')
        if (-not $allowed) {
            $outside = $outside + 1
            continue
        }
        if ($verdict -eq 'pure') { $pure = $pure + 1 }
        elseif ($verdict -eq 'impure') { $impure = $impure + 1 }
    }
    return (New-Object psobject -Property @{
        Pure = $pure
        Impure = $impure
        Outside = $outside
        None = $none
    })
}

function Get-BackupCompareResult {
    param([string]$BackupSha, [bool]$BackupReadable, $Rows)
    $result = New-Object psobject -Property @{
        State = 'backup_unreadable'
        Recreated = '0'
        Other = '0'
    }
    $same = $false
    $other = $false
    foreach ($row in @(Get-FlatRows -Rows $Rows)) {
        $sha = [string]$row.Sha
        $verdict = [string]$row.Verdict
        $shaHit = $BackupReadable -and (-not [string]::IsNullOrWhiteSpace($BackupSha)) -and [string]::Equals($sha, $BackupSha, $script:OrdinalIgnore)
        if ($shaHit) { $same = $true }
        elseif (($verdict -eq 'pure') -or ($verdict -eq 'impure')) { $other = $true }
    }
    if ($other) { $result.Other = '1' }
    if (-not $BackupReadable -or [string]::IsNullOrWhiteSpace($BackupSha)) { return $result }
    if ($same) { $result.Recreated = '1' }
    if ($same -and $other) { $result.State = 'same_and_other' }
    elseif ($same) { $result.State = 'returned' }
    elseif ($other) { $result.State = 'new_record' }
    else { $result.State = 'stayed_clear' }
    return $result
}

function Get-ReplacementFlag {
    param([string]$BackupKey, [string]$BackupName, [string]$BackupSha, [bool]$BackupReadable, $Rows)
    if (-not $BackupReadable -or [string]::IsNullOrWhiteSpace($BackupSha)) { return '0' }
    $canonKey = ConvertTo-CanonicalRegistryPath -Key $BackupKey
    $different = $false
    $same = $false
    foreach ($row in @(Get-FlatRows -Rows $Rows)) {
        $sameKey = [string]::Equals([string]$row.Key, $canonKey, $script:OrdinalIgnore)
        $sameName = [string]::Equals([string]$row.ValueName, $BackupName, $script:Ordinal)
        if (-not $sameKey -or -not $sameName) { continue }
        if ([string]::Equals([string]$row.Sha, $BackupSha, $script:OrdinalIgnore)) { $same = $true }
        else { $different = $true }
    }
    if ($different -and -not $same) { return '1' }
    return '0'
}

function Get-UnexplainedKeyTouch {
    param([string]$KeyWrite, [string]$Recreated, [string]$Other, [string]$Replaced)
    if (($KeyWrite -eq '1') -and ($Recreated -ne '1') -and ($Other -ne '1') -and ($Replaced -ne '1')) { return '1' }
    return '0'
}

function Get-DistinctionPrimary {
    param(
        [string]$Recreated,
        [string]$Other,
        [string]$Rewritten,
        [string]$Crash,
        [string]$KeyTouched,
        [string]$Replaced
    )
    $causes = New-Object System.Collections.Generic.List[string]
    if ($Recreated -eq '1') { [void]$causes.Add('resiliency_recreated') }
    if ($Other -eq '1') { [void]$causes.Add('resiliency_other_match') }
    if ($Replaced -eq '1') { [void]$causes.Add('resiliency_value_replaced') }
    if ($KeyTouched -eq '1') { [void]$causes.Add('resiliency_key_touched') }
    if ($Rewritten -eq '1') { [void]$causes.Add('workbook_rewritten') }
    if ($Crash -eq '1') { [void]$causes.Add('crash_after_launch') }
    if ($causes.Count -eq 1) { return [string]$causes[0] }
    if ($causes.Count -gt 1) { return 'multiple_signals' }
    return 'inconclusive'
}

function Get-DistinctionReason {
    param(
        [string]$Primary,
        [string]$Recreated,
        [string]$Other,
        [string]$Rewritten,
        [string]$Crash,
        [string]$Xll,
        [string]$Dialog,
        [string]$BackupState
    )
    if ($Primary -eq 'multiple_signals') { return 'multiple_signals' }
    if ($Primary -ne 'inconclusive') { return 'single_signal' }
    $unread = ($Recreated -eq 'unreadable') -or ($Other -eq 'unreadable') -or ($Rewritten -eq 'unreadable') -or ($Crash -eq 'unreadable') -or ($Xll -eq 'unreadable')
    $onlyCrash = ($Crash -eq 'unreadable') -and ($Recreated -ne 'unreadable') -and ($Other -ne 'unreadable') -and ($Rewritten -ne 'unreadable') -and ($Xll -ne 'unreadable')
    if (($Dialog -eq '1') -and $unread) { return 'dialog_visible_with_unreadable_evidence' }
    if ($BackupState -eq 'backup_unreadable') { return 'backup_unreadable' }
    if (($Dialog -eq '1') -and ($Xll -eq '1')) { return 'dialog_visible_xll_loaded_without_resiliency_crash_or_rewrite' }
    if ($Dialog -eq '1') { return 'dialog_visible_without_resiliency_crash_or_rewrite' }
    if ($onlyCrash) { return 'crash_query_unreadable' }
    if ($unread) { return 'evidence_unreadable' }
    return 'no_distinguishing_signal'
}

function Get-ModuleTokens {
    param([string]$Text)
    $found = New-Object System.Collections.Generic.List[string]
    if ([string]::IsNullOrEmpty($Text)) { return $found.ToArray() }
    $lower = $Text.ToLowerInvariant()
    foreach ($suffix in @('.dll', '.xll', '.exe')) {
        $start = 0
        while ($start -lt $lower.Length) {
            $at = $lower.IndexOf($suffix, $start, $script:Ordinal)
            if ($at -lt 0) { break }
            $end = $at + $suffix.Length
            $i = $at - 1
            while ($i -ge 0) {
                $ch = $lower[$i]
                $ok = (($ch -ge 'a') -and ($ch -le 'z')) -or (($ch -ge '0') -and ($ch -le '9')) -or ($ch -eq '.') -or ($ch -eq '_') -or ($ch -eq '-')
                if (-not $ok) { break }
                $i = $i - 1
            }
            $token = $lower.Substring($i + 1, $end - ($i + 1))
            if (-not $found.Contains($token)) { [void]$found.Add($token) }
            $start = $end
        }
    }
    return $found.ToArray()
}

function Test-TokenPresent {
    param([string]$Text, [string]$Token)
    foreach ($item in @(Get-ModuleTokens -Text $Text)) {
        if ([string]::Equals([string]$item, $Token, $script:Ordinal)) { return $true }
    }
    return $false
}

function Test-TokensClean {
    param([string]$Text)
    foreach ($item in @(Get-ModuleTokens -Text $Text)) {
        $value = [string]$item
        if ($value.IndexOf('|', $script:Ordinal) -ge 0) { return $false }
        if ($value.IndexOf('\', $script:Ordinal) -ge 0) { return $false }
    }
    return $true
}

function Test-SeriousErrorText {
    param([string]$Text)
    if ([string]::IsNullOrEmpty($Text)) { return $false }
    if ($Text.IndexOf($script:SeriousErrorJa, $script:Ordinal) -ge 0) { return $true }
    if ($Text.IndexOf($script:ReopenDocumentJa, $script:Ordinal) -ge 0) { return $true }
    if ($Text.IndexOf('serious problem', $script:OrdinalIgnore) -ge 0) { return $true }
    if ($Text.IndexOf('serious error', $script:OrdinalIgnore) -ge 0) { return $true }
    return $false
}

function Test-WriteAfterStart {
    param([long]$WriteTicks, [long]$StartTicks, [bool]$WriteKnown, [bool]$StartKnown)
    if (-not $WriteKnown -or -not $StartKnown) { return $false }
    if ($WriteTicks -le 0 -or $StartTicks -le 0) { return $false }
    return ($WriteTicks -gt $StartTicks)
}

function Get-AggregateFlag {
    param($Parts)
    $any1 = $false
    $anyU = $false
    foreach ($part in @(Get-FlatRows -Rows $Parts)) {
        $value = [string]$part
        if ($value -eq '1') { $any1 = $true }
        elseif ($value -eq 'unreadable') { $anyU = $true }
    }
    if ($any1) { return '1' }
    if ($anyU) { return 'unreadable' }
    return '0'
}

function Combine-CrashFlag {
    param([string]$EventFlag, [int]$WerCount)
    if ($EventFlag -eq '1' -or $WerCount -gt 0) { return '1' }
    if ($EventFlag -eq '0') { return '0' }
    return 'unreadable'
}

function Test-NoMatchingEventQuery {
    param([string]$ErrorId, [string]$Message)
    if ($ErrorId.IndexOf('NoMatchingEventsFound', $script:OrdinalIgnore) -ge 0) { return $true }
    if ($Message.IndexOf('No events', $script:OrdinalIgnore) -ge 0) { return $true }
    $missing = -join @(
        [char]0x898B, [char]0x3064, [char]0x304B, [char]0x308A, [char]0x307E, [char]0x305B, [char]0x3093
    )
    if ($Message.IndexOf($missing, $script:Ordinal) -ge 0) { return $true }
    return $false
}

function Select-DialogHit {
    param([int]$FocusPid, $Rows)
    $bestPid = 0
    $bestOwner = 0
    $bestParent = 0
    $bestClass = ''
    $bestHwnd = [int64]0
    $bestOwnerHwnd = [int64]0
    $bestParentHwnd = [int64]0
    $bestSource = ''
    $bestLeaf = '0'
    $bestSerious = '0'
    $bestReopen = '0'
    $bestSame = '0'
    $bestOwnerLinked = '0'
    $bestScore = -1
    $found = $false
    foreach ($row in @(Get-FlatRows -Rows $Rows)) {
        $title = [string]$row.Title
        $child = [string]$row.ChildText
        $source = ''
        $text = ''
        if (Test-SeriousErrorText -Text $child) {
            $source = 'child'
            $text = $child
        } elseif (Test-SeriousErrorText -Text $title) {
            $source = 'title'
            $text = $title
        } else {
            continue
        }
        $score = 1
        $same = '0'
        $linked = '0'
        if (($FocusPid -gt 0) -and ([int]$row.Pid -eq $FocusPid)) {
            $score = $score + 4
            $same = '1'
        }
        if (($FocusPid -gt 0) -and ([int]$row.OwnerPid -eq $FocusPid)) {
            $score = $score + 2
            $linked = '1'
        }
        if (Test-DialogClassName -ClassName ([string]$row.Class)) { $score = $score + 3 }
        $leaf = '0'
        $serious = '0'
        $reopen = '0'
        if ($text.IndexOf($script:Leaf, $script:OrdinalIgnore) -ge 0) {
            $score = $score + 2
            $leaf = '1'
        }
        if ($text.IndexOf($script:SeriousErrorJa, $script:Ordinal) -ge 0) {
            $score = $score + 1
            $serious = '1'
        }
        if ($text.IndexOf($script:ReopenDocumentJa, $script:Ordinal) -ge 0) { $reopen = '1' }
        if ($score -gt $bestScore) {
            $found = $true
            $bestScore = $score
            $bestPid = [int]$row.Pid
            $bestOwner = [int]$row.OwnerPid
            $bestParent = [int]$row.ParentPid
            $bestClass = [string]$row.Class
            $bestHwnd = [int64]$row.Hwnd
            $bestOwnerHwnd = [int64]$row.OwnerHwnd
            $bestParentHwnd = [int64]$row.ParentHwnd
            $bestSource = $source
            $bestLeaf = $leaf
            $bestSerious = $serious
            $bestReopen = $reopen
            $bestSame = $same
            $bestOwnerLinked = $linked
        }
    }
    $match = 'none'
    $visible = '0'
    if ($found) {
        $visible = '1'
        $match = 'serious_error_needle'
        if (($bestLeaf -eq '1') -and ($bestSerious -eq '1')) { $match = 'canonical_serious_error' }
    }
    return (New-Object psobject -Property @{
        Visible = $visible
        Pid = $bestPid
        OwnerPid = $bestOwner
        ParentPid = $bestParent
        Class = $bestClass
        Hwnd = $bestHwnd
        OwnerHwnd = $bestOwnerHwnd
        ParentHwnd = $bestParentHwnd
        HasLeaf = $bestLeaf
        HasSerious = $bestSerious
        HasReopen = $bestReopen
        Match = $match
        Source = $bestSource
        SameProcess = $bestSame
        OwnerLinked = $bestOwnerLinked
    })
}

function Test-DialogClassName {
    param([string]$ClassName)
    if ([string]::IsNullOrEmpty($ClassName)) { return $false }
    if ([string]::Equals($ClassName, '#32770', $script:Ordinal)) { return $true }
    if ([string]::Equals($ClassName, 'NUIDialog', $script:Ordinal)) { return $true }
    if ([string]::Equals($ClassName, 'bosa_sdm_XL9', $script:Ordinal)) { return $true }
    if ([string]::Equals($ClassName, 'NetUIHWND', $script:Ordinal)) { return $true }
    if ($ClassName.IndexOf('bosa_sdm', $script:Ordinal) -ge 0) { return $true }
    if ($ClassName.IndexOf('Dialog', $script:Ordinal) -ge 0) { return $true }
    return $false
}

function Test-OfficeProcessName {
    param([string]$Name)
    if ([string]::IsNullOrEmpty($Name)) { return $false }
    foreach ($token in @(
        'EXCEL',
        'OfficeClickToRun',
        'OfficeC2RClient',
        'sdxhelper',
        'AppVShNotify',
        'MsoSync',
        'integrator',
        'OfficeBackgroundTaskHandler'
    )) {
        if ([string]::Equals($Name, $token, $script:OrdinalIgnore)) { return $true }
    }
    return $false
}

function Test-SurveyRowWanted {
    param($Row, [int]$FocusPid)
    if ($null -eq $Row) { return $false }
    $role = [string]$Row.Role
    if ($role -eq 'foreground' -or $role -eq 'guithread' -or $role -eq 'owner') { return $true }
    if ([int]$Row.Needle -eq 1) { return $true }
    if ([int]$Row.Foreground -eq 1 -or [int]$Row.GuiActive -eq 1) { return $true }
    if (Test-DialogClassName -ClassName ([string]$Row.Class)) { return $true }
    if (Test-OfficeProcessName -Name ([string]$Row.Process)) { return $true }
    if ($FocusPid -gt 0) {
        if ([int]$Row.Pid -eq $FocusPid) { return $true }
        if ([int]$Row.OwnerPid -eq $FocusPid) { return $true }
        if ([int]$Row.ParentPid -eq $FocusPid) { return $true }
        if ([int]$Row.RootPid -eq $FocusPid) { return $true }
    }
    return $false
}

function New-SurveyProbeRow {
    param(
        [int]$PidValue,
        [int]$OwnerPid,
        [int]$ParentPid,
        [int]$RootPid,
        [string]$Class,
        [string]$Role,
        [string]$Process,
        [int]$Needle
    )
    return (New-Object psobject -Property @{
        Pid = $PidValue
        OwnerPid = $OwnerPid
        ParentPid = $ParentPid
        RootPid = $RootPid
        Class = $Class
        Role = $Role
        Process = $Process
        Needle = $Needle
        Foreground = 0
        GuiActive = 0
    })
}

function Get-RelLabel {
    param([string]$Name)
    if ([string]::IsNullOrEmpty($Name)) { return 'empty' }
    if ($Name.Length -gt 80) { return ('len_' + $Name.Length.ToString()) }
    foreach ($ch in $Name.ToCharArray()) {
        $code = [int]$ch
        if ($code -lt 33 -or $code -gt 126) { return ('len_' + $Name.Length.ToString()) }
        if ($ch -eq '=' -or $ch -eq ' ' -or $ch -eq ':' -or $ch -eq '/') {
            return ('len_' + $Name.Length.ToString())
        }
    }
    return $Name
}

function Get-PartLabel {
    param([string]$Name)
    if ([string]::IsNullOrEmpty($Name)) { return 'empty' }
    if ($Name.Length -gt 80) { return ('len_' + $Name.Length.ToString()) }
    foreach ($ch in $Name.ToCharArray()) {
        $code = [int]$ch
        if (($code -lt 33) -or ($code -gt 126)) { return ('len_' + $Name.Length.ToString()) }
        if (($ch -eq '=') -or ($ch -eq ' ') -or ($ch -eq ':') -or ($ch -eq '\')) {
            return ('len_' + $Name.Length.ToString())
        }
    }
    return $Name
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

function Get-LeafStem {
    param([string]$Leaf)
    if ([string]::IsNullOrEmpty($Leaf)) { return '' }
    $dot = $Leaf.LastIndexOf('.')
    if ($dot -gt 0) { return $Leaf.Substring(0, $dot) }
    return $Leaf
}

function Get-OwnerLockPath {
    param([string]$WorkbookPath)
    if ([string]::IsNullOrEmpty($WorkbookPath)) { return '' }
    $cut = $WorkbookPath.LastIndexOf('\')
    if ($cut -lt 0 -or $cut -ge ($WorkbookPath.Length - 1)) { return '' }
    return ($WorkbookPath.Substring(0, $cut) + '\~$' + $WorkbookPath.Substring($cut + 1))
}

function Get-XlkPath {
    param([string]$WorkbookPath)
    if ([string]::IsNullOrEmpty($WorkbookPath)) { return '' }
    $cut = $WorkbookPath.LastIndexOf('\')
    if ($cut -lt 0 -or $cut -ge ($WorkbookPath.Length - 1)) { return '' }
    $leaf = $WorkbookPath.Substring($cut + 1)
    return ($WorkbookPath.Substring(0, $cut) + '\' + (Get-LeafStem -Leaf $leaf) + '.xlk')
}

function Get-RecoveryElement {
    param([string]$Xml)
    if ([string]::IsNullOrEmpty($Xml)) { return '' }
    $marker = 'fileRecoveryPr'
    $at = $Xml.IndexOf($marker, $script:Ordinal)
    if ($at -lt 0) { return '' }
    $start = $at
    $back = $at - 1
    while (($back -ge 0) -and (($at - $back) -le 8)) {
        if ($Xml[$back] -eq '<') { $start = $back; break }
        $back = $back - 1
    }
    $end = $Xml.IndexOf('>', $at, $script:Ordinal)
    if ($end -lt 0) { return '' }
    return $Xml.Substring($start, ($end - $start) + 1)
}

function Get-XmlFlag {
    param([string]$Element, [string]$Name)
    if ([string]::IsNullOrEmpty($Element) -or [string]::IsNullOrEmpty($Name)) { return 'absent' }
    $token = $Name + '='
    $at = $Element.IndexOf($token, $script:Ordinal)
    if ($at -lt 0) { return 'absent' }
    $pos = $at + $token.Length
    if ($pos -ge $Element.Length) { return 'unreadable' }
    $quote = $Element[$pos]
    $raw = ''
    if (($quote -eq '"') -or ($quote -eq "'")) {
        $end = $Element.IndexOf([string]$quote, $pos + 1, $script:Ordinal)
        if ($end -lt 0) { return 'unreadable' }
        $raw = $Element.Substring($pos + 1, $end - ($pos + 1))
    } else {
        $i = $pos
        while ($i -lt $Element.Length) {
            $ch = $Element[$i]
            if (($ch -eq ' ') -or ($ch -eq '/') -or ($ch -eq '>')) { break }
            $i = $i + 1
        }
        $raw = $Element.Substring($pos, $i - $pos)
    }
    $lower = $raw.ToLowerInvariant()
    if (($lower -eq '1') -or ($lower -eq 'true')) { return '1' }
    if (($lower -eq '0') -or ($lower -eq 'false')) { return '0' }
    return 'unreadable'
}

function Get-PackageRecovery {
    param([string]$Xml)
    $element = Get-RecoveryElement -Xml $Xml
    $present = '0'
    if ($element.Length -gt 0) { $present = '1' }
    return (New-Object psobject -Property @{
        Present = $present
        CrashSave = (Get-XmlFlag -Element $element -Name 'crashSave')
        RepairLoad = (Get-XmlFlag -Element $element -Name 'repairLoad')
        AutoRecover = (Get-XmlFlag -Element $element -Name 'autoRecover')
        DataExtract = (Get-XmlFlag -Element $element -Name 'dataExtractLoad')
    })
}

function Test-PackagePartName {
    param([string]$Name)
    if ([string]::IsNullOrEmpty($Name)) { return $false }
    $lower = $Name.ToLowerInvariant()
    if ($lower.IndexOf('filerecovery', $script:Ordinal) -ge 0) { return $true }
    if ($lower.StartsWith('xl/revisions/', $script:Ordinal)) { return $true }
    if ($lower.IndexOf('/repair', $script:Ordinal) -ge 0) { return $true }
    return $false
}

function Get-FileRelation {
    param([bool]$Exists, [long]$WriteTicks, [bool]$WriteKnown, [long]$StartTicks, [bool]$StartKnown)
    if (-not $Exists) {
        return (New-Object psobject -Property @{ Exists = '0'; Relation = 'absent' })
    }
    if ((-not $WriteKnown) -or (-not $StartKnown) -or ($WriteTicks -le 0) -or ($StartTicks -le 0)) {
        return (New-Object psobject -Property @{ Exists = '1'; Relation = 'unreadable' })
    }
    if ($WriteTicks -lt $StartTicks) {
        return (New-Object psobject -Property @{ Exists = '1'; Relation = 'before_excel_start' })
    }
    if ($WriteTicks -gt $StartTicks) {
        return (New-Object psobject -Property @{ Exists = '1'; Relation = 'after_excel_start' })
    }
    return (New-Object psobject -Property @{ Exists = '1'; Relation = 'same_second' })
}

function Get-OpenXllClass {
    param([string]$Name, [string]$Text)
    if ([string]::IsNullOrEmpty($Name)) { return 'skip' }
    $open = $false
    if ([string]::Equals($Name, 'OPEN', $script:OrdinalIgnore)) { $open = $true }
    elseif ($Name.StartsWith('OPEN', $script:OrdinalIgnore)) {
        $rest = $Name.Substring(4)
        $digits = ($rest.Length -gt 0)
        foreach ($ch in $rest.ToCharArray()) {
            if (($ch -lt '0') -or ($ch -gt '9')) { $digits = $false }
        }
        if ($digits) { $open = $true }
    }
    if (-not $open) { return 'skip' }
    if ([string]::IsNullOrEmpty($Text)) { return 'plain' }
    if ($Text.IndexOf($script:XllLeaf, $script:OrdinalIgnore) -ge 0) { return 'rss' }
    if ($Text.IndexOf($script:XllStem, $script:OrdinalIgnore) -ge 0) { return 'rss' }
    if ($Text.IndexOf('.xll', $script:OrdinalIgnore) -ge 0) { return 'other' }
    return 'plain'
}

function Test-TokenHasXll {
    param([string]$Tokens)
    if ([string]::IsNullOrEmpty($Tokens)) { return $false }
    $lower = $Tokens.ToLowerInvariant()
    $stem = $script:XllStem.ToLowerInvariant()
    if ($lower.IndexOf($stem, $script:Ordinal) -ge 0) { return $true }
    if ($lower.IndexOf('.xll', $script:Ordinal) -ge 0) { return $true }
    return $false
}

function Get-CauseClass {
    param(
        [string]$CrashSave,
        [string]$RepairLoad,
        [string]$DataExtract,
        [string]$FileRecovery,
        [string]$PackageOpen,
        [string]$PriorState,
        [int]$PriorCount,
        [string]$PriorXll,
        [string]$LockBefore,
        [string]$XlkExists,
        [string]$DialogVisible
    )
    $flags = New-Object System.Collections.Generic.List[string]
    if ($CrashSave -eq '1') { [void]$flags.Add('workbook_crash_save') }
    if ($RepairLoad -eq '1') { [void]$flags.Add('workbook_repair_load') }
    if ($DataExtract -eq '1') { [void]$flags.Add('workbook_data_extract') }
    if (($FileRecovery -eq '1') -and ($CrashSave -ne '1') -and ($RepairLoad -ne '1') -and ($DataExtract -ne '1')) {
        [void]$flags.Add('workbook_file_recovery_pr')
    }
    if (($PriorState -eq 'ok') -and ($PriorCount -gt 0) -and ($PriorXll -eq '1')) { [void]$flags.Add('prior_crash_with_xll') }
    elseif (($PriorState -eq 'ok') -and ($PriorCount -gt 0)) { [void]$flags.Add('prior_excel_crash') }
    if ($LockBefore -eq '1') { [void]$flags.Add('stale_owner_lockfile') }
    if ($XlkExists -eq '1') { [void]$flags.Add('excel_backup_xlk') }
    $blocked = ($PackageOpen -eq 'locked') -or ($PackageOpen -eq 'unreadable') -or ($PackageOpen -eq 'truncated') -or ($FileRecovery -eq 'unreadable') -or ($PriorState -eq 'unreadable') -or ($LockBefore -eq 'unreadable') -or ($XlkExists -eq 'unreadable')
    $cause = 'still_inconclusive'
    if ($flags.Count -gt 0) { $cause = [string]$flags[0] }
    elseif ($blocked) { $cause = 'evidence_incomplete' }
    elseif (($DialogVisible -eq '1') -and ($FileRecovery -eq '0') -and ($PriorState -eq 'ok') -and ($PriorCount -eq 0) -and ($LockBefore -eq '0') -and ($XlkExists -eq '0')) {
        $cause = 'dialog_without_package_or_resiliency_marker'
    }
    $text = 'none'
    if ($flags.Count -gt 0) { $text = [string]::Join(',', $flags.ToArray()) }
    return (New-Object psobject -Property @{ Cause = $cause; Flags = $text })
}

function Test-Hex8 {
    param([string]$Text)
    if ([string]::IsNullOrEmpty($Text) -or $Text.Length -ne 8) { return $false }
    foreach ($ch in $Text.ToCharArray()) {
        $digit = (($ch -ge '0') -and ($ch -le '9')) -or (($ch -ge 'a') -and ($ch -le 'f'))
        if (-not $digit) { return $false }
    }
    return $true
}

function Get-HexCode {
    param([string]$Text)
    if ([string]::IsNullOrEmpty($Text)) { return '' }
    $lower = $Text.ToLowerInvariant()
    $at = 0
    while ($at -lt $lower.Length) {
        $hit = $lower.IndexOf('0x', $at, $script:Ordinal)
        if ($hit -lt 0) { break }
        if (($hit + 10) -le $lower.Length) {
            $hex = $lower.Substring($hit + 2, 8)
            if (Test-Hex8 -Text $hex) { return $hex }
        }
        $at = $hit + 2
    }
    $start = 0
    while ($start -lt $lower.Length) {
        $hit = $lower.IndexOf('c000', $start, $script:Ordinal)
        if ($hit -lt 0) { break }
        if (($hit + 8) -le $lower.Length) {
            $hex = $lower.Substring($hit, 8)
            if (Test-Hex8 -Text $hex) { return $hex }
        }
        $start = $hit + 4
    }
    return ''
}

function Test-BucketModule {
    param([string]$Token)
    if ([string]::IsNullOrEmpty($Token)) { return $false }
    $lower = $Token.ToLowerInvariant()
    if ($lower.StartsWith('appcrash_', $script:Ordinal)) { return $true }
    if ($lower.StartsWith('apphang_', $script:Ordinal)) { return $true }
    if ($lower.StartsWith('critical_', $script:Ordinal)) { return $true }
    return $false
}

function Test-ModuleToken {
    param([string]$Token)
    if ([string]::IsNullOrEmpty($Token)) { return $false }
    if ($Token.IndexOf('\', $script:Ordinal) -ge 0) { return $false }
    if ($Token.IndexOf('/', $script:Ordinal) -ge 0) { return $false }
    if ($Token.IndexOf(' ', $script:Ordinal) -ge 0) { return $false }
    $lower = $Token.ToLowerInvariant()
    if (Test-BucketModule -Token $lower) { return $false }
    if ($lower.EndsWith('.dll', $script:Ordinal)) { return $true }
    if ($lower.EndsWith('.exe', $script:Ordinal)) { return $true }
    if ($lower.EndsWith('.xll', $script:Ordinal)) { return $true }
    return $false
}

function Get-LabelValue {
    param([string]$Text, [string]$Label)
    if ([string]::IsNullOrEmpty($Text) -or [string]::IsNullOrEmpty($Label)) { return '' }
    $at = $Text.IndexOf($Label, $script:OrdinalIgnore)
    if ($at -lt 0) { return '' }
    $rest = $Text.Substring($at + $Label.Length).TrimStart()
    $end = $rest.Length
    $comma = $rest.IndexOf(',', $script:Ordinal)
    $nl = $rest.IndexOf("`n", $script:Ordinal)
    if (($comma -ge 0) -and ($comma -lt $end)) { $end = $comma }
    if (($nl -ge 0) -and ($nl -lt $end)) { $end = $nl }
    if ($end -le 0) { return '' }
    return $rest.Substring(0, $end).Trim()
}

function Get-FaultModule {
    param([string]$Text, [string]$ModuleHint)
    $labeled = Get-LabelValue -Text $Text -Label 'Faulting module name:'
    if (Test-ModuleToken -Token $labeled) { return $labeled.ToLowerInvariant() }
    if ((Test-ModuleToken -Token $ModuleHint) -and -not [string]::Equals($ModuleHint, 'excel.exe', $script:OrdinalIgnore)) {
        return $ModuleHint.ToLowerInvariant()
    }
    $dll = ''
    $exe = ''
    foreach ($token in @(Get-ModuleTokens -Text $Text)) {
        $value = [string]$token
        if (Test-BucketModule -Token $value) { continue }
        if ($value.EndsWith('.dll', $script:Ordinal)) {
            if ($dll.Length -eq 0) { $dll = $value }
        } elseif (($value.EndsWith('.exe', $script:Ordinal)) -and -not [string]::Equals($value, 'excel.exe', $script:Ordinal)) {
            if ($exe.Length -eq 0) { $exe = $value }
        }
    }
    if ($dll.Length -gt 0) { return $dll }
    if ($exe.Length -gt 0) { return $exe }
    if (-not [string]::IsNullOrEmpty($Text) -and ($Text.IndexOf('EXCEL.EXE', $script:OrdinalIgnore) -ge 0)) { return 'excel.exe' }
    return 'unknown'
}

function Get-CrashKind {
    param([int]$EventId, [string]$Text)
    $lower = ''
    if (-not [string]::IsNullOrEmpty($Text)) { $lower = $Text.ToLowerInvariant() }
    if ($lower.IndexOf('apphang', $script:Ordinal) -ge 0) { return 'apphang' }
    if ($lower.IndexOf('critical_excel', $script:Ordinal) -ge 0) { return 'critical' }
    if (($EventId -eq 1000) -or ($lower.IndexOf('appcrash', $script:Ordinal) -ge 0)) { return 'appcrash' }
    return 'other'
}

function Get-CrashEventClass {
    param([int]$EventId, [string]$Text, [string]$ModuleHint, [string]$ExceptionHint)
    $workbook = '0'
    $xll = '0'
    if (-not [string]::IsNullOrEmpty($Text)) {
        if ($Text.IndexOf($script:Leaf, $script:OrdinalIgnore) -ge 0) { $workbook = '1' }
        if ($Text.IndexOf($script:XllLeaf, $script:OrdinalIgnore) -ge 0) { $xll = '1' }
        elseif ($Text.IndexOf($script:XllStem, $script:OrdinalIgnore) -ge 0) { $xll = '1' }
    }
    $exception = ''
    $hintText = [string]$ExceptionHint
    if (Test-Hex8 -Text $hintText.ToLowerInvariant()) { $exception = $hintText.ToLowerInvariant() }
    else {
        $hint = Get-HexCode -Text $hintText
        if ($hint.Length -eq 8) { $exception = $hint }
        else { $exception = Get-HexCode -Text $Text }
    }
    return (New-Object psobject -Property @{
        Kind = (Get-CrashKind -EventId $EventId -Text $Text)
        Module = (Get-FaultModule -Text $Text -ModuleHint $ModuleHint)
        Exception = $exception
        Workbook = $workbook
        Xll = $xll
    })
}

function Get-CrashLinkVerdict {
    param([int]$Count, [int]$WorkbookHits, [int]$XllHits)
    if ($Count -le 0) { return 'no_prior_crash' }
    if (($WorkbookHits -gt 0) -and ($XllHits -gt 0)) { return 'workbook_and_xll_named' }
    if ($WorkbookHits -gt 0) { return 'workbook_named' }
    if ($XllHits -gt 0) { return 'xll_named' }
    return 'no_direct_link'
}

function Get-CrashCausation {
    param([string]$Verdict)
    if ($Verdict -eq 'workbook_named') { return 'mentioned_in_crash_text' }
    if ($Verdict -eq 'xll_named') { return 'mentioned_in_crash_text' }
    if ($Verdict -eq 'workbook_and_xll_named') { return 'mentioned_in_crash_text' }
    return 'not_established'
}

function Get-CauseLimit {
    param([string]$FileRecovery, [string]$Verdict)
    $flags = New-Object System.Collections.Generic.List[string]
    if ($FileRecovery -eq 'unreadable') { [void]$flags.Add('package_not_ruled_out') }
    if ($Verdict -eq 'no_direct_link') { [void]$flags.Add('correlation_only') }
    if ($flags.Count -eq 0) { return 'none' }
    return [string]::Join(',', $flags.ToArray())
}

function Get-PackageFlagState {
    param([string]$Status, [string]$Element)
    $state = New-Object psobject -Property @{
        PackageXml = 'unreadable'
        FileRecovery = 'unreadable'
        CrashSave = 'unreadable'
        RepairLoad = 'unreadable'
        AutoRecover = 'unreadable'
        DataExtract = 'unreadable'
        Reason = 'scan_error'
    }
    if ($Status -eq 'missing') {
        $state.PackageXml = 'absent'
        $state.Reason = 'workbook_xml_missing'
        return $state
    }
    if ($Status -eq 'locked') {
        $state.PackageXml = 'locked'
        $state.Reason = 'zip_locked'
        return $state
    }
    if ($Status -eq 'absent') {
        $state.PackageXml = 'readable'
        $state.FileRecovery = '0'
        $state.CrashSave = 'absent'
        $state.RepairLoad = 'absent'
        $state.AutoRecover = 'absent'
        $state.DataExtract = 'absent'
        $state.Reason = 'parsed_without_file_recovery_pr'
        return $state
    }
    if ($Status -eq 'found') {
        $parsed = Get-PackageRecovery -Xml $Element
        $state.PackageXml = 'readable'
        $state.FileRecovery = [string]$parsed.Present
        $state.CrashSave = [string]$parsed.CrashSave
        $state.RepairLoad = [string]$parsed.RepairLoad
        $state.AutoRecover = [string]$parsed.AutoRecover
        $state.DataExtract = [string]$parsed.DataExtract
        $state.Reason = 'parsed_file_recovery_pr'
        return $state
    }
    if ($Status -eq 'incomplete') {
        $state.PackageXml = 'truncated'
        $state.Reason = 'scan_incomplete'
        return $state
    }
    if ($Status -eq 'cut_element') {
        $state.PackageXml = 'truncated'
        $state.Reason = 'cut_element'
        return $state
    }
    return $state
}

function Test-WorkbookPart {
    param([string]$Name)
    if ([string]::IsNullOrEmpty($Name)) { return $false }
    $norm = $Name.Replace('\', '/').ToLowerInvariant()
    if ($norm -eq 'xl/workbook.xml') { return $true }
    if ($norm.EndsWith('/workbook.xml', $script:Ordinal)) { return $true }
    return $false
}

function Join-BytePrefix {
    param([byte[]]$Left, [byte[]]$Right)
    $leftLen = 0
    $rightLen = 0
    if ($null -ne $Left) { $leftLen = $Left.Length }
    if ($null -ne $Right) { $rightLen = $Right.Length }
    $out = New-Object byte[] ($leftLen + $rightLen)
    if ($leftLen -gt 0) { [Buffer]::BlockCopy($Left, 0, $out, 0, $leftLen) }
    if ($rightLen -gt 0) { [Buffer]::BlockCopy($Right, 0, $out, $leftLen, $rightLen) }
    return ,$out
}

function New-MarkerScan {
    return (New-Object psobject -Property @{
        Element = ''
        Done = $false
        CarryText = ''
    })
}

function Add-MarkerBytes {
    param($Scan, [byte[]]$Chunk)
    if ($Scan.Done) { return }
    $carry = New-Object byte[] 0
    if (-not [string]::IsNullOrEmpty([string]$Scan.CarryText)) {
        $carry = [Convert]::FromBase64String([string]$Scan.CarryText)
    }
    $combined = Join-BytePrefix -Left $carry -Right $Chunk
    $needle = [Text.Encoding]::ASCII.GetBytes('fileRecoveryPr')
    $at = Find-PatternOffset -Hay $combined -Needle $needle -Start 0
    if ($at -lt 0) {
        $keep = $needle.Length - 1
        if ($combined.Length -le 0) { return }
        if ($combined.Length -gt $keep) {
            $tail = New-Object byte[] $keep
            [Buffer]::BlockCopy($combined, ($combined.Length - $keep), $tail, 0, $keep)
            $Scan.CarryText = [Convert]::ToBase64String($tail)
        } else {
            $Scan.CarryText = [Convert]::ToBase64String($combined)
        }
        return
    }
    $start = $at
    if (($at -gt 0) -and ($combined[$at - 1] -eq 60)) { $start = $at - 1 }
    $end = -1
    for ($i = $at; $i -lt $combined.Length; $i++) {
        if ($combined[$i] -eq 62) { $end = $i; break }
    }
    if ($end -lt 0) {
        $pendingLen = $combined.Length - $start
        if ($pendingLen -gt 500) { $pendingLen = 500 }
        $pending = New-Object byte[] $pendingLen
        [Buffer]::BlockCopy($combined, $start, $pending, 0, $pendingLen)
        $Scan.CarryText = [Convert]::ToBase64String($pending)
        $Scan.Element = 'pending'
        return
    }
    $len = ($end - $start) + 1
    if ($len -gt 500) { $len = 500 }
    $slice = New-Object byte[] $len
    [Buffer]::BlockCopy($combined, $start, $slice, 0, $len)
    $Scan.Element = [Text.Encoding]::UTF8.GetString($slice)
    $Scan.Done = $true
    $Scan.CarryText = ''
}

function Complete-MarkerScan {
    param($Scan, [bool]$Eof)
    if ($Scan.Done -and -not [string]::Equals([string]$Scan.Element, 'pending', $script:Ordinal)) { return 'found' }
    if (-not $Eof) { return 'incomplete' }
    if ([string]::Equals([string]$Scan.Element, 'pending', $script:Ordinal)) { return 'cut_element' }
    return 'absent'
}

function Convert-ReportText {
    param([byte[]]$Bytes)
    if ($null -eq $Bytes -or $Bytes.Length -lt 2) { return '' }
    if (($Bytes[0] -eq 255) -and ($Bytes[1] -eq 254)) {
        return [Text.Encoding]::Unicode.GetString($Bytes, 2, ($Bytes.Length - 2))
    }
    if (($Bytes.Length -ge 3) -and ($Bytes[0] -eq 239) -and ($Bytes[1] -eq 187) -and ($Bytes[2] -eq 191)) {
        return [Text.Encoding]::UTF8.GetString($Bytes, 3, ($Bytes.Length - 3))
    }
    $zeros = 0
    $sample = $Bytes.Length
    if ($sample -gt 200) { $sample = 200 }
    for ($i = 1; $i -lt $sample; $i = $i + 2) {
        if ($Bytes[$i] -eq 0) { $zeros = $zeros + 1 }
    }
    if ($zeros -gt 40) { return [Text.Encoding]::Unicode.GetString($Bytes) }
    return [Text.Encoding]::UTF8.GetString($Bytes)
}

function Assert-Case {
    param([string]$Name, [bool]$Ok)
    $script:CaseCount = $script:CaseCount + 1
    if (-not $Ok) { throw ('SELFTEST FAIL ' + $Name) }
}

function Invoke-DiagnoseSelfTest {
    $fullText = Get-CanonicalFullPath
    Assert-Case 'full_has_day' ($fullText.IndexOf([char]0x30C7, $script:Ordinal) -ge 0)
    Assert-Case 'token' ([string]::Equals($script:ConfirmToken, 'DIAGNOSE_CANONICAL_SERIOUS_ERROR_READONLY', $script:Ordinal))
    $blob = New-PrefixedUtf16 -Text $script:Leaf
    Assert-Case 'prefixed_pure' ((Get-BlobVerdict -Bytes $blob) -eq 'pure')
    $ascii = [Text.Encoding]::ASCII.GetBytes('\' + $script:Leaf)
    Assert-Case 'ascii_pure' ((Get-BlobVerdict -Bytes $ascii) -eq 'pure')
    $prefixedName = [Text.Encoding]::ASCII.GetBytes('XX' + $script:Leaf)
    Assert-Case 'prefix_none' ((Get-BlobVerdict -Bytes $prefixedName) -eq 'none')
    $onlyXll = New-PrefixedUtf16 -Text ($script:XllStem + '_64bit.xll')
    Assert-Case 'xll_only_none' ((Get-BlobVerdict -Bytes $onlyXll) -eq 'none')
    $mixed = New-PrefixedUtf16 -Text ($script:Leaf + ' C:\Other.xlsx')
    Assert-Case 'mixed_impure' ((Get-BlobVerdict -Bytes $mixed) -eq 'impure')
    $withDll = New-PrefixedUtf16 -Text ($script:Leaf + ' C:\Addin.dll')
    Assert-Case 'dll_impure' ((Get-BlobVerdict -Bytes $withDll) -eq 'impure')
    $office = New-OfficeDisabledItemBytes -Path $fullText -Description ''
    Assert-Case 'office_pure' ((Get-BlobVerdict -Bytes $office) -eq 'pure')
    $odd = New-OddUtf16 -Text $script:Leaf
    Assert-Case 'odd_impure' ((Get-BlobVerdict -Bytes $odd) -eq 'impure')
    $disabled = 'Software\Microsoft\Office\16.0\Excel\Resiliency\DisabledItems'
    $disabledChild = $disabled + '\1664DDA6'
    $crashing = $script:ResiliencyRoot + '\CrashingAddinList'
    $deep = 'Software\Microsoft\Office\16.0\Excel\Resiliency\DocumentRecovery\1664DDA6\Extra'
    $startup = $script:ResiliencyRoot + '\StartupItems'
    $hive = 'HKEY_CURRENT_USER\' + $disabled
    Assert-Case 'area_disabled' ((Get-RecoveryArea -Key $disabled) -eq 'disabled_items')
    Assert-Case 'area_child' ((Get-RecoveryArea -Key $disabledChild) -eq 'disabled_items')
    Assert-Case 'area_crash' ((Get-RecoveryArea -Key $crashing) -eq 'other')
    Assert-Case 'area_deep' ((Get-RecoveryArea -Key $deep) -eq 'other')
    Assert-Case 'area_startup' ((Get-RecoveryArea -Key $startup) -eq 'other')
    Assert-Case 'hive_strip' ([string]::Equals((ConvertTo-CanonicalRegistryPath -Key $hive), $disabled, $script:OrdinalIgnore))
    $pureRow = New-Object psobject -Property @{
        Key = $disabled
        ValueName = '1664DDA6'
        Sha = 'aaa'
        Verdict = 'pure'
        Area = 'disabled_items'
    }
    $noneRow = New-Object psobject -Property @{
        Key = $disabled
        ValueName = 'BBBBBBBB'
        Sha = 'bbb'
        Verdict = 'none'
        Area = 'disabled_items'
    }
    $otherRow = New-Object psobject -Property @{
        Key = $crashing
        ValueName = 'CCCC'
        Sha = 'ccc'
        Verdict = 'pure'
        Area = 'other'
    }
    $counts = Get-MatchCounts -Rows @($pureRow, $noneRow)
    Assert-Case 'match_pure' ($counts.Pure -eq 1)
    Assert-Case 'match_none' ($counts.None -eq 1)
    $outsideCounts = Get-MatchCounts -Rows @($otherRow)
    Assert-Case 'match_outside' ($outsideCounts.Outside -eq 1)
    Assert-Case 'match_outside_pure' ($outsideCounts.Pure -eq 0)
    $returned = Get-BackupCompareResult -BackupSha 'aaa' -BackupReadable $true -Rows @($pureRow)
    Assert-Case 'backup_returned' ($returned.State -eq 'returned')
    Assert-Case 'backup_returned_flag' ($returned.Recreated -eq '1')
    $stayed = Get-BackupCompareResult -BackupSha 'zzz' -BackupReadable $true -Rows @($noneRow)
    Assert-Case 'backup_stayed' ($stayed.State -eq 'stayed_clear')
    Assert-Case 'backup_stayed_flag' ($stayed.Recreated -eq '0')
    $created = Get-BackupCompareResult -BackupSha 'zzz' -BackupReadable $true -Rows @($pureRow)
    Assert-Case 'backup_new' ($created.State -eq 'new_record')
    Assert-Case 'backup_new_other' ($created.Other -eq '1')
    $both = Get-BackupCompareResult -BackupSha 'aaa' -BackupReadable $true -Rows @($pureRow, $otherRow)
    Assert-Case 'backup_both' ($both.State -eq 'same_and_other')
    $unread = Get-BackupCompareResult -BackupSha '' -BackupReadable $false -Rows @($pureRow)
    Assert-Case 'backup_unread_state' ($unread.State -eq 'backup_unreadable')
    Assert-Case 'backup_unread_other' ($unread.Other -eq '1')
    Assert-Case 'backup_unread_recreated' ($unread.Recreated -eq '0')
    $replaced = Get-ReplacementFlag -BackupKey $hive -BackupName '1664DDA6' -BackupSha 'old' -BackupReadable $true -Rows @($pureRow)
    Assert-Case 'replaced_yes' ($replaced -eq '1')
    $notReplaced = Get-ReplacementFlag -BackupKey $disabled -BackupName '1664DDA6' -BackupSha 'aaa' -BackupReadable $true -Rows @($pureRow)
    Assert-Case 'replaced_no' ($notReplaced -eq '0')
    Assert-Case 'replaced_unread' ((Get-ReplacementFlag -BackupKey $disabled -BackupName '1664DDA6' -BackupSha 'aaa' -BackupReadable $false -Rows @($pureRow)) -eq '0')
    Assert-Case 'touch_hidden' ((Get-UnexplainedKeyTouch -KeyWrite '1' -Recreated '1' -Other '0' -Replaced '0') -eq '0')
    Assert-Case 'touch_open' ((Get-UnexplainedKeyTouch -KeyWrite '1' -Recreated '0' -Other '0' -Replaced '0') -eq '1')
    Assert-Case 'primary_recreated' ((Get-DistinctionPrimary -Recreated '1' -Other '0' -Rewritten '0' -Crash '0' -KeyTouched '0' -Replaced '0') -eq 'resiliency_recreated')
    Assert-Case 'primary_other' ((Get-DistinctionPrimary -Recreated '0' -Other '1' -Rewritten '0' -Crash '0' -KeyTouched '0' -Replaced '0') -eq 'resiliency_other_match')
    Assert-Case 'primary_rewritten' ((Get-DistinctionPrimary -Recreated '0' -Other '0' -Rewritten '1' -Crash '0' -KeyTouched '0' -Replaced '0') -eq 'workbook_rewritten')
    Assert-Case 'primary_crash' ((Get-DistinctionPrimary -Recreated '0' -Other '0' -Rewritten '0' -Crash '1' -KeyTouched '0' -Replaced '0') -eq 'crash_after_launch')
    Assert-Case 'primary_touch' ((Get-DistinctionPrimary -Recreated '0' -Other '0' -Rewritten '0' -Crash '0' -KeyTouched '1' -Replaced '0') -eq 'resiliency_key_touched')
    Assert-Case 'primary_replaced' ((Get-DistinctionPrimary -Recreated '0' -Other '0' -Rewritten '0' -Crash '0' -KeyTouched '0' -Replaced '1') -eq 'resiliency_value_replaced')
    Assert-Case 'primary_multi' ((Get-DistinctionPrimary -Recreated '1' -Other '0' -Rewritten '0' -Crash '1' -KeyTouched '0' -Replaced '0') -eq 'multiple_signals')
    Assert-Case 'primary_none' ((Get-DistinctionPrimary -Recreated '0' -Other '0' -Rewritten '0' -Crash '0' -KeyTouched '0' -Replaced '0') -eq 'inconclusive')
    $xllReason = Get-DistinctionReason -Primary 'inconclusive' -Recreated '0' -Other '0' -Rewritten '0' -Crash '0' -Xll '1' -Dialog '1' -BackupState 'stayed_clear'
    Assert-Case 'reason_xll' ($xllReason -eq 'dialog_visible_xll_loaded_without_resiliency_crash_or_rewrite')
    Assert-Case 'reason_single' ((Get-DistinctionReason -Primary 'resiliency_recreated' -Recreated '1' -Other '0' -Rewritten '0' -Crash '0' -Xll '0' -Dialog '1' -BackupState 'returned') -eq 'single_signal')
    Assert-Case 'reason_multi' ((Get-DistinctionReason -Primary 'multiple_signals' -Recreated '1' -Other '0' -Rewritten '0' -Crash '1' -Xll '0' -Dialog '1' -BackupState 'returned') -eq 'multiple_signals')
    Assert-Case 'reason_backup' ((Get-DistinctionReason -Primary 'inconclusive' -Recreated 'unreadable' -Other '0' -Rewritten '0' -Crash '0' -Xll '0' -Dialog '0' -BackupState 'backup_unreadable') -eq 'backup_unreadable')
    Assert-Case 'reason_crash_only' ((Get-DistinctionReason -Primary 'inconclusive' -Recreated '0' -Other '0' -Rewritten '0' -Crash 'unreadable' -Xll '1' -Dialog '0' -BackupState 'stayed_clear') -eq 'crash_query_unreadable')
    $eventText = 'EXCEL.EXE|Microsoft.Office.Excel|ucrtbase.dll|c0000005'
    Assert-Case 'module_ucrt' (Test-TokenPresent -Text $eventText -Token 'ucrtbase.dll')
    Assert-Case 'module_excel' (Test-TokenPresent -Text $eventText -Token 'excel.exe')
    Assert-Case 'module_clean' (Test-TokensClean -Text $eventText)
    Assert-Case 'module_xll' (Test-TokenPresent -Text ('loaded ' + $script:XllLeaf + ' ok') -Token 'marketspeed2_rss_64bit.xll')
    $dialog = $script:Leaf + ' ' + $script:SeriousErrorJa + ' ' + $script:ReopenDocumentJa
    Assert-Case 'dialog_yes' (Test-SeriousErrorText -Text $dialog)
    Assert-Case 'dialog_no' (-not (Test-SeriousErrorText -Text 'hello'))
    Assert-Case 'write_after' (Test-WriteAfterStart -WriteTicks 20 -StartTicks 10 -WriteKnown $true -StartKnown $true)
    Assert-Case 'write_equal' (-not (Test-WriteAfterStart -WriteTicks 10 -StartTicks 10 -WriteKnown $true -StartKnown $true))
    Assert-Case 'write_unknown' (-not (Test-WriteAfterStart -WriteTicks 20 -StartTicks 10 -WriteKnown $true -StartKnown $false))
    Assert-Case 'aggregate_one' ((Get-AggregateFlag -Parts @('0', '1', '0')) -eq '1')
    Assert-Case 'aggregate_unread' ((Get-AggregateFlag -Parts @('0', 'unreadable')) -eq 'unreadable')
    Assert-Case 'aggregate_zero' ((Get-AggregateFlag -Parts @('0', '0')) -eq '0')
    Assert-Case 'crash_event' ((Combine-CrashFlag -EventFlag '1' -WerCount 0) -eq '1')
    Assert-Case 'crash_wer' ((Combine-CrashFlag -EventFlag '0' -WerCount 2) -eq '1')
    Assert-Case 'crash_none' ((Combine-CrashFlag -EventFlag '0' -WerCount 0) -eq '0')
    Assert-Case 'crash_unread' ((Combine-CrashFlag -EventFlag 'unreadable' -WerCount 0) -eq 'unreadable')
    Assert-Case 'crash_wer_ignored' ((Combine-CrashFlag -EventFlag '0' -WerCount -1) -eq '0')
    Assert-Case 'no_event_en' (Test-NoMatchingEventQuery -ErrorId '' -Message 'No events were found')
    Assert-Case 'no_event_id' (Test-NoMatchingEventQuery -ErrorId 'NoMatchingEventsFound,Microsoft.PowerShell.Commands.GetWinEventCommand' -Message 'x')
    $missingEvents = -join @([char]0x898B, [char]0x3064, [char]0x304B, [char]0x308A, [char]0x307E, [char]0x305B, [char]0x3093)
    Assert-Case 'no_event_ja' (Test-NoMatchingEventQuery -ErrorId 'Other' -Message ('prefix ' + $missingEvents))
    Assert-Case 'event_real' (-not (Test-NoMatchingEventQuery -ErrorId 'AccessDenied' -Message 'Access is denied'))
    $mainOnly = New-Object psobject -Property @{
        Pid = 43904
        OwnerPid = 0
        ParentPid = 0
        Class = 'XLMAIN'
        Title = 'Microsoft Excel'
        ChildText = 'Ribbon'
        Hwnd = [int64]11
        OwnerHwnd = [int64]0
        ParentHwnd = [int64]0
    }
    $ownedDialog = New-Object psobject -Property @{
        Pid = 5000
        OwnerPid = 43904
        ParentPid = 0
        Class = '#32770'
        Title = 'Microsoft Excel'
        ChildText = ($script:Leaf + ' ' + $script:SeriousErrorJa + ' ' + $script:ReopenDocumentJa)
        Hwnd = [int64]22
        OwnerHwnd = [int64]11
        ParentHwnd = [int64]0
    }
    $ownedHit = Select-DialogHit -FocusPid 43904 -Rows @($mainOnly, $ownedDialog)
    Assert-Case 'dialog_owner_visible' ($ownedHit.Visible -eq '1')
    Assert-Case 'dialog_owner_pid' ($ownedHit.Pid -eq 5000)
    Assert-Case 'dialog_owner_link' ($ownedHit.OwnerLinked -eq '1')
    Assert-Case 'dialog_owner_same' ($ownedHit.SameProcess -eq '0')
    Assert-Case 'dialog_owner_source' ($ownedHit.Source -eq 'child')
    Assert-Case 'dialog_owner_class' ($ownedHit.Class -eq '#32770')
    Assert-Case 'dialog_owner_match' ($ownedHit.Match -eq 'canonical_serious_error')
    $miss = Select-DialogHit -FocusPid 43904 -Rows @($mainOnly)
    Assert-Case 'dialog_main_miss' ($miss.Visible -eq '0')
    $mainNeedle = New-Object psobject -Property @{
        Pid = 43904
        OwnerPid = 0
        ParentPid = 0
        Class = 'XLMAIN'
        Title = 'Microsoft Excel'
        ChildText = ($script:Leaf + ' ' + $script:SeriousErrorJa)
        Hwnd = [int64]11
        OwnerHwnd = [int64]0
        ParentHwnd = [int64]0
    }
    $childDialog = New-Object psobject -Property @{
        Pid = 43904
        OwnerPid = 43904
        ParentPid = 43904
        Class = 'bosa_sdm_XL9'
        Title = ''
        ChildText = ($script:Leaf + ' ' + $script:SeriousErrorJa + ' ' + $script:ReopenDocumentJa)
        Hwnd = [int64]33
        OwnerHwnd = [int64]11
        ParentHwnd = [int64]11
    }
    $childHit = Select-DialogHit -FocusPid 43904 -Rows @($mainNeedle, $childDialog)
    Assert-Case 'dialog_child_visible' ($childHit.Visible -eq '1')
    Assert-Case 'dialog_child_class' ($childHit.Class -eq 'bosa_sdm_XL9')
    Assert-Case 'dialog_child_pid' ($childHit.Pid -eq 43904)
    Assert-Case 'dialog_child_source' ($childHit.Source -eq 'child')
    Assert-Case 'dialog_child_match' ($childHit.Match -eq 'canonical_serious_error')
    $xlmainRow = New-SurveyProbeRow -PidValue 43904 -OwnerPid 0 -ParentPid 0 -RootPid 43904 -Class 'XLMAIN' -Role 'toplevel' -Process 'EXCEL' -Needle 0
    $foreignDialog = New-SurveyProbeRow -PidValue 7000 -OwnerPid 0 -ParentPid 0 -RootPid 7000 -Class 'NUIDialog' -Role 'toplevel' -Process 'sdxhelper' -Needle 0
    $bosaRow = New-SurveyProbeRow -PidValue 8000 -OwnerPid 0 -ParentPid 0 -RootPid 8000 -Class 'bosa_sdm_XL9' -Role 'child' -Process 'EXCEL' -Needle 0
    $standardRow = New-SurveyProbeRow -PidValue 8001 -OwnerPid 0 -ParentPid 0 -RootPid 8001 -Class '#32770' -Role 'toplevel' -Process 'EXCEL' -Needle 0
    $netUiRow = New-SurveyProbeRow -PidValue 8002 -OwnerPid 0 -ParentPid 0 -RootPid 8002 -Class 'NetUIHWND' -Role 'child' -Process 'EXCEL' -Needle 0
    $frontRow = New-SurveyProbeRow -PidValue 9 -OwnerPid 0 -ParentPid 0 -RootPid 9 -Class 'Button' -Role 'foreground' -Process 'notepad' -Needle 0
    $guiRow = New-SurveyProbeRow -PidValue 9 -OwnerPid 0 -ParentPid 0 -RootPid 9 -Class 'Static' -Role 'guithread' -Process 'notepad' -Needle 0
    $noiseRow = New-SurveyProbeRow -PidValue 9 -OwnerPid 0 -ParentPid 0 -RootPid 9 -Class 'Static' -Role 'child' -Process 'notepad' -Needle 0
    $plainOwner = New-SurveyProbeRow -PidValue 9 -OwnerPid 0 -ParentPid 0 -RootPid 9 -Class 'Static' -Role 'owner' -Process 'notepad' -Needle 0
    $ownerRow = New-SurveyProbeRow -PidValue 9 -OwnerPid 43904 -ParentPid 0 -RootPid 9 -Class 'Button' -Role 'owner' -Process 'notepad' -Needle 0
    $rootRow = New-SurveyProbeRow -PidValue 9 -OwnerPid 0 -ParentPid 0 -RootPid 43904 -Class 'Button' -Role 'owner' -Process 'notepad' -Needle 0
    $officeRow = New-SurveyProbeRow -PidValue 12 -OwnerPid 0 -ParentPid 0 -RootPid 12 -Class 'Chrome_WidgetWin_1' -Role 'toplevel' -Process 'OfficeClickToRun' -Needle 0
    $needleRow = New-SurveyProbeRow -PidValue 9 -OwnerPid 0 -ParentPid 0 -RootPid 9 -Class 'Static' -Role 'child' -Process 'notepad' -Needle 1
    Assert-Case 'survey_xlmain' (Test-SurveyRowWanted -Row $xlmainRow -FocusPid 43904)
    Assert-Case 'survey_nuidialog' (Test-SurveyRowWanted -Row $foreignDialog -FocusPid 43904)
    Assert-Case 'survey_bosa' (Test-SurveyRowWanted -Row $bosaRow -FocusPid 43904)
    Assert-Case 'survey_32770' (Test-SurveyRowWanted -Row $standardRow -FocusPid 43904)
    Assert-Case 'survey_netui' (Test-SurveyRowWanted -Row $netUiRow -FocusPid 43904)
    Assert-Case 'survey_foreground' (Test-SurveyRowWanted -Row $frontRow -FocusPid 43904)
    Assert-Case 'survey_guithread' (Test-SurveyRowWanted -Row $guiRow -FocusPid 43904)
    Assert-Case 'survey_noise' (-not (Test-SurveyRowWanted -Row $noiseRow -FocusPid 43904))
    Assert-Case 'survey_owner_role' (Test-SurveyRowWanted -Row $plainOwner -FocusPid 43904)
    Assert-Case 'survey_owner' (Test-SurveyRowWanted -Row $ownerRow -FocusPid 43904)
    Assert-Case 'survey_root' (Test-SurveyRowWanted -Row $rootRow -FocusPid 43904)
    Assert-Case 'survey_office' (Test-SurveyRowWanted -Row $officeRow -FocusPid 43904)
    Assert-Case 'survey_needle' (Test-SurveyRowWanted -Row $needleRow -FocusPid 43904)
    $ownerPattern = Get-TouchScope -RootFlag '1' -ChildFlags @('0', '0') -RootValueCount 0
    Assert-Case 'touch_parent_only' ($ownerPattern -eq 'parent_touch_without_surviving_value')
    $rootValues = Get-TouchScope -RootFlag '1' -ChildFlags @('0', '0') -RootValueCount 2
    Assert-Case 'touch_root_values' ($rootValues -eq 'root_values_present')
    $childTouch = Get-TouchScope -RootFlag '1' -ChildFlags @('1', '0') -RootValueCount 2
    Assert-Case 'touch_child_key' ($childTouch -eq 'child_key_write')
    $noTouch = Get-TouchScope -RootFlag '0' -ChildFlags @('0') -RootValueCount 4
    Assert-Case 'touch_none' ($noTouch -eq 'no_touch')
    $unreadTouch = Get-TouchScope -RootFlag '1' -ChildFlags @('unreadable') -RootValueCount 0
    Assert-Case 'touch_unread' ($unreadTouch -eq 'unreadable')
    $rootOnlyRow = New-Object psobject -Property @{ Key = $script:ResiliencyRoot; ValueName = 'StartupCheck'; Kind = 'Binary'; Length = 4; Sha = 'abc'; Verdict = 'none'; HasXll = '0' }
    $childOnlyRow = New-Object psobject -Property @{ Key = ($script:ResiliencyRoot + '\DisabledItems'); ValueName = '1664DDA6'; Kind = 'Binary'; Length = 8; Sha = 'def'; Verdict = 'none'; HasXll = '0' }
    $rootHits = @(Get-RootValueRows -Rows @($rootOnlyRow, $childOnlyRow))
    Assert-Case 'root_value_count' ($rootHits.Count -eq 1)
    Assert-Case 'subkey_value_count' ((Get-SubkeyValueCount -SubName 'DisabledItems' -Rows @($rootOnlyRow, $childOnlyRow)) -eq 1)
    $delay = Get-TouchDelaySeconds -StartUtc '2026-10-03T02:22:51Z' -WriteUtc '2026-10-03T02:22:54Z'
    Assert-Case 'touch_delay' ([int]$delay.Seconds -eq 3)
    Assert-Case 'touch_after' ([string]$delay.Correlation -eq 'after_excel_start')
    $before = Get-TouchDelaySeconds -StartUtc '2026-10-03T02:22:51Z' -WriteUtc '2026-10-02T14:09:01Z'
    Assert-Case 'touch_before' ([string]$before.Correlation -eq 'before_excel_start')
    Assert-Case 'label_hex' ((Get-SafeLabel -Name '1664DDA6') -eq '1664DDA6')
    Assert-Case 'label_path' ((Get-SafeLabel -Name 'C:\Secret.xlsx') -eq 'len_14')
    $root = Get-BackupRoot
    $stamp = $root + '\20261003T012345Z'
    Assert-Case 'backup_jail' (Test-BackupDirAllowed -Root $root -Candidate $stamp)
    Assert-Case 'backup_jail_dot' (-not (Test-BackupDirAllowed -Root $root -Candidate ($root + '\..\x')))
    $crashXml = '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fileRecoveryPr autoRecover="1" crashSave="1"/></workbook>'
    $crashPkg = Get-PackageRecovery -Xml $crashXml
    Assert-Case 'pkg_crash_present' ([string]$crashPkg.Present -eq '1')
    Assert-Case 'pkg_crash_save' ([string]$crashPkg.CrashSave -eq '1')
    Assert-Case 'pkg_crash_repair_absent' ([string]$crashPkg.RepairLoad -eq 'absent')
    $prefixedXml = '<workbook><x:fileRecoveryPr repairLoad="true" dataExtractLoad="false"/></workbook>'
    $repairPkg = Get-PackageRecovery -Xml $prefixedXml
    Assert-Case 'pkg_prefix_repair' ([string]$repairPkg.RepairLoad -eq '1')
    Assert-Case 'pkg_prefix_extract' ([string]$repairPkg.DataExtract -eq '0')
    $bareXml = '<fileRecoveryPr crashSave=0 repairLoad=1 autoRecover="0"/>'
    $barePkg = Get-PackageRecovery -Xml $bareXml
    Assert-Case 'pkg_bare_crash' ([string]$barePkg.CrashSave -eq '0')
    Assert-Case 'pkg_bare_repair' ([string]$barePkg.RepairLoad -eq '1')
    Assert-Case 'pkg_bare_auto' ([string]$barePkg.AutoRecover -eq '0')
    $cleanPkg = Get-PackageRecovery -Xml '<workbook><workbookPr/></workbook>'
    Assert-Case 'pkg_clean' ([string]$cleanPkg.Present -eq '0')
    Assert-Case 'pkg_clean_crash' ([string]$cleanPkg.CrashSave -eq 'absent')
    Assert-Case 'part_revision' (Test-PackagePartName -Name 'xl/revisions/revisionHeaders.xml')
    Assert-Case 'part_sheet' (-not (Test-PackagePartName -Name 'xl/worksheets/sheet1.xml'))
    $bookSample = 'C:\Desk\files\' + $script:Leaf
    $lockPath = Get-OwnerLockPath -WorkbookPath $bookSample
    Assert-Case 'lock_path' ($lockPath.EndsWith('\~$' + $script:Leaf, $script:Ordinal))
    $xlkPath = Get-XlkPath -WorkbookPath $bookSample
    Assert-Case 'xlk_path' ($xlkPath.EndsWith('\Kioxia_MS2_RSS_Live_Signals.xlk', $script:Ordinal))
    $beforeFile = Get-FileRelation -Exists $true -WriteTicks 10 -WriteKnown $true -StartTicks 20 -StartKnown $true
    Assert-Case 'file_before' ([string]$beforeFile.Relation -eq 'before_excel_start')
    $afterFile = Get-FileRelation -Exists $true -WriteTicks 30 -WriteKnown $true -StartTicks 20 -StartKnown $true
    Assert-Case 'file_after' ([string]$afterFile.Relation -eq 'after_excel_start')
    $missingFile = Get-FileRelation -Exists $false -WriteTicks 0 -WriteKnown $false -StartTicks 20 -StartKnown $true
    Assert-Case 'file_absent' ([string]$missingFile.Relation -eq 'absent')
    Assert-Case 'open_rss' ((Get-OpenXllClass -Name 'OPEN1' -Text ('C:\rss\' + $script:XllLeaf)) -eq 'rss')
    Assert-Case 'open_other' ((Get-OpenXllClass -Name 'OPEN' -Text 'C:\Other.xll') -eq 'other')
    Assert-Case 'open_plain' ((Get-OpenXllClass -Name 'OPEN2' -Text 'C:\Book.xlsx') -eq 'plain')
    Assert-Case 'open_skip' ((Get-OpenXllClass -Name 'AlertIfNotExcel' -Text $script:XllLeaf) -eq 'skip')
    Assert-Case 'token_xll' (Test-TokenHasXll -Tokens 'ucrtbase.dll,marketspeed2_rss_64bit.xll')
    Assert-Case 'token_no_xll' (-not (Test-TokenHasXll -Tokens 'ucrtbase.dll,excel.exe'))
    $causeCrash = Get-CauseClass -CrashSave '1' -RepairLoad '0' -DataExtract '0' -FileRecovery '1' -PackageOpen 'readable' -PriorState 'ok' -PriorCount 2 -PriorXll '1' -LockBefore '1' -XlkExists '0' -DialogVisible '1'
    Assert-Case 'cause_crash_save' ([string]$causeCrash.Cause -eq 'workbook_crash_save')
    Assert-Case 'cause_crash_flags' (([string]$causeCrash.Flags).IndexOf('prior_crash_with_xll', $script:Ordinal) -ge 0)
    $causePrior = Get-CauseClass -CrashSave 'absent' -RepairLoad 'absent' -DataExtract 'absent' -FileRecovery '0' -PackageOpen 'readable' -PriorState 'ok' -PriorCount 3 -PriorXll '1' -LockBefore '0' -XlkExists '0' -DialogVisible '1'
    Assert-Case 'cause_prior_xll' ([string]$causePrior.Cause -eq 'prior_crash_with_xll')
    $causeLock = Get-CauseClass -CrashSave 'absent' -RepairLoad 'absent' -DataExtract 'absent' -FileRecovery '0' -PackageOpen 'readable' -PriorState 'ok' -PriorCount 0 -PriorXll '0' -LockBefore '1' -XlkExists '0' -DialogVisible '1'
    Assert-Case 'cause_lock' ([string]$causeLock.Cause -eq 'stale_owner_lockfile')
    $causeClear = Get-CauseClass -CrashSave 'absent' -RepairLoad 'absent' -DataExtract 'absent' -FileRecovery '0' -PackageOpen 'readable' -PriorState 'ok' -PriorCount 0 -PriorXll '0' -LockBefore '0' -XlkExists '0' -DialogVisible '1'
    Assert-Case 'cause_clear' ([string]$causeClear.Cause -eq 'dialog_without_package_or_resiliency_marker')
    $causeUnread = Get-CauseClass -CrashSave 'unreadable' -RepairLoad 'unreadable' -DataExtract 'unreadable' -FileRecovery 'unreadable' -PackageOpen 'locked' -PriorState 'ok' -PriorCount 0 -PriorXll '0' -LockBefore '0' -XlkExists '0' -DialogVisible '1'
    Assert-Case 'cause_unread' ([string]$causeUnread.Cause -eq 'evidence_incomplete')
    $parsedAbsent = Get-PackageFlagState -Status 'absent' -Element ''
    Assert-Case 'pkg_absent_save' ([string]$parsedAbsent.CrashSave -eq 'absent')
    Assert-Case 'pkg_absent_reason' ([string]$parsedAbsent.Reason -eq 'parsed_without_file_recovery_pr')
    $parsedCut = Get-PackageFlagState -Status 'incomplete' -Element ''
    Assert-Case 'pkg_cut_save' ([string]$parsedCut.CrashSave -eq 'unreadable')
    Assert-Case 'pkg_cut_recovery' ([string]$parsedCut.FileRecovery -eq 'unreadable')
    Assert-Case 'pkg_cut_reason' ([string]$parsedCut.Reason -eq 'scan_incomplete')
    $scan = New-MarkerScan
    Add-MarkerBytes -Scan $scan -Chunk ([Text.Encoding]::ASCII.GetBytes('<fileRecove'))
    Add-MarkerBytes -Scan $scan -Chunk ([Text.Encoding]::ASCII.GetBytes('ryPr crashSave="1"/>'))
    Assert-Case 'marker_split' ((Complete-MarkerScan -Scan $scan -Eof $true) -eq 'found')
    $splitPkg = Get-PackageRecovery -Xml ([string]$scan.Element)
    Assert-Case 'marker_split_save' ([string]$splitPkg.CrashSave -eq '1')
    $tailScan = New-MarkerScan
    $pad = New-Object byte[] 4000
    for ($i = 0; $i -lt $pad.Length; $i++) { $pad[$i] = 120 }
    Add-MarkerBytes -Scan $tailScan -Chunk $pad
    Add-MarkerBytes -Scan $tailScan -Chunk ([Text.Encoding]::ASCII.GetBytes('<fileRecoveryPr repairLoad="0"/>'))
    $tailState = Get-PackageFlagState -Status (Complete-MarkerScan -Scan $tailScan -Eof $true) -Element ([string]$tailScan.Element)
    Assert-Case 'marker_tail_reason' ([string]$tailState.Reason -eq 'parsed_file_recovery_pr')
    Assert-Case 'marker_tail_repair' ([string]$tailState.RepairLoad -eq '0')
    Assert-Case 'marker_tail_save' ([string]$tailState.CrashSave -eq 'absent')
    $plainCrash = Get-CrashEventClass -EventId 1000 -Text 'Faulting application name: EXCEL.EXE, Faulting module name: ucrtbase.dll, Exception code: 0xc0000005' -ModuleHint '' -ExceptionHint ''
    Assert-Case 'crash_kind' ([string]$plainCrash.Kind -eq 'appcrash')
    Assert-Case 'crash_module' ([string]$plainCrash.Module -eq 'ucrtbase.dll')
    Assert-Case 'crash_code' ([string]$plainCrash.Exception -eq 'c0000005')
    Assert-Case 'crash_book' ([string]$plainCrash.Workbook -eq '0')
    Assert-Case 'crash_xll' ([string]$plainCrash.Xll -eq '0')
    $bucketCrash = Get-CrashEventClass -EventId 1001 -Text 'appcrash_excel.exe excel.exe combase.dll' -ModuleHint '' -ExceptionHint ''
    Assert-Case 'crash_bucket_module' ([string]$bucketCrash.Module -eq 'combase.dll')
    $hangCrash = Get-CrashEventClass -EventId 1001 -Text 'AppHang_EXCEL.EXE excel.exe ntdll.dll' -ModuleHint '' -ExceptionHint ''
    Assert-Case 'crash_hang' ([string]$hangCrash.Kind -eq 'apphang')
    $namedCrash = Get-CrashEventClass -EventId 1000 -Text ($script:Leaf + ' EXCEL.EXE ucrtbase.dll') -ModuleHint 'ucrtbase.dll' -ExceptionHint 'c0000005'
    Assert-Case 'crash_named_book' ([string]$namedCrash.Workbook -eq '1')
    $xllCrash = Get-CrashEventClass -EventId 1000 -Text ($script:XllLeaf + ' EXCEL.EXE ucrtbase.dll') -ModuleHint '' -ExceptionHint ''
    Assert-Case 'crash_named_xll' ([string]$xllCrash.Xll -eq '1')
    Assert-Case 'link_none' ((Get-CrashLinkVerdict -Count 13 -WorkbookHits 0 -XllHits 0) -eq 'no_direct_link')
    Assert-Case 'link_book' ((Get-CrashLinkVerdict -Count 13 -WorkbookHits 1 -XllHits 0) -eq 'workbook_named')
    Assert-Case 'cause_not' ((Get-CrashCausation -Verdict 'no_direct_link') -eq 'not_established')
    Assert-Case 'cause_mentioned' ((Get-CrashCausation -Verdict 'workbook_named') -eq 'mentioned_in_crash_text')
    $ownerLimit = Get-CauseLimit -FileRecovery 'unreadable' -Verdict 'no_direct_link'
    Assert-Case 'limit_owner' ($ownerLimit -eq 'package_not_ruled_out,correlation_only')
    Assert-Case 'limit_corr' ((Get-CauseLimit -FileRecovery '0' -Verdict 'no_direct_link') -eq 'correlation_only')
    $utf = New-Object byte[] 2
    $utf[0] = 255
    $utf[1] = 254
    $body = [Text.Encoding]::Unicode.GetBytes('EXCEL.EXE ' + $script:Leaf)
    $withBom = Join-BytePrefix -Left $utf -Right $body
    $reportText = Convert-ReportText -Bytes $withBom
    Assert-Case 'wer_leaf' ($reportText.IndexOf($script:Leaf, $script:Ordinal) -ge 0)
    $partLabel = Get-PartLabel -Name 'xl/revisions/revisionHeaders.xml'
    Assert-Case 'part_label' ($partLabel -eq 'xl/revisions/revisionHeaders.xml')
    Write-Output 'ACTION=diagnose_canonical_serious_error_readonly'
    Write-Output 'READ_ONLY=1'
    Write-Output 'ROT_QUERIED=0'
    Write-Output 'PROOF primary=resiliency_recreated'
    Write-Output 'PROOF primary=resiliency_other_match'
    Write-Output 'PROOF primary=workbook_rewritten'
    Write-Output 'PROOF primary=crash_after_launch'
    Write-Output 'PROOF primary=resiliency_key_touched'
    Write-Output 'PROOF primary=resiliency_value_replaced'
    Write-Output 'PROOF primary=multiple_signals'
    Write-Output 'PROOF primary=inconclusive'
    Write-Output 'PROOF module=ucrtbase.dll'
    Write-Output 'PROOF dialog_needle=1'
    Write-Output 'PROOF dialog_owner=1'
    Write-Output 'PROOF dialog_child=1'
    Write-Output 'PROOF survey_owner=1'
    Write-Output 'PROOF touch=parent_touch_without_surviving_value'
    Write-Output 'PROOF touch=root_values_present'
    Write-Output 'PROOF touch_delay=3'
    Write-Output 'PROOF cause=workbook_crash_save'
    Write-Output 'PROOF cause=prior_crash_with_xll'
    Write-Output 'PROOF cause=dialog_without_package_or_resiliency_marker'
    Write-Output 'PROOF crash_link=no_direct_link'
    Write-Output 'PROOF crash_causation=not_established'
    Write-Output 'PROOF reason=crash_query_unreadable'
    Write-Output 'PROOF backup=returned'
    Write-Output 'PROOF backup=stayed_clear'
    Write-Output 'PROOF backup=new_record'
    Write-Output 'PROOF backup=same_and_other'
    Write-Output 'PROOF backup=backup_unreadable'
    Write-Output 'PROOF area=disabled_items'
    Write-Output 'PROOF verdict=pure'
    Write-Output 'PROOF verdict=none'
    Write-Output ('PROOF reason=' + $xllReason)
    Write-Output ('CASE_COUNT=' + $script:CaseCount.ToString())
    Write-Output 'SELFTEST PASS'
    Write-Output 'NOTHING_TOUCHED=1'
    Write-Output 'REGISTRY_CHANGED=0'
    Write-Output 'EXCEL_PROCESSES_TOUCHED=0'
    Write-Output 'WORKBOOK_CHANGED=0'
    Write-Output 'XLL_CHANGED=0'
    Write-Output 'DIALOG_TOUCHED=0'
}

function Write-Refused {
    param([string]$Reason)
    Write-Output 'ACTION=diagnose_canonical_serious_error_readonly'
    Write-Output 'READ_ONLY=1'
    Write-Output 'ROT_QUERIED=0'
    Write-Output 'NOTHING_TOUCHED=1'
    Write-Output ('REASON=' + $Reason)
    Write-Output 'REGISTRY_CHANGED=0'
    Write-Output 'EXCEL_PROCESSES_TOUCHED=0'
    Write-Output 'WORKBOOK_CHANGED=0'
    Write-Output 'XLL_CHANGED=0'
    Write-Output 'DIALOG_TOUCHED=0'
}

function Get-KindName {
    param($Kind)
    $binaryKind = [Microsoft.Win32.RegistryValueKind]::Binary
    $stringKind = [Microsoft.Win32.RegistryValueKind]::String
    $expandKind = [Microsoft.Win32.RegistryValueKind]::ExpandString
    $multiKind = [Microsoft.Win32.RegistryValueKind]::MultiString
    $dwordKind = [Microsoft.Win32.RegistryValueKind]::DWord
    $qwordKind = [Microsoft.Win32.RegistryValueKind]::QWord
    $noneKind = [Microsoft.Win32.RegistryValueKind]::None
    if ($Kind -eq $binaryKind) { return 'Binary' }
    if ($Kind -eq $stringKind) { return 'String' }
    if ($Kind -eq $expandKind) { return 'ExpandString' }
    if ($Kind -eq $multiKind) { return 'MultiString' }
    if (($Kind -eq $dwordKind) -or ($Kind -eq $qwordKind) -or ($Kind -eq $noneKind)) { return 'Skip' }
    return ''
}

function Read-KindBytes {
    param($Opened, [string]$Name, [string]$KindName)
    $doNotExpand = [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames
    if ($KindName -eq 'Binary') {
        $raw = $Opened.GetValue($Name)
        if ($raw -isnot [byte[]]) { return $null }
        $copy = New-Object byte[] $raw.Length
        [Buffer]::BlockCopy($raw, 0, $copy, 0, $raw.Length)
        return (New-Object psobject -Property @{ Bytes = $copy; Text = '' })
    }
    if (($KindName -eq 'String') -or ($KindName -eq 'ExpandString')) {
        $text = [string]$Opened.GetValue($Name, '', $doNotExpand)
        $copy = [Text.Encoding]::Unicode.GetBytes($text)
        return (New-Object psobject -Property @{ Bytes = $copy; Text = $text })
    }
    if ($KindName -eq 'MultiString') {
        $parts = @($Opened.GetValue($Name))
        $text = [string]::Join("`n", $parts)
        $copy = [Text.Encoding]::Unicode.GetBytes($text)
        return (New-Object psobject -Property @{ Bytes = $copy; Text = $text })
    }
    return $null
}

function Add-LiveValues {
    param($Opened, $List, $State, [int]$Depth)
    if ($null -eq $Opened) { return }
    if ($Depth -gt 8) { return }
    if ($List.Count -ge 500) { $State.Cap = '1'; return }
    $canon = ConvertTo-CanonicalRegistryPath -Key ([string]$Opened.Name)
    $area = Get-RecoveryArea -Key $canon
    $names = $Opened.GetValueNames()
    if ($null -eq $names) { $names = @() }
    foreach ($name in $names) {
        if ($List.Count -ge 500) { $State.Cap = '1'; return }
        try {
            $kindName = Get-KindName -Kind ($Opened.GetValueKind([string]$name))
            if ($kindName -eq 'Skip') { continue }
            if ([string]::IsNullOrEmpty($kindName)) {
                $State.Unsupported = $State.Unsupported + 1
                continue
            }
            $packed = Read-KindBytes -Opened $Opened -Name ([string]$name) -KindName $kindName
            if ($null -eq $packed) {
                $State.Unsupported = $State.Unsupported + 1
                continue
            }
            $bytes = $packed.Bytes
            $sha = Get-Sha256Hex -Bytes $bytes
            $verdict = Get-BlobVerdict -Bytes $bytes
            $hasXll = '0'
            if (Test-BlobHasXllStem -Bytes $bytes) { $hasXll = '1' }
            $row = New-Object psobject -Property @{
                Key = $canon
                ValueName = [string]$name
                Kind = $kindName
                Length = [int]$bytes.Length
                Sha = $sha
                Verdict = $verdict
                Area = $area
                HasXll = $hasXll
            }
            [void]$List.Add($row)
        } catch {
            $State.Unsupported = $State.Unsupported + 1
        }
    }
    $subs = $Opened.GetSubKeyNames()
    if ($null -eq $subs) { return }
    foreach ($sub in $subs) {
        if ($List.Count -ge 500) { $State.Cap = '1'; return }
        $subName = [string]$sub
        if ($subName.IndexOf('\', $script:Ordinal) -ge 0) { continue }
        if ($subName.IndexOf('/', $script:Ordinal) -ge 0) { continue }
        if ($subName.IndexOf('..', $script:Ordinal) -ge 0) { continue }
        $child = $null
        try {
            $child = $Opened.OpenSubKey($subName, $false)
            if ($null -ne $child) {
                Add-LiveValues -Opened $child -List $List -State $State -Depth ($Depth + 1)
            }
        } catch {
            $State.Unsupported = $State.Unsupported + 1
        } finally {
            if ($null -ne $child) { $child.Close() }
        }
    }
}

function Read-ResiliencySnapshot {
    $list = New-Object System.Collections.Generic.List[object]
    $subNames = New-Object System.Collections.Generic.List[string]
    $state = New-Object psobject -Property @{ Unsupported = 0; Cap = '0' }
    $absent = '0'
    $opened = $null
    try {
        $opened = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($script:ResiliencyRoot, $false)
        if ($null -eq $opened) {
            $absent = '1'
        } else {
            $subs = $opened.GetSubKeyNames()
            if ($null -ne $subs) {
                foreach ($sub in $subs) { [void]$subNames.Add([string]$sub) }
            }
            Add-LiveValues -Opened $opened -List $list -State $state -Depth 0
        }
    } finally {
        if ($null -ne $opened) { $opened.Close() }
    }
    return (New-Object psobject -Property @{
        Absent = $absent
        Rows = $list.ToArray()
        Subkeys = $subNames.ToArray()
        Unsupported = $state.Unsupported
        Cap = $state.Cap
    })
}

function Get-KeyWriteFlag {
    param([string]$Relative, [long]$StartTicks, [bool]$StartKnown)
    $leaf = $Relative
    $cut = $Relative.LastIndexOf('\')
    if (($cut -ge 0) -and ($cut -lt ($Relative.Length - 1))) { $leaf = $Relative.Substring($cut + 1) }
    $flag = 'unreadable'
    $writeUtc = ''
    try {
        Add-CanonicalWindowType
        $ticks = [int64][CanonicalRegistryStamp]::LastWriteUtcTicks($Relative)
        if ($ticks -gt 0) {
            $writeUtc = [DateTime]::new($ticks, [DateTimeKind]::Utc).ToString('yyyy-MM-ddTHH:mm:ss') + 'Z'
            if (-not $StartKnown) { $flag = '0' }
            elseif (Test-WriteAfterStart -WriteTicks $ticks -StartTicks $StartTicks -WriteKnown $true -StartKnown $true) { $flag = '1' }
            else { $flag = '0' }
        }
    } catch {
        $flag = 'unreadable'
    }
    return (New-Object psobject -Property @{
        Name = (Get-SafeLabel -Name $leaf)
        Flag = $flag
        WriteUtc = $writeUtc
    })
}

function Get-TouchScope {
    param([string]$RootFlag, $ChildFlags, [int]$RootValueCount)
    if ($RootFlag -eq 'unreadable') { return 'unreadable' }
    $childUnread = $false
    $childWrite = $false
    foreach ($flag in @(Get-FlatRows -Rows $ChildFlags)) {
        $value = [string]$flag
        if ($value -eq '1') { $childWrite = $true }
        elseif ($value -eq 'unreadable') { $childUnread = $true }
    }
    if ($childUnread -and -not $childWrite) { return 'unreadable' }
    if ($childWrite) { return 'child_key_write' }
    if ($RootFlag -eq '1' -and $RootValueCount -gt 0) { return 'root_values_present' }
    if ($RootFlag -eq '1') { return 'parent_touch_without_surviving_value' }
    return 'no_touch'
}

function Get-RootValueRows {
    param($Rows)
    $list = New-Object System.Collections.Generic.List[object]
    foreach ($row in @(Get-FlatRows -Rows $Rows)) {
        if ($null -eq $row) { continue }
        if ([string]::Equals([string]$row.Key, $script:ResiliencyRoot, $script:OrdinalIgnore)) {
            [void]$list.Add($row)
        }
    }
    return $list.ToArray()
}

function Get-SubkeyValueCount {
    param([string]$SubName, $Rows)
    $prefix = $script:ResiliencyRoot + '\' + $SubName
    $count = 0
    foreach ($row in @(Get-FlatRows -Rows $Rows)) {
        if ($null -eq $row) { continue }
        $key = [string]$row.Key
        if ([string]::Equals($key, $prefix, $script:OrdinalIgnore)) { $count = $count + 1; continue }
        $childPrefix = $prefix + '\'
        if ($key.StartsWith($childPrefix, $script:OrdinalIgnore)) { $count = $count + 1 }
    }
    return $count
}

function Convert-UtcStamp {
    param([string]$Text)
    if ([string]::IsNullOrEmpty($Text)) { return $null }
    $core = $Text
    if ($core.EndsWith('Z', $script:Ordinal) -and $core.Length -gt 1) {
        $core = $core.Substring(0, $core.Length - 1)
    }
    $styles = [Globalization.DateTimeStyles]::AssumeUniversal
    $culture = [Globalization.CultureInfo]::InvariantCulture
    return [DateTime]::ParseExact($core, 'yyyy-MM-ddTHH:mm:ss', $culture, $styles)
}

function Get-TouchDelaySeconds {
    param([string]$StartUtc, [string]$WriteUtc)
    $info = New-Object psobject -Property @{ Seconds = -1; Correlation = 'unreadable' }
    if ([string]::IsNullOrEmpty($StartUtc) -or [string]::IsNullOrEmpty($WriteUtc)) { return $info }
    try {
        $start = Convert-UtcStamp -Text $StartUtc
        $write = Convert-UtcStamp -Text $WriteUtc
        if ($null -eq $start -or $null -eq $write) { return $info }
        $delta = [int][Math]::Floor(($write - $start).TotalSeconds)
        $info.Seconds = $delta
        if ($delta -ge 0) { $info.Correlation = 'after_excel_start' }
        else { $info.Correlation = 'before_excel_start' }
    } catch {
        $info.Seconds = -1
        $info.Correlation = 'unreadable'
    }
    return $info
}

function Find-WorkbookPath {
    $direct = Get-CanonicalFullPath
    if ([IO.File]::Exists($direct)) { return $direct }
    $day = -join @([char]0x30C7, [char]0x30A4, [char]0x30C8, [char]0x30EC)
    $roots = New-Object System.Collections.Generic.List[string]
    try { [void]$roots.Add([string][Environment]::GetFolderPath('Desktop')) } catch {}
    $profile = ''
    try { $profile = [string]$env:USERPROFILE } catch { $profile = '' }
    if (-not [string]::IsNullOrWhiteSpace($profile)) {
        [void]$roots.Add($profile + '\Desktop')
        [void]$roots.Add($profile + '\OneDrive\Desktop')
    }
    foreach ($root in $roots) {
        if ([string]::IsNullOrWhiteSpace([string]$root)) { continue }
        $candidate = [string]$root + '\' + $day + '\MarketSpeed II RSS\files\' + $script:Leaf
        if ([IO.File]::Exists($candidate)) { return $candidate }
    }
    return $direct
}

function Read-ZoneMarker {
    param([string]$Path)
    $ads = $Path + ':Zone.Identifier'
    $stream = $null
    try {
        $stream = [IO.File]::Open($ads, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
        $reader = New-Object IO.StreamReader($stream)
        $text = $reader.ReadToEnd()
        $reader.Close()
        $marker = 'ZoneId='
        $at = $text.IndexOf($marker, $script:Ordinal)
        if ($at -lt 0) { return 'present' }
        $rest = $text.Substring($at + $marker.Length)
        $digits = ''
        foreach ($ch in $rest.ToCharArray()) {
            if ($ch -ge '0' -and $ch -le '9') { $digits = $digits + $ch }
            else { break }
        }
        if ($digits.Length -gt 0) { return $digits }
        return 'present'
    } catch {
        return 'absent'
    } finally {
        if ($null -ne $stream) { $stream.Dispose() }
    }
}

function Read-ZipEntryText {
    param($Entry, [int]$Cap)
    $entryStream = $null
    try {
        $entryStream = $Entry.Open()
        $buf = New-Object byte[] $Cap
        $read = 0
        while ($read -lt $Cap) {
            $n = $entryStream.Read($buf, $read, ($Cap - $read))
            if ($n -le 0) { break }
            $read = $read + $n
        }
        if ($read -le 0) { return '' }
        return [Text.Encoding]::UTF8.GetString($buf, 0, $read)
    } finally {
        if ($null -ne $entryStream) { $entryStream.Dispose() }
    }
}

function Read-ZipMarker {
    param($Entry)
    $result = New-Object psobject -Property @{ Element = ''; Status = 'error'; Bytes = 0 }
    $entryStream = $null
    $scan = New-MarkerScan
    try {
        $entryStream = $Entry.Open()
        $total = 0
        $limit = 8388608
        while ($total -lt $limit) {
            $buf = New-Object byte[] 65536
            $n = $entryStream.Read($buf, 0, 65536)
            if ($n -le 0) {
                $result.Status = Complete-MarkerScan -Scan $scan -Eof $true
                $result.Element = [string]$scan.Element
                if ([string]::Equals($result.Element, 'pending', $script:Ordinal)) {
                    $result.Element = ''
                    $result.Status = 'cut_element'
                }
                $result.Bytes = $total
                return $result
            }
            $piece = New-Object byte[] $n
            [Buffer]::BlockCopy($buf, 0, $piece, 0, $n)
            Add-MarkerBytes -Scan $scan -Chunk $piece
            $total = $total + $n
            if ($scan.Done) {
                $result.Status = 'found'
                $result.Element = [string]$scan.Element
                $result.Bytes = $total
                return $result
            }
        }
        $result.Status = 'incomplete'
        $result.Bytes = $total
        return $result
    } catch {
        $result.Status = 'error'
        return $result
    } finally {
        if ($null -ne $entryStream) { $entryStream.Dispose() }
    }
}

function Get-WorkbookEvidence {
    param([string]$Path, [long]$StartTicks, [bool]$StartKnown)
    $info = New-Object psobject -Property @{
        Exists = '0'
        Length = [int64]0
        WriteUtc = ''
        Rewritten = '0'
        Open = 'absent'
        Zone = 'absent'
        Vba = '0'
        ExternalLinks = 0
        PackageXml = 'absent'
        FileRecovery = 'unreadable'
        CrashSave = 'unreadable'
        RepairLoad = 'unreadable'
        AutoRecover = 'unreadable'
        DataExtract = 'unreadable'
        AppRecovery = '0'
        CustomRecovery = '0'
        PartCount = 0
        PartNames = ''
        XmlReason = 'workbook_missing'
        XmlBytes = 0
        EntryName = ''
    }
    if (-not [IO.File]::Exists($Path)) { return $info }
    $info.Exists = '1'
    $info.Zone = Read-ZoneMarker -Path $Path
    try {
        $item = Get-Item -LiteralPath $Path -ErrorAction Stop
        $info.Length = [int64]$item.Length
        $ticks = [int64]$item.LastWriteTimeUtc.Ticks
        $info.WriteUtc = $item.LastWriteTimeUtc.ToString('yyyy-MM-ddTHH:mm:ss') + 'Z'
        if (-not $StartKnown) { $info.Rewritten = 'unreadable' }
        elseif (Test-WriteAfterStart -WriteTicks $ticks -StartTicks $StartTicks -WriteKnown $true -StartKnown $true) { $info.Rewritten = '1' }
        else { $info.Rewritten = '0' }
    } catch {
        $info.Rewritten = 'unreadable'
    }
    $stream = $null
    try {
        Add-Type -AssemblyName System.IO.Compression -ErrorAction SilentlyContinue
        Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction SilentlyContinue
        $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
        $zip = New-Object IO.Compression.ZipArchive($stream, [IO.Compression.ZipArchiveMode]::Read)
        try {
            $info.Open = 'readable'
            $links = 0
            $parts = New-Object System.Collections.Generic.List[string]
            $workbookEntry = $null
            $workbookExact = $false
            $workbookLabel = ''
            foreach ($entry in $zip.Entries) {
                $full = [string]$entry.FullName
                $norm = $full.Replace('\', '/')
                if ([string]::Equals($norm, 'xl/vbaProject.bin', $script:OrdinalIgnore)) { $info.Vba = '1' }
                if ($norm.StartsWith('xl/externalLinks/', $script:OrdinalIgnore)) { $links = $links + 1 }
                if (Test-PackagePartName -Name $norm) {
                    $info.PartCount = [int]$info.PartCount + 1
                    if ($parts.Count -lt 8) { [void]$parts.Add((Get-PartLabel -Name $norm)) }
                }
                if (Test-WorkbookPart -Name $norm) {
                    $exact = [string]::Equals($norm.ToLowerInvariant(), 'xl/workbook.xml', $script:Ordinal)
                    if (($null -eq $workbookEntry) -or ($exact -and -not $workbookExact)) {
                        $workbookEntry = $entry
                        $workbookExact = $exact
                        $workbookLabel = Get-PartLabel -Name $norm
                    }
                }
                $wantApp = [string]::Equals($norm, 'docProps/app.xml', $script:OrdinalIgnore)
                $wantCustom = [string]::Equals($norm, 'docProps/custom.xml', $script:OrdinalIgnore)
                if ($wantApp -or $wantCustom) {
                    $side = $null
                    try { $side = Read-ZipMarker -Entry $entry } catch { $side = $null }
                    if (($null -ne $side) -and ([string]$side.Status -eq 'found')) {
                        if ($wantApp) { $info.AppRecovery = '1' }
                        if ($wantCustom) { $info.CustomRecovery = '1' }
                    }
                }
            }
            $info.ExternalLinks = $links
            $info.PartNames = [string]::Join(',', $parts.ToArray())
            $info.EntryName = $workbookLabel
            if ($null -eq $workbookEntry) {
                $flags = Get-PackageFlagState -Status 'missing' -Element ''
            } else {
                $marker = Read-ZipMarker -Entry $workbookEntry
                $info.XmlBytes = [int]$marker.Bytes
                $flags = Get-PackageFlagState -Status ([string]$marker.Status) -Element ([string]$marker.Element)
            }
            $info.PackageXml = [string]$flags.PackageXml
            $info.FileRecovery = [string]$flags.FileRecovery
            $info.CrashSave = [string]$flags.CrashSave
            $info.RepairLoad = [string]$flags.RepairLoad
            $info.AutoRecover = [string]$flags.AutoRecover
            $info.DataExtract = [string]$flags.DataExtract
            $info.XmlReason = [string]$flags.Reason
        } finally {
            $zip.Dispose()
        }
    } catch {
        $info.Open = 'locked'
        $info.PackageXml = 'locked'
        $info.FileRecovery = 'unreadable'
        $info.CrashSave = 'unreadable'
        $info.RepairLoad = 'unreadable'
        $info.AutoRecover = 'unreadable'
        $info.DataExtract = 'unreadable'
        $info.AppRecovery = 'unreadable'
        $info.CustomRecovery = 'unreadable'
        $info.XmlReason = 'zip_locked'
    } finally {
        if ($null -ne $stream) { $stream.Dispose() }
    }
    return $info
}

function Get-PathLeafSafe {
    param([string]$Path)
    if ([string]::IsNullOrEmpty($Path)) { return '' }
    $cut = $Path.LastIndexOf('\')
    $leaf = $Path
    if (($cut -ge 0) -and ($cut -lt ($Path.Length - 1))) { $leaf = $Path.Substring($cut + 1) }
    return (Get-SafeLabel -Name $leaf)
}

function Get-StartupEvidence {
    $info = New-Object psobject -Property @{
        XlStartCount = -1
        XlStartCanonical = '0'
        XlStartNames = ''
        UnsavedExists = 'unreadable'
        UnsavedCount = -1
    }
    $roaming = ''
    $local = ''
    try { $roaming = [string][Environment]::GetFolderPath('ApplicationData') } catch { $roaming = '' }
    try { $local = [string][Environment]::GetFolderPath('LocalApplicationData') } catch { $local = '' }
    if ($roaming.Length -gt 0) {
        $xl = $roaming + '\Microsoft\Excel\XLSTART'
        if (-not [IO.Directory]::Exists($xl)) {
            $info.XlStartCount = 0
        } else {
            try {
                $names = New-Object System.Collections.Generic.List[string]
                $canon = '0'
                foreach ($file in [IO.Directory]::EnumerateFiles($xl)) {
                    $leaf = Get-PathLeafSafe -Path ([string]$file)
                    if ($leaf.Length -eq 0 -or $leaf.StartsWith('len_', $script:Ordinal)) { continue }
                    if ([string]::Equals($leaf, $script:Leaf, $script:OrdinalIgnore)) { $canon = '1' }
                    if ($names.Count -lt 20) { [void]$names.Add($leaf) }
                }
                $info.XlStartCount = $names.Count
                $info.XlStartCanonical = $canon
                $info.XlStartNames = [string]::Join(',', $names.ToArray())
            } catch {
                $info.XlStartCount = -1
            }
        }
    }
    if ($local.Length -gt 0) {
        $unsaved = $local + '\Microsoft\Office\UnsavedFiles'
        if (-not [IO.Directory]::Exists($unsaved)) {
            $info.UnsavedExists = '0'
            $info.UnsavedCount = 0
        } else {
            $info.UnsavedExists = '1'
            try {
                $count = 0
                foreach ($file in [IO.Directory]::EnumerateFiles($unsaved)) {
                    if (-not [string]::IsNullOrEmpty([string]$file)) { $count = $count + 1 }
                }
                $info.UnsavedCount = $count
            } catch {
                $info.UnsavedCount = -1
            }
        }
    }
    return $info
}

function Get-TrustEvidence {
    $info = New-Object psobject -Property @{
        Canonical = 'unreadable'
        OtherCount = -1
        CanonicalCount = -1
        ValueKind = 'unreadable'
        ValueLen = -1
        ValueSha = ''
    }
    $opened = $null
    try {
        $opened = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Software\Microsoft\Office\16.0\Excel\Security\Trusted Documents\TrustRecords', $false)
        if ($null -eq $opened) {
            $info.Canonical = '0'
            $info.OtherCount = 0
            $info.CanonicalCount = 0
            $info.ValueKind = 'absent'
            $info.ValueLen = 0
            return $info
        }
        $names = $opened.GetValueNames()
        if ($null -eq $names) { $names = @() }
        $canon = '0'
        $other = 0
        $canonCount = 0
        foreach ($name in $names) {
            $value = [string]$name
            if ($value.IndexOf($script:Leaf, $script:OrdinalIgnore) -ge 0) {
                $canon = '1'
                $canonCount = $canonCount + 1
                if ($canonCount -eq 1) {
                    $kindName = Get-KindName -Kind ($opened.GetValueKind($value))
                    $info.ValueKind = $kindName
                    if ([string]::IsNullOrEmpty($kindName)) { $info.ValueKind = 'other' }
                    $packed = Read-KindBytes -Opened $opened -Name $value -KindName $kindName
                    if ($null -ne $packed) {
                        $info.ValueLen = [int]$packed.Bytes.Length
                        $info.ValueSha = Get-Sha256Hex -Bytes $packed.Bytes
                    }
                }
            } else {
                $other = $other + 1
            }
        }
        $info.Canonical = $canon
        $info.OtherCount = $other
        $info.CanonicalCount = $canonCount
        if ($canonCount -eq 0) {
            $info.ValueKind = 'absent'
            $info.ValueLen = 0
        }
    } catch {
        $info.Canonical = 'unreadable'
        $info.ValueKind = 'unreadable'
    } finally {
        if ($null -ne $opened) { $opened.Close() }
    }
    return $info
}

function Read-RegistryNumber {
    param($Opened, [string]$Name)
    if ($null -eq $Opened) { return 'absent' }
    try {
        $kind = $Opened.GetValueKind($Name)
    } catch {
        return 'absent'
    }
    $dwordKind = [Microsoft.Win32.RegistryValueKind]::DWord
    $qwordKind = [Microsoft.Win32.RegistryValueKind]::QWord
    if (($kind -eq $dwordKind) -or ($kind -eq $qwordKind)) {
        $raw = $Opened.GetValue($Name)
        return ([int64]$raw).ToString()
    }
    return 'other'
}

function Read-OfficeNumber {
    param([string]$SubPath, [string]$Name)
    $opened = $null
    try {
        $opened = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($SubPath, $false)
        if ($null -eq $opened) { return 'absent' }
        return (Read-RegistryNumber -Opened $opened -Name $Name)
    } catch {
        return 'unreadable'
    } finally {
        if ($null -ne $opened) { $opened.Close() }
    }
}

function Get-AddinOpenCounts {
    $info = New-Object psobject -Property @{ Rss = 'unreadable'; Other = -1; Manager = 'unreadable'; Key = 'unreadable' }
    $opened = $null
    try {
        $opened = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Software\Microsoft\Office\16.0\Excel\Options', $false)
        if ($null -eq $opened) {
            $info.Rss = '0'
            $info.Other = 0
        } else {
            $rss = 0
            $other = 0
            $names = $opened.GetValueNames()
            if ($null -eq $names) { $names = @() }
            foreach ($name in $names) {
                $packed = $null
                try {
                    $kindName = Get-KindName -Kind ($opened.GetValueKind([string]$name))
                    $packed = Read-KindBytes -Opened $opened -Name ([string]$name) -KindName $kindName
                } catch {
                    $packed = $null
                }
                $text = ''
                if ($null -ne $packed) { $text = [string]$packed.Text }
                $class = Get-OpenXllClass -Name ([string]$name) -Text $text
                if ($class -eq 'rss') { $rss = $rss + 1 }
                elseif ($class -eq 'other') { $other = $other + 1 }
            }
            $info.Rss = $rss.ToString()
            $info.Other = $other
        }
    } catch {
        $info.Rss = 'unreadable'
    } finally {
        if ($null -ne $opened) { $opened.Close() }
    }
    $manager = $null
    try {
        $manager = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Software\Microsoft\Office\16.0\Excel\Add-in Manager', $false)
        if ($null -eq $manager) {
            $info.Manager = '0'
        } else {
            $hit = '0'
            $names = $manager.GetValueNames()
            if ($null -eq $names) { $names = @() }
            foreach ($name in $names) {
                $valueName = [string]$name
                if ($valueName.IndexOf($script:XllStem, $script:OrdinalIgnore) -ge 0) { $hit = '1' }
                $packed = $null
                try {
                    $kindName = Get-KindName -Kind ($manager.GetValueKind($valueName))
                    $packed = Read-KindBytes -Opened $manager -Name $valueName -KindName $kindName
                } catch {
                    $packed = $null
                }
                if (($null -ne $packed) -and ([string]$packed.Text).IndexOf($script:XllStem, $script:OrdinalIgnore) -ge 0) { $hit = '1' }
            }
            $info.Manager = $hit
        }
    } catch {
        $info.Manager = 'unreadable'
    } finally {
        if ($null -ne $manager) { $manager.Close() }
    }
    $addins = $null
    try {
        $addins = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Software\Microsoft\Office\Excel\Addins', $false)
        if ($null -eq $addins) {
            $info.Key = '0'
        } else {
            $hit = '0'
            $subs = $addins.GetSubKeyNames()
            if ($null -eq $subs) { $subs = @() }
            foreach ($sub in $subs) {
                if (([string]$sub).IndexOf($script:XllStem, $script:OrdinalIgnore) -ge 0) { $hit = '1' }
            }
            $info.Key = $hit
        }
    } catch {
        $info.Key = 'unreadable'
    } finally {
        if ($null -ne $addins) { $addins.Close() }
    }
    return $info
}

function Get-SiblingEvidence {
    param([string]$WorkbookPath, [long]$StartTicks, [bool]$StartKnown)
    $info = New-Object psobject -Property @{
        LockExists = '0'
        LockWriteUtc = ''
        LockRelation = 'absent'
        XlkExists = '0'
        XlkWriteUtc = ''
        XlkRelation = 'absent'
    }
    $lockPath = Get-OwnerLockPath -WorkbookPath $WorkbookPath
    $xlkPath = Get-XlkPath -WorkbookPath $WorkbookPath
    foreach ($pair in @(
        (New-Object psobject -Property @{ Kind = 'lock'; Path = $lockPath }),
        (New-Object psobject -Property @{ Kind = 'xlk'; Path = $xlkPath })
    )) {
        $target = [string]$pair.Path
        $exists = $false
        $ticks = [int64]0
        $known = $false
        $stamp = ''
        if ($target.Length -gt 0) {
            try {
                $file = New-Object IO.FileInfo $target
                $exists = $file.Exists
                if ($exists) {
                    $ticks = [int64]$file.LastWriteTimeUtc.Ticks
                    $known = $true
                    $stamp = $file.LastWriteTimeUtc.ToString('yyyy-MM-ddTHH:mm:ss') + 'Z'
                }
            } catch {
                $known = $false
                $exists = $true
            }
        }
        $relation = Get-FileRelation -Exists $exists -WriteTicks $ticks -WriteKnown $known -StartTicks $StartTicks -StartKnown $StartKnown
        if ([string]$pair.Kind -eq 'lock') {
            $info.LockExists = [string]$relation.Exists
            $info.LockRelation = [string]$relation.Relation
            $info.LockWriteUtc = $stamp
            if ($exists -and (-not $known)) { $info.LockRelation = 'unreadable' }
        } else {
            $info.XlkExists = [string]$relation.Exists
            $info.XlkRelation = [string]$relation.Relation
            $info.XlkWriteUtc = $stamp
            if ($exists -and (-not $known)) { $info.XlkRelation = 'unreadable' }
        }
    }
    return $info
}

function Read-BackupEvidence {
    param($Rows)
    $info = New-Object psobject -Property @{
        State = 'backup_unreadable'
        Sha = ''
        Area = ''
        ValueName = ''
        Verdict = ''
        SamePlace = '0'
        FileHashOk = '0'
        Recreated = 'unreadable'
        Other = '0'
        Replaced = '0'
        Leaf = ''
    }
    $compared = Get-BackupCompareResult -BackupSha '' -BackupReadable $false -Rows $Rows
    $info.Other = [string]$compared.Other
    try {
        $root = Get-BackupRoot
        $pointerPath = $root + '\LATEST_BACKUP_DIR.txt'
        if (-not [IO.File]::Exists($pointerPath)) { return $info }
        $pointer = [IO.File]::ReadAllText($pointerPath).Trim()
        if (-not (Test-BackupDirAllowed -Root $root -Candidate $pointer)) { return $info }
        $info.Leaf = $pointer.Substring($pointer.LastIndexOf('\') + 1)
        $payloadPath = $pointer + '\payload.bin'
        $manifestPath = $pointer + '\manifest.json'
        if ((-not [IO.File]::Exists($payloadPath)) -or (-not [IO.File]::Exists($manifestPath))) { return $info }
        $payload = [IO.File]::ReadAllBytes($payloadPath)
        $payloadSha = Get-Sha256Hex -Bytes $payload
        $parsed = [IO.File]::ReadAllText($manifestPath) | ConvertFrom-Json
        $manifestSha = [string]$parsed.sha256
        if (-not [string]::Equals($payloadSha, $manifestSha, $script:OrdinalIgnore)) { return $info }
        $decoded = [Convert]::FromBase64String([string]$parsed.base64)
        $decodedSha = Get-Sha256Hex -Bytes $decoded
        if (-not [string]::Equals($decodedSha, $payloadSha, $script:OrdinalIgnore)) { return $info }
        $info.FileHashOk = '1'
        $info.Sha = $payloadSha
        $info.ValueName = Get-SafeLabel -Name ([string]$parsed.value_name)
        $info.Area = Get-RecoveryArea -Key ([string]$parsed.key)
        $info.Verdict = Get-BlobVerdict -Bytes $payload
        $live = Get-BackupCompareResult -BackupSha $payloadSha -BackupReadable $true -Rows $Rows
        $info.State = [string]$live.State
        $info.Recreated = [string]$live.Recreated
        $info.Other = [string]$live.Other
        $info.Replaced = Get-ReplacementFlag -BackupKey ([string]$parsed.key) -BackupName ([string]$parsed.value_name) -BackupSha $payloadSha -BackupReadable $true -Rows $Rows
        $canonKey = ConvertTo-CanonicalRegistryPath -Key ([string]$parsed.key)
        foreach ($row in @(Get-FlatRows -Rows $Rows)) {
            $sameKey = [string]::Equals([string]$row.Key, $canonKey, $script:OrdinalIgnore)
            $sameName = [string]::Equals([string]$row.ValueName, [string]$parsed.value_name, $script:Ordinal)
            $sameSha = [string]::Equals([string]$row.Sha, $payloadSha, $script:OrdinalIgnore)
            if ($sameKey -and $sameName -and $sameSha) { $info.SamePlace = '1' }
        }
    } catch {
        $info.State = 'backup_unreadable'
        $info.Recreated = 'unreadable'
        $info.FileHashOk = '0'
    }
    return $info
}

function Get-CommandFlags {
    param([string]$Command)
    $readable = '1'
    if ([string]::IsNullOrWhiteSpace($Command)) { $readable = '0' }
    $canonical = '0'
    $embedding = '0'
    $isolated = '0'
    if ($readable -eq '1') {
        if ($Command.IndexOf($script:Leaf, $script:OrdinalIgnore) -ge 0) { $canonical = '1' }
        if ($Command.IndexOf('-Embedding', $script:OrdinalIgnore) -ge 0) { $embedding = '1' }
        if ($Command.IndexOf('/x', $script:OrdinalIgnore) -ge 0) { $isolated = '1' }
    } else {
        $canonical = 'unreadable'
        $embedding = 'unreadable'
        $isolated = 'unreadable'
    }
    return (New-Object psobject -Property @{
        Readable = $readable
        Canonical = $canonical
        Embedding = $embedding
        Isolated = $isolated
    })
}

function Get-ProcessRows {
    $rows = $null
    try {
        $rows = Get-CimInstance -ClassName Win32_Process -Filter "Name = 'EXCEL.EXE'" -ErrorAction Stop
    } catch {
        try {
            $rows = Get-WmiObject -Class Win32_Process -Filter "Name = 'EXCEL.EXE'" -ErrorAction Stop
        } catch {
            return @()
        }
    }
    if ($null -eq $rows) { return @() }
    $list = New-Object System.Collections.Generic.List[object]
    foreach ($row in @($rows)) {
        if ($null -eq $row) { continue }
        if ($list.Count -ge 20) { break }
        $procId = 0
        $parent = 0
        $command = ''
        try { $procId = [int]$row.ProcessId } catch { continue }
        try { $parent = [int]$row.ParentProcessId } catch { $parent = 0 }
        try { $command = [string]$row.CommandLine } catch { $command = '' }
        [void]$list.Add((New-Object psobject -Property @{
            Pid = $procId
            Parent = $parent
            Command = $command
        }))
    }
    return $list.ToArray()
}

function Get-XllEvidence {
    param([int]$ProcId)
    $info = New-Object psobject -Property @{
        Loaded = 'unreadable'
        OtherCount = -1
        Length = [int64]0
        WriteUtc = ''
        PathLabel = ''
        Hwnd = [int64]0
        Alive = '0'
        StartTicks = [int64]0
        StartUtc = ''
        Name = ''
        Session = -1
    }
    $proc = $null
    try {
        $proc = Get-Process -Id $ProcId -ErrorAction Stop
        $info.Name = Get-SafeLabel -Name ([string]$proc.ProcessName)
        $info.Alive = '1'
        try { $info.Hwnd = [int64]$proc.MainWindowHandle } catch { $info.Hwnd = [int64]0 }
        try { $info.Session = [int]$proc.SessionId } catch { $info.Session = -1 }
        try {
            $started = $proc.StartTime.ToUniversalTime()
            $info.StartTicks = [int64]$started.Ticks
            $info.StartUtc = $started.ToString('yyyy-MM-ddTHH:mm:ss') + 'Z'
        } catch {
            $info.StartTicks = [int64]0
        }
    } catch {
        return $info
    }
    try {
        $modules = $proc.Modules
        if ($null -eq $modules) {
            $info.Loaded = 'unreadable'
            return $info
        }
        $loaded = $false
        $other = 0
        $xllPath = ''
        foreach ($mod in $modules) {
            if ($null -eq $mod) { continue }
            $modName = [string]$mod.ModuleName
            if ([string]::Equals($modName, $script:XllLeaf, $script:OrdinalIgnore)) {
                $loaded = $true
                try { $xllPath = [string]$mod.FileName } catch { $xllPath = '' }
            } elseif ($modName.EndsWith('.xll', $script:OrdinalIgnore)) {
                $other = $other + 1
            }
        }
        if ($loaded) { $info.Loaded = '1' } else { $info.Loaded = '0' }
        $info.OtherCount = $other
        if ($loaded -and $xllPath.Length -gt 0 -and $xllPath.IndexOf('|', $script:Ordinal) -lt 0) {
            $info.PathLabel = $xllPath
            try {
                $file = Get-Item -LiteralPath $xllPath -ErrorAction Stop
                $info.Length = [int64]$file.Length
                $info.WriteUtc = $file.LastWriteTimeUtc.ToString('yyyy-MM-ddTHH:mm:ss') + 'Z'
            } catch {}
        }
    } catch {
        $info.Loaded = 'unreadable'
    }
    return $info
}

function Get-CrashEvidence {
    param([long]$StartTicks, [bool]$StartKnown)
    $info = New-Object psobject -Property @{
        EventFlag = 'unreadable'
        EventCount = 0
        Tokens = ''
        WerCount = -1
        QueryId = ''
    }
    if (-not $StartKnown -or $StartTicks -le 0) { return $info }
    $startUtc = [DateTime]::new($StartTicks, [DateTimeKind]::Utc)
    $startLocal = $startUtc.ToLocalTime()
    $events = @()
    $queryOk = $false
    try {
        $events = @(Get-WinEvent -FilterHashtable @{
            LogName = 'Application'
            StartTime = $startLocal
            Id = @(1000, 1001)
        } -ErrorAction Stop)
        $queryOk = $true
    } catch {
        $errorId = ''
        $msg = ''
        try { $errorId = [string]$_.FullyQualifiedErrorId } catch { $errorId = '' }
        try { $msg = [string]$_.Exception.Message } catch { $msg = '' }
        $idLeaf = $errorId
        $cut = $errorId.IndexOf(',', $script:Ordinal)
        if ($cut -gt 0) { $idLeaf = $errorId.Substring(0, $cut) }
        $info.QueryId = Get-SafeLabel -Name $idLeaf
        if (Test-NoMatchingEventQuery -ErrorId $errorId -Message $msg) {
            $events = @()
            $queryOk = $true
        }
    }
    if ($queryOk) {
        $info.EventFlag = '0'
        $tokens = New-Object System.Collections.Generic.List[string]
        $count = 0
        foreach ($ev in $events) {
            if ($null -eq $ev) { continue }
            $message = ''
            try { $message = [string]$ev.Message } catch { continue }
            if ($message.IndexOf('EXCEL.EXE', $script:OrdinalIgnore) -lt 0) { continue }
            $count = $count + 1
            foreach ($token in @(Get-ModuleTokens -Text $message)) {
                $value = [string]$token
                if ($value.Length -eq 0) { continue }
                if ((-not $tokens.Contains($value)) -and ($tokens.Count -lt 15)) { [void]$tokens.Add($value) }
            }
        }
        $info.EventCount = $count
        if ($count -gt 0) { $info.EventFlag = '1' }
        $info.Tokens = [string]::Join(',', $tokens.ToArray())
    }
    $werCount = 0
    $werFailed = $false
    foreach ($folder in @(
        'C:\ProgramData\Microsoft\Windows\WER\ReportArchive',
        'C:\ProgramData\Microsoft\Windows\WER\ReportQueue'
    )) {
        if (-not [IO.Directory]::Exists($folder)) { continue }
        try {
            foreach ($dir in [IO.Directory]::EnumerateDirectories($folder)) {
                $name = [string]$dir
                if ($name.IndexOf('EXCEL', $script:OrdinalIgnore) -lt 0) { continue }
                try {
                    $dirInfo = New-Object IO.DirectoryInfo $name
                    if ([int64]$dirInfo.LastWriteTimeUtc.Ticks -gt $StartTicks) { $werCount = $werCount + 1 }
                } catch {}
            }
        } catch {
            $werFailed = $true
        }
    }
    if ($werFailed) { $info.WerCount = -1 } else { $info.WerCount = $werCount }
    return $info
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

function Get-PriorCrashEvidence {
    param([long]$StartTicks, [bool]$StartKnown)
    $info = New-Object psobject -Property @{
        State = 'unreadable'
        EventCount = 0
        LatestUtc = ''
        Tokens = ''
        Xll = '0'
        WerCount = -1
        QueryId = ''
        Truncated = '0'
        WorkbookHits = 0
        XllHits = 0
        LatestKind = ''
        LatestModule = ''
        LatestException = ''
        LatestWorkbook = '0'
        LatestXll = '0'
        Rows = @()
        WerRows = @()
    }
    if (-not $StartKnown -or $StartTicks -le 0) { return $info }
    $startUtc = [DateTime]::new($StartTicks, [DateTimeKind]::Utc)
    $startLocal = $startUtc.ToLocalTime()
    $fromLocal = $startLocal.AddDays(-14)
    $toLocal = $startLocal.AddSeconds(-1)
    $events = @()
    $queryOk = $false
    try {
        $events = @(Get-WinEvent -FilterHashtable @{
            LogName = 'Application'
            StartTime = $fromLocal
            EndTime = $toLocal
            Id = @(1000, 1001)
        } -ErrorAction Stop)
        $queryOk = $true
    } catch {
        $errorId = ''
        $msg = ''
        try { $errorId = [string]$_.FullyQualifiedErrorId } catch { $errorId = '' }
        try { $msg = [string]$_.Exception.Message } catch { $msg = '' }
        $idLeaf = $errorId
        $cut = $errorId.IndexOf(',', $script:Ordinal)
        if ($cut -gt 0) { $idLeaf = $errorId.Substring(0, $cut) }
        $info.QueryId = Get-SafeLabel -Name $idLeaf
        if (Test-NoMatchingEventQuery -ErrorId $errorId -Message $msg) {
            $events = @()
            $queryOk = $true
        }
    }
    if ($queryOk) {
        $info.State = 'ok'
        $tokens = New-Object System.Collections.Generic.List[string]
        $rows = New-Object System.Collections.Generic.List[object]
        $count = 0
        $latest = [int64]0
        $workbookHits = 0
        $xllHits = 0
        foreach ($ev in $events) {
            if ($null -eq $ev) { continue }
            $message = ''
            try { $message = [string]$ev.Message } catch { $message = '' }
            $eventId = 0
            try { $eventId = [int]$ev.Id } catch { $eventId = 0 }
            $moduleHint = ''
            $exceptionHint = ''
            $bits = New-Object System.Collections.Generic.List[string]
            try {
                $propIndex = 0
                foreach ($prop in @($ev.Properties)) {
                    if ($null -eq $prop) { continue }
                    $propValue = ''
                    try { $propValue = [string]$prop.Value } catch { $propValue = '' }
                    if (($propValue.Length -gt 0) -and ($propValue.Length -lt 300)) { [void]$bits.Add($propValue) }
                    if (($eventId -eq 1000) -and ($propIndex -eq 3)) { $moduleHint = $propValue }
                    if (($eventId -eq 1000) -and ($propIndex -eq 6)) { $exceptionHint = $propValue }
                    $propIndex = $propIndex + 1
                }
            } catch {}
            $scanText = $message
            if ($bits.Count -gt 0) { $scanText = $message + ' ' + [string]::Join(' ', $bits.ToArray()) }
            if ($scanText.IndexOf('EXCEL.EXE', $script:OrdinalIgnore) -lt 0) { continue }
            $count = $count + 1
            $stamp = ''
            $ticks = [int64]0
            try {
                $created = $ev.TimeCreated.ToUniversalTime()
                $ticks = [int64]$created.Ticks
                $stamp = $created.ToString('yyyy-MM-ddTHH:mm:ss') + 'Z'
                if ($ticks -gt $latest) {
                    $latest = $ticks
                    $info.LatestUtc = $stamp
                }
            } catch {}
            $class = Get-CrashEventClass -EventId $eventId -Text $scanText -ModuleHint $moduleHint -ExceptionHint $exceptionHint
            if ([string]$class.Workbook -eq '1') { $workbookHits = $workbookHits + 1 }
            if ([string]$class.Xll -eq '1') { $xllHits = $xllHits + 1 }
            if ($rows.Count -lt 16) {
                [void]$rows.Add((New-Object psobject -Property @{
                    Utc = $stamp
                    Ticks = $ticks
                    Id = $eventId
                    Kind = [string]$class.Kind
                    Module = [string]$class.Module
                    Exception = [string]$class.Exception
                    Workbook = [string]$class.Workbook
                    Xll = [string]$class.Xll
                }))
            }
            if (($ticks -gt 0) -and ($ticks -ge $latest)) {
                $info.LatestKind = [string]$class.Kind
                $info.LatestModule = [string]$class.Module
                $info.LatestException = [string]$class.Exception
                $info.LatestWorkbook = [string]$class.Workbook
                $info.LatestXll = [string]$class.Xll
            }
            if ($count -le 40) {
                foreach ($token in @(Get-ModuleTokens -Text $scanText)) {
                    $value = [string]$token
                    if ($value.Length -eq 0) { continue }
                    if ((-not $tokens.Contains($value)) -and ($tokens.Count -lt 15)) { [void]$tokens.Add($value) }
                }
            }
            if ($count -ge 400) {
                $info.Truncated = '1'
                break
            }
        }
        $info.EventCount = $count
        $info.WorkbookHits = $workbookHits
        $info.XllHits = $xllHits
        $info.Rows = $rows.ToArray()
        $info.Tokens = [string]::Join(',', $tokens.ToArray())
        if (Test-TokenHasXll -Tokens ([string]$info.Tokens)) { $info.Xll = '1' }
        if ($xllHits -gt 0) { $info.Xll = '1' }
    }
    $werCount = 0
    $werFailed = $false
    $werRows = New-Object System.Collections.Generic.List[object]
    $floor = $StartTicks - ([int64]14 * [int64]86400 * [int64]10000000)
    foreach ($folder in @(
        'C:\ProgramData\Microsoft\Windows\WER\ReportArchive',
        'C:\ProgramData\Microsoft\Windows\WER\ReportQueue'
    )) {
        if (-not [IO.Directory]::Exists($folder)) { continue }
        try {
            foreach ($dir in [IO.Directory]::EnumerateDirectories($folder)) {
                $name = [string]$dir
                if ($name.IndexOf('EXCEL', $script:OrdinalIgnore) -lt 0) { continue }
                try {
                    $dirInfo = New-Object IO.DirectoryInfo $name
                    $ticks = [int64]$dirInfo.LastWriteTimeUtc.Ticks
                    if (($ticks -lt $StartTicks) -and ($ticks -ge $floor)) {
                        $werCount = $werCount + 1
                        if ($werRows.Count -lt 12) {
                            $reportPath = ''
                            foreach ($file in [IO.Directory]::EnumerateFiles($name)) {
                                $leaf = Get-PathLeafSafe -Path ([string]$file)
                                if ([string]::Equals($leaf, 'Report.wer', $script:OrdinalIgnore)) { $reportPath = [string]$file }
                            }
                            if ($reportPath.Length -gt 0) {
                                $raw = Read-CappedBytes -Path $reportPath -Cap 262144
                                $text = Convert-ReportText -Bytes $raw
                                $class = Get-CrashEventClass -EventId 1001 -Text $text -ModuleHint '' -ExceptionHint ''
                                $stamp = $dirInfo.LastWriteTimeUtc.ToString('yyyy-MM-ddTHH:mm:ss') + 'Z'
                                [void]$werRows.Add((New-Object psobject -Property @{
                                    Utc = $stamp
                                    Kind = [string]$class.Kind
                                    Module = [string]$class.Module
                                    Exception = [string]$class.Exception
                                    Workbook = [string]$class.Workbook
                                    Xll = [string]$class.Xll
                                }))
                            }
                        }
                    }
                } catch {}
            }
        } catch {
            $werFailed = $true
        }
    }
    $info.WerRows = $werRows.ToArray()
    if ($werFailed) { $info.WerCount = -1 } else { $info.WerCount = $werCount }
    return $info
}

function Add-CanonicalWindowType {
    try {
        [void][CanonicalWindowSurvey]
        return
    } catch {}
    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;

public class CanonicalWindowHit {
    public long Hwnd;
    public long OwnerHwnd;
    public long ParentHwnd;
    public int Pid;
    public int OwnerPid;
    public int ParentPid;
    public int Tid;
    public int RootPid;
    public int Depth;
    public int Foreground;
    public int GuiActive;
    public string ClassName;
    public string Title;
    public string ChildText;
    public string ProcessName;
    public string Role;
    public int TitleLen;
    public int DirectLen;
    public int SentLen;
    public int ChildLen;
    public int Visible;
    public int Needle;
}

public class CanonicalWindowSurveyResult {
    public int TopLevelSeen;
    public int FocusTopLevel;
    public int DialogClassCount;
    public int StandardDialogCount;
    public int ChildSeen;
    public int ChildTruncated;
    public int CandidateCount;
    public long ForegroundHwnd;
    public int ForegroundPid;
    public int ForegroundTid;
    public string ForegroundClass;
    public string ScriptDesktop;
    public string FocusDesktop;
    public string ForegroundDesktop;
    public int DesktopFocusMatch;
    public int DesktopForegroundMatch;
    public List<CanonicalWindowHit> Hits;
}

public class CanonicalRegistryStamp {
    [DllImport("advapi32.dll", CharSet = CharSet.Unicode)]
    static extern int RegOpenKeyEx(IntPtr hKey, string subKey, uint options, int sam, out IntPtr phkResult);
    [DllImport("advapi32.dll")]
    static extern int RegCloseKey(IntPtr hKey);
    [DllImport("advapi32.dll")]
    static extern int RegQueryInfoKey(
        IntPtr hKey,
        IntPtr lpClass,
        IntPtr lpcbClass,
        IntPtr lpReserved,
        IntPtr lpcSubKeys,
        IntPtr lpcbMaxSubKeyLen,
        IntPtr lpcbMaxClassLen,
        IntPtr lpcValues,
        IntPtr lpcbMaxValueNameLen,
        IntPtr lpcbMaxValueLen,
        IntPtr lpcbSecurityDescriptor,
        out long lpftLastWriteTime);

    static readonly IntPtr HkeyCurrentUser = new IntPtr(unchecked((int)0x80000001));
    const int KeyQueryValue = 0x0001;

    public static long LastWriteUtcTicks(string relative) {
        if (string.IsNullOrEmpty(relative)) { return 0; }
        IntPtr hkey;
        int opened = RegOpenKeyEx(HkeyCurrentUser, relative, 0, KeyQueryValue, out hkey);
        if (opened != 0 || hkey == IntPtr.Zero) { return 0; }
        try {
            long filetime;
            int query = RegQueryInfoKey(
                hkey,
                IntPtr.Zero,
                IntPtr.Zero,
                IntPtr.Zero,
                IntPtr.Zero,
                IntPtr.Zero,
                IntPtr.Zero,
                IntPtr.Zero,
                IntPtr.Zero,
                IntPtr.Zero,
                IntPtr.Zero,
                out filetime);
            if (query != 0 || filetime <= 0) { return 0; }
            return DateTime.FromFileTimeUtc(filetime).Ticks;
        } catch {
            return 0;
        } finally {
            RegCloseKey(hkey);
        }
    }
}

public class CanonicalWindowSurvey {
    delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);

    [StructLayout(LayoutKind.Sequential)]
    public struct RECT {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct GUITHREADINFO {
        public int cbSize;
        public int flags;
        public IntPtr hwndActive;
        public IntPtr hwndFocus;
        public IntPtr hwndCapture;
        public IntPtr hwndMenuOwner;
        public IntPtr hwndMoveSize;
        public IntPtr hwndCaret;
        public RECT rcCaret;
    }

    [DllImport("user32.dll")]
    static extern bool EnumWindows(EnumProc lpEnumFunc, IntPtr lParam);
    [DllImport("user32.dll")]
    static extern bool EnumChildWindows(IntPtr hWnd, EnumProc lpEnumFunc, IntPtr lParam);
    [DllImport("user32.dll")]
    static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
    [DllImport("user32.dll")]
    static extern IntPtr GetWindow(IntPtr hWnd, uint uCmd);
    [DllImport("user32.dll")]
    static extern IntPtr GetParent(IntPtr hWnd);
    [DllImport("user32.dll")]
    static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")]
    static extern IntPtr GetAncestor(IntPtr hWnd, uint gaFlags);
    [DllImport("user32.dll")]
    static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")]
    static extern bool GetGUIThreadInfo(uint idThread, ref GUITHREADINFO lpsi);
    [DllImport("user32.dll")]
    static extern IntPtr GetThreadDesktop(uint threadId);
    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern bool GetUserObjectInformation(IntPtr hObj, int nIndex, IntPtr pvInfo, int nLength, out int needed);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    static extern int GetClassName(IntPtr hWnd, StringBuilder lpClassName, int nMaxCount);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint msg, IntPtr wParam, StringBuilder lParam, uint flags, uint timeoutMs, out IntPtr result);
    [DllImport("kernel32.dll")]
    static extern uint GetCurrentThreadId();
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern IntPtr OpenProcess(uint access, bool inherit, uint pid);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern bool QueryFullProcessImageName(IntPtr hProcess, int flags, StringBuilder exeName, ref int size);
    [DllImport("kernel32.dll")]
    static extern bool CloseHandle(IntPtr hObject);

    const uint WM_GETTEXT = 0x000D;
    const uint SMTO_ABORTIFHUNG = 0x0002;
    const uint GW_OWNER = 4;
    const uint GA_ROOT = 2;
    const uint PROCESS_QUERY_LIMITED_INFORMATION = 0x1000;
    const int UOI_NAME = 2;

    static EnumProc topCallback;
    static EnumProc childCallback;
    static List<CanonicalWindowHit> hits;
    static Dictionary<int, string> processNames;
    static HashSet<long> walkedRoots;
    static int topLevelSeen;
    static int focusTopLevel;
    static int dialogClassCount;
    static int standardDialogCount;
    static int childSeen;
    static int childTruncated;
    static int childExamined;
    static int childRecorded;
    static int focusPidArg;
    static IntPtr foregroundHwnd;
    static string rootChildMatch;

    public static CanonicalWindowSurveyResult Collect(int focusPid) {
        hits = new List<CanonicalWindowHit>();
        processNames = new Dictionary<int, string>();
        walkedRoots = new HashSet<long>();
        topLevelSeen = 0;
        focusTopLevel = 0;
        dialogClassCount = 0;
        standardDialogCount = 0;
        childSeen = 0;
        childTruncated = 0;
        focusPidArg = focusPid;
        foregroundHwnd = GetForegroundWindow();
        string scriptDesktop = DesktopName(GetCurrentThreadId());
        string foregroundDesktop = "";
        int foregroundPid = 0;
        int foregroundTid = 0;
        string foregroundClass = "";
        if (foregroundHwnd != IntPtr.Zero) {
            Capture(foregroundHwnd, 0, "foreground", true);
            WalkChildren(foregroundHwnd);
            WalkChain(foregroundHwnd);
            CanonicalWindowHit fgHit = FindHit(foregroundHwnd.ToInt64());
            if (fgHit != null) {
                foregroundPid = fgHit.Pid;
                foregroundTid = fgHit.Tid;
                foregroundClass = fgHit.ClassName;
                foregroundDesktop = DesktopName((uint)fgHit.Tid);
            }
        }
        topCallback = OnTop;
        EnumWindows(topCallback, IntPtr.Zero);
        WalkInterestingChildren();
        CaptureGuiThreads();
        string focusDesktop = "";
        for (int i = 0; i < hits.Count; i++) {
            if (focusPidArg > 0 && hits[i].Pid == focusPidArg && hits[i].Depth == 0 && hits[i].Tid > 0) {
                focusDesktop = DesktopName((uint)hits[i].Tid);
                break;
            }
        }
        return new CanonicalWindowSurveyResult {
            TopLevelSeen = topLevelSeen,
            FocusTopLevel = focusTopLevel,
            DialogClassCount = dialogClassCount,
            StandardDialogCount = standardDialogCount,
            ChildSeen = childSeen,
            ChildTruncated = childTruncated,
            CandidateCount = hits.Count,
            ForegroundHwnd = foregroundHwnd.ToInt64(),
            ForegroundPid = foregroundPid,
            ForegroundTid = foregroundTid,
            ForegroundClass = foregroundClass,
            ScriptDesktop = scriptDesktop,
            FocusDesktop = focusDesktop,
            ForegroundDesktop = foregroundDesktop,
            DesktopFocusMatch = DesktopMatch(scriptDesktop, focusDesktop),
            DesktopForegroundMatch = DesktopMatch(scriptDesktop, foregroundDesktop),
            Hits = hits
        };
    }

    static bool OnTop(IntPtr hWnd, IntPtr lParam) {
        topLevelSeen++;
        uint pidRaw;
        GetWindowThreadProcessId(hWnd, out pidRaw);
        int pid = (int)pidRaw;
        if (pid == focusPidArg && focusPidArg > 0) { focusTopLevel++; }
        string className = ReadClass(hWnd);
        if (IsDialogClass(className)) { dialogClassCount++; }
        if (className == "#32770") { standardDialogCount++; }
        bool visible = IsWindowVisible(hWnd);
        IntPtr owner = GetWindow(hWnd, GW_OWNER);
        IntPtr parent = GetParent(hWnd);
        int ownerPid = PidOf(owner);
        int parentPid = PidOf(parent);
        int rootPid = RootPidOf(hWnd, pid);
        bool focus = focusPidArg > 0 && (pid == focusPidArg || ownerPid == focusPidArg || parentPid == focusPidArg || rootPid == focusPidArg);
        bool dialog = IsDialogClass(className);
        bool main = className == "XLMAIN";
        string leaf = ProcessLeaf(pid);
        bool office = IsOfficeProcess(leaf);
        if (!visible && !focus && !dialog) { return true; }
        string quick = visible ? QuickText(hWnd) : "";
        if (dialog || focus || main || office || HasNeedle(quick)) {
            Capture(hWnd, 0, "toplevel", HasNeedle(quick) || dialog);
        }
        return true;
    }

    static void WalkInterestingChildren() {
        var roots = new List<long>();
        for (int i = 0; i < hits.Count; i++) {
            if (hits[i].Depth != 0) { continue; }
            bool walk = (focusPidArg > 0 && hits[i].Pid == focusPidArg)
                || hits[i].ClassName == "XLMAIN"
                || IsDialogClass(hits[i].ClassName)
                || hits[i].Foreground == 1
                || IsOfficeProcess(hits[i].ProcessName);
            if (!walk) { continue; }
            if (roots.Contains(hits[i].Hwnd)) { continue; }
            roots.Add(hits[i].Hwnd);
            if (roots.Count >= 30) { break; }
        }
        for (int i = 0; i < roots.Count; i++) {
            WalkChildren(new IntPtr(roots[i]));
        }
    }

    static void CaptureGuiThreads() {
        var tids = new List<int>();
        for (int i = 0; i < hits.Count; i++) {
            if (focusPidArg <= 0 || hits[i].Pid != focusPidArg || hits[i].Depth != 0) { continue; }
            if (hits[i].Tid <= 0 || tids.Contains(hits[i].Tid)) { continue; }
            tids.Add(hits[i].Tid);
            if (tids.Count >= 8) { break; }
        }
        for (int i = 0; i < tids.Count; i++) {
            GUITHREADINFO info = new GUITHREADINFO();
            info.cbSize = Marshal.SizeOf(typeof(GUITHREADINFO));
            if (!GetGUIThreadInfo((uint)tids[i], ref info)) { continue; }
            NoteGui(info.hwndActive);
            if (info.hwndFocus != info.hwndActive) { NoteGui(info.hwndFocus); }
        }
    }

    static void NoteGui(IntPtr hWnd) {
        if (hWnd == IntPtr.Zero) { return; }
        Capture(hWnd, 0, "guithread", true);
        for (int i = 0; i < hits.Count; i++) {
            if (hits[i].Hwnd == hWnd.ToInt64()) { hits[i].GuiActive = 1; }
        }
        WalkChildren(hWnd);
        WalkChain(hWnd);
    }

    static void WalkChildren(IntPtr root) {
        if (root == IntPtr.Zero) { return; }
        long key = root.ToInt64();
        if (walkedRoots.Contains(key)) { return; }
        walkedRoots.Add(key);
        childExamined = 0;
        childRecorded = 0;
        rootChildMatch = "";
        childCallback = OnChild;
        EnumChildWindows(root, childCallback, root);
        childSeen = childSeen + childExamined;
        if (rootChildMatch.Length > 0) {
            for (int i = 0; i < hits.Count; i++) {
                if (hits[i].Hwnd != key) { continue; }
                if (hits[i].ChildText == null || hits[i].ChildText.Length == 0) { hits[i].ChildText = rootChildMatch; }
                hits[i].Needle = 1;
                hits[i].ChildLen = childExamined;
                break;
            }
        }
    }

    static bool OnChild(IntPtr hWnd, IntPtr lParam) {
        childExamined++;
        if (childExamined > 800) {
            childTruncated = 1;
            return false;
        }
        string className = ReadClass(hWnd);
        bool dialog = IsDialogClass(className);
        string quick = QuickText(hWnd);
        bool needle = HasNeedle(quick);
        bool officeUi = className.IndexOf("NUI", StringComparison.Ordinal) >= 0
            || className.IndexOf("bosa", StringComparison.Ordinal) >= 0
            || className.IndexOf("NetUI", StringComparison.Ordinal) >= 0
            || className.IndexOf("Mso", StringComparison.Ordinal) >= 0;
        if (!dialog && !needle && !officeUi) { return true; }
        if (!dialog && !needle && childRecorded >= 40) { return true; }
        Capture(hWnd, 1, "child", dialog || needle);
        childRecorded++;
        if (needle && rootChildMatch.Length == 0) { rootChildMatch = quick; }
        if (rootChildMatch.Length == 0) {
            CanonicalWindowHit hit = FindHit(hWnd.ToInt64());
            if (hit != null && hit.Needle == 1 && hit.Title != null && hit.Title.Length > 0) {
                rootChildMatch = hit.Title;
            }
        }
        return true;
    }

    static void WalkChain(IntPtr start) {
        IntPtr cur = start;
        for (int i = 0; i < 8 && cur != IntPtr.Zero; i++) {
            IntPtr owner = GetWindow(cur, GW_OWNER);
            IntPtr parent = GetParent(cur);
            IntPtr next = owner != IntPtr.Zero ? owner : parent;
            if (next == IntPtr.Zero || next == cur) { break; }
            Capture(next, 0, "owner", true);
            cur = next;
        }
    }

    static void Capture(IntPtr hWnd, int depth, string role, bool force) {
        if (hWnd == IntPtr.Zero) { return; }
        uint pidRaw;
        uint tid = GetWindowThreadProcessId(hWnd, out pidRaw);
        int pid = (int)pidRaw;
        IntPtr owner = GetWindow(hWnd, GW_OWNER);
        IntPtr parent = GetParent(hWnd);
        int ownerPid = PidOf(owner);
        int parentPid = PidOf(parent);
        string className = ReadClass(hWnd);
        int directLen;
        int sentLen;
        bool foreground = hWnd == foregroundHwnd;
        string text = ReadTextParts(hWnd, className, foreground || role == "foreground" || role == "guithread", out directLen, out sentLen);
        bool needle = HasNeedle(text);
        var hit = new CanonicalWindowHit();
        hit.Hwnd = hWnd.ToInt64();
        hit.OwnerHwnd = owner.ToInt64();
        hit.ParentHwnd = parent.ToInt64();
        hit.Pid = pid;
        hit.OwnerPid = ownerPid;
        hit.ParentPid = parentPid;
        hit.Tid = (int)tid;
        hit.RootPid = RootPidOf(hWnd, pid);
        hit.Depth = depth;
        hit.Foreground = foreground ? 1 : 0;
        hit.GuiActive = 0;
        hit.ClassName = className;
        hit.Title = needle ? text : "";
        hit.ChildText = "";
        hit.ProcessName = ProcessLeaf(pid);
        hit.Role = role;
        hit.TitleLen = directLen;
        hit.DirectLen = directLen;
        hit.SentLen = sentLen;
        hit.ChildLen = 0;
        hit.Visible = IsWindowVisible(hWnd) ? 1 : 0;
        hit.Needle = needle ? 1 : 0;
        AddHit(hit, force || needle || IsDialogClass(className));
    }

    static void AddHit(CanonicalWindowHit hit, bool force) {
        CanonicalWindowHit existing = FindHit(hit.Hwnd);
        if (existing != null) {
            if (hit.Foreground == 1) { existing.Foreground = 1; }
            if (hit.Needle == 1 && existing.Needle == 0) {
                existing.Needle = 1;
                existing.Title = hit.Title;
            }
            if (existing.Role == "toplevel" && (hit.Role == "foreground" || hit.Role == "guithread")) {
                existing.Role = hit.Role;
            }
            if (existing.SentLen < hit.SentLen) { existing.SentLen = hit.SentLen; }
            if (existing.DirectLen < hit.DirectLen) { existing.DirectLen = hit.DirectLen; }
            return;
        }
        if (!force && hits.Count >= 120) { return; }
        if (hits.Count >= 160) { return; }
        hits.Add(hit);
    }

    static CanonicalWindowHit FindHit(long hwnd) {
        for (int i = 0; i < hits.Count; i++) {
            if (hits[i].Hwnd == hwnd) { return hits[i]; }
        }
        return null;
    }

    static int PidOf(IntPtr hWnd) {
        if (hWnd == IntPtr.Zero) { return 0; }
        uint pid;
        GetWindowThreadProcessId(hWnd, out pid);
        return (int)pid;
    }

    static int RootPidOf(IntPtr hWnd, int ownPid) {
        IntPtr cur = hWnd;
        int root = ownPid;
        for (int i = 0; i < 8; i++) {
            IntPtr owner = GetWindow(cur, GW_OWNER);
            IntPtr parent = GetParent(cur);
            IntPtr ancestor = GetAncestor(cur, GA_ROOT);
            IntPtr next = owner != IntPtr.Zero ? owner : parent;
            if (ancestor != IntPtr.Zero && ancestor != cur && next == IntPtr.Zero) { next = ancestor; }
            if (next == IntPtr.Zero || next == cur) { break; }
            int pid = PidOf(next);
            if (pid > 0) { root = pid; }
            if (focusPidArg > 0 && pid == focusPidArg) { return pid; }
            cur = next;
        }
        return root;
    }

    static string ReadClass(IntPtr hWnd) {
        var sb = new StringBuilder(128);
        GetClassName(hWnd, sb, sb.Capacity);
        return sb.ToString();
    }

    static string QuickText(IntPtr hWnd) {
        var direct = new StringBuilder(512);
        GetWindowText(hWnd, direct, direct.Capacity);
        return direct.ToString().Trim();
    }

    static string ReadTextParts(IntPtr hWnd, string className, bool deep, out int directLen, out int sentLen) {
        string direct = QuickText(hWnd);
        directLen = direct.Length;
        sentLen = 0;
        bool send = deep || IsDialogClass(className) || directLen > 0;
        if (!send) { return direct; }
        var sb = new StringBuilder(512);
        IntPtr unused;
        uint timeout = deep ? (uint)200 : (uint)50;
        SendMessageTimeout(hWnd, WM_GETTEXT, (IntPtr)sb.Capacity, sb, SMTO_ABORTIFHUNG, timeout, out unused);
        string sent = sb.ToString().Trim();
        sentLen = sent.Length;
        if (HasNeedle(sent)) { return sent; }
        if (HasNeedle(direct)) { return direct; }
        if (sentLen > directLen) { return sent; }
        return direct;
    }

    static bool IsDialogClass(string className) {
        if (string.IsNullOrEmpty(className)) { return false; }
        if (className == "#32770") { return true; }
        if (className == "NUIDialog") { return true; }
        if (className == "bosa_sdm_XL9") { return true; }
        if (className == "NetUIHWND") { return true; }
        if (className.IndexOf("bosa_sdm", StringComparison.Ordinal) >= 0) { return true; }
        if (className.IndexOf("Dialog", StringComparison.Ordinal) >= 0) { return true; }
        return false;
    }

    static bool IsOfficeProcess(string leaf) {
        if (string.IsNullOrEmpty(leaf)) { return false; }
        string[] names = new string[] {
            "EXCEL",
            "OfficeClickToRun",
            "OfficeC2RClient",
            "sdxhelper",
            "AppVShNotify",
            "MsoSync",
            "integrator",
            "OfficeBackgroundTaskHandler"
        };
        for (int i = 0; i < names.Length; i++) {
            if (string.Equals(leaf, names[i], StringComparison.OrdinalIgnoreCase)) { return true; }
        }
        return false;
    }

    static string ProcessLeaf(int pid) {
        if (pid <= 0) { return ""; }
        string cached;
        if (processNames.TryGetValue(pid, out cached)) { return cached; }
        string leaf = "";
        IntPtr handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, (uint)pid);
        if (handle != IntPtr.Zero) {
            try {
                int size = 260;
                var sb = new StringBuilder(size);
                if (QueryFullProcessImageName(handle, 0, sb, ref size)) {
                    string full = sb.ToString();
                    int slash = full.LastIndexOf('\\');
                    leaf = slash >= 0 ? full.Substring(slash + 1) : full;
                    if (leaf.EndsWith(".exe", StringComparison.OrdinalIgnoreCase) && leaf.Length > 4) {
                        leaf = leaf.Substring(0, leaf.Length - 4);
                    }
                }
            } finally {
                CloseHandle(handle);
            }
        }
        processNames[pid] = leaf;
        return leaf;
    }

    static string DesktopName(uint tid) {
        if (tid == 0) { return ""; }
        IntPtr desk = GetThreadDesktop(tid);
        if (desk == IntPtr.Zero) { return ""; }
        int needed;
        GetUserObjectInformation(desk, UOI_NAME, IntPtr.Zero, 0, out needed);
        if (needed <= 0 || needed > 512) { return ""; }
        IntPtr buf = Marshal.AllocHGlobal(needed);
        try {
            int ignored;
            if (!GetUserObjectInformation(desk, UOI_NAME, buf, needed, out ignored)) { return ""; }
            string name = Marshal.PtrToStringUni(buf);
            if (name == null) { return ""; }
            return name;
        } finally {
            Marshal.FreeHGlobal(buf);
        }
    }

    static int DesktopMatch(string left, string right) {
        if (string.IsNullOrEmpty(left) || string.IsNullOrEmpty(right)) { return -1; }
        if (string.Equals(left, right, StringComparison.OrdinalIgnoreCase)) { return 1; }
        return 0;
    }

    static bool HasNeedle(string text) {
        if (string.IsNullOrEmpty(text)) { return false; }
        if (text.IndexOf("\u91cd\u5927\u306a\u30a8\u30e9\u30fc", StringComparison.Ordinal) >= 0) { return true; }
        if (text.IndexOf("\u3053\u306e\u30c9\u30ad\u30e5\u30e1\u30f3\u30c8\u3092\u958b\u304d\u307e\u3059\u304b", StringComparison.Ordinal) >= 0) { return true; }
        if (text.IndexOf("serious problem", StringComparison.OrdinalIgnoreCase) >= 0) { return true; }
        if (text.IndexOf("serious error", StringComparison.OrdinalIgnoreCase) >= 0) { return true; }
        return false;
    }
}
'@
}

function New-EmptyDialog {
    param([string]$Visible)
    return (New-Object psobject -Property @{
        Visible = $Visible
        Pid = 0
        OwnerPid = 0
        ParentPid = 0
        Class = ''
        Hwnd = [int64]0
        OwnerHwnd = [int64]0
        ParentHwnd = [int64]0
        HasLeaf = '0'
        HasSerious = '0'
        HasReopen = '0'
        Match = 'none'
        Source = ''
        SameProcess = '0'
        OwnerLinked = '0'
        TopLevelSeen = 0
        FocusTopLevel = 0
        DialogClassCount = 0
        StandardDialogCount = 0
        ChildSeen = 0
        ChildTruncated = 0
        CandidateCount = 0
        ForegroundHwnd = [int64]0
        ForegroundPid = 0
        ForegroundTid = 0
        ForegroundClass = ''
        ScriptDesktop = ''
        FocusDesktop = ''
        ForegroundDesktop = ''
        DesktopFocusMatch = -1
        DesktopForegroundMatch = -1
        Rows = @()
    })
}

function Get-DialogEvidence {
    param([int]$FocusPid, [int]$SessionId)
    $info = New-EmptyDialog -Visible '0'
    try {
        Add-CanonicalWindowType
    } catch {
        $info.Visible = 'unreadable'
        return $info
    }
    $survey = $null
    try {
        $survey = [CanonicalWindowSurvey]::Collect([int]$FocusPid)
    } catch {
        $info.Visible = 'unreadable'
        return $info
    }
    if ($null -eq $survey) {
        $info.Visible = 'unreadable'
        return $info
    }
    $info.TopLevelSeen = [int]$survey.TopLevelSeen
    $info.FocusTopLevel = [int]$survey.FocusTopLevel
    $info.DialogClassCount = [int]$survey.DialogClassCount
    $info.StandardDialogCount = [int]$survey.StandardDialogCount
    $info.ChildSeen = [int]$survey.ChildSeen
    $info.ChildTruncated = [int]$survey.ChildTruncated
    $info.CandidateCount = [int]$survey.CandidateCount
    $info.ForegroundHwnd = [int64]$survey.ForegroundHwnd
    $info.ForegroundPid = [int]$survey.ForegroundPid
    $info.ForegroundTid = [int]$survey.ForegroundTid
    $info.ForegroundClass = [string]$survey.ForegroundClass
    $info.ScriptDesktop = [string]$survey.ScriptDesktop
    $info.FocusDesktop = [string]$survey.FocusDesktop
    $info.ForegroundDesktop = [string]$survey.ForegroundDesktop
    $info.DesktopFocusMatch = [int]$survey.DesktopFocusMatch
    $info.DesktopForegroundMatch = [int]$survey.DesktopForegroundMatch
    $rows = New-Object System.Collections.Generic.List[object]
    $hits = $survey.Hits
    if ($null -ne $hits) {
    foreach ($hit in $hits) {
        if ($null -eq $hit) { continue }
        $pidValue = [int]$hit.Pid
        $ownerValue = [int]$hit.OwnerPid
        $rootValue = [int]$hit.RootPid
        $roleValue = [string]$hit.Role
        $linked = (($FocusPid -gt 0) -and (($pidValue -eq $FocusPid) -or ($ownerValue -eq $FocusPid) -or ([int]$hit.ParentPid -eq $FocusPid) -or ($rootValue -eq $FocusPid)))
        $needle = ([int]$hit.Needle -eq 1)
        $roleKeep = ($roleValue -eq 'foreground') -or ($roleValue -eq 'guithread') -or ([int]$hit.Foreground -eq 1) -or ([int]$hit.GuiActive -eq 1)
        $sessionOk = $true
        if ((-not $linked) -and (-not $needle) -and (-not $roleKeep) -and ($SessionId -ge 0) -and ($pidValue -gt 0)) {
            $sid = -1
            try { $sid = [int](Get-Process -Id $pidValue -ErrorAction Stop).SessionId } catch { $sid = -1 }
            if (($sid -ge 0) -and ($sid -ne $SessionId)) { $sessionOk = $false }
        }
        if (-not $sessionOk) { continue }
        [void]$rows.Add((New-Object psobject -Property @{
            Pid = $pidValue
            OwnerPid = $ownerValue
            ParentPid = [int]$hit.ParentPid
            Class = [string]$hit.ClassName
            Title = [string]$hit.Title
            ChildText = [string]$hit.ChildText
            Hwnd = [int64]$hit.Hwnd
            OwnerHwnd = [int64]$hit.OwnerHwnd
            ParentHwnd = [int64]$hit.ParentHwnd
            TitleLen = [int]$hit.TitleLen
            ChildLen = [int]$hit.ChildLen
            Needle = [int]$hit.Needle
            Tid = [int]$hit.Tid
            RootPid = $rootValue
            Depth = [int]$hit.Depth
            Foreground = [int]$hit.Foreground
            GuiActive = [int]$hit.GuiActive
            Role = $roleValue
            Process = [string]$hit.ProcessName
            DirectLen = [int]$hit.DirectLen
            SentLen = [int]$hit.SentLen
            VisibleFlag = [int]$hit.Visible
        }))
    }
    }
    $picked = Select-DialogHit -FocusPid $FocusPid -Rows $rows.ToArray()
    $info.Visible = [string]$picked.Visible
    $info.Pid = [int]$picked.Pid
    $info.OwnerPid = [int]$picked.OwnerPid
    $info.ParentPid = [int]$picked.ParentPid
    $info.Class = [string]$picked.Class
    $info.Hwnd = [int64]$picked.Hwnd
    $info.OwnerHwnd = [int64]$picked.OwnerHwnd
    $info.ParentHwnd = [int64]$picked.ParentHwnd
    $info.HasLeaf = [string]$picked.HasLeaf
    $info.HasSerious = [string]$picked.HasSerious
    $info.HasReopen = [string]$picked.HasReopen
    $info.Match = [string]$picked.Match
    $info.Source = [string]$picked.Source
    $info.SameProcess = [string]$picked.SameProcess
    $info.OwnerLinked = [string]$picked.OwnerLinked
    $info.Rows = $rows.ToArray()
    return $info
}

function Read-UiTree {
    param($Element, $List, $Best, [int]$Depth, $State, [int64]$Hwnd, [int]$PidValue)
    if ($null -eq $Element) { return }
    if ($Depth -gt 8) { return }
    if ([int]$State.Examined -ge 250) { return }
    $State.Examined = [int]$State.Examined + 1
    $name = ''
    $className = ''
    $control = ''
    try { $name = [string]$Element.Current.Name } catch { $name = '' }
    try { $className = [string]$Element.Current.ClassName } catch { $className = '' }
    try { $control = [string]$Element.Current.ControlType.ProgrammaticName } catch { $control = '' }
    $hasLeaf = '0'
    $hasSerious = '0'
    $hasReopen = '0'
    $needle = 0
    if (Test-SeriousErrorText -Text $name) { $needle = 1 }
    if ($name.IndexOf($script:Leaf, $script:OrdinalIgnore) -ge 0) { $hasLeaf = '1' }
    if ($name.IndexOf($script:SeriousErrorJa, $script:Ordinal) -ge 0) { $hasSerious = '1' }
    if ($name.IndexOf($script:ReopenDocumentJa, $script:Ordinal) -ge 0) { $hasReopen = '1' }
    $store = ($needle -eq 1) -or (($name.Length -gt 0) -and ($List.Count -lt 40))
    if ($store) {
        [void]$List.Add((New-Object psobject -Property @{
            Hwnd = $Hwnd
            Pid = $PidValue
            ClassName = $className
            Control = $control
            NameLen = $name.Length
            Needle = $needle
        }))
    }
    if ($needle -eq 1) {
        $score = 1
        if (($hasLeaf -eq '1') -and ($hasSerious -eq '1')) { $score = 3 }
        if ($score -gt [int]$Best.Score) {
            $Best.Score = $score
            $Best.Needle = '1'
            $Best.Hwnd = $Hwnd
            $Best.Pid = $PidValue
            $Best.Class = $className
            $Best.HasLeaf = $hasLeaf
            $Best.HasSerious = $hasSerious
            $Best.HasReopen = $hasReopen
            if ($score -ge 3) { $Best.Match = 'canonical_serious_error' }
            else { $Best.Match = 'serious_error_needle' }
        }
    }
    if ([int]$State.Examined -ge 250) { return }
    try {
        $walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
        $child = $walker.GetFirstChild($Element)
        $seen = 0
        while (($null -ne $child) -and ($seen -lt 50) -and ([int]$State.Examined -lt 250)) {
            Read-UiTree -Element $child -List $List -Best $Best -Depth ($Depth + 1) -State $State -Hwnd $Hwnd -PidValue $PidValue
            $child = $walker.GetNextSibling($child)
            $seen = $seen + 1
        }
    } catch {}
}

function Get-UiSurvey {
    param($Dialog, [int]$FocusPid, [int64]$FallbackHwnd)
    $result = New-Object psobject -Property @{
        Status = 'unreadable'
        Apartment = 'unreadable'
        Examined = 0
        Named = 0
        Needle = '0'
        Hwnd = [int64]0
        Pid = 0
        Class = ''
        HasLeaf = '0'
        HasSerious = '0'
        HasReopen = '0'
        Match = 'none'
        Nodes = @()
    }
    try { $result.Apartment = [string][Threading.Thread]::CurrentThread.GetApartmentState() } catch { $result.Apartment = 'unreadable' }
    if (-not [string]::Equals([string]$result.Apartment, 'STA', $script:Ordinal)) {
        $result.Status = 'not_sta'
        return $result
    }
    $targets = New-Object System.Collections.Generic.List[object]
    $seenHwnd = New-Object System.Collections.Generic.List[string]
    if ($FallbackHwnd -gt 0) {
        [void]$targets.Add((New-Object psobject -Property @{ Hwnd = $FallbackHwnd; Pid = $FocusPid }))
        [void]$seenHwnd.Add($FallbackHwnd.ToString())
    }
    foreach ($row in @($Dialog.Rows)) {
        if ($null -eq $row) { continue }
        if ($targets.Count -ge 4) { break }
        $className = [string]$row.Class
        $wanted = (Test-DialogClassName -ClassName $className) -or ($className -eq 'XLMAIN')
        if (-not $wanted) { continue }
        $hwndText = ([int64]$row.Hwnd).ToString()
        if ($seenHwnd.Contains($hwndText)) { continue }
        [void]$seenHwnd.Add($hwndText)
        [void]$targets.Add((New-Object psobject -Property @{ Hwnd = [int64]$row.Hwnd; Pid = [int]$row.Pid }))
    }
    try {
        Add-Type -AssemblyName UIAutomationClient -ErrorAction Stop
    } catch {
        $result.Status = 'assembly_missing'
        return $result
    }
    $nodes = New-Object System.Collections.Generic.List[object]
    $best = New-Object psobject -Property @{
        Score = 0
        Needle = '0'
        Hwnd = [int64]0
        Pid = 0
        Class = ''
        HasLeaf = '0'
        HasSerious = '0'
        HasReopen = '0'
        Match = 'none'
    }
    $state = New-Object psobject -Property @{ Examined = 0 }
    foreach ($target in $targets) {
        if ([int]$state.Examined -ge 250) { break }
        $hwnd = [int64]$target.Hwnd
        if ($hwnd -le 0) { continue }
        try {
            $root = [System.Windows.Automation.AutomationElement]::FromHandle(([IntPtr]$hwnd))
            Read-UiTree -Element $root -List $nodes -Best $best -Depth 0 -State $state -Hwnd $hwnd -PidValue ([int]$target.Pid)
        } catch {}
    }
    $result.Status = 'ok'
    $result.Examined = [int]$state.Examined
    $result.Named = $nodes.Count
    $result.Needle = [string]$best.Needle
    $result.Hwnd = [int64]$best.Hwnd
    $result.Pid = [int]$best.Pid
    $result.Class = [string]$best.Class
    $result.HasLeaf = [string]$best.HasLeaf
    $result.HasSerious = [string]$best.HasSerious
    $result.HasReopen = [string]$best.HasReopen
    $result.Match = [string]$best.Match
    $result.Nodes = $nodes.ToArray()
    return $result
}

function Invoke-LiveDiagnose {
    param([int]$FocusPid)
    Write-Output 'ACTION=diagnose_canonical_serious_error_readonly'
    Write-Output 'READ_ONLY=1'
    Write-Output 'NOTHING_TOUCHED=1'
    Write-Output 'REGISTRY_CHANGED=0'
    Write-Output 'EXCEL_PROCESSES_TOUCHED=0'
    Write-Output 'WORKBOOK_CHANGED=0'
    Write-Output 'XLL_CHANGED=0'
    Write-Output 'DIALOG_TOUCHED=0'
    Write-Output 'DIALOG_CLICKED=0'
    Write-Output 'EXCEL_STOP_REQUESTED=0'
    Write-Output 'ROT_QUERIED=0'
    Write-Output 'DIALOG_OPERATION=none'
    Write-Output 'REGISTRY_OPERATION=read'
    Write-Output 'PROCESS_OPERATION=read'
    Write-Output ('LAUNCHED_PID=' + $FocusPid.ToString())
    $mySession = -1
    try { $mySession = [int](Get-Process -Id $PID).SessionId } catch { $mySession = -1 }
    Write-Output ('SCRIPT_SESSION=' + $mySession.ToString())

    $processList = @()
    $processOk = $false
    try {
        $processList = @(Get-ProcessRows)
        $processOk = $true
    } catch {
        Write-Output 'SECTION_ERROR=process_list'
        Write-Output ('SECTION_ERROR_TYPE=' + $_.Exception.GetType().Name)
    }
    Write-Output ('PROCESS_LIST=' + $(if ($processOk) { 'ok' } else { 'failed' }))
    $parentPid = 0
    $command = ''
    $truncated = '0'
    if ($processList.Count -ge 20) { $truncated = '1' }
    Write-Output ('EXCEL_TRUNCATED=' + $truncated)
    foreach ($proc in $processList) {
        if ($null -eq $proc) { continue }
        if ([int]$proc.Pid -eq $FocusPid) {
            $parentPid = [int]$proc.Parent
            $command = [string]$proc.Command
        }
    }
    $flags = Get-CommandFlags -Command $command
    $xll = Get-XllEvidence -ProcId $FocusPid
    $startKnown = ($xll.StartTicks -gt 0)
    Write-Output ('LAUNCHED_ALIVE=' + $xll.Alive)
    Write-Output ('LAUNCHED_HWND=' + $xll.Hwnd.ToString())
    Write-Output ('LAUNCHED_START_UTC=' + $xll.StartUtc)
    Write-Output ('LAUNCHED_XLL=' + $xll.Loaded)
    Write-Output ('LAUNCHED_XLL_OTHER_COUNT=' + $xll.OtherCount.ToString())
    Write-Output ('LAUNCHED_XLL_LENGTH=' + $xll.Length.ToString())
    Write-Output ('LAUNCHED_XLL_WRITE_UTC=' + $xll.WriteUtc)
    Write-Output ('LAUNCHED_XLL_PATH=' + $xll.PathLabel)
    Write-Output ('LAUNCHED_PARENT=' + $parentPid.ToString())
    Write-Output ('LAUNCHED_CANONICAL=' + $flags.Canonical)
    Write-Output ('LAUNCHED_EMBEDDING=' + $flags.Embedding)
    Write-Output ('LAUNCHED_ISOLATED=' + $flags.Isolated)
    $sessionMatch = 'unreadable'
    if ($mySession -ge 0 -and $xll.Session -ge 0) {
        if ($xll.Session -eq $mySession) { $sessionMatch = '1' } else { $sessionMatch = '0' }
    }
    Write-Output ('LAUNCHED_SESSION_MATCH=' + $sessionMatch)

    $dialogIds = New-Object System.Collections.Generic.List[int]
    foreach ($proc in $processList) {
        if ($null -eq $proc) { continue }
        $rowXll = $null
        try { $rowXll = Get-XllEvidence -ProcId ([int]$proc.Pid) } catch { $rowXll = $null }
        $alive = '0'
        $hwnd = [int64]0
        $loaded = 'unreadable'
        $same = 'unreadable'
        if ($null -ne $rowXll) {
            $alive = [string]$rowXll.Alive
            $hwnd = [int64]$rowXll.Hwnd
            $loaded = [string]$rowXll.Loaded
            if ($mySession -ge 0 -and $rowXll.Session -ge 0) {
                if ([int]$rowXll.Session -eq $mySession) { $same = '1' } else { $same = '0' }
            }
        }
        $rowFlags = Get-CommandFlags -Command ([string]$proc.Command)
        Write-Output ('EXCEL pid=' + ([int]$proc.Pid).ToString() + ' parent=' + ([int]$proc.Parent).ToString() + ' alive=' + $alive + ' same_session=' + $same + ' canonical=' + $rowFlags.Canonical + ' embedding=' + $rowFlags.Embedding + ' isolated=' + $rowFlags.Isolated + ' hwnd=' + $hwnd.ToString() + ' xll=' + $loaded)
        if ($same -eq '1') { [void]$dialogIds.Add([int]$proc.Pid) }
    }

    $snap = $null
    $registryOk = $false
    try {
        $snap = Read-ResiliencySnapshot
        $registryOk = $true
    } catch {
        Write-Output 'SECTION_ERROR=resiliency'
        Write-Output ('SECTION_ERROR_TYPE=' + $_.Exception.GetType().Name)
    }
    $rows = @()
    if ($registryOk -and $null -ne $snap) {
        $rows = @($snap.Rows)
        Write-Output ('RESILIENCY_ABSENT=' + [string]$snap.Absent)
        Write-Output ('RESILIENCY_UNSUPPORTED=' + ([int]$snap.Unsupported).ToString())
        Write-Output ('RESILIENCY_VALUE_CAP=' + [string]$snap.Cap)
        foreach ($sub in @($snap.Subkeys)) {
            Write-Output ('RESILIENCY_SUBKEY=' + (Get-SafeLabel -Name ([string]$sub)))
        }
        $counts = Get-MatchCounts -Rows $rows
        Write-Output ('MATCH_PURE=' + $counts.Pure.ToString())
        Write-Output ('MATCH_IMPURE=' + $counts.Impure.ToString())
        Write-Output ('MATCH_OUTSIDE=' + $counts.Outside.ToString())
        Write-Output ('MATCH_NONE=' + $counts.None.ToString())
        $scan = 0
        $crashXll = '0'
        foreach ($row in $rows) {
            if ($null -eq $row) { continue }
            $head = Get-ResiliencyHead -Key ([string]$row.Key)
            if ([string]::Equals($head, 'CrashingAddinList', $script:OrdinalIgnore) -and ([string]$row.HasXll -eq '1')) {
                $crashXll = '1'
            }
            if ([string]$row.Verdict -eq 'none') { continue }
            $scan = $scan + 1
            if ($scan -gt 30) { continue }
            $rel = Get-ResiliencyRelative -Key ([string]$row.Key)
            Write-Output ('SCAN area=' + [string]$row.Area + ' rel=' + (Get-RelLabel -Name $rel) + ' value=' + (Get-SafeLabel -Name ([string]$row.ValueName)) + ' kind=' + [string]$row.Kind + ' len=' + ([int]$row.Length).ToString() + ' verdict=' + [string]$row.Verdict + ' sha=' + [string]$row.Sha)
        }
        if ($scan -gt 30) { Write-Output 'SCAN_TRUNCATED=1' }
        Write-Output ('CRASHING_ADDIN_XLL=' + $crashXll)
    } else {
        Write-Output 'RESILIENCY_READ=failed'
    }

    $keyFlags = New-Object System.Collections.Generic.List[string]
    $childWriteFlags = New-Object System.Collections.Generic.List[string]
    $rootFlag = $null
    if ($registryOk -and $null -ne $snap -and [string]$snap.Absent -eq '0') {
        $rootFlag = Get-KeyWriteFlag -Relative $script:ResiliencyRoot -StartTicks ([int64]$xll.StartTicks) -StartKnown $startKnown
        Write-Output ('KEY_WRITE name=' + $rootFlag.Name + ' after_start=' + $rootFlag.Flag + ' write_utc=' + $rootFlag.WriteUtc)
        [void]$keyFlags.Add([string]$rootFlag.Flag)
        foreach ($sub in @($snap.Subkeys)) {
            $rel = $script:ResiliencyRoot + '\' + [string]$sub
            $flag = Get-KeyWriteFlag -Relative $rel -StartTicks ([int64]$xll.StartTicks) -StartKnown $startKnown
            $subCount = Get-SubkeyValueCount -SubName ([string]$sub) -Rows $rows
            Write-Output ('KEY_WRITE name=' + $flag.Name + ' after_start=' + $flag.Flag + ' write_utc=' + $flag.WriteUtc)
            Write-Output ('SUBKEY_AUDIT name=' + $flag.Name + ' values=' + $subCount.ToString() + ' after_start=' + $flag.Flag)
            [void]$keyFlags.Add([string]$flag.Flag)
            [void]$childWriteFlags.Add([string]$flag.Flag)
        }
        $rootRows = @(Get-RootValueRows -Rows $rows)
        Write-Output ('ROOT_VALUE_COUNT=' + $rootRows.Count.ToString())
        $rootShown = 0
        foreach ($rootValue in $rootRows) {
            if ($null -eq $rootValue) { continue }
            if ($rootShown -ge 20) { break }
            Write-Output ('ROOT_VALUE name=' + (Get-SafeLabel -Name ([string]$rootValue.ValueName)) + ' kind=' + [string]$rootValue.Kind + ' len=' + ([int]$rootValue.Length).ToString() + ' verdict=' + [string]$rootValue.Verdict + ' xll=' + [string]$rootValue.HasXll + ' sha=' + [string]$rootValue.Sha)
            $rootShown = $rootShown + 1
        }
        if ($rootRows.Count -gt 20) { Write-Output 'ROOT_VALUE_TRUNCATED=1' }
        $touchScope = Get-TouchScope -RootFlag ([string]$rootFlag.Flag) -ChildFlags $childWriteFlags.ToArray() -RootValueCount $rootRows.Count
        $touchDelay = Get-TouchDelaySeconds -StartUtc ([string]$xll.StartUtc) -WriteUtc ([string]$rootFlag.WriteUtc)
        Write-Output ('TOUCH_SCOPE=' + $touchScope)
        Write-Output ('TOUCH_DELAY_SEC=' + ([int]$touchDelay.Seconds).ToString())
        Write-Output ('TOUCH_CORRELATION=' + [string]$touchDelay.Correlation)
        Write-Output 'WRITER_PID=unavailable'
    }
    $keyWrite = 'unreadable'
    if ($keyFlags.Count -gt 0) { $keyWrite = Get-AggregateFlag -Parts $keyFlags.ToArray() }
    elseif ($registryOk -and $null -ne $snap -and [string]$snap.Absent -eq '1') { $keyWrite = '0' }

    $backup = $null
    try {
        $backup = Read-BackupEvidence -Rows $rows
    } catch {
        Write-Output 'SECTION_ERROR=backup'
        Write-Output ('SECTION_ERROR_TYPE=' + $_.Exception.GetType().Name)
    }
    if ($null -eq $backup) {
        $backup = New-Object psobject -Property @{
            State = 'backup_unreadable'
            Sha = ''
            Area = ''
            ValueName = ''
            Verdict = ''
            SamePlace = '0'
            FileHashOk = '0'
            Recreated = 'unreadable'
            Other = '0'
            Replaced = '0'
            Leaf = ''
        }
    }
    Write-Output ('BACKUP_STATE=' + [string]$backup.State)
    Write-Output ('BACKUP_FILE_HASH_OK=' + [string]$backup.FileHashOk)
    Write-Output ('BACKUP_LEAF=' + [string]$backup.Leaf)
    Write-Output ('BACKUP_AREA=' + [string]$backup.Area)
    Write-Output ('BACKUP_VALUE=' + [string]$backup.ValueName)
    Write-Output ('BACKUP_SHA256=' + [string]$backup.Sha)
    Write-Output ('BACKUP_VERDICT=' + [string]$backup.Verdict)
    Write-Output ('BACKUP_SAME_PLACE=' + [string]$backup.SamePlace)

    $recreated = [string]$backup.Recreated
    $other = [string]$backup.Other
    $replaced = [string]$backup.Replaced
    if (-not $registryOk) {
        $recreated = 'unreadable'
        $other = 'unreadable'
        $replaced = 'unreadable'
    }

    $bookPath = ''
    $book = $null
    try {
        $bookPath = Find-WorkbookPath
        $book = Get-WorkbookEvidence -Path $bookPath -StartTicks ([int64]$xll.StartTicks) -StartKnown $startKnown
    } catch {
        Write-Output 'SECTION_ERROR=workbook'
        Write-Output ('SECTION_ERROR_TYPE=' + $_.Exception.GetType().Name)
    }
    if ($null -eq $book) {
        $book = New-Object psobject -Property @{
            Exists = '0'
            Length = [int64]0
            WriteUtc = ''
            Rewritten = 'unreadable'
            Open = 'failed'
            Zone = 'absent'
            Vba = '0'
            ExternalLinks = 0
            PackageXml = 'unreadable'
            FileRecovery = 'unreadable'
            CrashSave = 'unreadable'
            RepairLoad = 'unreadable'
            AutoRecover = 'unreadable'
            DataExtract = 'unreadable'
            AppRecovery = 'unreadable'
            CustomRecovery = 'unreadable'
            PartCount = 0
            PartNames = ''
            XmlReason = 'unreadable'
            XmlBytes = 0
            EntryName = ''
        }
    }
    Write-Output ('WORKBOOK_EXISTS=' + [string]$book.Exists)
    Write-Output ('WORKBOOK_LENGTH=' + ([int64]$book.Length).ToString())
    Write-Output ('WORKBOOK_WRITE_UTC=' + [string]$book.WriteUtc)
    Write-Output ('WORKBOOK_OPEN=' + [string]$book.Open)
    Write-Output ('WORKBOOK_VBA=' + [string]$book.Vba)
    Write-Output ('WORKBOOK_EXTERNAL_LINKS=' + ([int]$book.ExternalLinks).ToString())
    Write-Output ('WORKBOOK_ZONE=' + [string]$book.Zone)
    Write-Output ('WORKBOOK_REWRITTEN=' + [string]$book.Rewritten)
    Write-Output ('PACKAGE_WORKBOOK_XML=' + [string]$book.PackageXml)
    Write-Output ('PACKAGE_FILE_RECOVERY=' + [string]$book.FileRecovery)
    Write-Output ('PACKAGE_CRASH_SAVE=' + [string]$book.CrashSave)
    Write-Output ('PACKAGE_REPAIR_LOAD=' + [string]$book.RepairLoad)
    Write-Output ('PACKAGE_AUTO_RECOVER=' + [string]$book.AutoRecover)
    Write-Output ('PACKAGE_DATA_EXTRACT=' + [string]$book.DataExtract)
    Write-Output ('PACKAGE_APP_RECOVERY=' + [string]$book.AppRecovery)
    Write-Output ('PACKAGE_CUSTOM_RECOVERY=' + [string]$book.CustomRecovery)
    Write-Output ('PACKAGE_RECOVERY_PARTS=' + ([int]$book.PartCount).ToString())
    Write-Output ('PACKAGE_PARTS=' + [string]$book.PartNames)
    Write-Output ('PACKAGE_XML_REASON=' + [string]$book.XmlReason)
    Write-Output ('PACKAGE_XML_BYTES=' + ([int]$book.XmlBytes).ToString())
    Write-Output ('PACKAGE_ENTRY=' + [string]$book.EntryName)

    $sibling = $null
    try { $sibling = Get-SiblingEvidence -WorkbookPath $bookPath -StartTicks ([int64]$xll.StartTicks) -StartKnown $startKnown } catch {
        Write-Output 'SECTION_ERROR=sibling'
        Write-Output ('SECTION_ERROR_TYPE=' + $_.Exception.GetType().Name)
    }
    if ($null -eq $sibling) {
        $sibling = New-Object psobject -Property @{
            LockExists = 'unreadable'
            LockWriteUtc = ''
            LockRelation = 'unreadable'
            XlkExists = 'unreadable'
            XlkWriteUtc = ''
            XlkRelation = 'unreadable'
        }
    }
    Write-Output ('LOCKFILE_EXISTS=' + [string]$sibling.LockExists)
    Write-Output ('LOCKFILE_WRITE_UTC=' + [string]$sibling.LockWriteUtc)
    Write-Output ('LOCKFILE_RELATION=' + [string]$sibling.LockRelation)
    Write-Output ('XLK_EXISTS=' + [string]$sibling.XlkExists)
    Write-Output ('XLK_WRITE_UTC=' + [string]$sibling.XlkWriteUtc)
    Write-Output ('XLK_RELATION=' + [string]$sibling.XlkRelation)
    $xllFile = Get-TouchDelaySeconds -StartUtc ([string]$xll.StartUtc) -WriteUtc ([string]$xll.WriteUtc)
    Write-Output ('XLL_FILE_DELTA_SEC=' + ([int]$xllFile.Seconds).ToString())
    Write-Output ('XLL_FILE_CORRELATION=' + [string]$xllFile.Correlation)

    $startup = $null
    try { $startup = Get-StartupEvidence } catch {
        Write-Output 'SECTION_ERROR=startup'
        Write-Output ('SECTION_ERROR_TYPE=' + $_.Exception.GetType().Name)
    }
    if ($null -eq $startup) {
        $startup = New-Object psobject -Property @{
            XlStartCount = -1
            XlStartCanonical = 'unreadable'
            XlStartNames = ''
            UnsavedExists = 'unreadable'
            UnsavedCount = -1
        }
    }
    Write-Output ('XLSTART_COUNT=' + ([int]$startup.XlStartCount).ToString())
    Write-Output ('XLSTART_CANONICAL=' + [string]$startup.XlStartCanonical)
    Write-Output ('XLSTART_NAMES=' + [string]$startup.XlStartNames)
    Write-Output ('UNSAVED_EXISTS=' + [string]$startup.UnsavedExists)
    Write-Output ('UNSAVED_COUNT=' + ([int]$startup.UnsavedCount).ToString())

    $trust = $null
    try { $trust = Get-TrustEvidence } catch {
        Write-Output 'SECTION_ERROR=trust'
        Write-Output ('SECTION_ERROR_TYPE=' + $_.Exception.GetType().Name)
    }
    if ($null -eq $trust) {
        $trust = New-Object psobject -Property @{
            Canonical = 'unreadable'
            OtherCount = -1
            CanonicalCount = -1
            ValueKind = 'unreadable'
            ValueLen = -1
            ValueSha = ''
        }
    }
    Write-Output ('TRUST_CANONICAL=' + [string]$trust.Canonical)
    Write-Output ('TRUST_CANONICAL_COUNT=' + ([int]$trust.CanonicalCount).ToString())
    Write-Output ('TRUST_OTHER_COUNT=' + ([int]$trust.OtherCount).ToString())
    Write-Output ('TRUST_VALUE_KIND=' + [string]$trust.ValueKind)
    Write-Output ('TRUST_VALUE_LEN=' + ([int]$trust.ValueLen).ToString())
    Write-Output ('TRUST_VALUE_SHA=' + [string]$trust.ValueSha)
    $pvPath = 'Software\Microsoft\Office\16.0\Excel\Security\ProtectedView'
    $validationPath = 'Software\Microsoft\Office\16.0\Excel\Security\FileValidation'
    $blockPath = 'Software\Microsoft\Office\16.0\Excel\Security\FileBlock'
    Write-Output ('OFFICE_PV_ATTACHMENTS=' + (Read-OfficeNumber -SubPath $pvPath -Name 'DisableAttachmentsInPV'))
    Write-Output ('OFFICE_PV_INTERNET=' + (Read-OfficeNumber -SubPath $pvPath -Name 'DisableInternetFilesInPV'))
    Write-Output ('OFFICE_PV_UNSAFE=' + (Read-OfficeNumber -SubPath $pvPath -Name 'DisableUnsafeLocationsInPV'))
    Write-Output ('OFFICE_VALIDATION_ONLOAD=' + (Read-OfficeNumber -SubPath $validationPath -Name 'EnableOnLoad'))
    Write-Output ('OFFICE_FILEBLOCK_PV=' + (Read-OfficeNumber -SubPath $blockPath -Name 'OpenInProtectedView'))
    $addin = $null
    try { $addin = Get-AddinOpenCounts } catch {
        Write-Output 'SECTION_ERROR=addin'
        Write-Output ('SECTION_ERROR_TYPE=' + $_.Exception.GetType().Name)
    }
    if ($null -eq $addin) {
        $addin = New-Object psobject -Property @{ Rss = 'unreadable'; Other = -1; Manager = 'unreadable'; Key = 'unreadable' }
    }
    Write-Output ('ADDIN_OPEN_RSS=' + [string]$addin.Rss)
    Write-Output ('ADDIN_OPEN_OTHER_XLL=' + ([int]$addin.Other).ToString())
    Write-Output ('ADDIN_MANAGER_RSS=' + [string]$addin.Manager)
    Write-Output ('ADDIN_KEY_RSS=' + [string]$addin.Key)

    $dialog = $null
    try { $dialog = Get-DialogEvidence -FocusPid $FocusPid -SessionId $mySession } catch {
        Write-Output 'SECTION_ERROR=dialog'
        Write-Output ('SECTION_ERROR_TYPE=' + $_.Exception.GetType().Name)
    }
    if ($null -eq $dialog) { $dialog = New-EmptyDialog -Visible 'unreadable' }
    $focusDesk = 'unreadable'
    if ([int]$dialog.DesktopFocusMatch -eq 1) { $focusDesk = '1' }
    elseif ([int]$dialog.DesktopFocusMatch -eq 0) { $focusDesk = '0' }
    $fgDesk = 'unreadable'
    if ([int]$dialog.DesktopForegroundMatch -eq 1) { $fgDesk = '1' }
    elseif ([int]$dialog.DesktopForegroundMatch -eq 0) { $fgDesk = '0' }
    Write-Output ('WINDOW_TOPLEVEL_SEEN=' + ([int]$dialog.TopLevelSeen).ToString())
    Write-Output ('WINDOW_FOCUS_TOPLEVEL=' + ([int]$dialog.FocusTopLevel).ToString())
    Write-Output ('WINDOW_DIALOG_CLASS=' + ([int]$dialog.DialogClassCount).ToString())
    Write-Output ('WINDOW_CLASS_32770=' + ([int]$dialog.StandardDialogCount).ToString())
    Write-Output ('WINDOW_CHILD_SEEN=' + ([int]$dialog.ChildSeen).ToString())
    Write-Output ('WINDOW_CHILD_TRUNCATED=' + ([int]$dialog.ChildTruncated).ToString())
    Write-Output ('WINDOW_CANDIDATE_COUNT=' + ([int]$dialog.CandidateCount).ToString())
    Write-Output ('FOREGROUND_HWND=' + ([int64]$dialog.ForegroundHwnd).ToString())
    Write-Output ('FOREGROUND_PID=' + ([int]$dialog.ForegroundPid).ToString())
    Write-Output ('FOREGROUND_TID=' + ([int]$dialog.ForegroundTid).ToString())
    Write-Output ('FOREGROUND_CLASS=' + (Get-SafeLabel -Name ([string]$dialog.ForegroundClass)))
    Write-Output ('DESKTOP_SCRIPT=' + (Get-SafeLabel -Name ([string]$dialog.ScriptDesktop)))
    Write-Output ('DESKTOP_FOCUS=' + (Get-SafeLabel -Name ([string]$dialog.FocusDesktop)))
    Write-Output ('DESKTOP_FOREGROUND=' + (Get-SafeLabel -Name ([string]$dialog.ForegroundDesktop)))
    Write-Output ('DESKTOP_FOCUS_MATCH=' + $focusDesk)
    Write-Output ('DESKTOP_FOREGROUND_MATCH=' + $fgDesk)
    $windowPrinted = 0
    foreach ($pass in @(2, 1, 0)) {
        foreach ($row in @($dialog.Rows)) {
            if ($null -eq $row) { continue }
            if ($windowPrinted -ge 40) { break }
            if (-not (Test-SurveyRowWanted -Row $row -FocusPid $FocusPid)) { continue }
            $isNeedle = ([int]$row.Needle -eq 1)
            $isFront = (([int]$row.Foreground -eq 1) -or ([int]$row.GuiActive -eq 1) -or ([string]$row.Role -eq 'foreground') -or ([string]$row.Role -eq 'guithread'))
            $rank = 0
            if ($isNeedle) { $rank = 2 }
            elseif ($isFront) { $rank = 1 }
            if ($pass -ne $rank) { continue }
            $procName = Get-SafeLabel -Name ([string]$row.Process)
            if ($procName -eq 'empty' -or $procName -eq 'unreadable') {
                try { $procName = Get-SafeLabel -Name ([string](Get-Process -Id ([int]$row.Pid) -ErrorAction Stop).ProcessName) } catch { $procName = 'unreadable' }
            }
            Write-Output ('WINDOW role=' + (Get-SafeLabel -Name ([string]$row.Role)) + ' hwnd=' + ([int64]$row.Hwnd).ToString() + ' pid=' + ([int]$row.Pid).ToString() + ' tid=' + ([int]$row.Tid).ToString() + ' process=' + $procName + ' owner_hwnd=' + ([int64]$row.OwnerHwnd).ToString() + ' owner_pid=' + ([int]$row.OwnerPid).ToString() + ' parent_hwnd=' + ([int64]$row.ParentHwnd).ToString() + ' parent_pid=' + ([int]$row.ParentPid).ToString() + ' root_pid=' + ([int]$row.RootPid).ToString() + ' class=' + (Get-SafeLabel -Name ([string]$row.Class)) + ' visible=' + ([int]$row.VisibleFlag).ToString() + ' direct_len=' + ([int]$row.DirectLen).ToString() + ' wm_len=' + ([int]$row.SentLen).ToString() + ' child_count=' + ([int]$row.ChildLen).ToString() + ' foreground=' + ([int]$row.Foreground).ToString() + ' gui_active=' + ([int]$row.GuiActive).ToString() + ' needle=' + ([int]$row.Needle).ToString())
            $windowPrinted = $windowPrinted + 1
        }
    }
    if ($windowPrinted -ge 40) { Write-Output 'WINDOW_CANDIDATE_TRUNCATED=1' }
    $dialogPrinted = 0
    foreach ($row in @($dialog.Rows)) {
        if ($null -eq $row) { continue }
        if ($dialogPrinted -ge 12) { break }
        if (-not (Test-DialogClassName -ClassName ([string]$row.Class))) { continue }
        $procName = Get-SafeLabel -Name ([string]$row.Process)
        if ($procName -eq 'empty' -or $procName -eq 'unreadable') {
            try { $procName = Get-SafeLabel -Name ([string](Get-Process -Id ([int]$row.Pid) -ErrorAction Stop).ProcessName) } catch { $procName = 'unreadable' }
        }
        Write-Output ('DIALOG_CANDIDATE hwnd=' + ([int64]$row.Hwnd).ToString() + ' pid=' + ([int]$row.Pid).ToString() + ' tid=' + ([int]$row.Tid).ToString() + ' process=' + $procName + ' owner_pid=' + ([int]$row.OwnerPid).ToString() + ' root_pid=' + ([int]$row.RootPid).ToString() + ' class=' + (Get-SafeLabel -Name ([string]$row.Class)) + ' direct_len=' + ([int]$row.DirectLen).ToString() + ' wm_len=' + ([int]$row.SentLen).ToString() + ' needle=' + ([int]$row.Needle).ToString())
        $dialogPrinted = $dialogPrinted + 1
    }
    Write-Output ('DIALOG_CANDIDATE_COUNT=' + $dialogPrinted.ToString())
    $win32Visible = [string]$dialog.Visible
    $ui = $null
    try { $ui = Get-UiSurvey -Dialog $dialog -FocusPid $FocusPid -FallbackHwnd ([int64]$xll.Hwnd) } catch { $ui = $null }
    if ($null -eq $ui) {
        $ui = New-Object psobject -Property @{
            Status = 'unreadable'
            Apartment = 'unreadable'
            Examined = 0
            Named = 0
            Needle = '0'
            Hwnd = [int64]0
            Pid = 0
            Class = ''
            HasLeaf = '0'
            HasSerious = '0'
            HasReopen = '0'
            Match = 'none'
            Nodes = @()
        }
    }
    Write-Output ('UIA_STATUS=' + (Get-SafeLabel -Name ([string]$ui.Status)))
    Write-Output ('UIA_APARTMENT=' + (Get-SafeLabel -Name ([string]$ui.Apartment)))
    Write-Output ('UIA_EXAMINED=' + ([int]$ui.Examined).ToString())
    Write-Output ('UIA_NAMED=' + ([int]$ui.Named).ToString())
    Write-Output ('UIA_NEEDLE=' + [string]$ui.Needle)
    $uiaShown = 0
    foreach ($node in @($ui.Nodes)) {
        if ($null -eq $node) { continue }
        if ($uiaShown -ge 8 -and [int]$node.Needle -ne 1) { continue }
        if ($uiaShown -ge 12) { break }
        Write-Output ('UIA_NODE hwnd=' + ([int64]$node.Hwnd).ToString() + ' pid=' + ([int]$node.Pid).ToString() + ' class=' + (Get-SafeLabel -Name ([string]$node.ClassName)) + ' control=' + (Get-SafeLabel -Name ([string]$node.Control)) + ' name_len=' + ([int]$node.NameLen).ToString() + ' needle=' + ([int]$node.Needle).ToString())
        $uiaShown = $uiaShown + 1
    }
    Write-Output ('WIN32_DIALOG_VISIBLE=' + $win32Visible)
    if (([string]$ui.Needle -eq '1') -and ([string]$dialog.Visible -ne '1')) {
        $dialog.Visible = '1'
        $dialog.Source = 'uia'
        $dialog.Match = [string]$ui.Match
        $dialog.Pid = [int]$ui.Pid
        $dialog.Hwnd = [int64]$ui.Hwnd
        $dialog.Class = [string]$ui.Class
        $dialog.HasLeaf = [string]$ui.HasLeaf
        $dialog.HasSerious = [string]$ui.HasSerious
        $dialog.HasReopen = [string]$ui.HasReopen
        $dialog.OwnerLinked = '0'
        $dialog.SameProcess = '0'
        if (($FocusPid -gt 0) -and ([int]$ui.Pid -eq $FocusPid)) { $dialog.SameProcess = '1' }
    }
    Write-Output ('DIALOG_VISIBLE=' + [string]$dialog.Visible)
    Write-Output ('DIALOG_PID=' + ([int]$dialog.Pid).ToString())
    Write-Output ('DIALOG_PROCESS_HWND=' + ([int64]$dialog.Hwnd).ToString())
    Write-Output ('DIALOG_OWNER_HWND=' + ([int64]$dialog.OwnerHwnd).ToString())
    Write-Output ('DIALOG_OWNER_PID=' + ([int]$dialog.OwnerPid).ToString())
    Write-Output ('DIALOG_PARENT_HWND=' + ([int64]$dialog.ParentHwnd).ToString())
    Write-Output ('DIALOG_PARENT_PID=' + ([int]$dialog.ParentPid).ToString())
    Write-Output ('DIALOG_CLASS=' + (Get-SafeLabel -Name ([string]$dialog.Class)))
    Write-Output ('DIALOG_TEXT_SOURCE=' + [string]$dialog.Source)
    Write-Output ('DIALOG_SAME_PROCESS=' + [string]$dialog.SameProcess)
    Write-Output ('DIALOG_OWNER_LINKED=' + [string]$dialog.OwnerLinked)
    Write-Output ('DIALOG_SERIOUS=' + [string]$dialog.HasSerious)
    Write-Output ('DIALOG_REOPEN=' + [string]$dialog.HasReopen)
    Write-Output ('DIALOG_LEAF=' + [string]$dialog.HasLeaf)
    Write-Output ('DIALOG_MATCH=' + [string]$dialog.Match)

    $crash = $null
    try { $crash = Get-CrashEvidence -StartTicks ([int64]$xll.StartTicks) -StartKnown $startKnown } catch {
        Write-Output 'SECTION_ERROR=crash'
        Write-Output ('SECTION_ERROR_TYPE=' + $_.Exception.GetType().Name)
    }
    if ($null -eq $crash) {
        $crash = New-Object psobject -Property @{
            EventFlag = 'unreadable'
            EventCount = 0
            Tokens = ''
            WerCount = -1
            QueryId = ''
        }
    }
    $crashFlag = Combine-CrashFlag -EventFlag ([string]$crash.EventFlag) -WerCount ([int]$crash.WerCount)
    Write-Output ('CRASH_EVENT_FLAG=' + [string]$crash.EventFlag)
    Write-Output ('CRASH_QUERY_ID=' + [string]$crash.QueryId)
    Write-Output ('CRASH_EXCEL_EVENTS=' + ([int]$crash.EventCount).ToString())
    Write-Output ('CRASH_MODULES=' + [string]$crash.Tokens)
    Write-Output ('WER_EXCEL_AFTER_START=' + ([int]$crash.WerCount).ToString())
    $prior = $null
    try { $prior = Get-PriorCrashEvidence -StartTicks ([int64]$xll.StartTicks) -StartKnown $startKnown } catch {
        Write-Output 'SECTION_ERROR=prior_crash'
        Write-Output ('SECTION_ERROR_TYPE=' + $_.Exception.GetType().Name)
    }
    if ($null -eq $prior) {
        $prior = New-Object psobject -Property @{
            State = 'unreadable'
            EventCount = 0
            LatestUtc = ''
            Tokens = ''
            Xll = '0'
            WerCount = -1
            QueryId = ''
            Truncated = '0'
            WorkbookHits = 0
            XllHits = 0
            LatestKind = ''
            LatestModule = ''
            LatestException = ''
            LatestWorkbook = '0'
            LatestXll = '0'
            Rows = @()
            WerRows = @()
        }
    }
    Write-Output ('CRASH_BEFORE_STATE=' + [string]$prior.State)
    Write-Output ('CRASH_BEFORE_QUERY=' + [string]$prior.QueryId)
    Write-Output ('CRASH_BEFORE_COUNT=' + ([int]$prior.EventCount).ToString())
    Write-Output ('CRASH_BEFORE_LATEST_UTC=' + [string]$prior.LatestUtc)
    Write-Output ('CRASH_BEFORE_MODULES=' + [string]$prior.Tokens)
    Write-Output ('CRASH_BEFORE_XLL=' + [string]$prior.Xll)
    Write-Output ('CRASH_BEFORE_TRUNCATED=' + [string]$prior.Truncated)
    Write-Output ('WER_BEFORE_START=' + ([int]$prior.WerCount).ToString())
    foreach ($row in @($prior.Rows)) {
        if ($null -eq $row) { continue }
        Write-Output ('CRASH_EVENT utc=' + [string]$row.Utc + ' id=' + ([int]$row.Id).ToString() + ' kind=' + (Get-SafeLabel -Name ([string]$row.Kind)) + ' module=' + (Get-SafeLabel -Name ([string]$row.Module)) + ' exception=' + (Get-SafeLabel -Name ([string]$row.Exception)) + ' workbook=' + [string]$row.Workbook + ' xll=' + [string]$row.Xll)
    }
    foreach ($row in @($prior.WerRows)) {
        if ($null -eq $row) { continue }
        Write-Output ('WER_LINK utc=' + [string]$row.Utc + ' kind=' + (Get-SafeLabel -Name ([string]$row.Kind)) + ' module=' + (Get-SafeLabel -Name ([string]$row.Module)) + ' exception=' + (Get-SafeLabel -Name ([string]$row.Exception)) + ' workbook=' + [string]$row.Workbook + ' xll=' + [string]$row.Xll)
    }
    $werBook = 0
    $werXll = 0
    foreach ($row in @($prior.WerRows)) {
        if ($null -eq $row) { continue }
        if ([string]$row.Workbook -eq '1') { $werBook = $werBook + 1 }
        if ([string]$row.Xll -eq '1') { $werXll = $werXll + 1 }
    }
    $linkVerdict = 'unreadable'
    if ([string]$prior.State -eq 'ok') {
        $linkVerdict = Get-CrashLinkVerdict -Count ([int]$prior.EventCount) -WorkbookHits (([int]$prior.WorkbookHits) + $werBook) -XllHits (([int]$prior.XllHits) + $werXll)
    }
    $linkCause = Get-CrashCausation -Verdict $linkVerdict
    Write-Output ('LATEST_CRASH_KIND=' + (Get-SafeLabel -Name ([string]$prior.LatestKind)))
    Write-Output ('LATEST_CRASH_MODULE=' + (Get-SafeLabel -Name ([string]$prior.LatestModule)))
    Write-Output ('LATEST_CRASH_EXCEPTION=' + (Get-SafeLabel -Name ([string]$prior.LatestException)))
    Write-Output ('LATEST_CRASH_WORKBOOK=' + [string]$prior.LatestWorkbook)
    Write-Output ('LATEST_CRASH_XLL=' + [string]$prior.LatestXll)
    Write-Output ('CRASH_LINK_WORKBOOK=' + (([int]$prior.WorkbookHits) + $werBook).ToString())
    Write-Output ('CRASH_LINK_XLL=' + (([int]$prior.XllHits) + $werXll).ToString())
    Write-Output ('CRASH_LINK_VERDICT=' + $linkVerdict)
    Write-Output ('CRASH_CAUSATION=' + $linkCause)

    $keyCause = 'unreadable'
    if ($keyWrite -ne 'unreadable' -and $recreated -ne 'unreadable' -and $other -ne 'unreadable' -and $replaced -ne 'unreadable') {
        $keyCause = Get-UnexplainedKeyTouch -KeyWrite $keyWrite -Recreated $recreated -Other $other -Replaced $replaced
    } elseif ($keyWrite -eq '0') {
        $keyCause = '0'
    }
    $primary = Get-DistinctionPrimary -Recreated $recreated -Other $other -Rewritten ([string]$book.Rewritten) -Crash $crashFlag -KeyTouched $keyCause -Replaced $replaced
    $reason = Get-DistinctionReason -Primary $primary -Recreated $recreated -Other $other -Rewritten ([string]$book.Rewritten) -Crash $crashFlag -Xll ([string]$xll.Loaded) -Dialog ([string]$dialog.Visible) -BackupState ([string]$backup.State)
    Write-Output ('FLAG resiliency_recreated=' + $recreated)
    Write-Output ('FLAG resiliency_other_match=' + $other)
    Write-Output ('FLAG resiliency_value_replaced=' + $replaced)
    Write-Output ('FLAG resiliency_key_write_after_start=' + $keyWrite)
    Write-Output ('FLAG resiliency_key_touched=' + $keyCause)
    Write-Output ('FLAG workbook_rewritten=' + [string]$book.Rewritten)
    Write-Output ('FLAG xll_loaded=' + [string]$xll.Loaded)
    Write-Output ('FLAG crash_after_launch=' + $crashFlag)
    Write-Output ('FLAG dialog_visible=' + [string]$dialog.Visible)
    $unreadNames = New-Object System.Collections.Generic.List[string]
    if ($recreated -eq 'unreadable') { [void]$unreadNames.Add('resiliency_recreated') }
    if ($other -eq 'unreadable') { [void]$unreadNames.Add('resiliency_other_match') }
    if ($replaced -eq 'unreadable') { [void]$unreadNames.Add('resiliency_value_replaced') }
    if ($keyWrite -eq 'unreadable') { [void]$unreadNames.Add('resiliency_key_write_after_start') }
    if ($keyCause -eq 'unreadable') { [void]$unreadNames.Add('resiliency_key_touched') }
    if ([string]$book.Rewritten -eq 'unreadable') { [void]$unreadNames.Add('workbook_rewritten') }
    if ([string]$xll.Loaded -eq 'unreadable') { [void]$unreadNames.Add('xll_loaded') }
    if ($crashFlag -eq 'unreadable') { [void]$unreadNames.Add('crash_after_launch') }
    if ([string]$dialog.Visible -eq 'unreadable') { [void]$unreadNames.Add('dialog_visible') }
    if (([string]$book.PackageXml -eq 'locked') -or ([string]$book.PackageXml -eq 'unreadable') -or ([string]$book.PackageXml -eq 'truncated')) { [void]$unreadNames.Add('package_workbook_xml') }
    if ([string]$prior.State -eq 'unreadable') { [void]$unreadNames.Add('crash_before') }
    if ([string]$sibling.LockRelation -eq 'unreadable') { [void]$unreadNames.Add('lockfile') }
    $lockBefore = '0'
    if ([string]$sibling.LockRelation -eq 'before_excel_start') { $lockBefore = '1' }
    elseif ([string]$sibling.LockRelation -eq 'unreadable') { $lockBefore = 'unreadable' }
    $xlkFlag = '0'
    if ([string]$sibling.XlkRelation -eq 'unreadable') { $xlkFlag = 'unreadable' }
    elseif ([string]$sibling.XlkExists -eq '1') { $xlkFlag = '1' }
    $cause = Get-CauseClass -CrashSave ([string]$book.CrashSave) -RepairLoad ([string]$book.RepairLoad) -DataExtract ([string]$book.DataExtract) -FileRecovery ([string]$book.FileRecovery) -PackageOpen ([string]$book.PackageXml) -PriorState ([string]$prior.State) -PriorCount ([int]$prior.EventCount) -PriorXll ([string]$prior.Xll) -LockBefore $lockBefore -XlkExists $xlkFlag -DialogVisible ([string]$dialog.Visible)
    $unreadText = 'none'
    if ($unreadNames.Count -gt 0) { $unreadText = [string]::Join(',', $unreadNames.ToArray()) }
    Write-Output ('UNREADABLE=' + $unreadText)
    Write-Output ('BACKUP_STATE=' + [string]$backup.State)
    Write-Output ('PRIMARY=' + $primary)
    Write-Output ('REASON=' + $reason)
    Write-Output ('CAUSE=' + [string]$cause.Cause)
    Write-Output ('CAUSE_FLAGS=' + [string]$cause.Flags)
    Write-Output ('CAUSE_LIMIT=' + (Get-CauseLimit -FileRecovery ([string]$book.FileRecovery) -Verdict $linkVerdict))
    Write-Output 'NOTHING_TOUCHED=1'
    Write-Output 'REGISTRY_CHANGED=0'
}

if ($SelfTest) {
    Invoke-DiagnoseSelfTest
    return
}
if (-not [string]::Equals($Confirm, $script:ConfirmToken, $script:Ordinal)) {
    Write-Refused -Reason 'confirm_token_missing'
    throw 'confirm_token_missing'
}
Invoke-LiveDiagnose -FocusPid $LaunchedPid
