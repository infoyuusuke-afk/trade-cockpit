param(
    [int]$PollSeconds = 30,
    [double]$RoundTripCostBps = 8.0,
    [int]$MinimumProvisionalSamples = 15,
    [int]$MinimumApprovedSamples = 30
)

$ErrorActionPreference = "SilentlyContinue"
$recordsRoot = Join-Path $PSScriptRoot "records"
$resultCsv = Join-Path $PSScriptRoot "method_trade_results.csv"
$statsJson = Join-Path $PSScriptRoot "method_stats.json"
$rootStatsJson = Join-Path (Split-Path $PSScriptRoot -Parent) "method_stats.json"
$mutex = New-Object System.Threading.Mutex($false, "Local\AI_Cockpit_Method_Profit_Audit")
$hasMutex = $false
try { $hasMutex = $mutex.WaitOne(0, $false) } catch { $hasMutex = $false }
if (-not $hasMutex) { exit 0 }

function Num($value) {
    try {
        $n = [double]$value
        if ([double]::IsNaN($n) -or [double]::IsInfinity($n)) { return $null }
        return $n
    } catch { return $null }
}

function Write-Utf8([string]$path, [string]$text) {
    $tmp = "$path.tmp"
    [IO.File]::WriteAllText($tmp, $text, [Text.UTF8Encoding]::new($false))
    Move-Item -Force $tmp $path
}

function Strategy-Display([string]$strategy) {
    switch -Regex ($strategy) {
        '^OR5初動$' { return 'OR5初動（9:15前は実売買禁止・検証専用）' }
        '^OR15追随$' { return 'OR15順張りブレイク' }
        '^OR15押し目$' { return 'OR15/VWAP押し目買い' }
        '^OR15戻り$' { return 'OR15/VWAP戻り売り' }
        'リバ|反発' { return '急落リバウンド' }
        'レンジ' { return 'レンジ逆張り' }
        default { return $strategy }
    }
}

function Profit-Factor([object[]]$rows) {
    $wins = @($rows | Where-Object { [double]$_.net_r -gt 0 })
    $losses = @($rows | Where-Object { [double]$_.net_r -lt 0 })
    $gp = if ($wins.Count) { [double](($wins | Measure-Object -Property net_r -Sum).Sum) } else { 0.0 }
    $gl = if ($losses.Count) { [Math]::Abs([double](($losses | Measure-Object -Property net_r -Sum).Sum)) } else { 0.0 }
    if ($gl -le 0) { return $(if ($gp -gt 0) { 99.0 } else { 0.0 }) }
    return [Math]::Round($gp / $gl, 2)
}

function Max-DrawdownR([object[]]$rows) {
    $cum = 0.0; $peak = 0.0; $maxDd = 0.0
    foreach ($r in @($rows | Sort-Object entry_time)) {
        $cum += [double]$r.net_r
        if ($cum -gt $peak) { $peak = $cum }
        $dd = $peak - $cum
        if ($dd -gt $maxDd) { $maxDd = $dd }
    }
    return [Math]::Round($maxDd, 2)
}

