param(
    [int]$PollSeconds = 5,
    [int]$ModeChangeCooldownMinutes = 10
)

$ErrorActionPreference = "SilentlyContinue"
$jsonPath = Join-Path $PSScriptRoot "live_ms2.json"
$methodStatsPath = Join-Path $PSScriptRoot "method_stats.json"
$mutex = New-Object System.Threading.Mutex($false, "Local\AI_Cockpit_Today_Strategy_Speaker")
$hasMutex = $false
try { $hasMutex = $mutex.WaitOne(0, $false) } catch { $hasMutex = $false }
if (-not $hasMutex) { exit 0 }

$speaker = New-Object -ComObject SAPI.SpVoice
$speaker.Rate = 0
$speaker.Volume = 100
$activeDay = (Get-Date).ToString("yyyy-MM-dd")
$preopenSpoken = $false
$openingRuleSpoken = $false
$lastMode = ""
$lastModeSpokenAt = [datetime]::MinValue

function Speak-Text([string]$text) {
    if ([string]::IsNullOrWhiteSpace($text)) { return }
    try { $speaker.Speak($text, 1) | Out-Null } catch {}
}

function Get-Mode([object]$data) {
    if ($null -eq $data) { return "NO TRADE" }
    $valid = 0
    try { $valid = [int]$data.valid } catch {}
    if ([bool]$data.stale -or $valid -lt 90) { return "NO TRADE" }
    $state = [string]$data.market_state
    $breadth = $null
    try { if ($null -ne $data.breadth_pct) { $breadth = [double]$data.breadth_pct } } catch {}
    $rows = @($data.top5)
    $buy = @($rows | Where-Object { [string]$_.signal -eq "買いサイン" }).Count
    $sell = @($rows | Where-Object { [string]$_.signal -eq "空売りサイン" }).Count
    $longReady = @($rows | Where-Object { ([string]$_.strategy -match "OR15押し目|OR15追随") -and ([string]$_.signal -match "買い|上抜け|押し目") }).Count
    $shortReady = @($rows | Where-Object { ([string]$_.strategy -match "OR15戻り|OR15追随") -and ([string]$_.signal -match "空売り|下抜け|戻り") }).Count
    $rebound = @($rows | Where-Object { ([string]$_.strategy -match "リバ|反発") -or ([string]$_.signal -match "リバ|反発") }).Count
    if ($rebound -ge 2 -and $buy -gt $sell) { return "REBOUND" }
    if (($state -eq "地合い強い" -or ($null -ne $breadth -and $breadth -ge 60)) -and (($buy + $longReady) -ge 2) -and $buy -ge $sell) { return "TREND LONG" }
    if (($state -eq "地合い弱い" -or ($null -ne $breadth -and $breadth -le 40)) -and (($sell + $shortReady) -ge 2) -and $sell -ge $buy) { return "TREND SHORT" }
    if ($state -eq "地合い中立" -and [Math]::Abs($buy - $sell) -le 1) { return "RANGE" }
    return "NO TRADE"
}

function Get-MethodGate([string]$mode) {
    $required = switch ($mode) {
        'TREND LONG' { @('OR15押し目','OR15追随') }
        'TREND SHORT' { @('OR15戻り','OR15追随') }
        'REBOUND' { @('急落リバウンド') }
        'RANGE' { @('レンジ逆張り') }
        default { @() }
    }
    if (-not $required.Count) { return [pscustomobject]@{approved=$false;text='ノートレード'} }
    if (-not (Test-Path $methodStatsPath)) { return [pscustomobject]@{approved=$false;text='手法成績の検証データがまだありません'} }
    try { $stats = Get-Content -Raw -Encoding UTF8 $methodStatsPath | ConvertFrom-Json } catch { return [pscustomobject]@{approved=$false;text='手法成績を読み込めません'} }
    $rows = @($stats.methods | Where-Object { $_.strategy -in $required })
    if (-not $rows.Count) { return [pscustomobject]@{approved=$false;text='対象手法はまだ検証不足です'} }
    $good = @($rows | Where-Object { [string]$_.status -in @('採用','仮採用','条件付き') })
    if (-not $good.Count) {
        $detail = ($rows | ForEach-Object { ([string]$_.display)+'、'+([string]$_.samples)+'件、PF '+([string]$_.profit_factor)+'、判定 '+([string]$_.status) }) -join '。'
        return [pscustomobject]@{approved=$false;text=('手法成績ゲート不合格。'+$detail)}
    }
    $best = $good | Sort-Object @{Expression={try{[double]$_.profit_factor}catch{0}};Descending=$true} | Select-Object -First 1
    return [pscustomobject]@{approved=$true;text=(( [string]$best.display )+'、'+([string]$best.samples)+'件、PF '+([string]$best.profit_factor)+'、平均R '+([string]$best.avg_r)+'、判定 '+([string]$best.status))}
}

