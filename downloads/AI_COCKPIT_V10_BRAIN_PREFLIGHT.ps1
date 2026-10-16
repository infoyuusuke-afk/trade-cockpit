<#
Read-only, SHA-pinned V10 BRAIN observation acceptance.
No git mutation, process launch/stop, Excel COM, market rows or orders.
#>
param(
 [string]$RepoRoot = "",
 [string]$ExpectedSha = "",
 [string]$ExpectedBranch = "",
 [string]$StateRoot = "C:\AI_Cockpit_OneClick_Starter",
 [switch]$SelfTest
)
$ErrorActionPreference = "Stop"

function Test-Timestamp([object]$Stamp,[datetimeoffset]$Now,[double]$MaxAge) {
 if ($Stamp -isnot [string] -or
     $Stamp -cnotmatch '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,7})?(Z|[+-]\d{2}:\d{2})$') { return $false }
 $time = [datetimeoffset]::MinValue
 if (-not [datetimeoffset]::TryParse($Stamp,
     [Globalization.CultureInfo]::InvariantCulture,
     [Globalization.DateTimeStyles]::None, [ref]$time)) { return $false }
 $seconds=($Now.ToUniversalTime()-$time.ToUniversalTime()).TotalSeconds
 return ($seconds -ge 0 -and $seconds -le $MaxAge)
}

function Test-SafeLocalJson([string]$Path) {
 if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
 $item=Get-Item -LiteralPath $Path -ErrorAction Stop
 return (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0 -and
   $item.Length -gt 2 -and $item.Length -le 65536)
}

function Test-OwnedWorker([int]$PidValue,[string]$Expected) {
 if ($PidValue -le 0) { return $false }
 try {
  $p=Get-CimInstance Win32_Process -Filter ("ProcessId = "+$PidValue) -ErrorAction Stop
  if ($null -eq $p) { return $false }
  $cmd=[string]$p.CommandLine
  return (-not [string]::IsNullOrWhiteSpace($cmd) -and
    $cmd.IndexOf($Expected,[StringComparison]::OrdinalIgnoreCase) -ge 0)
 } catch { return $false }
}

function Get-BrainPreflightBlockers($State,$Health,$Brain,[string]$Sha,
 [datetimeoffset]$Now,[double]$FileAge) {
 $bad=New-Object 'System.Collections.Generic.List[string]'
 if ($null -eq $State -or [int]$State.brain_observer_pid -le 0) {
  [void]$bad.Add("BRAIN_PID_NOT_RECORDED")
 }
 if ($null -eq $Health -or [string]$Health.status -cne "ok" -or
     [string]$Health.ui_sha -cne $Sha) {
  [void]$bad.Add("GATEWAY_SHA_UNVERIFIED")
 }
 if ($null -eq $Health.runtime -or
     [string]$Health.runtime.brain_observer_state -cne "BRAIN_OBSERVING_PUBLICATION_ONLY" -or
     $Health.runtime.data_conflict -ne $false -or
     $Health.runtime.fail_closed -ne $false -or
     [string]$Health.runtime.price_source_status -cne "OK") {
  [void]$bad.Add("GATEWAY_SOURCE_NOT_ACCEPTABLE")
 }
 if ($null -eq $Health.execution -or
     $Health.execution.real_submit_allowed -ne $false) {
  [void]$bad.Add("EXECUTION_SAFETY_UNVERIFIED")
 }
 if (-not (Test-Timestamp $Health.runtime.brain_observer_updated_at $Now 30)) {
  [void]$bad.Add("GATEWAY_BRAIN_TIMESTAMP_UNVERIFIED")
 }
 if ($null -eq $Brain -or [string]$Brain.schema_version -cne "ai-brain-observer-1" -or
     [string]$Brain.component_role -cne "INDEPENDENT_BRAIN_OBSERVER_NOT_TRADE_ENGINE" -or
     [string]$Brain.state -cne "OBSERVATION_ONLY" -or
     [int]$Brain.engine_pid -ne [int]$State.brain_observer_pid) {
  [void]$bad.Add("BRAIN_OWNER_OR_STATE_UNVERIFIED")
 }
 if ($Brain.real_submit_allowed -ne $false -or
     $Brain.source_authenticated -ne $false -or
     $Brain.cross_source_join_allowed -ne $false -or
     $Brain.promotion_eligible -ne $false -or
     $Brain.tested_expectancy_available -ne $false -or
     $Brain.exchange_tick_date_verified -ne $false -or
     $Brain.signal_provenance_verified -ne $false -or
     $null -ne $Brain.last_market_data_at -or
     [string]$Brain.eligible_observed_n -cne "0") {
  [void]$bad.Add("BRAIN_UNSAFE_PROMOTION")
 }
 if (-not (Test-Timestamp $Brain.updated_at $Now 30) -or
     -not (Test-Timestamp $Brain.source_publication_at $Now 60) -or
     $FileAge -lt 0 -or $FileAge -gt 30) {
  [void]$bad.Add("BRAIN_STALE_OR_FUTURE")
 }
 if ([int]$Brain.observed_rows -lt 90 -or [int]$Brain.observed_rows -gt 110) {
  [void]$bad.Add("BRAIN_COVERAGE_UNVERIFIED")
 }
 return @($bad.ToArray())
}

