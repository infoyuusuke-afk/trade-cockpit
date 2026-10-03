param(
    [switch]$SelfTest,
    [string]$Confirm = '',
    [int]$LaunchedPid = 0
)

# Read-only Office Alerts check for the launch window of the canonical
# workbook. The local cache, Rules, Recovery, the registry, the workbook
# zip, and the dialog are already closed and are not opened here.
# Existing crash scans covered Application event IDs 1000 and 1001 only.
# -SelfTest does not read processes, files, or event logs.

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$script:Ordinal = [StringComparison]::Ordinal
$script:OrdinalIgnore = [StringComparison]::OrdinalIgnoreCase
$script:Leaf = 'Kioxia_MS2_RSS_Live_Signals.xlsx'
$script:PathTail = 'MarketSpeed II RSS\files\Kioxia_MS2_RSS_Live_Signals.xlsx'
$script:XllStem = 'MarketSpeed2_RSS'
$script:ConfirmToken = 'DIAGNOSE_CANONICAL_ALERT_LOG_READONLY'
$script:PinnedStartUtc = '2026-10-03T02:22:51Z'
$script:MaxEvents = 80
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
    $flat = $Name.Replace(' ', '_')
    return (Get-SafeLeaf -Name $flat)
}

function Get-AlertFlags {
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

function Test-SkippedEventId {
    param([int]$Id)
    if ($Id -eq 1000) { return $true }
    if ($Id -eq 1001) { return $true }
    return $false
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
    $absentJa = -join @(
        [char]0x5B58, [char]0x5728, [char]0x3057, [char]0x307E, [char]0x305B, [char]0x3093
    )
    if ($Message.IndexOf($absentJa, $script:Ordinal) -ge 0) { $absent = $true }
    if ($absent) { return 'absent' }
    return 'unreadable'
}

function Test-ReadableState {
    param([string]$State)
    if ($State -eq 'ok') { return $true }
    if ($State -eq 'empty') { return $true }
    return $false
}

function Get-AlertJudgment {
    param(
        [int]$Phrase,
        [int]$Leaf,
        [string]$OalertsState,
        [string]$AnyReadable,
        [string]$Truncated
    )
    if ($Phrase -eq 1 -and $Leaf -eq 1) { return 'launch_dialog_logged' }
    if ($Phrase -eq 1) { return 'dialog_logged_without_workbook' }
    if ($Leaf -eq 1) { return 'workbook_logged_not_dialog' }
    if ($OalertsState -eq 'absent') { return 'oalerts_absent' }
    if ($AnyReadable -ne '1') { return 'alert_log_unreadable' }
    if ($Truncated -eq '1') { return 'alert_incomplete' }
    return 'no_launch_alert'
}

function Get-AlertLimit {
    param(
        [string]$OalertsState,
        [string]$AppUnreadable,
        [string]$Truncated,
        [string]$AppQueried
    )
    $flags = New-Object System.Collections.Generic.List[string]
    if ($Truncated -eq '1') { [void]$flags.Add('alert_truncated') }
    if ($OalertsState -eq 'absent') { [void]$flags.Add('oalerts_absent') }
    if ($OalertsState -eq 'unreadable') { [void]$flags.Add('oalerts_unreadable') }
    if ($AppUnreadable -eq '1') { [void]$flags.Add('provider_unreadable') }
    if ($AppQueried -ne '1') { [void]$flags.Add('providers_not_queried') }
    if ($flags.Count -eq 0) { return 'none' }
    return [string]::Join(',', $flags.ToArray())
}

function Get-AlertWindow {
    param([string]$StartUtc)
    $parsed = [DateTimeOffset]::Parse($StartUtc)
    $begin = $parsed.AddMinutes(-2)
    $end = $parsed.AddMinutes(15)
    $beginUtc = $begin.UtcDateTime.ToString('yyyy-MM-ddTHH:mm:ss') + 'Z'
    $endUtc = $end.UtcDateTime.ToString('yyyy-MM-ddTHH:mm:ss') + 'Z'
    $beginLocal = $begin.ToLocalTime().DateTime
    $endLocal = $end.ToLocalTime().DateTime
    return (New-Object psobject -Property @{
        BeginUtc = $beginUtc
        EndUtc = $endUtc
        BeginLocal = $beginLocal
        EndLocal = $endLocal
    })
}

function Get-WindowSource {
    param([string]$Alive, [string]$StartUtc)
    if ($Alive -eq '1' -and -not [string]::IsNullOrEmpty($StartUtc)) { return 'process' }
    return 'pinned'
}

function Assert-Case {
    param([string]$Name, [bool]$Ok)
    $script:CaseCount = $script:CaseCount + 1
    if (-not $Ok) { throw ('selftest_failed:' + $Name) }
}

function Invoke-AlertLogSelfTest {
    Assert-Case 'serious_len' ($script:SeriousErrorJa.Length -eq 6)
    Assert-Case 'reopen_len' ($script:ReopenDocumentJa.Length -eq 14)
    $phraseOnly = Get-AlertFlags -Text $script:SeriousErrorJa
    Assert-Case 'phrase_ja' (([int]$phraseOnly.Phrase -eq 1) -and ([int]$phraseOnly.Leaf -eq 0))
    $reopenOnly = Get-AlertFlags -Text $script:ReopenDocumentJa
    Assert-Case 'phrase_reopen' (([int]$reopenOnly.Phrase -eq 1) -and ([int]$reopenOnly.Leaf -eq 0))
    $english = Get-AlertFlags -Text 'serious error while opening'
    Assert-Case 'phrase_en' ([int]$english.Phrase -eq 1)
    $leafOnly = Get-AlertFlags -Text $script:Leaf
    Assert-Case 'leaf_only' (([int]$leafOnly.Leaf -eq 1) -and ([int]$leafOnly.Phrase -eq 0))
    $both = Get-AlertFlags -Text ($script:Leaf + ' ' + $script:SeriousErrorJa)
    Assert-Case 'phrase_and_leaf' (([int]$both.Phrase -eq 1) -and ([int]$both.Leaf -eq 1))
    $xllOnly = Get-AlertFlags -Text $script:XllStem
    Assert-Case 'xll_only' (([int]$xllOnly.Xll -eq 1) -and ([int]$xllOnly.Leaf -eq 0) -and ([int]$xllOnly.Phrase -eq 0))
    $pathHit = Get-AlertFlags -Text $script:PathTail
    Assert-Case 'path_sets_leaf' (([int]$pathHit.Path -eq 1) -and ([int]$pathHit.Leaf -eq 1))
    Assert-Case 'skip_1000' ((Test-SkippedEventId -Id 1000) -eq $true)
    Assert-Case 'skip_1001' ((Test-SkippedEventId -Id 1001) -eq $true)
    Assert-Case 'keep_300' ((Test-SkippedEventId -Id 300) -eq $false)
    Assert-Case 'query_empty_id' ((Get-QueryState -ErrorId 'NoMatchingEventsFound,Microsoft.PowerShell.Commands.GetWinEventCommand' -Message 'x') -eq 'empty')
    Assert-Case 'query_empty_en' ((Get-QueryState -ErrorId '' -Message 'No events were found that match the specified selection criteria.') -eq 'empty')
    Assert-Case 'query_absent_exist' ((Get-QueryState -ErrorId 'Other' -Message 'The OAlerts event log does not exist.') -eq 'absent')
    Assert-Case 'query_absent_log' ((Get-QueryState -ErrorId 'Other' -Message 'There is not an event log on the localhost computer that matches OAlerts.') -eq 'absent')
    Assert-Case 'query_absent_provider' ((Get-QueryState -ErrorId 'Other' -Message 'The specified providers were not found.') -eq 'absent')
    $absentJa = -join @([char]0x5B58, [char]0x5728, [char]0x3057, [char]0x307E, [char]0x305B, [char]0x3093)
    Assert-Case 'query_absent_ja' ((Get-QueryState -ErrorId 'Other' -Message ('log ' + $absentJa)) -eq 'absent')
    Assert-Case 'query_unreadable' ((Get-QueryState -ErrorId 'AccessDenied' -Message 'Access is denied') -eq 'unreadable')
    Assert-Case 'judge_logged' ((Get-AlertJudgment -Phrase 1 -Leaf 1 -OalertsState 'empty' -AnyReadable '1' -Truncated '0') -eq 'launch_dialog_logged')
    Assert-Case 'judge_phrase' ((Get-AlertJudgment -Phrase 1 -Leaf 0 -OalertsState 'ok' -AnyReadable '1' -Truncated '0') -eq 'dialog_logged_without_workbook')
    Assert-Case 'judge_leaf' ((Get-AlertJudgment -Phrase 0 -Leaf 1 -OalertsState 'ok' -AnyReadable '1' -Truncated '0') -eq 'workbook_logged_not_dialog')
    Assert-Case 'judge_absent' ((Get-AlertJudgment -Phrase 0 -Leaf 0 -OalertsState 'absent' -AnyReadable '1' -Truncated '0') -eq 'oalerts_absent')
    Assert-Case 'judge_unreadable' ((Get-AlertJudgment -Phrase 0 -Leaf 0 -OalertsState 'unreadable' -AnyReadable '0' -Truncated '0') -eq 'alert_log_unreadable')
    Assert-Case 'judge_incomplete' ((Get-AlertJudgment -Phrase 0 -Leaf 0 -OalertsState 'empty' -AnyReadable '1' -Truncated '1') -eq 'alert_incomplete')
    Assert-Case 'judge_clear' ((Get-AlertJudgment -Phrase 0 -Leaf 0 -OalertsState 'empty' -AnyReadable '1' -Truncated '0') -eq 'no_launch_alert')
    Assert-Case 'judge_ok_nomatch' ((Get-AlertJudgment -Phrase 0 -Leaf 0 -OalertsState 'ok' -AnyReadable '1' -Truncated '0') -eq 'no_launch_alert')
    Assert-Case 'judge_hit_beats_absent' ((Get-AlertJudgment -Phrase 1 -Leaf 1 -OalertsState 'absent' -AnyReadable '1' -Truncated '1') -eq 'launch_dialog_logged')
    Assert-Case 'limit_none' ((Get-AlertLimit -OalertsState 'empty' -AppUnreadable '0' -Truncated '0' -AppQueried '1') -eq 'none')
    Assert-Case 'limit_ok_none' ((Get-AlertLimit -OalertsState 'ok' -AppUnreadable '0' -Truncated '0' -AppQueried '1') -eq 'none')
    Assert-Case 'limit_trunc' ((Get-AlertLimit -OalertsState 'empty' -AppUnreadable '0' -Truncated '1' -AppQueried '1') -eq 'alert_truncated')
    Assert-Case 'limit_absent' ((Get-AlertLimit -OalertsState 'absent' -AppUnreadable '0' -Truncated '0' -AppQueried '1') -eq 'oalerts_absent')
    Assert-Case 'limit_unread' ((Get-AlertLimit -OalertsState 'unreadable' -AppUnreadable '1' -Truncated '0' -AppQueried '1') -eq 'oalerts_unreadable,provider_unreadable')
    $window = Get-AlertWindow -StartUtc $script:PinnedStartUtc
    Assert-Case 'window_begin' ([string]$window.BeginUtc -eq '2026-10-03T02:20:51Z')
    Assert-Case 'window_end' ([string]$window.EndUtc -eq '2026-10-03T02:37:51Z')
    Assert-Case 'source_pinned' ((Get-WindowSource -Alive '0' -StartUtc '') -eq 'pinned')
    Assert-Case 'source_process' ((Get-WindowSource -Alive '1' -StartUtc $script:PinnedStartUtc) -eq 'process')
    Assert-Case 'safe_provider' ((Get-SafeProvider -Name 'Microsoft Office 16 Alerts') -eq 'Microsoft_Office_16_Alerts')
    Assert-Case 'max_events' ($script:MaxEvents -eq 80)
    Write-Output 'ACTION=diagnose_canonical_alert_log_readonly'
    Write-Output 'READ_ONLY=1'
    Write-Output 'CACHE_REREAD=0'
    Write-Output 'RULES_REREAD=0'
    Write-Output 'PACKAGE_REREAD=0'
    Write-Output 'REGISTRY_REREAD=0'
    Write-Output 'DIALOG_QUERIED=0'
    Write-Output 'PROOF judgment=no_launch_alert'
    Write-Output 'PROOF judgment=launch_dialog_logged'
    Write-Output 'PROOF judgment=oalerts_absent'
    Write-Output 'PROOF judgment=dialog_logged_without_workbook'
    Write-Output 'PROOF judgment=workbook_logged_not_dialog'
    Write-Output 'PROOF judgment=alert_log_unreadable'
    Write-Output 'PROOF judgment=alert_incomplete'
    Write-Output 'PROOF phrase=serious'
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
    Write-Output 'ACTION=diagnose_canonical_alert_log_readonly'
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

function Get-AlertQuery {
    param(
        [string]$LogName,
        [string]$ProviderName,
        [datetime]$BeginLocal,
        [datetime]$EndLocal
    )
    $result = New-Object psobject -Property @{
        State = 'unreadable'
        Events = 0
        Truncated = '0'
        Phrase = 0
        Leaf = 0
        Xll = 0
        Hits = (New-Object System.Collections.Generic.List[object])
    }
    $events = @()
    try {
        $filter = @{
            LogName = $LogName
            StartTime = $BeginLocal
            EndTime = $EndLocal
        }
        if (-not [string]::IsNullOrEmpty($ProviderName)) {
            $filter['ProviderName'] = $ProviderName
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
        if (Test-SkippedEventId -Id $eventId) { continue }
        $message = ''
        try { $message = [string]$ev.Message } catch { $message = '' }
        $flags = Get-AlertFlags -Text $message
        if ([int]$flags.Phrase -eq 1) { $result.Phrase = 1 }
        if ([int]$flags.Leaf -eq 1) { $result.Leaf = 1 }
        if ([int]$flags.Xll -eq 1) { $result.Xll = 1 }
        if (([int]$flags.Phrase -ne 1) -and ([int]$flags.Leaf -ne 1)) { continue }
        $providerLabel = ''
        if (-not [string]::IsNullOrEmpty($ProviderName)) {
            $providerLabel = Get-SafeProvider -Name $ProviderName
        } else {
            $rawProvider = ''
            try { $rawProvider = [string]$ev.ProviderName } catch { $rawProvider = '' }
            $providerLabel = Get-SafeProvider -Name $rawProvider
        }
        $utc = ''
        try {
            $created = $ev.TimeCreated.ToUniversalTime()
            $utc = $created.ToString('yyyy-MM-ddTHH:mm:ss') + 'Z'
        } catch {
            $utc = ''
        }
        [void]$result.Hits.Add((New-Object psobject -Property @{
            Phrase = [int]$flags.Phrase
            Leaf = [int]$flags.Leaf
            Path = [int]$flags.Path
            Id = $eventId
            Provider = $providerLabel
            Utc = $utc
        }))
    }
    if ($raw -ge $script:MaxEvents) { $result.Truncated = '1' }
    if (($result.State -eq 'ok') -and ($raw -eq 0)) { $result.State = 'empty' }
    $result.Events = $raw
    return $result
}

function Add-AlertHits {
    param($State, $Query)
    if ([int]$Query.Phrase -eq 1) { $State.Phrase = 1 }
    if ([int]$Query.Leaf -eq 1) { $State.Leaf = 1 }
    if ([int]$Query.Xll -eq 1) { $State.Xll = 1 }
    if ([string]$Query.Truncated -eq '1') { $State.Truncated = '1' }
    if (Test-ReadableState -State ([string]$Query.State)) { $State.AnyReadable = '1' }
    foreach ($hit in $Query.Hits) {
        if ($State.Hits.Count -ge 8) {
            $State.Omitted = [int]$State.Omitted + 1
            continue
        }
        [void]$State.Hits.Add($hit)
    }
}

function Invoke-LiveAlert {
    param([int]$FocusPid)
    $launch = Get-LaunchStamp -ProcId $FocusPid
    $source = Get-WindowSource -Alive ([string]$launch.Alive) -StartUtc ([string]$launch.StartUtc)
    $startUtc = $script:PinnedStartUtc
    if ($source -eq 'process') { $startUtc = [string]$launch.StartUtc }
    $window = $null
    try { $window = Get-AlertWindow -StartUtc $startUtc } catch { $window = $null }
    if ($null -eq $window) {
        $source = 'pinned'
        $startUtc = $script:PinnedStartUtc
        $window = Get-AlertWindow -StartUtc $startUtc
    }
    Write-Output 'ACTION=diagnose_canonical_alert_log_readonly'
    Write-Output 'READ_ONLY=1'
    Write-Output 'CACHE_REREAD=0'
    Write-Output 'RULES_REREAD=0'
    Write-Output 'PACKAGE_REREAD=0'
    Write-Output 'REGISTRY_REREAD=0'
    Write-Output 'DIALOG_QUERIED=0'
    Write-Output ('LAUNCHED_PID=' + $FocusPid.ToString())
    Write-Output ('LAUNCHED_ALIVE=' + [string]$launch.Alive)
    Write-Output ('LAUNCHED_EXCEL=' + [string]$launch.Excel)
    Write-Output ('LAUNCHED_CANONICAL=' + [string]$launch.Canonical)
    Write-Output ('LAUNCHED_START_UTC=' + [string]$launch.StartUtc)
    Write-Output ('WINDOW_SOURCE=' + $source)
    Write-Output ('WINDOW_BEGIN_UTC=' + [string]$window.BeginUtc)
    Write-Output ('WINDOW_END_UTC=' + [string]$window.EndUtc)
    $state = New-Object psobject -Property @{
        Phrase = 0
        Leaf = 0
        Xll = 0
        Truncated = '0'
        AnyReadable = '0'
        Omitted = 0
        Hits = (New-Object System.Collections.Generic.List[object])
    }
    Write-Output 'QUERY_BEGIN log=oalerts'
    $oalerts = Get-AlertQuery -LogName 'OAlerts' -ProviderName '' -BeginLocal $window.BeginLocal -EndLocal $window.EndLocal
    Write-Output ('QUERY log=oalerts state=' + [string]$oalerts.State + ' events=' + ([int]$oalerts.Events).ToString() + ' truncated=' + [string]$oalerts.Truncated)
    Add-AlertHits -State $state -Query $oalerts
    $providers = @(
        'Microsoft Office 16 Alerts',
        'Microsoft Office Alerts',
        'Microsoft Excel'
    )
    $appUnreadable = '0'
    $appQueried = '0'
    foreach ($provider in $providers) {
        $label = Get-SafeProvider -Name $provider
        Write-Output ('QUERY_BEGIN log=application provider=' + $label)
        $query = Get-AlertQuery -LogName 'Application' -ProviderName $provider -BeginLocal $window.BeginLocal -EndLocal $window.EndLocal
        Write-Output ('QUERY log=application provider=' + $label + ' state=' + [string]$query.State + ' events=' + ([int]$query.Events).ToString() + ' truncated=' + [string]$query.Truncated)
        if ([string]$query.State -eq 'unreadable') { $appUnreadable = '1' }
        Add-AlertHits -State $state -Query $query
    }
    $appQueried = '1'
    foreach ($hit in $state.Hits) {
        Write-Output ('HIT phrase=' + ([int]$hit.Phrase).ToString() + ' leaf=' + ([int]$hit.Leaf).ToString() + ' path=' + ([int]$hit.Path).ToString() + ' id=' + ([int]$hit.Id).ToString() + ' provider=' + [string]$hit.Provider + ' utc=' + [string]$hit.Utc)
    }
    $primary = Get-AlertJudgment -Phrase ([int]$state.Phrase) -Leaf ([int]$state.Leaf) -OalertsState ([string]$oalerts.State) -AnyReadable ([string]$state.AnyReadable) -Truncated ([string]$state.Truncated)
    $limit = Get-AlertLimit -OalertsState ([string]$oalerts.State) -AppUnreadable $appUnreadable -Truncated ([string]$state.Truncated) -AppQueried $appQueried
    Write-Output ('OALERTS_STATE=' + [string]$oalerts.State)
    Write-Output ('PHRASE_MATCH=' + ([int]$state.Phrase).ToString())
    Write-Output ('LEAF_MATCH=' + ([int]$state.Leaf).ToString())
    Write-Output ('XLL_HIT=' + ([int]$state.Xll).ToString())
    Write-Output ('HIT_OMITTED=' + ([int]$state.Omitted).ToString())
    Write-Output 'APP_QUERIED=1'
    Write-Output ('JUDGMENT_ALERT=' + $primary)
    Write-Output ('JUDGMENT_LIMIT=' + $limit)
    Write-Output 'NOTHING_TOUCHED=1'
    Write-Output 'REGISTRY_CHANGED=0'
    Write-Output 'WORKBOOK_CHANGED=0'
    Write-Output 'XLL_CHANGED=0'
    Write-Output 'DIALOG_CLICKED=0'
    Write-Output 'EXCEL_STOP_REQUESTED=0'
}

if ($SelfTest) {
    Invoke-AlertLogSelfTest
    return
}
if (-not [string]::Equals($Confirm, $script:ConfirmToken, $script:Ordinal)) {
    Write-Refused -Reason 'confirm_token_missing'
    throw 'confirm_token_missing'
}
Invoke-LiveAlert -FocusPid $LaunchedPid
