param(
    [switch]$SelfTest,
    [string]$Confirm = '',
    [int]$LaunchedPid = 0
)

# Read-only classification of the Controller's own identity-probe records
# from the launch that left the serious-error dialog up. This does not open
# the local cache, Rules, Recovery, the registry, the workbook zip, or the
# dialog. It does not print paths, command lines, or dialog text.
# -SelfTest does not read processes or files.

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$script:Ordinal = [StringComparison]::Ordinal
$script:OrdinalIgnore = [StringComparison]::OrdinalIgnoreCase
$script:Leaf = 'Kioxia_MS2_RSS_Live_Signals.xlsx'
$script:PathTail = 'MarketSpeed II RSS\files\Kioxia_MS2_RSS_Live_Signals.xlsx'
$script:XllStem = 'MarketSpeed2_RSS'
$script:ConfirmToken = 'DIAGNOSE_CANONICAL_LAUNCH_RECORD_READONLY'
$script:PinnedStartUtc = '2026-10-03T02:22:51Z'
$script:TextCap = 262144
$script:CaseCount = 0
$script:ResultPath = 'C:\AI_Cockpit_OneClick_Starter\Logs\V9\identity_probe\result.json'
$script:DiagPath = 'C:\AI_Cockpit_OneClick_Starter\Logs\V9\identity_probe\open_diagnostics.json'
$script:IncidentPath = 'C:\AI_Cockpit_OneClick_Starter\Logs\V9\ai_shadow\incidents.jsonl'
$script:SeriousErrorJa = -join @(
    [char]0x91CD, [char]0x5927, [char]0x306A, [char]0x30A8, [char]0x30E9, [char]0x30FC
)
$script:ReopenDocumentJa = -join @(
    [char]0x3053, [char]0x306E, [char]0x30C9, [char]0x30AD, [char]0x30E5, [char]0x30E1, [char]0x30F3, [char]0x30C8, [char]0x3092, [char]0x958B, [char]0x304D, [char]0x307E, [char]0x3059, [char]0x304B
)

function Get-Prop {
    param($Obj, [string]$Name)
    if ($null -eq $Obj) { return $null }
    $prop = $Obj.PSObject.Properties[$Name]
    if ($null -eq $prop) { return $null }
    return $prop.Value
}

function Get-RecordFlags {
    param([string]$Text)
    $flags = New-Object psobject -Property @{ Phrase = 0; Leaf = 0; Path = 0; Xll = 0 }
    if ([string]::IsNullOrEmpty($Text)) { return $flags }
    if ($Text.IndexOf($script:SeriousErrorJa, $script:Ordinal) -ge 0) { $flags.Phrase = 1 }
    if ($Text.IndexOf($script:ReopenDocumentJa, $script:Ordinal) -ge 0) { $flags.Phrase = 1 }
    if ($Text.IndexOf('serious problem', $script:OrdinalIgnore) -ge 0) { $flags.Phrase = 1 }
    if ($Text.IndexOf('serious error', $script:OrdinalIgnore) -ge 0) { $flags.Phrase = 1 }
    if ($Text.IndexOf($script:Leaf, $script:OrdinalIgnore) -ge 0) { $flags.Leaf = 1 }
    if ($Text.IndexOf($script:PathTail, $script:OrdinalIgnore) -ge 0) { $flags.Path = 1; $flags.Leaf = 1 }
    if ($Text.IndexOf($script:XllStem, $script:OrdinalIgnore) -ge 0) { $flags.Xll = 1 }
    return $flags
}

function Get-KnownToken {
    param([string]$Value, [string[]]$Allowed)
    if ([string]::IsNullOrEmpty($Value)) { return 'absent' }
    foreach ($token in $Allowed) {
        if ([string]::Equals($Value, $token, $script:Ordinal)) { return $token }
    }
    return 'other'
}

function Get-KnownCode {
    param([string]$Value)
    return (Get-KnownToken -Value $Value -Allowed @(
        'EXCEL_IDENTITY_PROBE_FAILED',
        'EXCEL_SERIOUS_ERROR_PROMPT',
        'EXCEL_WORKBOOK_OPEN_BLOCKED',
        'EXCEL_PROCESS_EXITED',
        'EXCEL_IDENTITY_MISMATCH',
        'EXCEL_IDENTITY_PROBE_TIMEOUT'
    ))
}

