param(
    [switch]$SelfTest,
    [string]$Confirm,
    [string]$BackupDir
)

# Restores one backed-up HKCU resiliency value. The key must be DocumentRecovery
# or DisabledItems. Refuses to write when the backup is outside the backup
# jail, the manifest does not match the payload, the live value differs, or
# the canonical Excel process is running.

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$script:Ordinal = [StringComparison]::Ordinal
$script:OrdinalIgnore = [StringComparison]::OrdinalIgnoreCase
$script:Leaf = 'Kioxia_MS2_RSS_Live_Signals.xlsx'
$script:PathTail = 'MarketSpeed II RSS\files\Kioxia_MS2_RSS_Live_Signals.xlsx'
$script:RecoveryPrefix = 'Software\Microsoft\Office\16.0\Excel\Resiliency\DocumentRecovery'
$script:DisabledPrefix = 'Software\Microsoft\Office\16.0\Excel\Resiliency\DisabledItems'
$script:CaseCount = 0
$script:NoChangePrinted = $false
$script:WriteAttempted = $false
$script:BlockingPids = ''

function Get-BackupRoot {
    return 'C:\AI_Cockpit_OneClick_Starter\Logs\V9\canonical_workbook_recovery_backup'
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

function Test-ExcelCommandBlocked {
    param([string]$CommandLine)
    if ([string]::IsNullOrWhiteSpace($CommandLine)) { return $true }
    if ($CommandLine.IndexOf($script:Leaf, $script:OrdinalIgnore) -ge 0) { return $true }
    if ($CommandLine.IndexOf($script:PathTail, $script:OrdinalIgnore) -ge 0) { return $true }
    return $false
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

function Test-ManifestFields {
    param($Manifest, [byte[]]$Payload)
    if ($null -eq $Manifest -or $null -eq $Payload) { return 'manifest_missing' }
    if ([int]$Manifest.schema -ne 1) { return 'schema' }
    $purpose = 'canonical_workbook_document_recovery_value'
    if (-not [string]::Equals([string]$Manifest.purpose, $purpose, $script:Ordinal)) { return 'purpose' }
    if (-not (Test-AllowedMutationKey -Key ([string]$Manifest.key))) { return 'key' }
    if (-not (Test-AllowedValueName -Name ([string]$Manifest.value_name))) { return 'value_name' }
    $kind = [string]$Manifest.kind
    if (($kind -ne 'Binary') -and ($kind -ne 'String') -and ($kind -ne 'ExpandString')) { return 'kind' }
    if ([int]$Manifest.length -ne $Payload.Length) { return 'length' }
    $sha = Get-Sha256Hex -Bytes $Payload
    $claimed = ([string]$Manifest.sha256).ToLowerInvariant()
    if (-not [string]::Equals($sha, $claimed, $script:Ordinal)) { return 'sha256' }
    $decoded = [Convert]::FromBase64String([string]$Manifest.base64)
    if (-not (Test-SameBytes -Left $Payload -Right $decoded)) { return 'base64' }
    return ''
}

function Resolve-RequestedBackupDir {
    param([string]$Requested)
    $root = Get-BackupRoot
    $candidate = $Requested
    if ([string]::IsNullOrWhiteSpace($candidate)) {
        $pointer = Join-Path $root 'LATEST_BACKUP_DIR.txt'
        if (-not [IO.File]::Exists($pointer)) { return '' }
        $candidate = [IO.File]::ReadAllText($pointer).Trim()
    }
    if ($candidate.IndexOf('..', $script:Ordinal) -ge 0) { return '' }
    $full = [IO.Path]::GetFullPath($candidate)
    if (-not (Test-BackupDirAllowed -Root $root -Candidate $full)) { return '' }
    return $full
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
    return $null
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

function Write-RestoredValue {
    param([string]$KeyPath, [string]$ValueName, [string]$Kind, [byte[]]$Bytes, [string]$Text)
    if (-not (Test-AllowedMutationKey -Key $KeyPath)) { throw 'restore path jail rejected the key' }
    if (-not (Test-AllowedValueName -Name $ValueName)) { throw 'restore path jail rejected the value' }
    $opened = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($KeyPath, $true)
    if ($null -eq $opened) { $opened = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey($KeyPath) }
    if ($null -eq $opened) { throw 'restore could not open the key' }
    try {
        $binaryKind = [Microsoft.Win32.RegistryValueKind]::Binary
        $stringKind = [Microsoft.Win32.RegistryValueKind]::String
        $expandKind = [Microsoft.Win32.RegistryValueKind]::ExpandString
        if ($Kind -eq 'Binary') { $opened.SetValue($ValueName, $Bytes, $binaryKind) }
        elseif ($Kind -eq 'String') { $opened.SetValue($ValueName, $Text, $stringKind) }
        elseif ($Kind -eq 'ExpandString') { $opened.SetValue($ValueName, $Text, $expandKind) }
        else { throw 'restore kind is not supported' }
    } finally {
        $opened.Close()
    }
}

function Invoke-Restore {
    Write-Output 'ACTION=restore_one_canonical_resiliency_value'
    $dir = Resolve-RequestedBackupDir -Requested $BackupDir
    if ([string]::IsNullOrWhiteSpace($dir)) {
        Write-NoChange 'backup_dir_not_allowed'
        throw 'backup directory is missing or outside the jail'
    }
    $manifestPath = Join-Path $dir 'manifest.json'
    $payloadPath = Join-Path $dir 'payload.bin'
    if ((-not [IO.File]::Exists($manifestPath)) -or (-not [IO.File]::Exists($payloadPath))) {
        Write-NoChange 'backup_files_missing'
        throw 'backup files are missing'
    }
    $payload = [IO.File]::ReadAllBytes($payloadPath)
    $manifest = ([IO.File]::ReadAllText($manifestPath)) | ConvertFrom-Json
    $problem = Test-ManifestFields -Manifest $manifest -Payload $payload
    if (-not [string]::IsNullOrWhiteSpace($problem)) {
        Write-NoChange ('backup_' + $problem)
        throw 'backup manifest did not verify'
    }
    $block = Get-ExcelBlockReason
    if (-not [string]::IsNullOrWhiteSpace($block)) {
        if ($block -eq 'canonical_excel_still_running' -and $script:BlockingPids -match '^[0-9,]+$') {
            Write-Output ('BLOCKING_PIDS=' + $script:BlockingPids)
        }
        Write-NoChange $block
        throw 'registry was not changed'
    }
    $keyPath = [string]$manifest.key
    $valueName = [string]$manifest.value_name
    $kind = [string]$manifest.kind
    $text = ''
    if (($kind -eq 'String') -or ($kind -eq 'ExpandString')) {
        $text = [Text.Encoding]::Unicode.GetString($payload)
        $again = [Text.Encoding]::Unicode.GetBytes($text)
        if (-not (Test-SameBytes -Left $payload -Right $again)) {
            Write-NoChange 'string_roundtrip_failed'
            throw 'string backup did not round-trip'
        }
    }
    $live = Read-LiveValue -KeyPath $keyPath -ValueName $valueName
    if ($null -ne $live) {
        $same = ([string]::Equals([string]$live.Kind, $kind, $script:Ordinal)) -and (Test-SameBytes -Left $payload -Right $live.Bytes)
        if ($same) {
            Write-Output ('BACKUP_DIR=' + $dir)
            Write-Output 'ALREADY_PRESENT=1'
            Write-NoChange 'already_present'
            return
        }
        Write-NoChange 'live_value_differs'
        throw 'live registry value differs from the backup'
    }
    Write-RestoredValue -KeyPath $keyPath -ValueName $valueName -Kind $kind -Bytes $payload -Text $text
    $script:WriteAttempted = $true
    $check = Read-LiveValue -KeyPath $keyPath -ValueName $valueName
    $ok = $false
    if ($null -ne $check) {
        $ok = ([string]::Equals([string]$check.Kind, $kind, $script:Ordinal)) -and (Test-SameBytes -Left $payload -Right $check.Bytes)
    }
    if (-not $ok) {
        Write-Output ('BACKUP_DIR=' + $dir)
        Write-Output 'ROLLBACK_VERIFY_FAILED=1'
        throw 'restored value did not match the backup'
    }
    $shown = $valueName
    if ($shown.Length -eq 0) { $shown = '(default)' }
    Write-Output ('TARGET_KEY=' + $keyPath)
    Write-Output ('TARGET_VALUE=' + $shown)
    Write-Output ('TARGET_KIND=' + $kind)
    Write-Output ('BACKUP_DIR=' + $dir)
    Write-Output 'BACKUP_VERIFY=1'
    Write-Output 'RESTORED=1'
    Write-Output 'LIVE_MATCH=1'
    Write-Output 'REGISTRY_CHANGED=1'
    Write-Output 'EXCEL_PROCESSES_TOUCHED=0'
    Write-Output 'WORKBOOK_CHANGED=0'
    Write-Output 'XLL_CHANGED=0'
    Write-Output 'DIALOG_TOUCHED=0'
    Write-Output 'SUCCESS=1'
}

function Assert-Case {
    param([string]$Name, [bool]$Ok)
    $script:CaseCount = $script:CaseCount + 1
    if (-not $Ok) { throw ('SELFTEST FAIL ' + $Name) }
}

function Invoke-RestoreSelfTest {
    $doc = 'Software\Microsoft\Office\16.0\Excel\Resiliency\DocumentRecovery\1'
    $disabled = 'Software\Microsoft\Office\16.0\Excel\Resiliency\DisabledItems'
    $startup = 'Software\Microsoft\Office\16.0\Excel\Resiliency\StartupItems'
    Assert-Case 'jail_child' (Test-AllowedRecoveryKey -Key $doc)
    Assert-Case 'jail_disabled' (-not (Test-AllowedRecoveryKey -Key $disabled))
    Assert-Case 'jail_dotdot' (-not (Test-AllowedRecoveryKey -Key ($script:RecoveryPrefix + '\..\DisabledItems')))
    Assert-Case 'mutation_disabled' (Test-AllowedMutationKey -Key $disabled)
    Assert-Case 'mutation_startup' (-not (Test-AllowedMutationKey -Key $startup))
    Assert-Case 'mutation_extra' (-not (Test-AllowedDisabledItemsKey -Key ($disabled + 'Extra')))
    Assert-Case 'mutation_dotdot' (-not (Test-AllowedDisabledItemsKey -Key ($script:DisabledPrefix + '\..\DocumentRecovery')))
    Assert-Case 'value_default' (Test-AllowedValueName -Name '')
    Assert-Case 'value_slash' (-not (Test-AllowedValueName -Name 'A\B'))
    $root = Get-BackupRoot
    $good = $root + '\20261003T010203Z'
    Assert-Case 'backup_ok' (Test-BackupDirAllowed -Root $root -Candidate $good)
    Assert-Case 'backup_dotdot' (-not (Test-BackupDirAllowed -Root $root -Candidate ($root + '\..\20261003T010203Z')))
    Assert-Case 'backup_other' (-not (Test-BackupDirAllowed -Root $root -Candidate 'C:\Temp\20261003T010203Z'))
    $embed = '"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE" -Embedding'
    Assert-Case 'embed_ok' (-not (Test-ExcelCommandBlocked -CommandLine $embed))
    Assert-Case 'leaf_blocked' (Test-ExcelCommandBlocked -CommandLine ('EXCEL.EXE /x C:\Temp\' + $script:Leaf))
    $payload = [Text.Encoding]::ASCII.GetBytes('\' + $script:Leaf)
    $sha = Get-Sha256Hex -Bytes $payload
    $b64 = [Convert]::ToBase64String($payload)
    $json = '{' +
        '"schema":1,' +
        '"purpose":"canonical_workbook_document_recovery_value",' +
        '"created_utc":"2026-10-03T01:02:03Z",' +
        '"key":"Software\\Microsoft\\Office\\16.0\\Excel\\Resiliency\\DocumentRecovery\\1",' +
        '"value_name":"A",' +
        '"kind":"Binary",' +
        '"sha256":"' + $sha + '",' +
        '"length":' + $payload.Length + ',' +
        '"base64":"' + $b64 + '"}'
    $manifest = $json | ConvertFrom-Json
    Assert-Case 'manifest_ok' ((Test-ManifestFields -Manifest $manifest -Payload $payload) -eq '')
    $disabledJson = $json.Replace('DocumentRecovery\\1', 'DisabledItems').Replace('"value_name":"A"', '"value_name":"1664DDA6"')
    $disabledManifest = $disabledJson | ConvertFrom-Json
    Assert-Case 'manifest_disabled' ((Test-ManifestFields -Manifest $disabledManifest -Payload $payload) -eq '')
    Assert-Case 'manifest_disabled_key' ([string]$disabledManifest.key -eq $disabled)
    $startupJson = $json.Replace('DocumentRecovery\\1', 'StartupItems')
    $startupManifest = $startupJson | ConvertFrom-Json
    Assert-Case 'manifest_startup' ((Test-ManifestFields -Manifest $startupManifest -Payload $payload) -eq 'key')
    $manifest.length = 1
    Assert-Case 'manifest_len' ((Test-ManifestFields -Manifest $manifest -Payload $payload) -eq 'length')
    $temp = Join-Path ([IO.Path]::GetTempPath()) ('wb-restore-' + [Guid]::NewGuid().ToString('n'))
    [IO.Directory]::CreateDirectory($temp) | Out-Null
    try {
        $bin = Join-Path $temp 'payload.bin'
        [IO.File]::WriteAllBytes($bin, $payload)
        $read = [IO.File]::ReadAllBytes($bin)
        Assert-Case 'payload_roundtrip' (Test-SameBytes -Left $payload -Right $read)
    } finally {
        if ([IO.Directory]::Exists($temp)) { [IO.Directory]::Delete($temp, $true) }
    }
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
    Invoke-RestoreSelfTest
    return
}
if (-not [string]::Equals($Confirm, 'RESTORE_ONE_CANONICAL_WORKBOOK_RECOVERY', $script:Ordinal)) {
    Write-NoChange 'confirm_token_missing'
    throw 'Refusing to change registry without -Confirm RESTORE_ONE_CANONICAL_WORKBOOK_RECOVERY'
}
try {
    Invoke-Restore
} catch {
    if ((-not $script:WriteAttempted) -and (-not $script:NoChangePrinted)) {
        Write-NoChange 'exception'
    }
    throw
}
