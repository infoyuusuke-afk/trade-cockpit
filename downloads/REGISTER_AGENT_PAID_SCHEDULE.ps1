#requires -Version 5.1
<#
Registers the weekday 08:30 and 12:15 JST specialist GPT runs (AGENT_PAID_SCHEDULED_RUN.ps1)
in this user's Windows Task Scheduler and writes the OWNER's standing approval file.

Run ONLY after the OWNER approved this exact code version by its full SHA in the project
chat, and pass that SHA and the OWNER's own approval words. It refuses a SHA that is not
this checkout's HEAD. -Unregister removes both tasks and the approval file.
#>
[CmdletBinding()]
param(
    [string]$ApprovedSha = "",
    [string]$OwnerMessage = "",
    [switch]$Unregister
)
$ErrorActionPreference = "Stop"
$base = Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "100B_AGENT"
$approvalPath = Join-Path $base "paid_schedule_approval.json"
$tasks = @{ "100B_GPT_0830" = "0830"; "100B_GPT_1215" = "1215" }

if ($Unregister) {
    foreach ($name in $tasks.Keys) { Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue }
    Remove-Item -LiteralPath $approvalPath -ErrorAction SilentlyContinue
    Write-Output "SCHEDULE=REMOVED"
    exit 0
}

$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$head = (& git -C $repo rev-parse HEAD 2>$null)
if ($ApprovedSha -cnotmatch '^[0-9a-f]{40}$' -or [string]$head -cne $ApprovedSha) { throw "APPROVED_SHA_IS_NOT_THIS_CHECKOUT" }
if ([string]::IsNullOrWhiteSpace($OwnerMessage)) { throw "OWNER_APPROVAL_WORDS_REQUIRED" }

New-Item -ItemType Directory -Force -Path $base | Out-Null
$approval = [ordered]@{
    schema        = "100b-paid-schedule-approval-v1"
    approved_sha  = $ApprovedSha
    slots         = @("0830", "1215")
    approved_at   = (Get-Date).ToString("o")
    owner_message = $OwnerMessage
}
[IO.File]::WriteAllText($approvalPath, ($approval | ConvertTo-Json), [Text.UTF8Encoding]::new($false))

$runner = Join-Path $PSScriptRoot "AGENT_PAID_SCHEDULED_RUN.ps1"
foreach ($name in $tasks.Keys) {
    $slot = $tasks[$name]
    $at = [datetime]::Today.AddHours([int]$slot.Substring(0, 2)).AddMinutes([int]$slot.Substring(2, 2))
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ('-NoLogo -NoProfile -ExecutionPolicy Bypass -File "' + $runner + '" -Slot ' + $slot)
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $at
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable:$false -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
}
Write-Output ("SCHEDULE=REGISTERED " + ($tasks.Keys -join ","))