function Get-KnownError {
    param([string]$Value)
    return (Get-KnownToken -Value $Value -Allowed @(
        'ROT_MONIKER_NOT_REGISTERED',
        'HWND_PROCESS_NOT_READY',
        'HWND_NOT_READY',
        'EXCEL_BUSY',
        'PREVIOUS_SERIOUS_ERROR_DIALOG',
        'LAUNCHED_PID_EXITED',
        'PROBE_TIMEOUT',
        'PROBE_ARGUMENTS_MISSING',
        'NOT_STARTED',
        'RESULT_MISSING',
        'ROT_ENUMERATION_FAILED',
        'WORKBOOK_NAME_MISMATCH',
        'PID_MISMATCH',
        'SESSION_MISMATCH',
        'COMMAND_LINE_NOT_VISIBLE',
        'COMMAND_LINE_MISMATCH',
        'PARENT_MISMATCH',
        'FULL_NAME_IDENTITY_UNREADABLE',
        'FULL_NAME_DIFFERENT_FILE',
        'COM_READ_FAILED'
    ))
}

function Get-CountValue {
    param($Obj, [string]$Name)
    $info = New-Object psobject -Property @{ Known = '0'; Value = -1 }
    $raw = Get-Prop -Obj $Obj -Name $Name
    if ($null -eq $raw) { return $info }
    $text = [string]$raw
    if ($text -match '^-?\d+$') {
        $info.Known = '1'
        $info.Value = [int]$text
    }
    return $info
}

function Get-BoolFlag {
    param($Obj, [string]$Name)
    $raw = Get-Prop -Obj $Obj -Name $Name
    if ($null -eq $raw) { return 'unreadable' }
    if ($raw -is [bool]) {
        if ($raw) { return '1' }
        return '0'
    }
    $text = [string]$raw
    if ($text -eq 'True' -or $text -eq 'true' -or $text -eq '1') { return '1' }
    if ($text -eq 'False' -or $text -eq 'false' -or $text -eq '0') { return '0' }
    return 'unreadable'
}

function Get-LaunchSwitch {
    param([string]$Value)
    if ([string]::IsNullOrEmpty($Value)) { return 'absent' }
    if ([string]::Equals($Value, '/x', $script:Ordinal)) { return '/x' }
    return 'other'
}

function Get-SubmitFlag {
    param($Obj)
    $raw = Get-Prop -Obj $Obj -Name 'real_submit_allowed'
    if ($null -eq $raw) { return 'unreadable' }
    if ($raw -is [bool]) {
        if ($raw) { return '1' }
        return '0'
    }
    $text = [string]$raw
    if ($text -eq 'True' -or $text -eq 'true' -or $text -eq '1') { return '1' }
    if ($text -eq 'False' -or $text -eq 'false' -or $text -eq '0') { return '0' }
    return 'unreadable'
}

function Get-LaunchJudgment {
    param(
        [string]$ResultState,
        [string]$DiagState,
        [int]$Phrase,
        [string]$DisabledKnown,
        [int]$DisabledCount,
        [string]$RecoveryKnown,
        [int]$RecoveryMatch
    )
    if ($Phrase -eq 1) { return 'probe_recorded_dialog' }
    if ($ResultState -ne 'ok' -and $DiagState -ne 'ok') {
        if ($ResultState -eq 'absent' -and $DiagState -eq 'absent') { return 'launch_record_absent' }
        return 'launch_record_unreadable'
    }
    if ($DisabledKnown -eq '1' -and $DisabledCount -gt 0) { return 'disabled_items_counted_at_fail' }
    if ($DisabledKnown -eq '1' -and $DisabledCount -eq 0 -and $RecoveryKnown -eq '1' -and $RecoveryMatch -eq 0) {
        return 'no_disabled_count_at_fail'
    }
    if ($ResultState -eq 'ok') { return 'probe_recorded_without_dialog' }
    return 'launch_record_incomplete'
}

