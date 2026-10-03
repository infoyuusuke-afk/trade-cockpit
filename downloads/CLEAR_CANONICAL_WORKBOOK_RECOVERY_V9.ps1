param(
    [switch]$SelfTest,
    [string]$Confirm
)

# Removes one HKCU resiliency value only when its bytes are uniquely the
# canonical RSS workbook. The value may be under DocumentRecovery or
# DisabledItems. Backup bytes are read back and compared before any registry
# write. Any other resiliency value, the workbook, and the RSS xll stay
# untouched. This file does not click dialogs or stop processes.

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$script:Ordinal = [StringComparison]::Ordinal
$script:OrdinalIgnore = [StringComparison]::OrdinalIgnoreCase
$script:Leaf = 'Kioxia_MS2_RSS_Live_Signals.xlsx'
$script:PathTail = 'MarketSpeed II RSS\files\Kioxia_MS2_RSS_Live_Signals.xlsx'
$script:XllStem = 'MarketSpeed2_RSS'
$script:RecoveryPrefix = 'Software\Microsoft\Office\16.0\Excel\Resiliency\DocumentRecovery'
$script:DisabledPrefix = 'Software\Microsoft\Office\16.0\Excel\Resiliency\DisabledItems'
$script:ResiliencyRoot = 'Software\Microsoft\Office\16.0\Excel\Resiliency'
$script:CaseCount = 0
$script:NoChangePrinted = $false
$script:DeleteAttempted = $false
$script:BlockingPids = ''

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

