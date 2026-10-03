param(
    [switch]$SelfTest,
    [string]$Confirm = '',
    [int]$LaunchedPid = 0
)

# Read-only listing of every OAlerts event in the launch window, plus the
# safe error class of the three Application providers that stayed unreadable.
# The earlier alert scan already judged the one matching event. This script
# does not open the local cache, Rules, Recovery, the registry, the workbook,
# or the dialog, and it does not print event messages.
# -SelfTest does not read processes, files, or event logs.

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$script:Ordinal = [StringComparison]::Ordinal
$script:OrdinalIgnore = [StringComparison]::OrdinalIgnoreCase
$script:Leaf = 'Kioxia_MS2_RSS_Live_Signals.xlsx'
$script:PathTail = 'MarketSpeed II RSS\files\Kioxia_MS2_RSS_Live_Signals.xlsx'
$script:XllStem = 'MarketSpeed2_RSS'
$script:ConfirmToken = 'DIAGNOSE_CANONICAL_ALERT_SIBLING_READONLY'
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
    $absentJa = -join @([char]0x5B58, [char]0x5728, [char]0x3057, [char]0x307E, [char]0x305B, [char]0x3093)
    if ($Message.IndexOf($absentJa, $script:Ordinal) -ge 0) { $absent = $true }
    if ($absent) { return 'absent' }
    return 'unreadable'
}

