param(
    [int]$PollSeconds = 5,
    [int]$ModeChangeCooldownMinutes = 10,
    [string]$SbV2BaseUrl = "http://127.0.0.1:5000",
    [string]$SbV2ModelName = "amitaro",
    [string]$SbV2SpeakerName = "あみたろ",
    [string]$SbV2Style = "Neutral",
    [double]$SbV2StyleWeight = 0.4,
    [double]$SbV2Length = 1.2,
    [double]$SbV2SplitInterval = 0.7
)

$ErrorActionPreference = "SilentlyContinue"
$jsonPath = Join-Path $PSScriptRoot "live_ms2.json"
$methodStatsPath = Join-Path $PSScriptRoot "method_stats.json"
$mutex = New-Object System.Threading.Mutex($false, "Local\AI_Cockpit_Today_Strategy_Speaker")
$hasMutex = $false
try { $hasMutex = $mutex.WaitOne(0, $false) } catch { $hasMutex = $false }
if (-not $hasMutex) { exit 0 }

# Windows SAPI is retained only as a fallback when SBV2 is unavailable.
$speaker = New-Object -ComObject SAPI.SpVoice
$speaker.Rate = -2
$speaker.Volume = 100

$activeDay = (Get-Date).ToString("yyyy-MM-dd")
$preopenSpoken = $false
$openingRuleSpoken = $false
$lastMode = ""
$lastModeSpokenAt = [datetime]::MinValue
$spokenClock = @{}

# Market-clock announcements are time-based only. They must not claim live market facts
# (VWAP/volume/board state) unless those facts come from live data.
$marketClockAnnouncements = @(
    [pscustomobject]@{ Key='0915'; Time='09:15:00'; Text="9時15分です。OR15が確定しました。VWAP、出来高、板、歩み値を確認してください。" },
    [pscustomobject]@{ Key='0930'; Time='09:30:00'; Text="9時30分です。相場の転換に注意してください。高値追い、安値追いは慎重に。" },
    [pscustomobject]@{ Key='0955'; Time='09:55:00'; Text="9時55分です。10時前の転換警戒に入ります。新規ロング、新規ショートともに慎重に。" },
    [pscustomobject]@{ Key='1000'; Time='10:00:00'; Text="10時です。転換警戒です。VWAP、出来高、指数方向をもう一度確認してください。" },
    [pscustomobject]@{ Key='1025'; Time='10:25:00'; Text="10時25分です。流れが切り替わりやすい時間です。ポジションと出来高の変化を確認してください。" },
    [pscustomobject]@{ Key='1100'; Time='11:00:00'; Text="11時です。前場終盤です。無理な新規エントリーは避け、前場の流れを確認してください。" },
    [pscustomobject]@{ Key='1300'; Time='13:00:00'; Text="13時です。後場の方向を確認してください。前場の流れをそのまま決めつけないでください。" },
    [pscustomobject]@{ Key='1400'; Time='14:00:00'; Text="14時です。後場後半です。出来高と指数方向、VWAPからの位置を確認してください。" },
    [pscustomobject]@{ Key='1430'; Time='14:30:00'; Text="14時30分です。引け需給に注意する時間です。持ち越し判断は慎重に。" },
    [pscustomobject]@{ Key='1500'; Time='15:00:00'; Text="15時です。大引けまで30分です。引け需給とポジション管理を優先してください。" }
)

function Convert-ToInvariant([double]$value) {
    return $value.ToString([System.Globalization.CultureInfo]::InvariantCulture)
}

function Normalize-SpeechText([string]$text) {
    if ([string]::IsNullOrWhiteSpace($text)) { return $text }

    $result = $text
    $replacements = [ordered]@{
        'AIコクピット' = 'えーあいコクピット'
        'キオクシア' = 'きおくしあ'
        'VWAP上' = 'ぶいわっぷ、うえ'
        'VWAP下' = 'ぶいわっぷ、した'
        'VWAP' = 'ぶいわっぷ'
        'OR15' = 'おーあーる、じゅうご'
        'OR5' = 'おーあーる、ご'
        'EMA20' = 'いーえむえー、にじゅう'
        'EMA9' = 'いーえむえー、きゅう'
        'EMA' = 'いーえむえー'
        'TOP5' = 'トップ、ご'
        'GU' = 'ぎゃっぷあっぷ'
        'GD' = 'ぎゃっぷだうん'
        'PF' = 'ぴーえふ'
    }
    foreach ($entry in $replacements.GetEnumerator()) {
        $result = $result.Replace([string]$entry.Key, [string]$entry.Value)
    }
    $result = $result.Replace('%', 'パーセント')
    return $result
}

