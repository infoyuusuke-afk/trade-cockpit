# Issue #382: strict OLD vs NEW PowerShell 5.1 canonical-record parity.
# All inputs are synthetic. No MS2/Excel startup or OWNER private records.
param(
    [string]$BaselineCommit = '9861b9ed0acb375bbe137c5b485a670c3d1feffe',
    [string]$CurrentPath = 'scripts/ms2_ps_python_bridge_producer.ps1'
)
$ErrorActionPreference='Stop'
if($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1){ throw 'PS51_REQUIRED' }
if($BaselineCommit -notmatch '^[0-9a-f]{40}$'){throw 'BASELINE_SHA_INVALID'}
$spec=$BaselineCommit+':scripts/ms2_ps_python_bridge_producer.ps1'
$originalLines=@(& git show $spec)
if($LASTEXITCODE -ne 0 -or $originalLines.Count -lt 100){throw 'BASELINE_UNAVAILABLE'}
$oldText=$originalLines -join [Environment]::NewLine
$newText=[System.IO.File]::ReadAllText((Resolve-Path $CurrentPath))
if($oldText -notmatch [regex]::Escape('$parsed += $row')){throw 'BASELINE_DRIFT'}
if($newText -notmatch [regex]::Escape('[void]$parsed.Add($row)')){throw 'OPTIMIZATION_NOT_APPLIED'}
# Only these three transformations are permitted between pinned baseline and
# candidate; checks below independently compare all resulting bytes/reasons.
Invoke-Expression $oldText

function New-SyntheticCapture([int]$Depth) {
    $ts='2026-10-14T09:00:00.012+09:00'
    $rows=@()
    for($i=1;$i -le $Depth;$i++){
        $rows+=@{
            Level=[int]$i
            AskPrice=[double](101+$i)
            BidPrice=[double](100+$i)
            AskQty=[int]($i*100)
            BidQty=[int]0
            read_at=$ts
        }
    }
    return @{
        symbol='285A.T';market='TSE';source='synthetic-382'
        poll_seq=[int]3
        observation_id='synthetic-382-3'
        watcher_observed_at=$ts;read_started_at=$ts;read_finished_at=$ts
        event_time=$ts;received_at=$ts
        snapshot_atomic=$false;sequence_basis='POLL'
        data_freshness='OK';levels=$rows
        gap=@{suspected_gap=$false;prev_poll_nonempty=$true;window_size=4;overlap_with_prev=2;new_appended=2}
    }
}
$cases=New-Object 'System.Collections.Generic.List[object]'
function Add-Case([string]$Name,[hashtable]$Capture) {
    [void]$script:cases.Add(@{name=$Name;capture=$Capture})
}
Add-Case 'one_level' (New-SyntheticCapture 1)
Add-Case 'ten_levels' (New-SyntheticCapture 10)
Add-Case 'no_levels' (New-SyntheticCapture 0)
Add-Case 'five_levels' (New-SyntheticCapture 5)
$x=New-SyntheticCapture 1;$x.levels[0].BidQty=$null
Add-Case 'unknown_bid_qty' $x
$x=New-SyntheticCapture 1;$x.levels[0].AskPrice=$null;$x.levels[0].BidPrice=$null
Add-Case 'missing_price_not_zero' $x
$x=New-SyntheticCapture 1;$x.levels[0].AskQty=[int]0;$x.levels[0].BidQty=[int]0
Add-Case 'known_true_zero_quantity' $x
$x=New-SyntheticCapture 1;$x.symbol='試験銘柄'
Add-Case 'utf8_symbol' $x
$x=New-SyntheticCapture 1;$x.data_freshness='UNKNOWN'
Add-Case 'unknown_freshness' $x
$x=New-SyntheticCapture 1;$x.source='Kioxia_RSS_Live_Watcher.ps1'
Add-Case 'watcher_source_refusal' $x
$x=New-SyntheticCapture 1;$x.poll_seq=0
Add-Case 'bad_poll' $x
$x=New-SyntheticCapture 2;$x.levels[1].Level=3
Add-Case 'level_gap' $x
$x=New-SyntheticCapture 1;$x.levels[0].AskQty=[int]-1
Add-Case 'negative_quantity' $x
$x=New-SyntheticCapture 1;$x.levels[0].AskPrice=[double]0
Add-Case 'nonpositive_ask' $x
$x=New-SyntheticCapture 1;$x.levels[0].BidPrice=[double]::NaN
Add-Case 'nan_bid' $x
$x=New-SyntheticCapture 1;$x.levels[0].AskQty='200'
Add-Case 'string_quantity' $x
$x=New-SyntheticCapture 1;$x.read_finished_at='2026-10-14T00:00:00.000Z'
Add-Case 'timezone_guess_refusal' $x
$x=New-SyntheticCapture 1;$x.levels[0].read_at='badclock'
Add-Case 'bad_level_clock' $x
$x=New-SyntheticCapture 11
Add-Case 'depth_limit' $x
$x=New-SyntheticCapture 1;$x.market='UNKNOWN'
Add-Case 'market_refusal' $x
$x=New-SyntheticCapture 1;$x.gap=$null
Add-Case 'no_gap' $x
$x=New-SyntheticCapture 1;$x.levels[0].BidPrice=[double]1.5;$x.levels[0].AskPrice=[double]1.75
Add-Case 'fractional_price' $x