function Get-ModeVoice([string]$mode, [object]$data) {
    $state = [string]$data.market_state
    $breadthText = ""
    try { if ($null -ne $data.breadth_pct) { $breadthText = "。VWAP上の銘柄比率は" + [Math]::Round([double]$data.breadth_pct) + "パーセント" } } catch {}
    $head = "AIコクピット。本日の相場モードは、" + $mode + "。" + $state + $breadthText + "。"
    if ($mode -eq 'NO TRADE') { return $head + "本日の戦略はノートレード。方向が決まるまで入るな。サインだけで飛び乗るな。勝つより先に、崩れない。" }
    $gate = Get-MethodGate $mode
    if (-not $gate.approved) { return $head + $gate.text + "。この手法は実弾許可しません。検証継続。迷ったらノートレード。" }
    $audit = "手法成績確認。" + $gate.text + "。"
    switch ($mode) {
        "TREND LONG" { return $head + $audit + "今日の手法は順張りの押し目買い。OR15上抜け、VWAP上、EMA9と20上向き、出来高増加、板と歩み値の買い優勢がそろうまで待つ。高値追い禁止。初押しだけ。" }
        "TREND SHORT" { return $head + $audit + "今日の手法は順張りの戻り売り。OR15下抜け、VWAP下、EMA9と20下向き、出来高増加、板と歩み値の売り優勢がそろうまで待つ。追い売り禁止。初戻りだけ。" }
        "REBOUND" { return $head + $audit + "今日の手法は急落リバウンド。ただし下げ途中では買わない。下げ止まり、VWAP回復またはOR15高値回復、歩み値改善を確認してから入る。利確は早め。" }
        "RANGE" { return $head + $audit + "今日の手法はレンジ逆張り。上下端だけ。真ん中では入らない。上端は売り、下端は買い。利確は早め。" }
    }
}

try {
    while ($true) {
        $now = Get-Date
        $day = $now.ToString("yyyy-MM-dd")
        if ($day -ne $activeDay) { $activeDay=$day; $preopenSpoken=$false; $openingRuleSpoken=$false; $lastMode=""; $lastModeSpokenAt=[datetime]::MinValue }
        if ($now.DayOfWeek -in @([DayOfWeek]::Saturday,[DayOfWeek]::Sunday)) { Start-Sleep -Seconds 60; continue }
        $clock = $now.TimeOfDay
        if ($clock -gt [TimeSpan]::Parse("15:35:00")) { break }
        if (-not $preopenSpoken -and $clock -ge [TimeSpan]::Parse("08:55:00") -and $clock -lt [TimeSpan]::Parse("09:00:00")) {
            Speak-Text "AIコクピット。まもなく寄り付きです。9時15分までは原則ノートレード。寄り直後は見学。焦って飛び乗らない。モードが決まるまで入るな。"
            $preopenSpoken=$true
        }
        if (-not $openingRuleSpoken -and $clock -ge [TimeSpan]::Parse("09:00:00") -and $clock -lt [TimeSpan]::Parse("09:15:00")) {
            Speak-Text "寄り付きました。9時15分までは入らない。OR15を作る時間です。板、歩み値、出来高、VWAP、指数方向を観察してください。"
            $openingRuleSpoken=$true
        }
        if ($clock -ge [TimeSpan]::Parse("09:15:00") -and $clock -le [TimeSpan]::Parse("15:30:00") -and (Test-Path $jsonPath)) {
            $data=$null; try { $data=Get-Content -Raw -Encoding UTF8 $jsonPath | ConvertFrom-Json } catch {}
            if ($null -ne $data) {
                $mode=Get-Mode $data; $shouldSpeak=$false
                if ([string]::IsNullOrWhiteSpace($lastMode)) { $shouldSpeak=$true }
                elseif ($mode -ne $lastMode -and ($now-$lastModeSpokenAt).TotalMinutes -ge $ModeChangeCooldownMinutes) { $shouldSpeak=$true }
                if ($shouldSpeak) { Speak-Text (Get-ModeVoice $mode $data); $lastMode=$mode; $lastModeSpokenAt=$now }
            }
        }
        Start-Sleep -Seconds ([Math]::Max(2,$PollSeconds))
    }
}
finally {
    try { if ($hasMutex) { $mutex.ReleaseMutex() } } catch {}
    try { $mutex.Dispose() } catch {}
}
