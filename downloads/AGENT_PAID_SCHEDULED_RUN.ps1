#requires -Version 5.1
<#
OWNER 2026-10-22 (audit 6339629207 item 6): the specialist GPT run at 08:30 and 12:15 JST
on weekdays, without a per-run approval message, inside the existing paid limits.

The OWNER's standing approval is a local file written at registration time, after the
OWNER approved this exact code version by its full SHA:
  <LocalAppData>\100B_AGENT\paid_schedule_approval.json
  {"schema":"100b-paid-schedule-approval-v1","approved_sha":"<40 hex>",
   "slots":["0830","1215"],"approved_at":"...","owner_message":"..."}
This script runs only when that file exists, names this checkout's HEAD and this slot,
and the JST clock is inside the slot window on a weekday. It then issues the run id
(sched_YYYYMMDD_HHMM) itself. Every money limit stays in the pilot: 25 cents reserved
per run, 8 USD lifetime, 2 runs per JST day, one run per day and slot, no retry, and
the two-copy spend record (D-041). This script never registers itself and never
changes the approval file. It reads no secret into its output.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet("0830", "1215")][string]$Slot,
    [string]$RepoRoot = ""
)
$ErrorActionPreference = "Stop"
$SlotNames = @{ "0830" = "premarket_0830"; "1215" = "midday_1215" }
$WindowMinutes = 30

function Stop-Run([string]$Reason) {
    Write-Output ("SCHEDULED_RUN=BLOCKED " + $Reason)
    Write-Output "PAID_CALL_MADE=0"
    exit 2
}

if ([string]::IsNullOrWhiteSpace($RepoRoot)) { $RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..")) }
$base = Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "100B_AGENT"
$approvalPath = Join-Path $base "paid_schedule_approval.json"

# 1. The OWNER's standing approval for this exact version and slot.
if (-not (Test-Path -LiteralPath $approvalPath -PathType Leaf)) { Stop-Run "SCHEDULE_NOT_APPROVED" }
try { $approval = [IO.File]::ReadAllText($approvalPath, [Text.Encoding]::UTF8) | ConvertFrom-Json } catch { Stop-Run "SCHEDULE_APPROVAL_UNREADABLE" }
if ([string]$approval.schema -cne "100b-paid-schedule-approval-v1" -or
    [string]$approval.approved_sha -cnotmatch '^[0-9a-f]{40}$' -or
    @($approval.slots) -cnotcontains $Slot) { Stop-Run "SCHEDULE_APPROVAL_INVALID_OR_SLOT_NOT_APPROVED" }
$head = (& git -C $RepoRoot rev-parse HEAD 2>$null)
if ($LASTEXITCODE -ne 0 -or [string]$head -cne [string]$approval.approved_sha) { Stop-Run "CODE_IS_NOT_THE_APPROVED_SHA" }

# 2. Weekday and inside the slot window (JST).
$jst = [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTime]::UtcNow, "Tokyo Standard Time")
if ($jst.DayOfWeek -eq [DayOfWeek]::Saturday -or $jst.DayOfWeek -eq [DayOfWeek]::Sunday) { Stop-Run "WEEKEND" }
$slotStart = $jst.Date.AddHours([int]$Slot.Substring(0, 2)).AddMinutes([int]$Slot.Substring(2, 2))
if ($jst -lt $slotStart -or $jst -ge $slotStart.AddMinutes($WindowMinutes)) { Stop-Run "OUTSIDE_SLOT_WINDOW" }

# 3. The active paid ledger from the registry (the pilot checks it again).
$registryPath = Join-Path $base "paid_ledger_registry.json"
try { $registry = [IO.File]::ReadAllText($registryPath, [Text.Encoding]::UTF8) | ConvertFrom-Json } catch { Stop-Run "PAID_LEDGER_REGISTRY_UNREADABLE" }
$active = @($registry.ledgers | Where-Object { [string]$_.ledger_id -ceq [string]$registry.active })
if ($active.Count -ne 1) { Stop-Run "NO_ACTIVE_PAID_LEDGER" }

$runId = "sched_" + $jst.ToString("yyyyMMdd") + "_" + $Slot
$work = Join-Path $base ("runs\" + $runId)
New-Item -ItemType Directory -Force -Path $work | Out-Null
Start-Transcript -LiteralPath (Join-Path $work "run.log") -Append | Out-Null
try {
    # The OWNER's user-level settings, for this process only.
    foreach ($n in "OPENAI_API_KEY", "V10_AGENT_RESEARCH_INBOX", "AGENT_BRIDGE_HMAC_KEY", "AGENT_BRAIN_RECEIVER_HMAC_KEY") {
        Set-Item -Path ("Env:" + $n) -Value ([Environment]::GetEnvironmentVariable($n, "User"))
    }
    Remove-Item Env:OPENAI_BASE_URL -ErrorAction SilentlyContinue
    Remove-Item Env:OPENAI_AGENT_MODEL -ErrorAction SilentlyContinue
    Remove-Item Env:AGENT_PAID_LEDGER_REGISTRY -ErrorAction SilentlyContinue
    $env:AGENT_PAID_ALLOW_OFFICIAL_STATISTICS = "OWNER_DECISION_RECORDED"   # OWNER 2026-10-22 JPX
    $env:AGENT_PAID_LEDGER_PATH = [string]$active[0].path
    $env:AGENT_PAID_LEDGER_ID = [string]$active[0].ledger_id
    $env:AGENT_PAID_RUN_APPROVED_RUN_ID = $runId   # issued under the standing approval above

    $watch = [IO.File]::ReadAllText((Join-Path $RepoRoot "ms2_live\watchlist_100.json"), [Text.Encoding]::UTF8) | ConvertFrom-Json
    $codes = (@($watch.stocks.PSObject.Properties | Select-Object -First 100 | ForEach-Object { ([string]$_.Value.ticker) -replace '\.T$', '' }) -join ",")
    $evidence = Join-Path $work "evidence.json"
    Set-Location -LiteralPath $RepoRoot
    & python -B scripts\agent_sdk_evidence_bundle.py --fetch --run-id $runId --output $evidence --boj --boj-per-role 3 --jpx-margin-all-codes $codes
    if (-not (Test-Path -LiteralPath $evidence)) { Stop-Run "EVIDENCE_NOT_WRITTEN" }
    & python -B scripts\agent_sdk_coordination_pilot.py --input $evidence --enable-billable-api `
        --paid-budget-db $env:AGENT_PAID_LEDGER_PATH --receipt-db (Join-Path $work "receipts.sqlite") `
        --handoff-dir $env:V10_AGENT_RESEARCH_INBOX --slot $SlotNames[$Slot]
    $code = $LASTEXITCODE
    Write-Output ("SCHEDULED_RUN=" + $(if ($code -eq 0) { "DONE" } else { "PILOT_EXIT_" + $code }) + " " + $runId)
    exit $code
} finally {
    Stop-Transcript | Out-Null
}