function Get-ErrorToken {
    param([string]$ErrorId, [string]$Message)
    $state = Get-QueryState -ErrorId $ErrorId -Message $Message
    if ($state -eq 'empty' -or $state -eq 'absent') { return $state }
    if ([string]::IsNullOrEmpty($Message)) { $Message = '' }
    if ($Message.IndexOf('Access is denied', $script:OrdinalIgnore) -ge 0) { return 'access_denied' }
    $denied = -join @([char]0x30A2, [char]0x30AF, [char]0x30BB, [char]0x30B9, [char]0x304C, [char]0x62D2, [char]0x5426)
    if ($Message.IndexOf($denied, $script:Ordinal) -ge 0) { return 'access_denied' }
    if ($Message.IndexOf('parameter is incorrect', $script:OrdinalIgnore) -ge 0) { return 'parameter_incorrect' }
    $paramJa = -join @([char]0x30D1, [char]0x30E9, [char]0x30E1, [char]0x30FC, [char]0x30BF, [char]0x30FC)
    if ($Message.IndexOf($paramJa, $script:Ordinal) -ge 0) { return 'parameter_incorrect' }
    $idLeaf = $ErrorId
    if ([string]::IsNullOrEmpty($idLeaf)) { return 'unreadable' }
    $cut = $idLeaf.IndexOf(',', $script:Ordinal)
    if ($cut -gt 0) { $idLeaf = $idLeaf.Substring(0, $cut) }
    return (Get-SafeLeaf -Name $idLeaf)
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

function Get-WindowSource {
    param([string]$Alive, [string]$StartUtc)
    if ($Alive -eq '1' -and -not [string]::IsNullOrEmpty($StartUtc)) { return 'process' }
    return 'pinned'
}

function Get-SiblingJudgment {
    param([string]$OalertsState, [string]$Truncated)
    if ($Truncated -eq '1' -and ($OalertsState -eq 'ok' -or $OalertsState -eq 'empty')) { return 'sibling_truncated' }
    if ($OalertsState -eq 'absent') { return 'oalerts_absent' }
    if ($OalertsState -eq 'ok' -or $OalertsState -eq 'empty') { return 'sibling_listed' }
    return 'oalerts_unreadable'
}

function Assert-Case {
    param([string]$Name, [bool]$Ok)
    $script:CaseCount = $script:CaseCount + 1
    if (-not $Ok) { throw ('selftest_failed:' + $Name) }
}

function Invoke-AlertSiblingSelfTest {
    Assert-Case 'serious_len' ($script:SeriousErrorJa.Length -eq 6)
    Assert-Case 'reopen_len' ($script:ReopenDocumentJa.Length -eq 14)
    $both = Get-RecordFlags -Text ($script:Leaf + ' ' + $script:SeriousErrorJa)
    Assert-Case 'phrase_and_leaf' (([int]$both.Phrase -eq 1) -and ([int]$both.Leaf -eq 1) -and ([int]$both.Path -eq 0))
    $plain = Get-RecordFlags -Text 'dialog closed'
    Assert-Case 'plain_off' (([int]$plain.Phrase -eq 0) -and ([int]$plain.Leaf -eq 0) -and ([int]$plain.Xll -eq 0))
    Assert-Case 'skip_1000' ((Test-SkippedEventId -Id 1000) -eq $true)
    Assert-Case 'keep_300' ((Test-SkippedEventId -Id 300) -eq $false)
    Assert-Case 'err_empty' ((Get-ErrorToken -ErrorId 'NoMatchingEventsFound,Microsoft.PowerShell.Commands.GetWinEventCommand' -Message 'x') -eq 'empty')
    Assert-Case 'err_absent' ((Get-ErrorToken -ErrorId 'Other' -Message 'The specified providers were not found.') -eq 'absent')
    Assert-Case 'err_denied' ((Get-ErrorToken -ErrorId 'Other' -Message 'Access is denied') -eq 'access_denied')
    Assert-Case 'err_param' ((Get-ErrorToken -ErrorId 'Other' -Message 'The parameter is incorrect') -eq 'parameter_incorrect')
    Assert-Case 'err_type' ((Get-ErrorToken -ErrorId 'InvalidOperationException,Microsoft.PowerShell.Commands.GetWinEventCommand' -Message 'failed') -eq 'InvalidOperationException')
    Assert-Case 'judge_listed' ((Get-SiblingJudgment -OalertsState 'ok' -Truncated '0') -eq 'sibling_listed')
    Assert-Case 'judge_empty' ((Get-SiblingJudgment -OalertsState 'empty' -Truncated '0') -eq 'sibling_listed')
    Assert-Case 'judge_absent' ((Get-SiblingJudgment -OalertsState 'absent' -Truncated '0') -eq 'oalerts_absent')
    Assert-Case 'judge_unread' ((Get-SiblingJudgment -OalertsState 'unreadable' -Truncated '0') -eq 'oalerts_unreadable')
    Assert-Case 'judge_trunc' ((Get-SiblingJudgment -OalertsState 'ok' -Truncated '1') -eq 'sibling_truncated')
    $window = Get-AlertWindow -StartUtc $script:PinnedStartUtc
    Assert-Case 'window_begin' ([string]$window.BeginUtc -eq '2026-10-03T02:20:51Z')
    Assert-Case 'window_end' ([string]$window.EndUtc -eq '2026-10-03T02:37:51Z')
    Assert-Case 'source_process' ((Get-WindowSource -Alive '1' -StartUtc $script:PinnedStartUtc) -eq 'process')
    Assert-Case 'provider_safe' ((Get-SafeProvider -Name 'Microsoft Office 16 Alerts') -eq 'Microsoft_Office_16_Alerts')
    Write-Output 'ACTION=diagnose_canonical_alert_sibling_readonly'
    Write-Output 'READ_ONLY=1'
    Write-Output 'CACHE_REREAD=0'
    Write-Output 'RULES_REREAD=0'
    Write-Output 'PACKAGE_REREAD=0'
    Write-Output 'REGISTRY_REREAD=0'
    Write-Output 'DIALOG_QUERIED=0'
    Write-Output 'PROOF judgment=sibling_listed'
    Write-Output 'PROOF judgment=oalerts_absent'
    Write-Output 'PROOF judgment=oalerts_unreadable'
    Write-Output 'PROOF error=access_denied'
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
    Write-Output 'ACTION=diagnose_canonical_alert_sibling_readonly'
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
    $info = New-Object psobject -Property @{ Alive = '0'; Excel = '0'; Canonical = 'unreadable'; StartUtc = '' }
    if ($ProcId -le 0) { return $info }
    $proc = $null
    try { $proc = Get-Process -Id $ProcId -ErrorAction Stop } catch { return $info }
    $info.Alive = '1'
    $name = ''
    try { $name = [string]$proc.ProcessName } catch { $name = '' }
    if ($name.Equals('EXCEL', $script:OrdinalIgnore) -or $name.Equals('EXCEL.EXE', $script:OrdinalIgnore)) { $info.Excel = '1' }
    try {
        $info.StartUtc = $proc.StartTime.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss') + 'Z'
    } catch {
        $info.StartUtc = ''
    }
    $command = ''
    try {
        $row = Get-CimInstance -ClassName Win32_Process -Filter ('ProcessId=' + $ProcId.ToString()) -ErrorAction Stop
        try { $command = [string]$row.CommandLine } catch { $command = '' }
    } catch {
        $command = ''
    }
    if ([string]::IsNullOrEmpty($command)) { $info.Canonical = 'unreadable' }
    elseif ($command.IndexOf($script:Leaf, $script:OrdinalIgnore) -ge 0) { $info.Canonical = '1' }
    else { $info.Canonical = '0' }
    return $info
}

function Get-EventRows {
    param(
        [string]$LogName,
        [string]$ProviderName,
        [datetime]$BeginLocal,
        [datetime]$EndLocal
    )
    $result = New-Object psobject -Property @{
        State = 'unreadable'
        ErrorToken = 'unreadable'
        Truncated = '0'
        Events = (New-Object System.Collections.Generic.List[object])
    }
    $events = @()
    try {
        $filter = @{
            LogName = $LogName
            StartTime = $BeginLocal
            EndTime = $EndLocal
        }
        if (-not [string]::IsNullOrEmpty($ProviderName)) { $filter['ProviderName'] = $ProviderName }
        $events = @(Get-WinEvent -FilterHashtable $filter -MaxEvents $script:MaxEvents -ErrorAction Stop)
        $result.State = 'ok'
        $result.ErrorToken = 'ok'
    } catch {
        $errorId = ''
        $msg = ''
        try { $errorId = [string]$_.FullyQualifiedErrorId } catch { $errorId = '' }
        try { $msg = [string]$_.Exception.Message } catch { $msg = '' }
        $result.State = Get-QueryState -ErrorId $errorId -Message $msg
        $result.ErrorToken = Get-ErrorToken -ErrorId $errorId -Message $msg
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
        $flags = Get-RecordFlags -Text $message
        $providerLabel = ''
        if (-not [string]::IsNullOrEmpty($ProviderName)) {
            $providerLabel = Get-SafeProvider -Name $ProviderName
        } else {
            $rawProvider = ''
            try { $rawProvider = [string]$ev.ProviderName } catch { $rawProvider = '' }
            $providerLabel = Get-SafeProvider -Name $rawProvider
        }
        $utc = ''
        try { $utc = $ev.TimeCreated.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss') + 'Z' } catch { $utc = '' }
        if ($result.Events.Count -ge 8) { continue }
        [void]$result.Events.Add((New-Object psobject -Property @{
            Id = $eventId
            Provider = $providerLabel
            Utc = $utc
            Phrase = [int]$flags.Phrase
            Leaf = [int]$flags.Leaf
            Path = [int]$flags.Path
            Xll = [int]$flags.Xll
        }))
    }
    if ($raw -ge $script:MaxEvents) { $result.Truncated = '1' }
    if (($result.State -eq 'ok') -and ($raw -eq 0)) {
        $result.State = 'empty'
        $result.ErrorToken = 'empty'
    }
    return $result
}

function Invoke-LiveSibling {
    param([int]$FocusPid)
    $launch = Get-LaunchStamp -ProcId $FocusPid
    $source = Get-WindowSource -Alive ([string]$launch.Alive) -StartUtc ([string]$launch.StartUtc)
    $startUtc = $script:PinnedStartUtc
    if ($source -eq 'process') { $startUtc = [string]$launch.StartUtc }
    $window = $null
    try { $window = Get-AlertWindow -StartUtc $startUtc } catch { $window = $null }
    if ($null -eq $window) {
        $source = 'pinned'
        $window = Get-AlertWindow -StartUtc $script:PinnedStartUtc
    }
    Write-Output 'ACTION=diagnose_canonical_alert_sibling_readonly'
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
    Write-Output 'QUERY_BEGIN log=oalerts'
    $oalerts = Get-EventRows -LogName 'OAlerts' -ProviderName '' -BeginLocal $window.BeginLocal -EndLocal $window.EndLocal
    Write-Output ('QUERY log=oalerts state=' + [string]$oalerts.State + ' class=' + [string]$oalerts.ErrorToken + ' listed=' + ([int]$oalerts.Events.Count).ToString() + ' truncated=' + [string]$oalerts.Truncated)
    $n = 0
    foreach ($row in $oalerts.Events) {
        $n = $n + 1
        Write-Output ('EVENT n=' + $n.ToString() + ' id=' + ([int]$row.Id).ToString() + ' provider=' + [string]$row.Provider + ' utc=' + [string]$row.Utc + ' phrase=' + ([int]$row.Phrase).ToString() + ' leaf=' + ([int]$row.Leaf).ToString() + ' path=' + ([int]$row.Path).ToString() + ' xll=' + ([int]$row.Xll).ToString())
    }
    foreach ($provider in @(
        'Microsoft Office 16 Alerts',
        'Microsoft Office Alerts',
        'Microsoft Excel'
    )) {
        $label = Get-SafeProvider -Name $provider
        Write-Output ('QUERY_BEGIN log=application provider=' + $label)
        $query = Get-EventRows -LogName 'Application' -ProviderName $provider -BeginLocal $window.BeginLocal -EndLocal $window.EndLocal
        Write-Output ('PROVIDER name=' + $label + ' class=' + [string]$query.ErrorToken + ' state=' + [string]$query.State + ' listed=' + ([int]$query.Events.Count).ToString())
    }
    $primary = Get-SiblingJudgment -OalertsState ([string]$oalerts.State) -Truncated ([string]$oalerts.Truncated)
    Write-Output ('JUDGMENT_SIBLING=' + $primary)
    Write-Output 'NOTHING_TOUCHED=1'
    Write-Output 'REGISTRY_CHANGED=0'
    Write-Output 'WORKBOOK_CHANGED=0'
    Write-Output 'XLL_CHANGED=0'
    Write-Output 'DIALOG_CLICKED=0'
    Write-Output 'EXCEL_STOP_REQUESTED=0'
}

if ($SelfTest) {
    Invoke-AlertSiblingSelfTest
    return
}
if (-not [string]::Equals($Confirm, $script:ConfirmToken, $script:Ordinal)) {
    Write-Refused -Reason 'confirm_token_missing'
    throw 'confirm_token_missing'
}
Invoke-LiveSibling -FocusPid $LaunchedPid