function Get-LaunchLimit {
    param(
        [string]$ResultState,
        [string]$DiagState,
        [string]$IncidentState,
        [int]$Phrase,
        [string]$DisabledKnown,
        [int]$DisabledCount,
        [string]$SubmitFlag,
        [string]$Truncated
    )
    $flags = New-Object System.Collections.Generic.List[string]
    if ($Truncated -eq '1') { [void]$flags.Add('record_truncated') }
    if ($ResultState -eq 'absent' -or $DiagState -eq 'absent' -or $IncidentState -eq 'absent') {
        [void]$flags.Add('record_absent')
    }
    if ($ResultState -eq 'unreadable' -or $DiagState -eq 'unreadable' -or $IncidentState -eq 'unreadable') {
        [void]$flags.Add('record_unreadable')
    }
    if ($Phrase -ne 1 -and $ResultState -eq 'ok') { [void]$flags.Add('dialog_text_absent') }
    if ($DisabledKnown -eq '1' -and $DisabledCount -gt 0) { [void]$flags.Add('count_is_not_name_match') }
    if ($SubmitFlag -eq '1') { [void]$flags.Add('real_submit_not_false') }
    if ($SubmitFlag -eq 'unreadable' -and ($ResultState -eq 'ok' -or $IncidentState -eq 'ok')) {
        [void]$flags.Add('real_submit_unreadable')
    }
    if ($flags.Count -eq 0) { return 'none' }
    return [string]::Join(',', $flags.ToArray())
}

function Assert-Case {
    param([string]$Name, [bool]$Ok)
    $script:CaseCount = $script:CaseCount + 1
    if (-not $Ok) { throw ('selftest_failed:' + $Name) }
}

