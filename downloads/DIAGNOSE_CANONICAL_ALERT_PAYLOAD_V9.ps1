param(
    [switch]$SelfTest,
    [string]$Confirm = '',
    [int]$LaunchedPid = 0
)

# Read-only split of OAlerts Event ID 300 insertion strings.
# ID 300 is a general Office alert record, not a crash code. The earlier
# scans already listed the two launch-window events and did not query their
# fields. This script does not query the Application log, the Excel process,
# the dialog, the registry, the workbook, the cache, Rules, or Recovery,
# and it does not print alert text.
# -SelfTest does not read processes, files, or event logs.

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$script:Ordinal = [StringComparison]::Ordinal
$script:OrdinalIgnore = [StringComparison]::OrdinalIgnoreCase
$script:Leaf = 'Kioxia_MS2_RSS_Live_Signals.xlsx'
$script:PathTail = 'MarketSpeed II RSS\files\Kioxia_MS2_RSS_Live_Signals.xlsx'
$script:XllStem = 'MarketSpeed2_RSS'
$script:ConfirmToken = 'DIAGNOSE_CANONICAL_ALERT_PAYLOAD_READONLY'
$script:PinnedStartUtc = '2026-10-03T02:22:51Z'
$script:Known52 = '2026-10-03T02:22:52Z'
$script:Known54 = '2026-10-03T02:22:54Z'
$script:MaxEvents = 80
$script:MaxFields = 8
$script:CaseCount = 0
$script:SeriousErrorJa = -join @(
    [char]0x91CD, [char]0x5927, [char]0x306A, [char]0x30A8, [char]0x30E9, [char]0x30FC
)
$script:ReopenDocumentJa = -join @(
    [char]0x3053, [char]0x306E, [char]0x30C9, [char]0x30AD, [char]0x30E5, [char]0x30E1, [char]0x30F3, [char]0x30C8, [char]0x3092, [char]0x958B, [char]0x304D, [char]0x307E, [char]0x3059, [char]0x304B
)

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