if ($SelfTest) {
 $sha="a"*40
 $now=[datetimeoffset]::UtcNow
 $stamp=$now.ToString("o")
 $st=('{"brain_observer_pid":1234}' | ConvertFrom-Json)
 $he=('{"status":"ok","ui_sha":"'+$sha+'","runtime":{"brain_observer_state":"BRAIN_OBSERVING_PUBLICATION_ONLY","brain_observer_updated_at":"'+$stamp+'","data_conflict":false,"fail_closed":false,"price_source_status":"OK"},"execution":{"real_submit_allowed":false}}' | ConvertFrom-Json)
 $br=('{"schema_version":"ai-brain-observer-1","component_role":"INDEPENDENT_BRAIN_OBSERVER_NOT_TRADE_ENGINE","state":"OBSERVATION_ONLY","engine_pid":1234,"updated_at":"'+$stamp+'","source_publication_at":"'+$stamp+'","observed_rows":100,"real_submit_allowed":false,"source_authenticated":false,"cross_source_join_allowed":false,"promotion_eligible":false,"tested_expectancy_available":false,"exchange_tick_date_verified":false,"signal_provenance_verified":false,"eligible_observed_n":0,"last_market_data_at":null}' | ConvertFrom-Json)
 if (@(Get-BrainPreflightBlockers $st $he $br $sha $now 0).Count -ne 0) {
  throw "VALID_SYNTHETIC_OBSERVATION_REJECTED"
 }
 $br.source_authenticated=$true
 if (@(Get-BrainPreflightBlockers $st $he $br $sha $now 0) -cnotcontains "BRAIN_UNSAFE_PROMOTION") {
  throw "FORGED_SOURCE_AUTH_ACCEPTED"
 }
 $br.source_authenticated=$false
 $he.ui_sha="b"*40
 if (@(Get-BrainPreflightBlockers $st $he $br $sha $now 0) -cnotcontains "GATEWAY_SHA_UNVERIFIED") {
  throw "WRONG_GATEWAY_BUILD_ACCEPTED"
 }
 $he.ui_sha=$sha
 $br.engine_pid=1235
 if (@(Get-BrainPreflightBlockers $st $he $br $sha $now 0) -cnotcontains "BRAIN_OWNER_OR_STATE_UNVERIFIED") {
  throw "RECYCLED_BRAIN_PID_ACCEPTED"
 }
 $br.engine_pid=1234
 $br.updated_at="2026-01-01T00:00:00+00:00"
 if (@(Get-BrainPreflightBlockers $st $he $br $sha $now 0) -cnotcontains "BRAIN_STALE_OR_FUTURE") {
  throw "STALE_BRAIN_ACCEPTED"
 }
 $br.updated_at=$stamp
 $br.promotion_eligible=$true
 if (@(Get-BrainPreflightBlockers $st $he $br $sha $now 0) -cnotcontains "BRAIN_UNSAFE_PROMOTION") {
  throw "FALSE_PROMOTION_ACCEPTED"
 }
 $br.promotion_eligible=$false
 if (Test-Timestamp "2026-10-17 09:00:00" $now 30) { throw "NAIVE_TIME_ACCEPTED" }
 Write-Output "PASS: V10_BRAIN_READONLY_PREFLIGHT_SYNTHETIC"
 exit 0
}