function Capture-Output($Case) {
    $result=ConvertTo-Ms2PsBridgeRecord $Case.capture
    if($null -eq $result -or $result.Ok -notin @($true,$false)){throw 'PACK_RESULT_INVALID'}
    if($result.Ok){
        if($null -eq $result.Record -or $result.Record.Length -ne 2048){throw 'PACK_SIZE_DRIFT'}
        return @{Ok=$true;Reason=$result.Reason;Data=[Convert]::ToBase64String($result.Record)}
    }
    if($null -ne $result.Record){throw 'REFUSED_WITH_PAYLOAD'}
    return @{Ok=$false;Reason=$result.Reason;Data=$null}
}
$before=@()
foreach($case in $cases){$before+=Capture-Output $case}

# Timings are DIAGNOSTIC ONLY, never CI performance acceptance.
$stress=New-SyntheticCapture 10
for($i=0;$i -lt 3;$i++){[void](ConvertTo-Ms2PsBridgeRecord $stress)}
$clock=[Diagnostics.Stopwatch]::StartNew()
for($i=0;$i -lt 35;$i++){[void](ConvertTo-Ms2PsBridgeRecord $stress)}
$clock.Stop();$oldMillis=[Math]::Round($clock.Elapsed.TotalMilliseconds,4)

# Script contains pure definitions and .NET type-reflection initialization only.
# No Collector, broker, RSS, or real process is invoked.
Invoke-Expression $newText
$checked=0;$valid=0;$refusals=0
for($i=0;$i -lt $cases.Count;$i++){
    $got=Capture-Output $cases[$i]
    $expected=$before[$i]
    if($got.Ok -cne $expected.Ok -or $got.Reason -cne $expected.Reason -or $got.Data -cne $expected.Data){
        # Do not print synthetic payloads. A difference is fatal.
        throw ('CANONICAL_OR_REFUSAL_DRIFT_CASE_'+$i)
    }
    if($got.Ok){$valid++}else{$refusals++}
    $checked++
}
for($i=0;$i -lt 3;$i++){[void](ConvertTo-Ms2PsBridgeRecord $stress)}
$clock=[Diagnostics.Stopwatch]::StartNew()
for($i=0;$i -lt 35;$i++){[void](ConvertTo-Ms2PsBridgeRecord $stress)}
$clock.Stop();$newMillis=[Math]::Round($clock.Elapsed.TotalMilliseconds,4)

# CI success means canonical compatibility for those fixtures ONLY.
[pscustomobject]@{
  status='STRICT_PINNED_BASELINE_PARITY_PASS'
  baseline=$BaselineCommit
  cases=$checked
  valid=$valid
  refused=$refusals
  bytes_per_valid_record=2048
  baseline_35x_10level_ms=$oldMillis
  candidate_35x_10level_ms=$newMillis
  performance_proven=$false
  real_market_input_used=$false
  original_contract_changed=$false
  real_submit_allowed=$false
  release_eligible=$false
}|ConvertTo-Json -Compress