function Get-SafeProvider {
    param([string]$Name)
    if ([string]::IsNullOrEmpty($Name)) { return 'empty' }
    return (Get-SafeLeaf -Name ($Name.Replace(' ', '_')))
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

function Test-ExcelApp {
    param([string]$Text)
    if ([string]::IsNullOrEmpty($Text)) { return $false }
    if ($Text.Equals('Microsoft Excel', $script:OrdinalIgnore)) { return $true }
    if ($Text.Equals('EXCEL', $script:OrdinalIgnore)) { return $true }
    return $false
}

function Test-NumericText {
    param([string]$Text)
    if ([string]::IsNullOrEmpty($Text)) { return $false }
    if ($Text.Length -lt 1 -or $Text.Length -gt 12) { return $false }
    foreach ($ch in $Text.ToCharArray()) {
        $code = [int]$ch
        if ($code -lt 48 -or $code -gt 57) { return $false }
    }
    return $true
}

function Test-VersionText {
    param([string]$Text)
    if ([string]::IsNullOrEmpty($Text)) { return $false }
    if ($Text.Length -gt 24) { return $false }
    $dots = 0
    $prevDot = $true
    foreach ($ch in $Text.ToCharArray()) {
        $code = [int]$ch
        if (($code -ge 48) -and ($code -le 57)) { $prevDot = $false; continue }
        if (($ch -eq '.') -and (-not $prevDot)) { $dots = $dots + 1; $prevDot = $true; continue }
        return $false
    }
    if ($prevDot) { return $false }
    return ($dots -ge 1)
}

function Get-FieldKind {
    param([string]$Text)
    $result = New-Object psobject -Property @{
        Kind = 'other'
        Length = 0
        Phrase = 0
        Leaf = 0
        Path = 0
        Xll = 0
        Value = 'omitted'
    }
    if ([string]::IsNullOrEmpty($Text)) {
        $result.Kind = 'empty'
        $result.Value = 'empty'
        return $result
    }
    $result.Length = $Text.Length
    $flags = Get-RecordFlags -Text $Text
    $result.Phrase = [int]$flags.Phrase
    $result.Leaf = [int]$flags.Leaf
    $result.Path = [int]$flags.Path
    $result.Xll = [int]$flags.Xll
    if ([int]$flags.Phrase -eq 1) { $result.Kind = 'serious_phrase'; return $result }
    if ([int]$flags.Path -eq 1) { $result.Kind = 'path'; return $result }
    if ([int]$flags.Xll -eq 1) { $result.Kind = 'xll'; return $result }
    if ([int]$flags.Leaf -eq 1) { $result.Kind = 'leaf'; return $result }
    if (Test-ExcelApp -Text $Text) { $result.Kind = 'excel_app'; $result.Value = 'excel'; return $result }
    if (Test-NumericText -Text $Text) { $result.Kind = 'numeric'; $result.Value = $Text; return $result }
    if (Test-VersionText -Text $Text) { $result.Kind = 'version'; $result.Value = $Text; return $result }
    return $result
}

function Get-PropertyText {
    param($Property)
    if ($null -eq $Property) { return '' }
    $value = $Property
    $hasValue = $false
    try { $hasValue = $null -ne $Property.PSObject.Properties['Value'] } catch { $hasValue = $false }
    if ($hasValue) {
        try { $value = $Property.Value } catch { $value = $Property }
    }
    if ($null -eq $value) { return '' }
    return [string]$value
}

function Get-PidMatch {
    param([string]$EventPid, [int]$FocusPid)
    if ($EventPid -eq 'unavailable') { return 'unavailable' }
    $parsed = 0
    $ok = [int]::TryParse($EventPid, [ref]$parsed)
    if (-not $ok) { return 'unavailable' }
    if (($parsed -eq $FocusPid) -and ($FocusPid -gt 0)) { return '1' }
    return '0'
}

function Get-AlertWindow {
    param([string]$StartUtc)
    $parsed = [DateTimeOffset]::Parse($StartUtc)
    $begin = $parsed.AddMinutes(-2)
    $end = $parsed.AddMinutes(15)
    return (New-Object psobject -Property @{
        BeginUtc = ($begin.UtcDateTime.ToString('yyyy-MM-ddTHH:mm:ss') + 'Z')
        EndUtc = ($end.UtcDateTime.ToString('yyyy-MM-ddTHH:mm:ss') + 'Z')
        BeginLocal = $begin.ToLocalTime().DateTime
        EndLocal = $end.ToLocalTime().DateTime
    })
}

function Get-PayloadJudgment {
    param([string]$State, [string]$Truncated, [int]$Listed, [int]$SplitCount, [int]$MessageOnly)
    if ($Truncated -eq '1' -and ($State -eq 'ok' -or $State -eq 'empty')) { return 'payload_truncated' }
    if ($State -eq 'absent') { return 'oalerts_absent' }
    if ($State -eq 'unreadable') { return 'payload_unreadable' }
    if ($State -eq 'empty' -or $Listed -eq 0) { return 'payload_absent' }
    if ($SplitCount -gt 0) { return 'fields_read' }
    if ($MessageOnly -gt 0) { return 'message_only' }
    return 'payload_unreadable'
}

function Test-NoMatchingEventQuery {
    param([string]$ErrorId, [string]$Message)
    if ([string]::IsNullOrEmpty($ErrorId)) { $ErrorId = '' }
    if ([string]::IsNullOrEmpty($Message)) { $Message = '' }
    if ($ErrorId.IndexOf('NoMatchingEventsFound', $script:OrdinalIgnore) -ge 0) { return $true }
    if ($Message.IndexOf('No events', $script:OrdinalIgnore) -ge 0) { return $true }
    $missing = -join @(
        [char]0x898B, [char]0x3064, [char]0x304B, [char]0x308A, [char]0x307E, [char]0x305B, [char]0x3093
    )
    if ($Message.IndexOf($missing, $script:Ordinal) -ge 0) { return $true }
    return $false
}

function Get-QueryState {
    param([string]$ErrorId, [string]$Message)
    if ([string]::IsNullOrEmpty($ErrorId)) { $ErrorId = '' }
    if ([string]::IsNullOrEmpty($Message)) { $Message = '' }
    if (Test-NoMatchingEventQuery -ErrorId $ErrorId -Message $Message) { return 'empty' }
    $absent = $false
    if ($ErrorId.IndexOf('EventLogNotFound', $script:OrdinalIgnore) -ge 0) { $absent = $true }
    if ($Message.IndexOf('EventLogNotFound', $script:OrdinalIgnore) -ge 0) { $absent = $true }
    if ($Message.IndexOf('does not exist', $script:OrdinalIgnore) -ge 0) { $absent = $true }
    if ($Message.IndexOf('not an event log', $script:OrdinalIgnore) -ge 0) { $absent = $true }
    if ($Message.IndexOf('were not found', $script:OrdinalIgnore) -ge 0) { $absent = $true }
    $absentJa = -join @([char]0x5B58, [char]0x5728, [char]0x3057, [char]0x307E, [char]0x305B, [char]0x3093)
    if ($Message.IndexOf($absentJa, $script:Ordinal) -ge 0) { $absent = $true }
    if ($absent) { return 'absent' }
    return 'unreadable'
}

function Assert-Case {
    param([string]$Name, [bool]$Ok)
    $script:CaseCount = $script:CaseCount + 1
    if (-not $Ok) { throw ('selftest_failed:' + $Name) }
}

function Invoke-AlertPayloadSelfTest {
    Assert-Case 'serious_len' ($script:SeriousErrorJa.Length -eq 6)
    Assert-Case 'reopen_len' ($script:ReopenDocumentJa.Length -eq 14)
    $phrase = Get-FieldKind -Text ($script:Leaf + ' ' + $script:SeriousErrorJa)
    Assert-Case 'phrase_kind' ([string]$phrase.Kind -eq 'serious_phrase')
    Assert-Case 'phrase_flags' (([int]$phrase.Phrase -eq 1) -and ([int]$phrase.Leaf -eq 1) -and ([int]$phrase.Path -eq 0) -and ([string]$phrase.Value -eq 'omitted'))
    $excel = Get-FieldKind -Text 'Microsoft Excel'
    Assert-Case 'excel_app' (([string]$excel.Kind -eq 'excel_app') -and ([string]$excel.Value -eq 'excel'))
    $short = Get-FieldKind -Text 'EXCEL'
    Assert-Case 'excel_short' ([string]$short.Kind -eq 'excel_app')
    $other = Get-FieldKind -Text 'Compositor Type: 0'
    Assert-Case 'compositor_other' (([string]$other.Kind -eq 'other') -and ([string]$other.Value -eq 'omitted') -and ([int]$other.Phrase -eq 0))
    $numeric = Get-FieldKind -Text '200054'
    Assert-Case 'numeric_kind' (([string]$numeric.Kind -eq 'numeric') -and ([string]$numeric.Value -eq '200054'))
    $longNum = Get-FieldKind -Text '1234567890123'
    Assert-Case 'numeric_cap' ([string]$longNum.Kind -eq 'other')
    $version = Get-FieldKind -Text '16.0.18623.20208'
    Assert-Case 'version_kind' (([string]$version.Kind -eq 'version') -and ([string]$version.Value -eq '16.0.18623.20208'))
    $empty = Get-FieldKind -Text ''
    Assert-Case 'empty_kind' (([string]$empty.Kind -eq 'empty') -and ([string]$empty.Value -eq 'empty'))
    $xll = Get-FieldKind -Text $script:XllStem
    Assert-Case 'xll_kind' (([string]$xll.Kind -eq 'xll') -and ([int]$xll.Xll -eq 1) -and ([string]$xll.Value -eq 'omitted'))
    Assert-Case 'pid_match' ((Get-PidMatch -EventPid '43904' -FocusPid 43904) -eq '1')
    Assert-Case 'pid_zero' ((Get-PidMatch -EventPid '0' -FocusPid 43904) -eq '0')
    Assert-Case 'pid_missing' ((Get-PidMatch -EventPid 'unavailable' -FocusPid 43904) -eq 'unavailable')
    Assert-Case 'judge_fields' ((Get-PayloadJudgment -State 'ok' -Truncated '0' -Listed 2 -SplitCount 2 -MessageOnly 0) -eq 'fields_read')
    Assert-Case 'judge_message' ((Get-PayloadJudgment -State 'ok' -Truncated '0' -Listed 1 -SplitCount 0 -MessageOnly 1) -eq 'message_only')
    Assert-Case 'judge_absent_rows' ((Get-PayloadJudgment -State 'empty' -Truncated '0' -Listed 0 -SplitCount 0 -MessageOnly 0) -eq 'payload_absent')
    Assert-Case 'judge_log_absent' ((Get-PayloadJudgment -State 'absent' -Truncated '0' -Listed 0 -SplitCount 0 -MessageOnly 0) -eq 'oalerts_absent')
    Assert-Case 'judge_unread' ((Get-PayloadJudgment -State 'unreadable' -Truncated '0' -Listed 0 -SplitCount 0 -MessageOnly 0) -eq 'payload_unreadable')
    Assert-Case 'judge_trunc' ((Get-PayloadJudgment -State 'ok' -Truncated '1' -Listed 2 -SplitCount 2 -MessageOnly 0) -eq 'payload_truncated')
    Assert-Case 'query_absent' ((Get-QueryState -ErrorId 'Other' -Message 'The specified providers were not found.') -eq 'absent')
    $window = Get-AlertWindow -StartUtc $script:PinnedStartUtc
    Assert-Case 'window_begin' ([string]$window.BeginUtc -eq '2026-10-03T02:20:51Z')
    Assert-Case 'window_end' ([string]$window.EndUtc -eq '2026-10-03T02:37:51Z')
    Assert-Case 'provider_safe' ((Get-SafeProvider -Name 'Microsoft Office 16 Alerts') -eq 'Microsoft_Office_16_Alerts')
    Write-Output 'ACTION=diagnose_canonical_alert_payload_readonly'
    Write-Output 'READ_ONLY=1'
    Write-Output 'APPLICATION_QUERIED=0'
    Write-Output 'PROCESS_QUERIED=0'
    Write-Output 'DIALOG_QUERIED=0'
    Write-Output 'REGISTRY_REREAD=0'
    Write-Output 'PROOF judgment=fields_read'
    Write-Output 'PROOF judgment=message_only'
    Write-Output 'PROOF judgment=payload_absent'
    Write-Output 'PROOF field=excel_app'
    Write-Output ('PROOF value=' + [string]$numeric.Value)
    Write-Output ('PROOF value=' + [string]$version.Value)
    Write-Output ('CASE_COUNT=' + $script:CaseCount.ToString())
    Write-Output 'SELFTEST PASS'
    Write-Output 'NOTHING_TOUCHED=1'
    Write-Output 'REGISTRY_CHANGED=0'
    Write-Output 'WORKBOOK_CHANGED=0'
    Write-Output 'XLL_CHANGED=0'
    Write-Output 'DIALOG_CLICKED=0'
    Write-Output 'EXCEL_STOP_REQUESTED=0'
}

function Write-Refused {
    param([string]$Reason)
    Write-Output 'ACTION=diagnose_canonical_alert_payload_readonly'
    Write-Output 'READ_ONLY=1'
    Write-Output ('REASON=' + $Reason)
    Write-Output 'APPLICATION_QUERIED=0'
    Write-Output 'PROCESS_QUERIED=0'
    Write-Output 'NOTHING_TOUCHED=1'
    Write-Output 'REGISTRY_CHANGED=0'
    Write-Output 'WORKBOOK_CHANGED=0'
    Write-Output 'XLL_CHANGED=0'
    Write-Output 'DIALOG_CLICKED=0'
    Write-Output 'EXCEL_STOP_REQUESTED=0'
}

function Get-Id300Rows {
    param([datetime]$BeginLocal, [datetime]$EndLocal)
    $result = New-Object psobject -Property @{
        State = 'unreadable'
        Truncated = '0'
        Events = (New-Object System.Collections.Generic.List[object])
    }
    $events = @()
    try {
        $filter = @{
            LogName = 'OAlerts'
            Id = 300
            StartTime = $BeginLocal
            EndTime = $EndLocal
        }
        $events = @(Get-WinEvent -FilterHashtable $filter -MaxEvents $script:MaxEvents -ErrorAction Stop)
        $result.State = 'ok'
    } catch {
        $errorId = ''
        $msg = ''
        try { $errorId = [string]$_.FullyQualifiedErrorId } catch { $errorId = '' }
        try { $msg = [string]$_.Exception.Message } catch { $msg = '' }
        $result.State = Get-QueryState -ErrorId $errorId -Message $msg
        $events = @()
    }
    $raw = 0
    foreach ($ev in $events) {
        if ($null -eq $ev) { continue }
        $raw = $raw + 1
        $eventId = 0
        try { $eventId = [int]$ev.Id } catch { $eventId = 0 }
        if ($eventId -ne 300) { continue }
        if ($result.Events.Count -ge 8) { continue }
        $message = ''
        $messageState = 'empty'
        try {
            $message = [string]$ev.Message
            if ([string]::IsNullOrEmpty($message)) { $messageState = 'empty' } else { $messageState = 'formatted' }
        } catch {
            $message = ''
            $messageState = 'unreadable'
        }
        $messageFlags = Get-RecordFlags -Text $message
        $propState = 'ok'
        $propValues = New-Object System.Collections.Generic.List[string]
        try {
            $incomingCount = 0
            if ($null -ne $ev.Properties) { $incomingCount = [int]$ev.Properties.Count }
            $p = 0
            while ($p -lt $incomingCount) {
                [void]$propValues.Add((Get-PropertyText -Property $ev.Properties[$p]))
                $p = $p + 1
            }
        } catch {
            $propState = 'unreadable'
            $propValues = New-Object System.Collections.Generic.List[string]
        }
        $provider = ''
        try { $provider = [string]$ev.ProviderName } catch { $provider = '' }
        $utc = ''
        try { $utc = $ev.TimeCreated.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss') + 'Z' } catch { $utc = '' }
        $level = 'unavailable'
        try { if ($null -ne $ev.Level) { $level = ([int]$ev.Level).ToString() } } catch { $level = 'unavailable' }
        $record = 'unavailable'
        try { if ($null -ne $ev.RecordId) { $record = ([int64]$ev.RecordId).ToString() } } catch { $record = 'unavailable' }
        $eventPid = 'unavailable'
        try { if ($null -ne $ev.ProcessId) { $eventPid = ([int]$ev.ProcessId).ToString() } } catch { $eventPid = 'unavailable' }
        [void]$result.Events.Add((New-Object psobject -Property @{
            Id = $eventId
            Provider = (Get-SafeProvider -Name $provider)
            Utc = $utc
            Level = $level
            Record = $record
            EventPid = $eventPid
            MessageState = $messageState
            MessageLength = $message.Length
            MessagePhrase = [int]$messageFlags.Phrase
            MessageLeaf = [int]$messageFlags.Leaf
            MessagePath = [int]$messageFlags.Path
            MessageXll = [int]$messageFlags.Xll
            PropState = $propState
            PropValues = $propValues
        }))
    }
    if ($raw -ge $script:MaxEvents) { $result.Truncated = '1' }
    if (($result.State -eq 'ok') -and ($raw -eq 0)) { $result.State = 'empty' }
    return $result
}

function Invoke-LivePayload {
    param([int]$FocusPid)
    $window = Get-AlertWindow -StartUtc $script:PinnedStartUtc
    Write-Output 'ACTION=diagnose_canonical_alert_payload_readonly'
    Write-Output 'READ_ONLY=1'
    Write-Output 'APPLICATION_QUERIED=0'
    Write-Output 'PROCESS_QUERIED=0'
    Write-Output 'DIALOG_QUERIED=0'
    Write-Output 'CACHE_REREAD=0'
    Write-Output 'RULES_REREAD=0'
    Write-Output 'PACKAGE_REREAD=0'
    Write-Output 'REGISTRY_REREAD=0'
    Write-Output ('LAUNCHED_PID=' + $FocusPid.ToString())
    Write-Output 'WINDOW_SOURCE=pinned'
    Write-Output ('WINDOW_BEGIN_UTC=' + [string]$window.BeginUtc)
    Write-Output ('WINDOW_END_UTC=' + [string]$window.EndUtc)
    Write-Output 'QUERY_BEGIN log=oalerts id=300'
    $rows = Get-Id300Rows -BeginLocal $window.BeginLocal -EndLocal $window.EndLocal
    Write-Output ('QUERY log=oalerts id=300 state=' + [string]$rows.State + ' listed=' + ([int]$rows.Events.Count).ToString() + ' truncated=' + [string]$rows.Truncated)
    $n = 0
    $splitCount = 0
    $messageOnly = 0
    $known52 = 0
    $known54 = 0
    foreach ($row in $rows.Events) {
        $n = $n + 1
        $propCount = 0
        $propPhrase = 0
        $propLeaf = 0
        $propPath = 0
        $propXll = 0
        $fields = New-Object System.Collections.Generic.List[object]
        if ([string]$row.PropState -eq 'ok') {
            $propCount = [int]$row.PropValues.Count
            $index = 0
            while ($index -lt $propCount) {
                $kind = Get-FieldKind -Text ([string]$row.PropValues[$index])
                if ([int]$kind.Phrase -eq 1) { $propPhrase = 1 }
                if ([int]$kind.Leaf -eq 1) { $propLeaf = 1 }
                if ([int]$kind.Path -eq 1) { $propPath = 1 }
                if ([int]$kind.Xll -eq 1) { $propXll = 1 }
                if ($index -lt $script:MaxFields) {
                    [void]$fields.Add((New-Object psobject -Property @{
                        Index = $index
                        Kind = [string]$kind.Kind
                        Length = [int]$kind.Length
                        Phrase = [int]$kind.Phrase
                        Leaf = [int]$kind.Leaf
                        Path = [int]$kind.Path
                        Xll = [int]$kind.Xll
                        Value = [string]$kind.Value
                    }))
                }
                $index = $index + 1
            }
            if ($propCount -gt 0) { $splitCount = $splitCount + 1 }
        }
        if (([string]$row.MessageState -eq 'formatted') -and ($propCount -eq 0)) { $messageOnly = $messageOnly + 1 }
        $pidMatch = Get-PidMatch -EventPid ([string]$row.EventPid) -FocusPid $FocusPid
        if ([string]$row.Utc -eq $script:Known52) { $known52 = 1 }
        if ([string]$row.Utc -eq $script:Known54) { $known54 = 1 }
        $fieldTrunc = '0'
        if ($propCount -gt $script:MaxFields) { $fieldTrunc = '1' }
        Write-Output ('PAYLOAD n=' + $n.ToString() + ' id=' + ([int]$row.Id).ToString() + ' provider=' + [string]$row.Provider + ' utc=' + [string]$row.Utc + ' level=' + [string]$row.Level + ' record=' + [string]$row.Record + ' event_pid=' + [string]$row.EventPid + ' event_pid_match=' + $pidMatch + ' msg_state=' + [string]$row.MessageState + ' msg_len=' + ([int]$row.MessageLength).ToString() + ' prop_state=' + [string]$row.PropState + ' prop_count=' + $propCount.ToString() + ' field_truncated=' + $fieldTrunc + ' msg_phrase=' + ([int]$row.MessagePhrase).ToString() + ' msg_leaf=' + ([int]$row.MessageLeaf).ToString() + ' msg_path=' + ([int]$row.MessagePath).ToString() + ' msg_xll=' + ([int]$row.MessageXll).ToString() + ' prop_phrase=' + $propPhrase.ToString() + ' prop_leaf=' + $propLeaf.ToString() + ' prop_path=' + $propPath.ToString() + ' prop_xll=' + $propXll.ToString())
        $fieldIndex = 0
        while ($fieldIndex -lt $fields.Count) {
            $field = $fields[$fieldIndex]
            Write-Output ('FIELD n=' + $n.ToString() + ' i=' + ([int]$field.Index).ToString() + ' kind=' + [string]$field.Kind + ' len=' + ([int]$field.Length).ToString() + ' phrase=' + ([int]$field.Phrase).ToString() + ' leaf=' + ([int]$field.Leaf).ToString() + ' path=' + ([int]$field.Path).ToString() + ' xll=' + ([int]$field.Xll).ToString() + ' value=' + [string]$field.Value)
            $fieldIndex = $fieldIndex + 1
        }
    }
    $primary = Get-PayloadJudgment -State ([string]$rows.State) -Truncated ([string]$rows.Truncated) -Listed $n -SplitCount $splitCount -MessageOnly $messageOnly
    Write-Output ('KNOWN_52=' + $known52.ToString())
    Write-Output ('KNOWN_54=' + $known54.ToString())
    Write-Output ('JUDGMENT_PAYLOAD=' + $primary)
    Write-Output 'JUDGMENT_LIMIT=id_300_is_alert_record_not_cause'
    Write-Output 'NOTHING_TOUCHED=1'
    Write-Output 'REGISTRY_CHANGED=0'
    Write-Output 'WORKBOOK_CHANGED=0'
    Write-Output 'XLL_CHANGED=0'
    Write-Output 'DIALOG_CLICKED=0'
    Write-Output 'EXCEL_STOP_REQUESTED=0'
}

if ($SelfTest) {
    Invoke-AlertPayloadSelfTest
    return
}
if (-not [string]::Equals($Confirm, $script:ConfirmToken, $script:Ordinal)) {
    Write-Refused -Reason 'confirm_token_missing'
    throw 'confirm_token_missing'
}
Invoke-LivePayload -FocusPid $LaunchedPid