try {
 if ($ExpectedSha -cnotmatch '^[0-9a-fA-F]{40}$' -or
   [string]::IsNullOrWhiteSpace($ExpectedBranch) -or
   [string]::IsNullOrWhiteSpace($RepoRoot)) { throw "PINNED_SHA_BRANCH_REQUIRED" }
 $repo=[IO.Path]::GetFullPath($RepoRoot)
 if (-not (Test-Path -LiteralPath $repo -PathType Container)) { throw "REPO_NOT_FOUND" }
 $rootInfo=Get-Item -LiteralPath $repo -ErrorAction Stop
 if (($rootInfo.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "REPO_UNTRUSTED" }
 $actualSha=& git -C $repo rev-parse HEAD 2>$null
 if ($LASTEXITCODE -ne 0 -or [string]$actualSha -cne $ExpectedSha) { throw "SHA_MISMATCH" }
 $actualBranch=& git -C $repo rev-parse --abbrev-ref HEAD 2>$null
 if ($LASTEXITCODE -ne 0 -or [string]$actualBranch -cne $ExpectedBranch) { throw "BRANCH_MISMATCH" }
 $trackedChanges=@(& git -C $repo diff --name-only HEAD -- 2>$null)
 if ($LASTEXITCODE -ne 0 -or $trackedChanges.Count -gt 0) { throw "TRACKED_REPO_DIRTY" }
 $stopPath=Join-Path $repo "downloads\STOP_AI_COCKPIT_V10.ps1"
 $enginePath=Join-Path $repo "scripts\ai_brain_observer.py"
 if (-not (Test-Path -LiteralPath $stopPath -PathType Leaf) -or
     -not (Test-Path -LiteralPath $enginePath -PathType Leaf)) { throw "REQUIRED_SOURCE_MISSING" }
 $stopScript=[IO.File]::ReadAllText($stopPath,[Text.Encoding]::UTF8)
 if (-not $stopScript.Contains('"brain_observer_pid" { "ai_brain_observer.py" }') -or
     $stopScript -cnotmatch 'foreach \(\$field in @\([^\r\n]*"brain_observer_pid"') {
  throw "BRAIN_SAFE_STOP_NOT_PROVED"
 }
 $statePath=Join-Path $StateRoot "V10_CONTROLLER_STATE.json"
 if (-not (Test-SafeLocalJson $statePath)) { throw "CONTROLLER_STATE_UNVERIFIED" }
 $state=[IO.File]::ReadAllText($statePath,[Text.Encoding]::UTF8) | ConvertFrom-Json
 if ([string]$state.repo_root -cne $repo) { throw "WRONG_RUNTIME_REPO" }
 $runtime=[string]$state.runtime_dir
 if ([string]::IsNullOrWhiteSpace($runtime) -or
     -not (Test-Path -LiteralPath $runtime -PathType Container)) { throw "RUNTIME_DIR_UNVERIFIED" }
 $runtimeInfo=Get-Item -LiteralPath $runtime -ErrorAction Stop
 if (($runtimeInfo.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "RUNTIME_DIR_UNTRUSTED" }
 $stateAge=([datetime]::UtcNow-(Get-Item -LiteralPath $statePath).LastWriteTimeUtc).TotalSeconds
 if ($stateAge -lt 0 -or $stateAge -gt 30) { throw "CONTROLLER_STATE_STALE" }
 $controllerPid=[int]$state.controller_pid
 if (-not (Test-OwnedWorker $controllerPid "AI_COCKPIT_CONTROLLER_V10.ps1") -and
     -not (Test-OwnedWorker $controllerPid "RUN_AI_COCKPIT_V10.ps1")) {
  throw "CONTROLLER_PROCESS_UNVERIFIED"
 }
 if (-not (Test-OwnedWorker ([int]$state.brain_observer_pid) "ai_brain_observer.py")) {
  throw "BRAIN_PROCESS_UNVERIFIED"
 }
 $brainPath=Join-Path $runtime "ai_brain_observer_status_v1.json"
 if (-not (Test-SafeLocalJson $brainPath)) { throw "BRAIN_STATUS_UNVERIFIED" }
 $brainAge=([datetime]::UtcNow-(Get-Item -LiteralPath $brainPath).LastWriteTimeUtc).TotalSeconds
 $brain=[IO.File]::ReadAllText($brainPath,[Text.Encoding]::UTF8) | ConvertFrom-Json
 $web=Invoke-WebRequest -Uri "http://127.0.0.1:28581/health" -UseBasicParsing -TimeoutSec 3
 if ($web.StatusCode -ne 200) { throw "GATEWAY_HTTP_UNAVAILABLE" }
 $health=$web.Content | ConvertFrom-Json
 $blockers=@(Get-BrainPreflightBlockers $state $health $brain $ExpectedSha ([datetimeoffset]::UtcNow) $brainAge)
 if ($blockers.Count -gt 0) {
  Write-Output "V10_BRAIN_PREFLIGHT=BLOCKED"
  foreach ($b in @($blockers | Sort-Object -Unique)) { Write-Output ("BLOCKER="+$b) }
  Write-Output "REAL_SUBMIT_ALLOWED=0"
  exit 2
 }
} catch {
 # Do not reveal Windows paths or raw market/credential information.
 Write-Output "V10_BRAIN_PREFLIGHT=BLOCKED"
 Write-Output "BLOCKER=SHA_BRANCH_CONTROLLER_OR_RUNTIME_UNVERIFIED"
 Write-Output "REAL_SUBMIT_ALLOWED=0"
 exit 2
}
Write-Output "V10_BRAIN_PREFLIGHT=OBSERVATION_ONLY"
Write-Output ("VERIFIED_SHA="+$ExpectedSha)
Write-Output "EXCHANGE_TICK_DATE_VERIFIED=0"
Write-Output "EXPECTED_RETURN_VALIDATED=0"
Write-Output "SOURCE_AUTHENTICATED=0"
Write-Output "REAL_SUBMIT_ALLOWED=0"
exit 0