function Test-SbV2Ready {
    try {
        $status = Invoke-WebRequest -UseBasicParsing -Uri ($SbV2BaseUrl.TrimEnd('/') + '/status') -Method Get -TimeoutSec 2
        return ($status.StatusCode -eq 200)
    } catch {
        return $false
    }
}

function Invoke-SbV2Speech([string]$text) {
    if ([string]::IsNullOrWhiteSpace($text)) { return $false }
    if (-not (Test-SbV2Ready)) { return $false }

    $normalized = Normalize-SpeechText $text
    $query = [ordered]@{
        text = $normalized
        model_name = $SbV2ModelName
        speaker_name = $SbV2SpeakerName
        language = 'JP'
        length = (Convert-ToInvariant $SbV2Length)
        auto_split = 'true'
        split_interval = (Convert-ToInvariant $SbV2SplitInterval)
        style = $SbV2Style
        style_weight = (Convert-ToInvariant $SbV2StyleWeight)
    }

    $pairs = @()
    foreach ($entry in $query.GetEnumerator()) {
        $pairs += ([System.Uri]::EscapeDataString([string]$entry.Key) + '=' + [System.Uri]::EscapeDataString([string]$entry.Value))
    }
    $uri = $SbV2BaseUrl.TrimEnd('/') + '/voice?' + ($pairs -join '&')
    $wavPath = Join-Path $env:TEMP ("ai_cockpit_voice_" + [guid]::NewGuid().ToString('N') + '.wav')

    try {
        Invoke-WebRequest -UseBasicParsing -Uri $uri -Method Get -OutFile $wavPath -TimeoutSec 30 | Out-Null
        if (-not (Test-Path $wavPath)) { return $false }
        $player = New-Object System.Media.SoundPlayer $wavPath
        $player.Load()
        $player.PlaySync()
        $player.Dispose()
        return $true
    } catch {
        return $false
    } finally {
        if (Test-Path $wavPath) { Remove-Item -Force $wavPath -ErrorAction SilentlyContinue }
    }
}

# Shared voice mutex serializes all cockpit voice processes.
function Speak-Text([string]$text) {
    if ([string]::IsNullOrWhiteSpace($text)) { return }
    $voiceMutex = $null
    $voiceAcquired = $false
    try {
        $voiceMutex = New-Object System.Threading.Mutex($false, "Global\KioxiaVoiceMutex")
        $voiceAcquired = $voiceMutex.WaitOne(20000)

        $spoken = Invoke-SbV2Speech $text
        if (-not $spoken) {
            # Fail-safe: keep an audible warning even if SBV2 is down.
            $speaker.Speak((Normalize-SpeechText $text), 0) | Out-Null
        }
    } catch {
    } finally {
        if ($voiceAcquired -and $null -ne $voiceMutex) { try { $voiceMutex.ReleaseMutex() } catch {} }
        if ($null -ne $voiceMutex) { $voiceMutex.Dispose() }
    }
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

function Get-ModeLabel([string]$mode) {
    switch ($mode) {
        'TREND LONG' { return 'トレンドロング' }
        'TREND SHORT' { return 'トレンドショート' }
        'REBOUND' { return 'リバウンド' }
        'RANGE' { return 'レンジ' }
        default { return 'ノートレード' }
    }
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
    $head = "AIコクピット。本日の相場モードは、" + (Get-ModeLabel $mode) + "。" + $state + $breadthText + "。"
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

function Invoke-MarketClockAnnouncements([datetime]$now) {
    $clock = $now.TimeOfDay
    foreach ($item in $marketClockAnnouncements) {
        if ($spokenClock.ContainsKey($item.Key)) { continue }
        $at = [TimeSpan]::Parse([string]$item.Time)
        $until = $at.Add([TimeSpan]::FromMinutes(1.5))
        if ($clock -ge $at -and $clock -lt $until) {
            Speak-Text ([string]$item.Text)
            $spokenClock[$item.Key] = $true
        }
    }
}

try {
    while ($true) {
        $now = Get-Date
        $day = $now.ToString("yyyy-MM-dd")
        if ($day -ne $activeDay) {
            $activeDay=$day
            $preopenSpoken=$false
            $openingRuleSpoken=$false
            $lastMode=""
            $lastModeSpokenAt=[datetime]::MinValue
            $spokenClock.Clear()
        }
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

        Invoke-MarketClockAnnouncements $now

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