function Invoke-LaunchRecordSelfTest {
    Assert-Case 'serious_len' ($script:SeriousErrorJa.Length -eq 6)
    Assert-Case 'reopen_len' ($script:ReopenDocumentJa.Length -eq 14)
    $phrase = Get-RecordFlags -Text ($script:Leaf + ' ' + $script:SeriousErrorJa)
    Assert-Case 'phrase_and_leaf' (([int]$phrase.Phrase -eq 1) -and ([int]$phrase.Leaf -eq 1))
    $plain = Get-RecordFlags -Text 'ROT_MONIKER_NOT_REGISTERED'
    Assert-Case 'plain_off' (([int]$plain.Phrase -eq 0) -and ([int]$plain.Leaf -eq 0))
    Assert-Case 'code_fail' ((Get-KnownCode -Value 'EXCEL_IDENTITY_PROBE_FAILED') -eq 'EXCEL_IDENTITY_PROBE_FAILED')
    Assert-Case 'code_other' ((Get-KnownCode -Value 'C:\secret\book.xlsx') -eq 'other')
    Assert-Case 'err_rot' ((Get-KnownError -Value 'ROT_MONIKER_NOT_REGISTERED') -eq 'ROT_MONIKER_NOT_REGISTERED')
    Assert-Case 'err_other' ((Get-KnownError -Value 'C:\secret') -eq 'other')
    Assert-Case 'switch_x' ((Get-LaunchSwitch -Value '/x') -eq '/x')
    Assert-Case 'switch_other' ((Get-LaunchSwitch -Value '/x /s') -eq 'other')
    $diag = '{"disabled_item_count":0,"document_recovery_match_count":0,"startup_item_count":0,"safe_mode_switch":false,"launch_switches":"/x","real_submit_allowed":false}' | ConvertFrom-Json
    $disabled = Get-CountValue -Obj $diag -Name 'disabled_item_count'
    $recovery = Get-CountValue -Obj $diag -Name 'document_recovery_match_count'
    Assert-Case 'count_zero' (([string]$disabled.Known -eq '1') -and ([int]$disabled.Value -eq 0))
    Assert-Case 'bool_off' ((Get-BoolFlag -Obj $diag -Name 'safe_mode_switch') -eq '0')
    Assert-Case 'submit_off' ((Get-SubmitFlag -Obj $diag) -eq '0')
    Assert-Case 'judge_clear' ((Get-LaunchJudgment -ResultState 'ok' -DiagState 'ok' -Phrase 0 -DisabledKnown '1' -DisabledCount 0 -RecoveryKnown '1' -RecoveryMatch 0) -eq 'no_disabled_count_at_fail')
    Assert-Case 'judge_count' ((Get-LaunchJudgment -ResultState 'ok' -DiagState 'ok' -Phrase 0 -DisabledKnown '1' -DisabledCount 2 -RecoveryKnown '1' -RecoveryMatch 0) -eq 'disabled_items_counted_at_fail')
    Assert-Case 'judge_dialog' ((Get-LaunchJudgment -ResultState 'ok' -DiagState 'ok' -Phrase 1 -DisabledKnown '1' -DisabledCount 0 -RecoveryKnown '1' -RecoveryMatch 0) -eq 'probe_recorded_dialog')
    Assert-Case 'judge_absent' ((Get-LaunchJudgment -ResultState 'absent' -DiagState 'absent' -Phrase 0 -DisabledKnown '0' -DisabledCount -1 -RecoveryKnown '0' -RecoveryMatch -1) -eq 'launch_record_absent')
    Assert-Case 'judge_unread' ((Get-LaunchJudgment -ResultState 'unreadable' -DiagState 'absent' -Phrase 0 -DisabledKnown '0' -DisabledCount -1 -RecoveryKnown '0' -RecoveryMatch -1) -eq 'launch_record_unreadable')
    Assert-Case 'limit_none' ((Get-LaunchLimit -ResultState 'ok' -DiagState 'ok' -IncidentState 'ok' -Phrase 1 -DisabledKnown '1' -DisabledCount 0 -SubmitFlag '0' -Truncated '0') -eq 'none')
    Assert-Case 'limit_count' ((Get-LaunchLimit -ResultState 'ok' -DiagState 'ok' -IncidentState 'ok' -Phrase 0 -DisabledKnown '1' -DisabledCount 2 -SubmitFlag '0' -Truncated '0') -eq 'dialog_text_absent,count_is_not_name_match')
    Assert-Case 'limit_submit' ((Get-LaunchLimit -ResultState 'ok' -DiagState 'ok' -IncidentState 'absent' -Phrase 1 -DisabledKnown '1' -DisabledCount 0 -SubmitFlag '1' -Truncated '0') -eq 'record_absent,real_submit_not_false')
    $bad = '{"real_submit_allowed":true,"code":"EXCEL_IDENTITY_PROBE_FAILED"}' | ConvertFrom-Json
    Assert-Case 'submit_on' ((Get-SubmitFlag -Obj $bad) -eq '1')
    Assert-Case 'missing_count' ([string](Get-CountValue -Obj $diag -Name 'missing').Known -eq '0')
    Write-Output 'ACTION=diagnose_canonical_launch_record_readonly'
    Write-Output 'READ_ONLY=1'
    Write-Output 'CACHE_REREAD=0'
    Write-Output 'RULES_REREAD=0'
    Write-Output 'PACKAGE_REREAD=0'
    Write-Output 'REGISTRY_REREAD=0'
    Write-Output 'DIALOG_QUERIED=0'
    Write-Output 'LOG_TEXT_REREAD=0'
    Write-Output 'PROOF judgment=probe_recorded_dialog'
    Write-Output 'PROOF judgment=no_disabled_count_at_fail'
    Write-Output 'PROOF judgment=disabled_items_counted_at_fail'
    Write-Output 'PROOF judgment=launch_record_absent'
    Write-Output 'PROOF launch=/x'
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
    Write-Output 'ACTION=diagnose_canonical_launch_record_readonly'
    Write-Output 'READ_ONLY=1'
    Write-Output ('REASON=' + $Reason)
    Write-Output 'NOTHING_TOUCHED=1'
    Write-Output 'REGISTRY_CHANGED=0'
    Write-Output 'WORKBOOK_CHANGED=0'
    Write-Output 'XLL_CHANGED=0'
    Write-Output 'DIALOG_CLICKED=0'
    Write-Output 'EXCEL_STOP_REQUESTED=0'
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

function Read-TextCap {
    param([string]$Path, [int]$Cap)
    $result = New-Object psobject -Property @{ State = 'unreadable'; Text = ''; Truncated = '0' }
    if (-not [IO.File]::Exists($Path)) { $result.State = 'absent'; return $result }
    $fs = $null
    try {
        $fs = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
        $len = [int64]$fs.Length
        if ($len -le 0) { $result.State = 'ok'; return $result }
        $start = [int64]0
        if ($len -gt $Cap) {
            $start = $len - $Cap
            $result.Truncated = '1'
        }
        if ($start -gt 0) { [void]$fs.Seek($start, [IO.SeekOrigin]::Begin) }
        $want = [int]($len - $start)
        $buf = New-Object byte[] $want
        $read = 0
        while ($read -lt $want) {
            $n = $fs.Read($buf, $read, ($want - $read))
            if ($n -le 0) { break }
            $read = $read + $n
        }
        $text = [Text.Encoding]::UTF8.GetString($buf, 0, $read)
        if ($text.Length -gt 0 -and [int]$text[0] -eq 0xFEFF) { $text = $text.Substring(1) }
        $result.Text = $text
        $result.State = 'ok'
    } catch {
        $result.State = 'unreadable'
        $result.Text = ''
    } finally {
        if ($null -ne $fs) { $fs.Dispose() }
    }
    return $result
}

function Get-JsonObject {
    param([string]$Text, [string]$Truncated)
    $info = New-Object psobject -Property @{ State = 'unreadable'; Obj = $null }
    if ($Truncated -eq '1') { $info.State = 'unreadable'; return $info }
    if ([string]::IsNullOrEmpty($Text)) { $info.State = 'absent'; return $info }
    try {
        $info.Obj = $Text | ConvertFrom-Json
        $info.State = 'ok'
    } catch {
        $info.State = 'unreadable'
    }
    return $info
}

function Get-LatestIncident {
    param([string]$Text, [string]$Truncated)
    $info = New-Object psobject -Property @{ State = 'absent'; Obj = $null; Skipped = 0 }
    if ([string]::IsNullOrEmpty($Text)) { return $info }
    $body = $Text
    if ($Truncated -eq '1') {
        $cut = $body.IndexOf("`n", $script:Ordinal)
        if ($cut -ge 0 -and ($cut + 1) -lt $body.Length) { $body = $body.Substring($cut + 1) }
    }
    $lines = $body.Split([char]10)
    $chosen = $null
    foreach ($line in $lines) {
        $rowText = $line.Trim()
        if ($rowText.Length -eq 0) { continue }
        if ($rowText.EndsWith("`r", $script:Ordinal)) { $rowText = $rowText.Substring(0, $rowText.Length - 1) }
        $row = $null
        try { $row = $rowText | ConvertFrom-Json } catch { $info.Skipped = [int]$info.Skipped + 1; continue }
        $component = [string](Get-Prop -Obj $row -Name 'component')
        if ($component -ne 'excel_identity' -and $component -ne 'workbook_open' -and $component -ne 'excel_process_exit') { continue }
        $chosen = $row
    }
    if ($null -eq $chosen) { return $info }
    $info.State = 'ok'
    $info.Obj = $chosen
    return $info
}

function Invoke-LiveLaunchRecord {
    param([int]$FocusPid)
    $launch = Get-LaunchStamp -ProcId $FocusPid
    Write-Output 'ACTION=diagnose_canonical_launch_record_readonly'
    Write-Output 'READ_ONLY=1'
    Write-Output 'CACHE_REREAD=0'
    Write-Output 'RULES_REREAD=0'
    Write-Output 'PACKAGE_REREAD=0'
    Write-Output 'REGISTRY_REREAD=0'
    Write-Output 'DIALOG_QUERIED=0'
    Write-Output 'LOG_TEXT_REREAD=0'
    Write-Output ('LAUNCHED_PID=' + $FocusPid.ToString())
    Write-Output ('LAUNCHED_ALIVE=' + [string]$launch.Alive)
    Write-Output ('LAUNCHED_EXCEL=' + [string]$launch.Excel)
    Write-Output ('LAUNCHED_CANONICAL=' + [string]$launch.Canonical)
    Write-Output ('LAUNCHED_START_UTC=' + [string]$launch.StartUtc)
    Write-Output ('PINNED_START_UTC=' + $script:PinnedStartUtc)
    Write-Output 'READ_BEGIN file=result_json'
    $resultRead = Read-TextCap -Path $script:ResultPath -Cap $script:TextCap
    $resultJson = Get-JsonObject -Text ([string]$resultRead.Text) -Truncated ([string]$resultRead.Truncated)
    $resultState = [string]$resultRead.State
    if ($resultState -eq 'ok') { $resultState = [string]$resultJson.State }
    Write-Output ('READ file=result_json state=' + $resultState + ' truncated=' + [string]$resultRead.Truncated)
    Write-Output 'READ_BEGIN file=open_diagnostics'
    $diagRead = Read-TextCap -Path $script:DiagPath -Cap $script:TextCap
    $diagJson = Get-JsonObject -Text ([string]$diagRead.Text) -Truncated ([string]$diagRead.Truncated)
    $diagState = [string]$diagRead.State
    if ($diagState -eq 'ok') { $diagState = [string]$diagJson.State }
    Write-Output ('READ file=open_diagnostics state=' + $diagState + ' truncated=' + [string]$diagRead.Truncated)
    Write-Output 'READ_BEGIN file=incidents'
    $incidentRead = Read-TextCap -Path $script:IncidentPath -Cap $script:TextCap
    $incidentState = [string]$incidentRead.State
    $incident = $null
    $skipped = 0
    if ($incidentState -eq 'ok') {
        $incident = Get-LatestIncident -Text ([string]$incidentRead.Text) -Truncated ([string]$incidentRead.Truncated)
        $incidentState = [string]$incident.State
        $skipped = [int]$incident.Skipped
    }
    Write-Output ('READ file=incidents state=' + $incidentState + ' truncated=' + [string]$incidentRead.Truncated + ' skipped=' + $skipped.ToString())
    $resultObj = $null
    if ($resultState -eq 'ok') { $resultObj = $resultJson.Obj }
    $diagObj = $null
    if ($diagState -eq 'ok') { $diagObj = $diagJson.Obj }
    $dialogText = [string](Get-Prop -Obj $resultObj -Name 'dialog_text')
    $dialogFlags = Get-RecordFlags -Text $dialogText
    $commandFlags = Get-RecordFlags -Text ([string](Get-Prop -Obj $resultObj -Name 'command_line'))
    $nameFlags = Get-RecordFlags -Text ([string](Get-Prop -Obj $resultObj -Name 'full_name'))
    $disabled = Get-CountValue -Obj $diagObj -Name 'disabled_item_count'
    $recovery = Get-CountValue -Obj $diagObj -Name 'document_recovery_match_count'
    $startup = Get-CountValue -Obj $diagObj -Name 'startup_item_count'
    $links = Get-CountValue -Obj $diagObj -Name 'external_link_count'
    $submit = Get-SubmitFlag -Obj $resultObj
    if ($submit -eq 'unreadable' -and $null -ne $incident -and [string]$incident.State -eq 'ok') {
        $submit = Get-SubmitFlag -Obj $incident.Obj
    }
    $truncated = '0'
    if ([string]$resultRead.Truncated -eq '1' -or [string]$diagRead.Truncated -eq '1' -or [string]$incidentRead.Truncated -eq '1') {
        $truncated = '1'
    }
    $code = Get-KnownCode -Value ([string](Get-Prop -Obj $resultObj -Name 'code'))
    $lastError = Get-KnownError -Value ([string](Get-Prop -Obj $resultObj -Name 'last_error'))
    $incidentCode = 'absent'
    $incidentComponent = 'absent'
    $incidentError = 'absent'
    if ($null -ne $incident -and [string]$incident.State -eq 'ok') {
        $incidentComponent = Get-KnownToken -Value ([string](Get-Prop -Obj $incident.Obj -Name 'component')) -Allowed @('excel_identity', 'workbook_open', 'excel_process_exit')
        $incidentCode = Get-KnownCode -Value ([string](Get-Prop -Obj $incident.Obj -Name 'error_code'))
        $incidentError = Get-KnownError -Value ([string](Get-Prop -Obj $incident.Obj -Name 'suspected_cause'))
    }
    $phrase = [int]$dialogFlags.Phrase
    $primary = Get-LaunchJudgment -ResultState $resultState -DiagState $diagState -Phrase $phrase -DisabledKnown ([string]$disabled.Known) -DisabledCount ([int]$disabled.Value) -RecoveryKnown ([string]$recovery.Known) -RecoveryMatch ([int]$recovery.Value)
    $limit = Get-LaunchLimit -ResultState $resultState -DiagState $diagState -IncidentState $incidentState -Phrase $phrase -DisabledKnown ([string]$disabled.Known) -DisabledCount ([int]$disabled.Value) -SubmitFlag $submit -Truncated $truncated
    Write-Output ('RECORD_CODE=' + $code)
    Write-Output ('RECORD_LAST_ERROR=' + $lastError)
    Write-Output ('RECORD_DIALOG_PHRASE=' + $phrase.ToString())
    Write-Output ('RECORD_DIALOG_LEAF=' + ([int]$dialogFlags.Leaf).ToString())
    Write-Output ('RECORD_COMMAND_LEAF=' + ([int]$commandFlags.Leaf).ToString())
    Write-Output ('RECORD_FULL_NAME_LEAF=' + ([int]$nameFlags.Leaf).ToString())
    Write-Output ('RECORD_DISABLED_COUNT=' + ([int]$disabled.Value).ToString())
    Write-Output ('RECORD_DISABLED_KNOWN=' + [string]$disabled.Known)
    Write-Output ('RECORD_RECOVERY_MATCH=' + ([int]$recovery.Value).ToString())
    Write-Output ('RECORD_RECOVERY_KNOWN=' + [string]$recovery.Known)
    Write-Output ('RECORD_STARTUP_COUNT=' + ([int]$startup.Value).ToString())
    Write-Output ('RECORD_SAFE_MODE=' + (Get-BoolFlag -Obj $diagObj -Name 'safe_mode_switch'))
    Write-Output ('RECORD_LAUNCH=' + (Get-LaunchSwitch -Value ([string](Get-Prop -Obj $diagObj -Name 'launch_switches'))))
    Write-Output ('RECORD_VBA=' + (Get-BoolFlag -Obj $diagObj -Name 'has_vba_project'))
    Write-Output ('RECORD_LINKS=' + ([int]$links.Value).ToString())
    Write-Output ('RECORD_LINKS_KNOWN=' + [string]$links.Known)
    Write-Output ('RECORD_ADDIN=' + (Get-BoolFlag -Obj $diagObj -Name 'marketspeed_addin_present'))
    Write-Output ('INCIDENT_COMPONENT=' + $incidentComponent)
    Write-Output ('INCIDENT_CODE=' + $incidentCode)
    Write-Output ('INCIDENT_CAUSE=' + $incidentError)
    Write-Output ('REAL_SUBMIT=' + $submit)
    Write-Output ('JUDGMENT_LAUNCH=' + $primary)
    Write-Output ('JUDGMENT_LIMIT=' + $limit)
    Write-Output 'NOTHING_TOUCHED=1'
    Write-Output 'REGISTRY_CHANGED=0'
    Write-Output 'WORKBOOK_CHANGED=0'
    Write-Output 'XLL_CHANGED=0'
    Write-Output 'DIALOG_CLICKED=0'
    Write-Output 'EXCEL_STOP_REQUESTED=0'
}

if ($SelfTest) {
    Invoke-LaunchRecordSelfTest
    return
}
if (-not [string]::Equals($Confirm, $script:ConfirmToken, $script:Ordinal)) {
    Write-Refused -Reason 'confirm_token_missing'
    throw 'confirm_token_missing'
}
Invoke-LiveLaunchRecord -FocusPid $LaunchedPid
