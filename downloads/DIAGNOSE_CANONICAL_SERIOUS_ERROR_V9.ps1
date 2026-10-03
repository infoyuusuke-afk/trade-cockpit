param(
    [switch]$SelfTest,
    [string]$Confirm = '',
    [int]$LaunchedPid = 0
)

# Read-only diagnosis for the canonical workbook serious-error prompt.
# Distinguishes a resiliency value that returned, a different resiliency
# match, a workbook rewrite, the RSS xll load, and a crash after launch.
# This file does not delete registry values, stop Excel, click a dialog,
# or modify the workbook or the RSS xll. -SelfTest does not read HKCU,
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
    if (($Dialog -eq '1') -and $unread) { return 'dialog_visible_with_unreadable_evidence' }
    if ($BackupState -eq 'backup_unreadable') { return 'backup_unreadable' }
    if (($Dialog -eq '1') -and ($Xll -eq '1')) { return 'dialog_visible_xll_loaded_without_resiliency_crash_or_rewrite' }
    if ($Dialog -eq '1') { return 'dialog_visible_without_resiliency_crash_or_rewrite' }
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
    if ($EventFlag -eq 'unreadable' -or $WerCount -lt 0) { return 'unreadable' }
    return '0'
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
    Assert-Case 'label_hex' ((Get-SafeLabel -Name '1664DDA6') -eq '1664DDA6')
    Assert-Case 'label_path' ((Get-SafeLabel -Name 'C:\Secret.xlsx') -eq 'len_14')
    $root = Get-BackupRoot
    $stamp = $root + '\20261003T012345Z'
    Assert-Case 'backup_jail' (Test-BackupDirAllowed -Root $root -Candidate $stamp)
    Assert-Case 'backup_jail_dot' (-not (Test-BackupDirAllowed -Root $root -Candidate ($root + '\..\x')))
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
        $item = Get-Item -LiteralPath ('HKCU:\' + $Relative) -ErrorAction Stop
        $ticks = [int64]$item.LastWriteTimeUtc.Ticks
        $writeUtc = $item.LastWriteTimeUtc.ToString('yyyy-MM-ddTHH:mm:ss') + 'Z'
        if (-not $StartKnown) { $flag = '0' }
        elseif (Test-WriteAfterStart -WriteTicks $ticks -StartTicks $StartTicks -WriteKnown $true -StartKnown $true) { $flag = '1' }
        else { $flag = '0' }
    } catch {
        $flag = 'unreadable'
    }
    return (New-Object psobject -Property @{
        Name = (Get-SafeLabel -Name $leaf)
        Flag = $flag
        WriteUtc = $writeUtc
    })
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
            foreach ($entry in $zip.Entries) {
                $full = [string]$entry.FullName
                if ([string]::Equals($full, 'xl/vbaProject.bin', $script:Ordinal)) { $info.Vba = '1' }
                if ($full.StartsWith('xl/externalLinks/', $script:Ordinal)) { $links = $links + 1 }
            }
            $info.ExternalLinks = $links
        } finally {
            $zip.Dispose()
        }
    } catch {
        $info.Open = 'locked'
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
    $info = New-Object psobject -Property @{ Canonical = 'unreadable'; OtherCount = -1 }
    $opened = $null
    try {
        $opened = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Software\Microsoft\Office\16.0\Excel\Security\Trusted Documents\TrustRecords', $false)
        if ($null -eq $opened) {
            $info.Canonical = '0'
            $info.OtherCount = 0
            return $info
        }
        $names = $opened.GetValueNames()
        if ($null -eq $names) { $names = @() }
        $canon = '0'
        $other = 0
        foreach ($name in $names) {
            $value = [string]$name
            if ($value.IndexOf($script:Leaf, $script:OrdinalIgnore) -ge 0) { $canon = '1' }
            else { $other = $other + 1 }
        }
        $info.Canonical = $canon
        $info.OtherCount = $other
    } catch {
        $info.Canonical = 'unreadable'
    } finally {
        if ($null -ne $opened) { $opened.Close() }
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
        $msg = ''
        try { $msg = [string]$_.Exception.Message } catch { $msg = '' }
        if ($msg.IndexOf('No events', $script:OrdinalIgnore) -ge 0) {
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

function Add-CanonicalWindowType {
    try {
        [void][CanonicalSeriousErrorWindows]
        return
    } catch {}
    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;

public class CanonicalSeriousErrorWindows {
    delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")]
    static extern bool EnumWindows(EnumProc lpEnumFunc, IntPtr lParam);
    [DllImport("user32.dll")]
    static extern bool EnumChildWindows(IntPtr hWnd, EnumProc lpEnumFunc, IntPtr lParam);
    [DllImport("user32.dll")]
    static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint msg, IntPtr wParam, StringBuilder lParam, uint flags, uint timeoutMs, out IntPtr result);

    const uint WM_GETTEXT = 0x000D;
    const uint SMTO_ABORTIFHUNG = 0x0002;
    static EnumProc topCallback;
    static EnumProc childCallback;

    public static List<string> VisibleTexts(int processId) {
        var texts = new List<string>();
        topCallback = (hWnd, lParam) => {
            uint pid;
            GetWindowThreadProcessId(hWnd, out pid);
            if ((int)pid != processId) { return true; }
            AddText(hWnd, texts);
            if (texts.Count >= 40) { return false; }
            childCallback = (child, childParam) => {
                AddText(child, texts);
                return texts.Count < 40;
            };
            EnumChildWindows(hWnd, childCallback, IntPtr.Zero);
            return texts.Count < 40;
        };
        EnumWindows(topCallback, IntPtr.Zero);
        return texts;
    }

    static void AddText(IntPtr hWnd, List<string> texts) {
        if (texts.Count >= 40) { return; }
        var sb = new StringBuilder(512);
        IntPtr unused;
        SendMessageTimeout(hWnd, WM_GETTEXT, (IntPtr)sb.Capacity, sb, SMTO_ABORTIFHUNG, 200, out unused);
        var text = sb.ToString().Trim();
        if (text.Length > 0) { texts.Add(text); }
    }
}
'@
}

function Get-DialogEvidence {
    param([int]$FocusPid, $ProcessIds)
    $info = New-Object psobject -Property @{
        Visible = '0'
        Pid = 0
        HasLeaf = '0'
        HasSerious = '0'
        HasReopen = '0'
        Match = 'none'
    }
    try {
        Add-CanonicalWindowType
    } catch {
        $info.Visible = 'unreadable'
        return $info
    }
    $ids = New-Object System.Collections.Generic.List[int]
    if ($FocusPid -gt 0) { [void]$ids.Add($FocusPid) }
    foreach ($procId in @(Get-FlatRows -Rows $ProcessIds)) {
        $n = 0
        try { $n = [int]$procId } catch { continue }
        if (($n -gt 0) -and (-not $ids.Contains($n))) { [void]$ids.Add($n) }
    }
    foreach ($procId in $ids) {
        $texts = @()
        try { $texts = @([CanonicalSeriousErrorWindows]::VisibleTexts([int]$procId)) } catch { continue }
        foreach ($text in $texts) {
            $value = [string]$text
            if (-not (Test-SeriousErrorText -Text $value)) { continue }
            $info.Visible = '1'
            $info.Pid = [int]$procId
            if ($value.IndexOf($script:SeriousErrorJa, $script:Ordinal) -ge 0) { $info.HasSerious = '1' }
            if ($value.IndexOf($script:ReopenDocumentJa, $script:Ordinal) -ge 0) { $info.HasReopen = '1' }
            if ($value.IndexOf($script:Leaf, $script:OrdinalIgnore) -ge 0) { $info.HasLeaf = '1' }
            if (($info.HasLeaf -eq '1') -and ($info.HasSerious -eq '1')) { $info.Match = 'canonical_serious_error' }
            else { $info.Match = 'serious_error_needle' }
            return $info
        }
    }
    return $info
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
    if ($registryOk -and $null -ne $snap -and [string]$snap.Absent -eq '0') {
        $rootFlag = Get-KeyWriteFlag -Relative $script:ResiliencyRoot -StartTicks ([int64]$xll.StartTicks) -StartKnown $startKnown
        Write-Output ('KEY_WRITE name=' + $rootFlag.Name + ' after_start=' + $rootFlag.Flag + ' write_utc=' + $rootFlag.WriteUtc)
        [void]$keyFlags.Add([string]$rootFlag.Flag)
        foreach ($sub in @($snap.Subkeys)) {
            $rel = $script:ResiliencyRoot + '\' + [string]$sub
            $flag = Get-KeyWriteFlag -Relative $rel -StartTicks ([int64]$xll.StartTicks) -StartKnown $startKnown
            Write-Output ('KEY_WRITE name=' + $flag.Name + ' after_start=' + $flag.Flag + ' write_utc=' + $flag.WriteUtc)
            [void]$keyFlags.Add([string]$flag.Flag)
        }
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
        $trust = New-Object psobject -Property @{ Canonical = 'unreadable'; OtherCount = -1 }
    }
    Write-Output ('TRUST_CANONICAL=' + [string]$trust.Canonical)
    Write-Output ('TRUST_OTHER_COUNT=' + ([int]$trust.OtherCount).ToString())

    $dialog = $null
    try { $dialog = Get-DialogEvidence -FocusPid $FocusPid -ProcessIds $dialogIds.ToArray() } catch {
        Write-Output 'SECTION_ERROR=dialog'
        Write-Output ('SECTION_ERROR_TYPE=' + $_.Exception.GetType().Name)
    }
    if ($null -eq $dialog) {
        $dialog = New-Object psobject -Property @{
            Visible = 'unreadable'
            Pid = 0
            HasLeaf = '0'
            HasSerious = '0'
            HasReopen = '0'
            Match = 'none'
        }
    }
    Write-Output ('DIALOG_VISIBLE=' + [string]$dialog.Visible)
    Write-Output ('DIALOG_PID=' + ([int]$dialog.Pid).ToString())
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
        }
    }
    $crashFlag = Combine-CrashFlag -EventFlag ([string]$crash.EventFlag) -WerCount ([int]$crash.WerCount)
    Write-Output ('CRASH_EVENT_FLAG=' + [string]$crash.EventFlag)
    Write-Output ('CRASH_EXCEL_EVENTS=' + ([int]$crash.EventCount).ToString())
    Write-Output ('CRASH_MODULES=' + [string]$crash.Tokens)
    Write-Output ('WER_EXCEL_AFTER_START=' + ([int]$crash.WerCount).ToString())

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
    Write-Output ('BACKUP_STATE=' + [string]$backup.State)
    Write-Output ('PRIMARY=' + $primary)
    Write-Output ('REASON=' + $reason)
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