function Evaluate-Signal($signal, [object[]]$ticks, [bool]$dayComplete) {
    $entry = Num $signal.entry; $stop = Num $signal.stop; $target = Num $signal.target1
    if ($null -eq $entry -or $null -eq $stop -or $null -eq $target) { return $null }
    try { $signalAt = [datetime]::Parse([string]$signal.captured_at) } catch { return $null }
    $side = if ([string]$signal.signal -eq '買いサイン') { 'LONG' } elseif ([string]$signal.signal -eq '空売りサイン') { 'SHORT' } else { return $null }
    $risk = if ($side -eq 'LONG') { $entry - $stop } else { $stop - $entry }
    if ($risk -le 0) { return $null }

    $after = @($ticks | Where-Object { $_.At -ge $signalAt } | Sort-Object At)
    if (-not $after.Count) { return $null }
    $triggerTick = $null
    foreach ($t in $after) {
        if (($side -eq 'LONG' -and $t.Price -ge $entry) -or ($side -eq 'SHORT' -and $t.Price -le $entry)) { $triggerTick = $t; break }
    }
    if ($null -eq $triggerTick) {
        return [pscustomobject]@{
            key=([string]$signal.captured_at+'|'+[string]$signal.ticker+'|'+[string]$signal.strategy+'|'+[string]$signal.signal_bar)
            signal_time=[string]$signal.captured_at; entry_time=''; exit_time=''; ticker=[string]$signal.ticker; name=[string]$signal.name
            side=$side; strategy=[string]$signal.strategy; display_strategy=(Strategy-Display ([string]$signal.strategy)); status='未発動'
            entry=$entry; stop=$stop; target1=$target; exit_price=$null; raw_r=$null; net_r=$null; cost_bps=$RoundTripCostBps
        }
    }

    $exitPrice = $null; $exitAt = $null; $status = '保有中'
    foreach ($t in @($after | Where-Object { $_.At -ge $triggerTick.At })) {
        if ($side -eq 'LONG') {
            if ($t.Price -le $stop) { $exitPrice=$stop; $exitAt=$t.At; $status='STOP'; break }
            if ($t.Price -ge $target) { $exitPrice=$target; $exitAt=$t.At; $status='TARGET1'; break }
        } else {
            if ($t.Price -ge $stop) { $exitPrice=$stop; $exitAt=$t.At; $status='STOP'; break }
            if ($t.Price -le $target) { $exitPrice=$target; $exitAt=$t.At; $status='TARGET1'; break }
        }
    }
    if ($null -eq $exitPrice -and $dayComplete) {
        $last = @($after | Where-Object { $_.At.TimeOfDay -le [TimeSpan]::Parse('15:30:00') } | Sort-Object At | Select-Object -Last 1)
        if ($last.Count) { $exitPrice=[double]$last[0].Price; $exitAt=$last[0].At; $status='大引け決済' }
    }
    if ($null -eq $exitPrice) {
        return [pscustomobject]@{
            key=([string]$signal.captured_at+'|'+[string]$signal.ticker+'|'+[string]$signal.strategy+'|'+[string]$signal.signal_bar)
            signal_time=[string]$signal.captured_at; entry_time=$triggerTick.At.ToString('yyyy-MM-dd HH:mm:ss'); exit_time=''; ticker=[string]$signal.ticker; name=[string]$signal.name
            side=$side; strategy=[string]$signal.strategy; display_strategy=(Strategy-Display ([string]$signal.strategy)); status='保有中'
            entry=$entry; stop=$stop; target1=$target; exit_price=$null; raw_r=$null; net_r=$null; cost_bps=$RoundTripCostBps
        }
    }

    $rawPnl = if ($side -eq 'LONG') { $exitPrice - $entry } else { $entry - $exitPrice }
    $rawR = $rawPnl / $risk
    $costPerShare = $entry * ($RoundTripCostBps / 10000.0)
    $netR = ($rawPnl - $costPerShare) / $risk
    return [pscustomobject]@{
        key=([string]$signal.captured_at+'|'+[string]$signal.ticker+'|'+[string]$signal.strategy+'|'+[string]$signal.signal_bar)
        signal_time=[string]$signal.captured_at; entry_time=$triggerTick.At.ToString('yyyy-MM-dd HH:mm:ss'); exit_time=$exitAt.ToString('yyyy-MM-dd HH:mm:ss')
        ticker=[string]$signal.ticker; name=[string]$signal.name; side=$side; strategy=[string]$signal.strategy
        display_strategy=(Strategy-Display ([string]$signal.strategy)); status=$status; entry=[Math]::Round($entry,2); stop=[Math]::Round($stop,2)
        target1=[Math]::Round($target,2); exit_price=[Math]::Round($exitPrice,2); raw_r=[Math]::Round($rawR,3); net_r=[Math]::Round($netR,3); cost_bps=$RoundTripCostBps
    }
}