function ConvertTo-JsonString {
    param([string]$Text)
    if ($null -eq $Text) { $Text = '' }
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.Append('"')
    foreach ($ch in $Text.ToCharArray()) {
        $code = [int]$ch
        if ($ch -eq '"') { [void]$sb.Append('\"') }
        elseif ($ch -eq '\') { [void]$sb.Append('\\') }
        elseif ($code -eq 10) { [void]$sb.Append('\n') }
        elseif ($code -eq 13) { [void]$sb.Append('\r') }
        elseif ($code -lt 32) { [void]$sb.Append('\u'); [void]$sb.Append($code.ToString('x4')) }
        else { [void]$sb.Append($ch) }
    }
    [void]$sb.Append('"')
    return $sb.ToString()
}

function New-ManifestJson {
    param(
        [string]$Created,
        [string]$KeyPath,
        [string]$ValueName,
        [string]$Kind,
        [string]$Sha,
        [int]$Length,
        [string]$Base64
    )
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.AppendLine('{')
    [void]$sb.AppendLine('  "schema": 1,')
    [void]$sb.AppendLine('  "purpose": "canonical_workbook_document_recovery_value",')
    [void]$sb.AppendLine('  "created_utc": ' + (ConvertTo-JsonString $Created) + ',')
    [void]$sb.AppendLine('  "key": ' + (ConvertTo-JsonString $KeyPath) + ',')
    [void]$sb.AppendLine('  "value_name": ' + (ConvertTo-JsonString $ValueName) + ',')
    [void]$sb.AppendLine('  "kind": ' + (ConvertTo-JsonString $Kind) + ',')
    [void]$sb.AppendLine('  "sha256": ' + (ConvertTo-JsonString $Sha) + ',')
    [void]$sb.AppendLine('  "length": ' + $Length.ToString() + ',')
    [void]$sb.AppendLine('  "base64": ' + (ConvertTo-JsonString $Base64))
    [void]$sb.Append('}')
    return $sb.ToString()
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

function Test-SameBytes {
    param([byte[]]$Left, [byte[]]$Right)
    if ($null -eq $Left -or $null -eq $Right) { return $false }
    if ($Left.Length -ne $Right.Length) { return $false }
    for ($i = 0; $i -lt $Left.Length; $i++) {
        if ($Left[$i] -ne $Right[$i]) { return $false }
    }
    return $true
}

function Test-AllowedRecoveryKey {
    param([string]$Key)
    if ([string]::IsNullOrWhiteSpace($Key)) { return $false }
    if ($Key.IndexOf('..', $script:Ordinal) -ge 0) { return $false }
    if ($Key.IndexOf('/', $script:Ordinal) -ge 0) { return $false }
    if ($Key.StartsWith('HKCU', $script:OrdinalIgnore)) { return $false }
    if ([string]::Equals($Key, $script:RecoveryPrefix, $script:OrdinalIgnore)) { return $true }
    $child = $script:RecoveryPrefix + '\'
    if ($Key.StartsWith($child, $script:OrdinalIgnore) -and $Key.Length -gt $child.Length) { return $true }
    return $false
}

function Test-AllowedDisabledItemsKey {
    param([string]$Key)
    if ([string]::IsNullOrWhiteSpace($Key)) { return $false }
    if ($Key.IndexOf('..', $script:Ordinal) -ge 0) { return $false }
    if ($Key.IndexOf('/', $script:Ordinal) -ge 0) { return $false }
    if ($Key.StartsWith('HKCU', $script:OrdinalIgnore)) { return $false }
    if ([string]::Equals($Key, $script:DisabledPrefix, $script:OrdinalIgnore)) { return $true }
    $child = $script:DisabledPrefix + '\'
    if ($Key.StartsWith($child, $script:OrdinalIgnore) -and $Key.Length -gt $child.Length) { return $true }
    return $false
}

function Test-AllowedMutationKey {
    param([string]$Key)
    if (Test-AllowedRecoveryKey -Key $Key) { return $true }
    if (Test-AllowedDisabledItemsKey -Key $Key) { return $true }
    return $false
}

function Test-AllowedValueName {
    param([string]$Name)
    if ($null -eq $Name) { return $false }
    if ($Name.Length -gt 256) { return $false }
    if ($Name.IndexOf('\', $script:Ordinal) -ge 0) { return $false }
    if ($Name.IndexOf('/', $script:Ordinal) -ge 0) { return $false }
    if ($Name.IndexOf('..', $script:Ordinal) -ge 0) { return $false }
    return $true
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
        if (-not [string]::IsNullOrWhiteSpace($s)) { [void]$texts.Add($s) }
    }
    foreach ($s in @(Get-Utf16Strings -Hay $Hay -MinChars 6)) {
        if (-not [string]::IsNullOrWhiteSpace($s)) { [void]$texts.Add($s) }
    }
    $pattern = '(?i)(?<leaf>[A-Za-z0-9][A-Za-z0-9 ._-]{0,160}\.(?:xlsx|xlsm|xlsb|xltx|xltm|xls))(?![A-Za-z0-9])'
    $regex = New-Object System.Text.RegularExpressions.Regex($pattern)
    foreach ($text in $texts) {
        foreach ($m in @($regex.Matches($text))) {
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
    $xllAsciiAt = Find-PatternOffset -Hay $Bytes -Needle $xllAscii -Start 0
    $xllUtf16At = Find-PatternOffset -Hay $Bytes -Needle $xllUtf16 -Start 0
    $hasXll = ($xllAsciiAt -ge 0) -or ($xllUtf16At -ge 0)
    $foreign = $false
    foreach ($leaf in @(Get-SpreadsheetLeaves -Hay $Bytes)) {
        if (-not [string]::Equals([string]$leaf, $script:Leaf, $script:OrdinalIgnore)) { $foreign = $true }
    }
    $hasModule = $false
    foreach ($suffix in @('.xll', '.dll', '.ocx')) {
        $suffixAscii = [Text.Encoding]::ASCII.GetBytes($suffix)
        $suffixUtf16 = [Text.Encoding]::Unicode.GetBytes($suffix)
        $asciiAt = Find-PatternOffset -Hay $Bytes -Needle $suffixAscii -Start 0
        $utf16At = Find-PatternOffset -Hay $Bytes -Needle $suffixUtf16 -Start 0
        if (($asciiAt -ge 0) -or ($utf16At -ge 0)) { $hasModule = $true }
    }
    if ($hasXll -or $foreign -or $odd -or $hasModule) { return 'impure' }
    return 'pure'
}

function New-RecoveryEntry {
    param([string]$Key, [string]$ValueName, [string]$Kind, [byte[]]$Bytes)
    return (New-Object psobject -Property @{
        Key = $Key
        ValueName = $ValueName
        Kind = $Kind
        Bytes = $Bytes
        Text = ''
    })
}

function Select-UniqueCanonicalTarget {
    param($Entries)
    $pure = New-Object System.Collections.Generic.List[object]
    $impure = 0
    $outside = 0
    $unsupported = 0
    $items = @()
    if ($null -ne $Entries) { $items = @($Entries) }
    foreach ($entry in $items) {
        if ($null -eq $entry) { throw 'recovery entry was null' }
        $verdict = Get-BlobVerdict -Bytes $entry.Bytes
        if ($verdict -eq 'none') { continue }
        if (-not (Test-AllowedMutationKey -Key ([string]$entry.Key))) {
            $outside = $outside + 1
            continue
        }
        $kind = [string]$entry.Kind
        $kindOk = ($kind -eq 'Binary') -or ($kind -eq 'String') -or ($kind -eq 'ExpandString')
        if ((-not (Test-AllowedValueName -Name ([string]$entry.ValueName))) -or (-not $kindOk)) {
            $unsupported = $unsupported + 1
            continue
        }
        if ($verdict -eq 'impure') {
            $impure = $impure + 1
            continue
        }
        if ($verdict -eq 'pure') { [void]$pure.Add($entry) }
    }
    $reason = 'no_match'
    $target = $null
    if ($outside -gt 0) { $reason = 'outside_resiliency_match' }
    elseif ($impure -gt 0) { $reason = 'impure_match' }
    elseif ($unsupported -gt 0) { $reason = 'unsupported_value' }
    elseif ($pure.Count -gt 1) { $reason = 'not_unique' }
    elseif ($pure.Count -eq 1) {
        $reason = 'ok'
        $target = $pure[0]
    }
    return (New-Object psobject -Property @{
        Reason = $reason
        Target = $target
        Pure = $pure.Count
        Impure = $impure
        Outside = $outside
        Unsupported = $unsupported
    })
}

function Test-ExcelCommandBlocked {
    param([string]$CommandLine)
    if ([string]::IsNullOrWhiteSpace($CommandLine)) { return $true }
    if ($CommandLine.IndexOf($script:Leaf, $script:OrdinalIgnore) -ge 0) { return $true }
    if ($CommandLine.IndexOf($script:PathTail, $script:OrdinalIgnore) -ge 0) { return $true }
    return $false
}

function Get-ValueDisplay {
    param([string]$Name)
    if ($Name.Length -eq 0) { return '(default)' }
    return $Name.Replace("`r", '').Replace("`n", '')
}

function Write-NoChange {
    param([string]$Reason)
    if ($Reason -notmatch '^[a-z0-9_]+$') { $Reason = 'unspecified' }
    Write-Output 'NOTHING_CHANGED=1'
    Write-Output ('REASON=' + $Reason)
    Write-Output 'REGISTRY_CHANGED=0'
    Write-Output 'EXCEL_PROCESSES_TOUCHED=0'
    Write-Output 'WORKBOOK_CHANGED=0'
    Write-Output 'XLL_CHANGED=0'
    Write-Output 'DIALOG_TOUCHED=0'
    $script:NoChangePrinted = $true
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

function Add-KeyValues {
    param($Opened, [string]$KeyPath, $List)
    foreach ($name in @($Opened.GetValueNames())) {
        if ($null -eq $name) { throw 'registry value name was null' }
        $kindEnum = $Opened.GetValueKind([string]$name)
        $kindName = Get-KindName -Kind $kindEnum
        if ($kindName -eq 'Skip') { continue }
        if ($kindName -eq '') { throw 'registry value kind is outside the restorable set' }
        $packed = Read-KindBytes -Opened $Opened -Name ([string]$name) -KindName $kindName
        if ($null -eq $packed) { throw 'registry value bytes were unreadable' }
        $entry = New-Object psobject -Property @{
            Key = $KeyPath
            ValueName = [string]$name
            Kind = $kindName
            Bytes = $packed.Bytes
            Text = [string]$packed.Text
        }
        [void]$List.Add($entry)
        if ($List.Count -gt 500) { throw 'resiliency value count exceeded the fail-closed cap' }
    }
}

function Add-ResiliencyTree {
    param($Opened, [string]$KeyPath, $List, [int]$Depth)
    if ($Depth -gt 8) { throw 'resiliency key depth exceeded the fail-closed cap' }
    Add-KeyValues -Opened $Opened -KeyPath $KeyPath -List $List
    foreach ($sub in @($Opened.GetSubKeyNames())) {
        if ([string]::IsNullOrWhiteSpace([string]$sub)) { throw 'registry subkey name was empty' }
        $subName = [string]$sub
        if ($subName.IndexOf('\', $script:Ordinal) -ge 0) { throw 'registry subkey name was unsafe' }
        $childPath = $KeyPath + '\' + $subName
        $child = $Opened.OpenSubKey($subName)
        if ($null -eq $child) { throw 'registry subkey was unreadable' }
        try {
            Add-ResiliencyTree -Opened $child -KeyPath $childPath -List $List -Depth ($Depth + 1)
        } finally {
            $child.Close()
        }
    }
}

function Get-ResiliencyEntries {
    $root = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($script:ResiliencyRoot)
    if ($null -eq $root) { return ,@() }
    $list = New-Object System.Collections.Generic.List[object]
    try {
        Add-ResiliencyTree -Opened $root -KeyPath $script:ResiliencyRoot -List $list -Depth 0
    } finally {
        $root.Close()
    }
    return ,$list.ToArray()
}

function Read-LiveValue {
    param([string]$KeyPath, [string]$ValueName)
    if (-not (Test-AllowedMutationKey -Key $KeyPath)) { throw 'read path jail rejected the key' }
    if (-not (Test-AllowedValueName -Name $ValueName)) { throw 'read path jail rejected the value' }
    $opened = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($KeyPath)
    if ($null -eq $opened) { return $null }
    try {
        $found = $false
        foreach ($name in @($opened.GetValueNames())) {
            if ([string]::Equals([string]$name, $ValueName, $script:Ordinal)) { $found = $true; break }
        }
        if (-not $found) { return $null }
        $kindName = Get-KindName -Kind ($opened.GetValueKind($ValueName))
        if ($kindName -eq '' -or $kindName -eq 'Skip') { throw 'live value kind changed' }
        $packed = Read-KindBytes -Opened $opened -Name $ValueName -KindName $kindName
        if ($null -eq $packed) { throw 'live value bytes were unreadable' }
        return (New-Object psobject -Property @{
            Kind = $kindName
            Bytes = $packed.Bytes
            Text = [string]$packed.Text
        })
    } finally {
        $opened.Close()
    }
}

function Get-Fingerprint {
    $map = @{}
    $entries = Get-ResiliencyEntries
    foreach ($entry in @($entries)) {
        if ($null -eq $entry) { continue }
        $id = [string]$entry.Key + [char]0x1F + [string]$entry.ValueName
        if ($map.ContainsKey($id)) { throw 'duplicate registry value in scan' }
        $prefix = [Text.Encoding]::ASCII.GetBytes(([string]$entry.Kind) + "`n")
        $joined = New-Object byte[] ($prefix.Length + $entry.Bytes.Length)
        [Buffer]::BlockCopy($prefix, 0, $joined, 0, $prefix.Length)
        [Buffer]::BlockCopy($entry.Bytes, 0, $joined, $prefix.Length, $entry.Bytes.Length)
        $map[$id] = Get-Sha256Hex -Bytes $joined
    }
    return $map
}

function Test-OnlyTargetRemoved {
    param($Before, $After, [string]$KeyPath, [string]$ValueName)
    $id = $KeyPath + [char]0x1F + $ValueName
    if (-not $Before.ContainsKey($id)) { return $false }
    if ($After.ContainsKey($id)) { return $false }
    foreach ($existing in @($Before.Keys)) {
        if ([string]::Equals([string]$existing, $id, $script:Ordinal)) { continue }
        if (-not $After.ContainsKey([string]$existing)) { return $false }
        if (-not [string]::Equals([string]$After[[string]$existing], [string]$Before[[string]$existing], $script:Ordinal)) { return $false }
    }
    foreach ($existing in @($After.Keys)) {
        if (-not $Before.ContainsKey([string]$existing)) { return $false }
    }
    return $true
}

function Write-VerifiedBackup {
    param($Target)
    $root = Get-BackupRoot
    $stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmss') + 'Z'
    $dir = Join-Path $root $stamp
    if (-not (Test-BackupDirAllowed -Root $root -Candidate $dir)) { throw 'backup directory failed the path jail' }
    if ([IO.Directory]::Exists($dir)) { throw 'backup directory already exists' }
    [IO.Directory]::CreateDirectory($dir) | Out-Null
    try {
        $payload = Join-Path $dir 'payload.bin'
        $manifestPath = Join-Path $dir 'manifest.json'
        [IO.File]::WriteAllBytes($payload, $Target.Bytes)
        $sha = Get-Sha256Hex -Bytes $Target.Bytes
        $b64 = [Convert]::ToBase64String($Target.Bytes)
        $created = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss') + 'Z'
        $json = New-ManifestJson -Created $created -KeyPath ([string]$Target.Key) -ValueName ([string]$Target.ValueName) -Kind ([string]$Target.Kind) -Sha $sha -Length ([int]$Target.Bytes.Length) -Base64 $b64
        $utf8 = New-Object System.Text.UTF8Encoding $false
        [IO.File]::WriteAllText($manifestPath, $json, $utf8)
        $readBack = [IO.File]::ReadAllBytes($payload)
        if (-not (Test-SameBytes -Left $Target.Bytes -Right $readBack)) { throw 'backup byte compare failed' }
        $readSha = Get-Sha256Hex -Bytes $readBack
        if (-not [string]::Equals($readSha, $sha, $script:Ordinal)) { throw 'backup hash compare failed' }
        $decoded = [Convert]::FromBase64String($b64)
        if (-not (Test-SameBytes -Left $Target.Bytes -Right $decoded)) { throw 'backup base64 compare failed' }
        $parsed = $json | ConvertFrom-Json
        if (-not [string]::Equals([string]$parsed.key, [string]$Target.Key, $script:Ordinal)) { throw 'backup manifest key mismatch' }
        if (-not [string]::Equals([string]$parsed.value_name, [string]$Target.ValueName, $script:Ordinal)) { throw 'backup manifest value mismatch' }
        if (-not [string]::Equals([string]$parsed.sha256, $sha, $script:Ordinal)) { throw 'backup manifest hash mismatch' }
        if (([string]$Target.Kind -eq 'String') -or ([string]$Target.Kind -eq 'ExpandString')) {
            $round = [Text.Encoding]::Unicode.GetString($Target.Bytes)
            $again = [Text.Encoding]::Unicode.GetBytes($round)
            if (-not (Test-SameBytes -Left $Target.Bytes -Right $again)) { throw 'string backup did not round-trip' }
            if (-not [string]::Equals($round, [string]$Target.Text, $script:Ordinal)) { throw 'string backup text mismatch' }
        }
        return $dir
    } catch {
        if ([IO.Directory]::Exists($dir)) { [IO.Directory]::Delete($dir, $true) }
        throw
    }
}

function Restore-TargetBytes {
    param($Target)
    if (-not (Test-AllowedMutationKey -Key ([string]$Target.Key))) { throw 'restore path jail rejected the key' }
    if (-not (Test-AllowedValueName -Name ([string]$Target.ValueName))) { throw 'restore path jail rejected the value' }
    $opened = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey([string]$Target.Key, $true)
    if ($null -eq $opened) {
        $opened = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey([string]$Target.Key)
    }
    if ($null -eq $opened) { throw 'restore could not open the key' }
    try {
        $binaryKind = [Microsoft.Win32.RegistryValueKind]::Binary
        $stringKind = [Microsoft.Win32.RegistryValueKind]::String
        $expandKind = [Microsoft.Win32.RegistryValueKind]::ExpandString
        if ([string]$Target.Kind -eq 'Binary') {
            $opened.SetValue([string]$Target.ValueName, $Target.Bytes, $binaryKind)
        } elseif ([string]$Target.Kind -eq 'String') {
            $opened.SetValue([string]$Target.ValueName, [string]$Target.Text, $stringKind)
        } elseif ([string]$Target.Kind -eq 'ExpandString') {
            $opened.SetValue([string]$Target.ValueName, [string]$Target.Text, $expandKind)
        } else {
            throw 'restore kind is not supported'
        }
    } finally {
        $opened.Close()
    }
}

function Get-ExcelBlockReason {
    $rows = $null
    $listed = $false
    try {
        $rows = Get-CimInstance -ClassName Win32_Process -Filter "Name = 'EXCEL.EXE'" -ErrorAction Stop
        $listed = $true
    } catch {
        try {
            $rows = Get-WmiObject -Class Win32_Process -Filter "Name = 'EXCEL.EXE'" -ErrorAction Stop
            $listed = $true
        } catch {
            $listed = $false
        }
    }
    if (-not $listed) { return 'excel_process_list_unreadable' }
    if ($null -eq $rows) { return '' }
    $blocking = New-Object System.Collections.Generic.List[string]
    foreach ($row in @($rows)) {
        if ($null -eq $row) { return 'excel_process_list_unreadable' }
        $cmd = ''
        try { $cmd = [string]$row.CommandLine } catch { return 'excel_command_line_unreadable' }
        $processId = ''
        try { $processId = [string]$row.ProcessId } catch { $processId = '' }
        if (Test-ExcelCommandBlocked -CommandLine $cmd) {
            if ([string]::IsNullOrWhiteSpace($cmd)) { return 'excel_command_line_unreadable' }
            if ($processId -match '^[0-9]+$') { [void]$blocking.Add($processId) }
        }
    }
    if ($blocking.Count -gt 0) {
        $script:BlockingPids = ($blocking.ToArray() -join ',')
        return 'canonical_excel_still_running'
    }
    return ''
}

function Remove-BackupDirIfPresent {
    param([string]$Dir)
    if ([string]::IsNullOrWhiteSpace($Dir)) { return }
    if ([IO.Directory]::Exists($Dir)) { [IO.Directory]::Delete($Dir, $true) }
}

function Invoke-Clear {
    Write-Output 'ACTION=clear_one_canonical_resiliency_value'
    $entries = @(Get-ResiliencyEntries)
    foreach ($entry in $entries) {
        if ($null -eq $entry) { continue }
        $verdict = Get-BlobVerdict -Bytes $entry.Bytes
        if ($verdict -eq 'none') { continue }
        $area = 'other'
        if (Test-AllowedRecoveryKey -Key ([string]$entry.Key)) { $area = 'document_recovery' }
        elseif (Test-AllowedDisabledItemsKey -Key ([string]$entry.Key)) { $area = 'disabled_items' }
        $shown = Get-ValueDisplay -Name ([string]$entry.ValueName)
        Write-Output ('SCAN area=' + $area + ' key=' + [string]$entry.Key + ' value=' + $shown + ' kind=' + [string]$entry.Kind + ' len=' + [string]$entry.Bytes.Length + ' verdict=' + $verdict)
    }
    $choice = Select-UniqueCanonicalTarget -Entries $entries
    Write-Output ('MATCH_PURE=' + [string]$choice.Pure)
    Write-Output ('MATCH_IMPURE=' + [string]$choice.Impure)
    Write-Output ('MATCH_OUTSIDE=' + [string]$choice.Outside)
    Write-Output ('MATCH_UNSUPPORTED=' + [string]$choice.Unsupported)
    if ([string]$choice.Reason -ne 'ok') {
        Write-NoChange ([string]$choice.Reason)
        throw 'canonical workbook recovery target is not unique'
    }
    $target = $choice.Target
    Write-Output ('SELECTED_KEY=' + [string]$target.Key)
    Write-Output ('SELECTED_VALUE=' + (Get-ValueDisplay -Name ([string]$target.ValueName)))
    Write-Output ('SELECTED_KIND=' + [string]$target.Kind)
    if ((Get-BlobVerdict -Bytes $target.Bytes) -ne 'pure') {
        Write-NoChange 'target_lost_pure_verdict'
        throw 'target verdict changed before backup'
    }
    if (-not (Test-AllowedMutationKey -Key ([string]$target.Key))) {
        Write-NoChange 'target_key_not_allowed'
        throw 'target key failed the path jail'
    }
    $block = Get-ExcelBlockReason
    if (-not [string]::IsNullOrWhiteSpace($block)) {
        if ($block -eq 'canonical_excel_still_running' -and $script:BlockingPids -match '^[0-9,]+$') {
            Write-Output ('BLOCKING_PIDS=' + $script:BlockingPids)
        }
        Write-NoChange $block
        throw 'registry was not changed'
    }
    $backupDir = ''
    $pointerWritten = $false
    $hadPreviousPointer = $false
    $previousPointer = ''
    $failReason = 'backup_not_verified'
    $root = Get-BackupRoot
    $pointer = $root + '\LATEST_BACKUP_DIR.txt'
    try {
        $backupDir = Write-VerifiedBackup -Target $target
        $live = Read-LiveValue -KeyPath ([string]$target.Key) -ValueName ([string]$target.ValueName)
        if ($null -eq $live) { throw 'target disappeared before delete' }
        if (-not [string]::Equals([string]$live.Kind, [string]$target.Kind, $script:Ordinal)) { throw 'target kind changed before delete' }
        if (-not (Test-SameBytes -Left $target.Bytes -Right $live.Bytes)) { throw 'target bytes changed before delete' }
        $before = Get-Fingerprint
        $writable = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey([string]$target.Key, $true)
        if ($null -eq $writable) {
            $failReason = 'target_key_not_writable'
            throw 'target key was not writable'
        }
        try {
            if ([IO.File]::Exists($pointer)) {
                $hadPreviousPointer = $true
                $previousPointer = [IO.File]::ReadAllText($pointer)
            }
            $utf8 = New-Object System.Text.UTF8Encoding $false
            [IO.File]::WriteAllText($pointer, $backupDir + "`r`n", $utf8)
            $pointerText = [IO.File]::ReadAllText($pointer).Trim()
            if (-not [string]::Equals($pointerText, $backupDir, $script:Ordinal)) { throw 'backup pointer mismatch' }
            $pointerWritten = $true
            $throwOnMissing = $true
            $failReason = 'delete_not_attempted'
            $writable.DeleteValue([string]$target.ValueName, $throwOnMissing)
            $script:DeleteAttempted = $true
        } finally {
            $writable.Close()
        }
    } catch {
        if (-not $script:DeleteAttempted) {
            Remove-BackupDirIfPresent -Dir $backupDir
            if ($pointerWritten) {
                if ($hadPreviousPointer) {
                    $utf8Restore = New-Object System.Text.UTF8Encoding $false
                    [IO.File]::WriteAllText($pointer, $previousPointer, $utf8Restore)
                } elseif ([IO.File]::Exists($pointer)) {
                    [IO.File]::Delete($pointer)
                }
            }
            if (-not $script:NoChangePrinted) { Write-NoChange $failReason }
        }
        throw
    }
    $onlyRemoved = $false
    try {
        $after = Get-Fingerprint
        $onlyRemoved = Test-OnlyTargetRemoved -Before $before -After $after -KeyPath ([string]$target.Key) -ValueName ([string]$target.ValueName)
    } catch {
        $onlyRemoved = $false
    }
    if ($onlyRemoved) {
        Write-Output ('TARGET_KEY=' + [string]$target.Key)
        Write-Output ('TARGET_VALUE=' + (Get-ValueDisplay -Name ([string]$target.ValueName)))
        Write-Output ('TARGET_KIND=' + [string]$target.Kind)
        Write-Output ('TARGET_SHA256=' + (Get-Sha256Hex -Bytes $target.Bytes))
        Write-Output ('BACKUP_DIR=' + $backupDir)
        Write-Output 'BACKUP_VERIFY=1'
        Write-Output 'LIVE_REREAD_MATCH=1'
        Write-Output 'DELETED=1'
        Write-Output 'POST_CHECK=1'
        Write-Output 'OTHER_VALUES_CHANGED=0'
        Write-Output 'REGISTRY_CHANGED=1'
        Write-Output 'EXCEL_PROCESSES_TOUCHED=0'
        Write-Output 'WORKBOOK_CHANGED=0'
        Write-Output 'XLL_CHANGED=0'
        Write-Output 'DIALOG_TOUCHED=0'
        Write-Output 'SUCCESS=1'
        return
    }
    $restoredOk = $false
    try {
        Restore-TargetBytes -Target $target
        $restored = Read-LiveValue -KeyPath ([string]$target.Key) -ValueName ([string]$target.ValueName)
        if ($null -ne $restored) {
            $restoredOk = ([string]::Equals([string]$restored.Kind, [string]$target.Kind, $script:Ordinal)) -and (Test-SameBytes -Left $target.Bytes -Right $restored.Bytes)
        }
    } catch {
        $restoredOk = $false
    }
    Write-Output ('BACKUP_DIR=' + $backupDir)
    if ($restoredOk) {
        Write-Output 'OWN_TARGET_RESTORED=1'
        Write-Output 'NET_OWN_VALUE_CHANGE=0'
        Write-Output 'REASON=post_check_failed_value_restored'
        Write-Output 'ROLLBACK_REQUIRED=0'
        throw 'post-check failed; the backed up value was restored'
    }
    Write-Output 'ROLLBACK_REQUIRED=1'
    Write-Output 'REASON=post_check_failed_restore_unverified'
    throw 'post-check failed and automatic restore did not verify'
}

function Assert-Case {
    param([string]$Name, [bool]$Ok)
    $script:CaseCount = $script:CaseCount + 1
    if (-not $Ok) { throw ('SELFTEST FAIL ' + $Name) }
}

function Invoke-RecoverySelfTest {
    $doc = 'Software\Microsoft\Office\16.0\Excel\Resiliency\DocumentRecovery\1'
    $doc2 = 'Software\Microsoft\Office\16.0\Excel\Resiliency\DocumentRecovery\2'
    $disabled = 'Software\Microsoft\Office\16.0\Excel\Resiliency\DisabledItems'
    $blob = New-PrefixedUtf16 -Text $script:Leaf
    Assert-Case 'prefixed_len' ($blob.Length -eq (6 + (2 * $script:Leaf.Length)))
    Assert-Case 'prefixed_pure' ((Get-BlobVerdict -Bytes $blob) -eq 'pure')
    $ascii = [Text.Encoding]::ASCII.GetBytes('\' + $script:Leaf)
    Assert-Case 'ascii_pure' ((Get-BlobVerdict -Bytes $ascii) -eq 'pure')
    $prefixedName = [Text.Encoding]::ASCII.GetBytes('XX' + $script:Leaf)
    Assert-Case 'prefix_none' ((Get-BlobVerdict -Bytes $prefixedName) -eq 'none')
    $other = New-PrefixedUtf16 -Text 'C:\Other.xlsx'
    Assert-Case 'other_none' ((Get-BlobVerdict -Bytes $other) -eq 'none')
    $mixed = New-PrefixedUtf16 -Text ($script:Leaf + ' C:\Other.xlsx')
    Assert-Case 'mixed_impure' ((Get-BlobVerdict -Bytes $mixed) -eq 'impure')
    $withXll = New-PrefixedUtf16 -Text ($script:Leaf + ' ' + $script:XllStem + '_64bit.xll')
    Assert-Case 'xll_impure' ((Get-BlobVerdict -Bytes $withXll) -eq 'impure')
    $withDll = New-PrefixedUtf16 -Text ($script:Leaf + ' C:\Addin.dll')
    Assert-Case 'dll_impure' ((Get-BlobVerdict -Bytes $withDll) -eq 'impure')
    $withOcx = New-PrefixedUtf16 -Text ($script:Leaf + ' C:\Addin.ocx')
    Assert-Case 'ocx_impure' ((Get-BlobVerdict -Bytes $withOcx) -eq 'impure')
    $onlyXll = New-PrefixedUtf16 -Text ($script:XllStem + '_64bit.xll')
    Assert-Case 'xll_only' ((Get-BlobVerdict -Bytes $onlyXll) -eq 'none')
    $tail = New-PrefixedUtf16 -Text $script:PathTail
    Assert-Case 'tail_pure' ((Get-BlobVerdict -Bytes $tail) -eq 'pure')
    $fullText = Get-CanonicalFullPath
    Assert-Case 'full_has_day' ($fullText.IndexOf([char]0x30C7, $script:Ordinal) -ge 0)
    $full = New-PrefixedUtf16 -Text $fullText
    Assert-Case 'full_pure' ((Get-BlobVerdict -Bytes $full) -eq 'pure')
    $startup = 'Software\Microsoft\Office\16.0\Excel\Resiliency\StartupItems'
    $one = New-RecoveryEntry -Key $doc -ValueName 'A' -Kind 'Binary' -Bytes $blob
    $two = New-RecoveryEntry -Key $doc2 -ValueName 'B' -Kind 'Binary' -Bytes $blob
    $outsideEntry = New-RecoveryEntry -Key $startup -ValueName 'D' -Kind 'Binary' -Bytes $blob
    $disabledEntry = New-RecoveryEntry -Key $disabled -ValueName '1664DDA6' -Kind 'Binary' -Bytes $blob
    $disabledOther = New-RecoveryEntry -Key $disabled -ValueName 'EEEEEEEE' -Kind 'Binary' -Bytes $blob
    $disabledDll = New-RecoveryEntry -Key $disabled -ValueName '1664DDA6' -Kind 'Binary' -Bytes $withDll
    $otherEntry = New-RecoveryEntry -Key $doc -ValueName 'O' -Kind 'Binary' -Bytes $other
    $mixedEntry = New-RecoveryEntry -Key $doc -ValueName 'M' -Kind 'Binary' -Bytes $mixed
    $multi = New-RecoveryEntry -Key $doc -ValueName 'S' -Kind 'MultiString' -Bytes $blob
    $badName = New-RecoveryEntry -Key $doc -ValueName 'A\B' -Kind 'Binary' -Bytes $blob
    Assert-Case 'one_pure' ((Select-UniqueCanonicalTarget -Entries @($one)).Reason -eq 'ok')
    Assert-Case 'two_pure' ((Select-UniqueCanonicalTarget -Entries @($one, $two)).Reason -eq 'not_unique')
    Assert-Case 'none_match' ((Select-UniqueCanonicalTarget -Entries @($otherEntry)).Reason -eq 'no_match')
    Assert-Case 'outside' ((Select-UniqueCanonicalTarget -Entries @($one, $outsideEntry)).Reason -eq 'outside_resiliency_match')
    Assert-Case 'disabled_ok' ((Select-UniqueCanonicalTarget -Entries @($disabledEntry, $otherEntry)).Reason -eq 'ok')
    Assert-Case 'two_areas' ((Select-UniqueCanonicalTarget -Entries @($one, $disabledEntry)).Reason -eq 'not_unique')
    Assert-Case 'two_disabled' ((Select-UniqueCanonicalTarget -Entries @($disabledEntry, $disabledOther)).Reason -eq 'not_unique')
    Assert-Case 'disabled_dll' ((Select-UniqueCanonicalTarget -Entries @($disabledDll)).Reason -eq 'impure_match')
    Assert-Case 'startup_blocks' ((Select-UniqueCanonicalTarget -Entries @($disabledEntry, $outsideEntry)).Reason -eq 'outside_resiliency_match')
    Assert-Case 'impure_blocks' ((Select-UniqueCanonicalTarget -Entries @($mixedEntry)).Reason -eq 'impure_match')
    Assert-Case 'multi_blocks' ((Select-UniqueCanonicalTarget -Entries @($multi)).Reason -eq 'unsupported_value')
    Assert-Case 'bad_name' ((Select-UniqueCanonicalTarget -Entries @($badName)).Reason -eq 'unsupported_value')
    Assert-Case 'empty' ((Select-UniqueCanonicalTarget -Entries $null).Reason -eq 'no_match')
    Assert-Case 'jail_child' (Test-AllowedRecoveryKey -Key $doc)
    Assert-Case 'jail_root' (Test-AllowedRecoveryKey -Key $script:RecoveryPrefix)
    Assert-Case 'jail_disabled' (-not (Test-AllowedRecoveryKey -Key $disabled))
    Assert-Case 'jail_dotdot' (-not (Test-AllowedRecoveryKey -Key ($script:RecoveryPrefix + '\..\DisabledItems')))
    Assert-Case 'jail_15' (-not (Test-AllowedRecoveryKey -Key 'Software\Microsoft\Office\15.0\Excel\Resiliency\DocumentRecovery'))
    Assert-Case 'jail_extra' (-not (Test-AllowedRecoveryKey -Key 'Software\Microsoft\Office\16.0\Excel\Resiliency\DocumentRecoveryExtra'))
    Assert-Case 'mutation_disabled' (Test-AllowedMutationKey -Key $disabled)
    Assert-Case 'mutation_child' (Test-AllowedDisabledItemsKey -Key ($disabled + '\1'))
    Assert-Case 'mutation_startup' (-not (Test-AllowedMutationKey -Key $startup))
    Assert-Case 'mutation_extra' (-not (Test-AllowedDisabledItemsKey -Key ($disabled + 'Extra')))
    Assert-Case 'mutation_dotdot' (-not (Test-AllowedDisabledItemsKey -Key ($script:DisabledPrefix + '\..\DocumentRecovery')))
    Assert-Case 'value_ok' (Test-AllowedValueName -Name 'Item')
    Assert-Case 'value_default' (Test-AllowedValueName -Name '')
    Assert-Case 'value_slash' (-not (Test-AllowedValueName -Name 'A\B'))
    $embed = '"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE" -Embedding'
    Assert-Case 'embed_ok' (-not (Test-ExcelCommandBlocked -CommandLine $embed))
    Assert-Case 'empty_blocked' (Test-ExcelCommandBlocked -CommandLine '')
    Assert-Case 'leaf_blocked' (Test-ExcelCommandBlocked -CommandLine ('EXCEL.EXE /x "' + $fullText + '"'))
    $backupRoot = Get-BackupRoot
    $goodBackup = $backupRoot + '\20261003T010203Z'
    Assert-Case 'backup_ok' (Test-BackupDirAllowed -Root $backupRoot -Candidate $goodBackup)
    Assert-Case 'backup_parent' (-not (Test-BackupDirAllowed -Root $backupRoot -Candidate $backupRoot))
    Assert-Case 'backup_dotdot' (-not (Test-BackupDirAllowed -Root $backupRoot -Candidate ($backupRoot + '\..\20261003T010203Z')))
    Assert-Case 'backup_nested' (-not (Test-BackupDirAllowed -Root $backupRoot -Candidate ($goodBackup + '\extra')))
    $temp = Join-Path ([IO.Path]::GetTempPath()) ('wb-recovery-' + [Guid]::NewGuid().ToString('n'))
    [IO.Directory]::CreateDirectory($temp) | Out-Null
    try {
        $bin = Join-Path $temp 'payload.bin'
        [IO.File]::WriteAllBytes($bin, $blob)
        $read = [IO.File]::ReadAllBytes($bin)
        Assert-Case 'backup_roundtrip' (Test-SameBytes -Left $blob -Right $read)
        $read[0] = [byte](($read[0] + 1) % 255)
        Assert-Case 'tamper_detected' (-not (Test-SameBytes -Left $blob -Right $read))
        Assert-Case 'hash_differs' ((Get-Sha256Hex -Bytes $blob) -ne (Get-Sha256Hex -Bytes $read))
    } finally {
        if ([IO.Directory]::Exists($temp)) { [IO.Directory]::Delete($temp, $true) }
    }
    $sampleSha = Get-Sha256Hex -Bytes $blob
    $sampleB64 = [Convert]::ToBase64String($blob)
    $json = New-ManifestJson -Created '2026-10-03T01:02:03Z' -KeyPath $doc -ValueName 'A' -Kind 'Binary' -Sha $sampleSha -Length $blob.Length -Base64 $sampleB64
    $parsed = $json | ConvertFrom-Json
    Assert-Case 'json_key' ([string]$parsed.key -eq $doc)
    Assert-Case 'json_name' ([string]$parsed.value_name -eq 'A')
    Assert-Case 'json_sha' ([string]$parsed.sha256 -eq $sampleSha)
    $emptyJson = New-ManifestJson -Created '2026-10-03T01:02:03Z' -KeyPath $script:RecoveryPrefix -ValueName '' -Kind 'Binary' -Sha $sampleSha -Length $blob.Length -Base64 $sampleB64
    $emptyParsed = $emptyJson | ConvertFrom-Json
    Assert-Case 'json_default' ([string]$emptyParsed.value_name -eq '')
    Write-Output ('CASE_COUNT=' + [string]$script:CaseCount)
    Write-Output 'SELFTEST PASS'
    Write-Output 'NOTHING_CHANGED=1'
    Write-Output 'REGISTRY_CHANGED=0'
    Write-Output 'EXCEL_PROCESSES_TOUCHED=0'
    Write-Output 'WORKBOOK_CHANGED=0'
    Write-Output 'XLL_CHANGED=0'
    Write-Output 'DIALOG_TOUCHED=0'
}

if ($SelfTest) {
    Invoke-RecoverySelfTest
    return
}
if (-not [string]::Equals($Confirm, 'CLEAR_ONE_CANONICAL_WORKBOOK_RECOVERY', $script:Ordinal)) {
    Write-NoChange 'confirm_token_missing'
    throw 'Refusing to change registry without -Confirm CLEAR_ONE_CANONICAL_WORKBOOK_RECOVERY'
}
try {
    Invoke-Clear
} catch {
    if ((-not $script:DeleteAttempted) -and (-not $script:NoChangePrinted)) {
        Write-NoChange 'exception'
    }
    throw
}
