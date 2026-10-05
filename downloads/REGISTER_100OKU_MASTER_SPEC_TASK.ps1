param(
    [string]$RepoRoot = "",
    [switch]$Register
)

# Print the daily 16:45 JST registration. Do not register unless -Register is present.
# This script does not start or stop Excel, MarketSpeed II, the Collector, the Gateway, or AI SHADOW.
# It does not submit orders. real_submit_allowed is unchanged.
$ErrorActionPreference = "Stop"

function Get-DefaultRepoRoot {
    if (-not [string]::IsNullOrWhiteSpace($RepoRoot)) { return $RepoRoot }
    return (Split-Path -Parent $PSScriptRoot)
}

$root = Get-DefaultRepoRoot
$wrapper = [IO.Path]::Combine([IO.Path]::Combine($root, "downloads"), "UPDATE_AND_SYNC_100OKU_MASTER_SPEC.ps1")
$task = "TradeCockpit-100oku-MasterSpec-Sync"
# schtasks splits a /TR value on embedded quotes. These paths have no spaces.
# The task runs the fetch-then-sync wrapper, not a copy of a frozen worktree.
if ($root.IndexOf(" ") -ge 0 -or $root.IndexOf([char]34) -ge 0 -or $wrapper.IndexOf(" ") -ge 0 -or $wrapper.IndexOf([char]34) -ge 0) {
    Write-Output "TASK_REGISTER=FAIL"
    Write-Output "REASON=PATH_HAS_SPACE_OR_QUOTE"
    exit 1
}
$action = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File " + $wrapper + " -RepoRoot " + $root

Write-Output "TASK_NAME=$task"
Write-Output "TASK_TIME=16:45"
Write-Output "TASK_TIMEZONE_ASSUMPTION=LOCAL_CLOCK_IS_JST"
Write-Output "TASK_ACTION=$action"
Write-Output "CLOUD_AGENT_WROTE_D_DRIVE=0"

if (-not $Register) {
    Write-Output "TASK_REGISTER=NOT_RUN"
    exit 0
}

if (-not (Test-Path -LiteralPath $wrapper)) {
    Write-Output "TASK_REGISTER=FAIL"
    Write-Output "REASON=WRAPPER_MISSING"
    exit 1
}

& schtasks.exe /Create /F /TN $task /SC DAILY /ST 16:45 /TR $action
if ($LASTEXITCODE -ne 0) {
    Write-Output "TASK_REGISTER=FAIL"
    exit $LASTEXITCODE
}
Write-Output "TASK_REGISTER=PASS"
exit 0