function Build-Audit {
    if (-not (Test-Path $recordsRoot)) { return }
    $all = @()
    $today = (Get-Date).ToString('yyyy-MM-dd')
    foreach ($dir in @(Get-ChildItem -Path $recordsRoot -Directory | Sort-Object Name)) {
        $signalsPath = Join-Path $dir.FullName 'trade_signals.csv'
        $ticksPath = Join-Path $dir.FullName 'ticks.csv'
        if (-not (Test-Path $signalsPath) -or -not (Test-Path $ticksPath)) { continue }
        try { $signals = @(Import-Csv -Encoding UTF8 $signalsPath) } catch { continue }
        try { $tickRows = @(Import-Csv -Encoding UTF8 $ticksPath) } catch { continue }
        if (-not $signals.Count -or -not $tickRows.Count) { continue }
        $ticksByTicker = @{}
        foreach ($r in $tickRows) {
            $price = Num $r.price
            if ($null -eq $price) { continue }
            try { $at = [datetime]::Parse([string]$r.captured_at) } catch { continue }
            $tk = [string]$r.ticker
            if (-not $ticksByTicker.ContainsKey($tk)) { $ticksByTicker[$tk] = [Collections.ArrayList]::new() }
            [void]$ticksByTicker[$tk].Add([pscustomobject]@{At=$at;Price=$price})
        }
        $complete = ($dir.Name -lt $today) -or (($dir.Name -eq $today) -and ((Get-Date).TimeOfDay -ge [TimeSpan]::Parse('15:30:00')))
        foreach ($s in $signals) {
            $tk = [string]$s.ticker
            if (-not $ticksByTicker.ContainsKey($tk)) { continue }
            $result = Evaluate-Signal $s @($ticksByTicker[$tk]) $complete
            if ($null -ne $result) { $all += $result }
        }
    }

    $dedup = @{}
    foreach ($r in $all) { $dedup[[string]$r.key] = $r }
    $all = @($dedup.Values | Sort-Object signal_time)
    if ($all.Count) {
        $csv = ($all | Select-Object signal_time,entry_time,exit_time,ticker,name,side,strategy,display_strategy,status,entry,stop,target1,exit_price,raw_r,net_r,cost_bps | ConvertTo-Csv -NoTypeInformation) -join [Environment]::NewLine
        Write-Utf8 $resultCsv ($csv + [Environment]::NewLine)
    }

    $completed = @($all | Where-Object { $_.status -in @('STOP','TARGET1','大引け決済') -and $null -ne $_.net_r })
    $expected = @('OR5初動','OR15追随','OR15押し目','OR15戻り','急落リバウンド','レンジ逆張り')
    $observed = @($completed | Select-Object -ExpandProperty strategy -Unique)
    $methods = @()
    foreach ($strategy in @($expected + $observed | Select-Object -Unique)) {
        $rows = @($completed | Where-Object { [string]$_.strategy -eq $strategy } | Sort-Object entry_time)
        $n = $rows.Count
        $wins = @($rows | Where-Object { [double]$_.net_r -gt 0 }).Count
        $avg = if ($n) { [Math]::Round([double](($rows | Measure-Object -Property net_r -Average).Average),3) } else { $null }
        $pf = if ($n) { Profit-Factor $rows } else { $null }
        $recent = @($rows | Select-Object -Last 20)
        $recentPf = if ($recent.Count) { Profit-Factor $recent } else { $null }
        $status = '検証不足'
        if ($strategy -eq 'OR5初動') { $status = '9:15前・実売買禁止' }
        elseif ($n -ge $MinimumApprovedSamples -and $pf -ge 1.30 -and $recentPf -ge 1.15 -and $avg -gt 0) { $status = '採用' }
        elseif ($n -ge $MinimumApprovedSamples -and $pf -ge 1.10 -and $avg -gt 0) { $status = '条件付き' }
        elseif ($n -ge $MinimumApprovedSamples) { $status = '停止' }
        elseif ($n -ge $MinimumProvisionalSamples -and $pf -ge 1.30 -and $avg -gt 0) { $status = '仮採用' }
        elseif ($n -ge $MinimumProvisionalSamples) { $status = '検証中' }
        $methods += [pscustomobject]@{
            strategy=$strategy; display=(Strategy-Display $strategy); samples=$n
            wins=$wins; losses=($n-$wins); win_rate=if($n){[Math]::Round($wins/$n*100,1)}else{$null}
            profit_factor=$pf; recent20_profit_factor=$recentPf; avg_r=$avg
            max_drawdown_r=if($n){Max-DrawdownR $rows}else{$null}; status=$status
        }
    }
    $payload = [ordered]@{
        updated_at=(Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
        source='MS2 RSS trade_signals.csv + ticks.csv'
        round_trip_cost_bps=$RoundTripCostBps
        minimum_provisional_samples=$MinimumProvisionalSamples
        minimum_approved_samples=$MinimumApprovedSamples
        rule='PFだけで採用しない。30件以上、PF>=1.30、直近20件PF>=1.15、平均R>0を正式採用条件とする。9:15前のOR5は検証のみで実売買禁止。'
        completed_trades=$completed.Count
        methods=$methods
        po3=[ordered]@{status='外部統計待ち';note='TradingView Po3は外部インジのためMS2ログから同一ロジックを再現せず、表示されたCycles/Target/Stop/Avg Rを別検証する。'}
    }
    $json = $payload | ConvertTo-Json -Depth 8
    Write-Utf8 $statsJson $json
    try { Write-Utf8 $rootStatsJson $json } catch {}
}

try {
    while ($true) {
        Build-Audit
        if ((Get-Date).TimeOfDay -gt [TimeSpan]::Parse('15:40:00')) { break }
        Start-Sleep -Seconds ([Math]::Max(15, $PollSeconds))
    }
}
finally {
    try { if ($hasMutex) { $mutex.ReleaseMutex() } } catch {}
    try { $mutex.Dispose() } catch {}
}
