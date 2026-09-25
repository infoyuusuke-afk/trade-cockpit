param(
    [int]$PollSeconds = 3,
    [int]$CooldownSeconds = 90,
    [int]$HotRepeatSeconds = 180,
    [int]$MaxDataAgeSeconds = 30,
    [int]$DebounceSeconds = 6,
    [string]$JsonPath = (Join-Path $PSScriptRoot "live_ms2.json"),
    [string]$SbV2BaseUrl = "http://127.0.0.1:5000",
    [string]$SbV2ModelName = "amitaro",
    [string]$SbV2SpeakerName = "あみたろ",
    [string]$SbV2Style = "Neutral",
    [switch]$Once,
    [switch]$DryRun
)

$ErrorActionPreference = "SilentlyContinue"
$mutex = New-Object System.Threading.Mutex($false, "Local\AI_Cockpit_Live_Emotion_Speaker")
$hasMutex = $false
try { $hasMutex = $mutex.WaitOne(0, $false) } catch { $hasMutex = $false }
if (-not $hasMutex) { exit 0 }

$sapi = $null # V9 bridge only; no Windows SAPI fallback

$lastKey = ""
$lastSpokenAt = [datetime]::MinValue
$lastHotAt = [datetime]::MinValue
$lastScore = 0
$candidateKey = ""
$candidateSince = [datetime]::MinValue

function Limit([double]$value, [double]$low, [double]$high) {
    return [Math]::Max($low, [Math]::Min($high, $value))
}

function Num($value, [double]$fallback = 0) {
    try {
        if ($null -eq $value -or [string]::IsNullOrWhiteSpace([string]$value)) { return $fallback }
        return [double]$value
    } catch { return $fallback }
}

function Bool($value) {
    if ($value -is [bool]) { return $value }
    if ($null -eq $value) { return $false }
    return ([string]$value -match '^(?i:true|1)$')
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
        'GU' = 'ぎゃっぷあっぷ'
        'GD' = 'ぎゃっぷだうん'
        # ユーザー指摘（2026-09-19）: 「歩み値」の「値」がTTSに「ち」と読まれていた
        # （正しくは相場用語として「あゆみね」）。他の漢字表記より先に変換する必要はない
        # （文字列としての重複が無いため順序非依存）。
        '歩み値' = 'あゆみね'
    }
    foreach ($entry in $replacements.GetEnumerator()) {
        $result = $result.Replace([string]$entry.Key, [string]$entry.Value)
    }
    $result = $result.Replace('%', 'パーセント')
    return $result
}

function To-Invariant([double]$value) {
    return $value.ToString([System.Globalization.CultureInfo]::InvariantCulture)
}

function Get-VoiceProfile([string]$level) {
    switch ($level) {
        'HOT'    { return [pscustomobject]@{length=1.03; styleWeight=0.70; split=0.35} }
        'DANGER' { return [pscustomobject]@{length=1.10; styleWeight=0.80; split=0.45} }
        'WATCH'  { return [pscustomobject]@{length=1.13; styleWeight=0.50; split=0.50} }
        default  { return [pscustomobject]@{length=1.20; styleWeight=0.35; split=0.60} }
    }
}

function Test-SbV2Ready {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri ($SbV2BaseUrl.TrimEnd('/') + '/status') -TimeoutSec 2
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}

function Invoke-Voice([string]$text, [string]$level) {
    if ([string]::IsNullOrWhiteSpace($text)) { return $false }
    $normalized = Normalize-SpeechText $text
    if ($DryRun) {
        Write-Host ("[" + $level + "] " + $normalized)
        return $true
    }
    try {
        $encoded=[Uri]::EscapeDataString($normalized)
        $uri="http://127.0.0.1:28583/announce?level="+[Uri]::EscapeDataString($level)+"&text="+$encoded
        $r=Invoke-WebRequest -UseBasicParsing -Uri $uri -TimeoutSec 35
        return ($r.StatusCode -eq 200)
    } catch {
        Write-Host ("[EMOTION VOICE] SBV2 bridge unavailable; no SAPI fallback: "+$_.Exception.Message) -ForegroundColor DarkYellow
        return $false
    }
}

function Get-EmotionState([object]$data, [datetime]$now = (Get-Date)) {
    $dataWarning = [pscustomobject]@{level='DANGER';side='NONE';score=100;key='DANGER:DATA';reasons=@('データ更新不足');text='注意。MS2のデータが不足しています。リアルタイム判定を止めます。新規判断はしないでください。'}
    if ($null -eq $data) { return $dataWarning }
    $valid = [int](Num $data.valid 0)
    $capturedAt = [datetime]::MinValue
    $hasTime = [datetime]::TryParseExact([string]$data.updated_at, 'yyyy-MM-dd HH:mm:ss', [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::None, [ref]$capturedAt)
    $age = ($now - $capturedAt).TotalSeconds
    if (-not $hasTime -or $age -lt -5 -or $age -gt $MaxDataAgeSeconds -or (Bool $data.stale) -or $valid -lt 90) {
        return $dataWarning
    }

    $k = $data.kioxia
    if ($null -eq $k) { return $dataWarning }
    $price = Num $k.price 0
    $vwap = Num $k.vwap 0
    if ($price -le 0) { return $dataWarning }

    $signal = [string]$k.signal
    $strategy = [string]$k.strategy
    $market = [string]$data.market_state
    if ([string]::IsNullOrWhiteSpace($market)) { $market = [string]$k.market_state }
    $breadth = Num $data.breadth_pct (Num $k.breadth_pct 50)
    $ema9 = Num $k.ema9 0
    $ema20 = Num $k.ema20 0
    $volumeBurst = Num $k.volume_burst 0
    $flowBias = Num $k.flow_bias 0
    $orHigh = Num $k.or_high 0
    $orLow = Num $k.or_low 0
    $commonDecision = [string]$k.common_decision
    $whipsaw = Bool $k.whipsaw
    $chaseGuard = Bool $k.chase_guard

    if ($whipsaw -or $chaseGuard -or $signal -match '往復ピンタ|回避|禁止') {
        $reason = if ($whipsaw) {'往復ピンタ警戒'} elseif ($chaseGuard) {'高値安値追い警戒'} else {'安全ゲート警戒'}
        return [pscustomobject]@{
            level='DANGER'; side='NONE'; score=95; key=('DANGER:'+$reason); reasons=@($reason)
            text=('危ない。キオクシア、'+$reason+'です。いったん追わない。VWAPと板、歩み値が、落ち着くまで待ってください。')
        }
    }

    $long = 0.0
    $short = 0.0
    $longReasons = New-Object System.Collections.Generic.List[string]
    $shortReasons = New-Object System.Collections.Generic.List[string]

    if ($market -eq '地合い強い') { $long += 12; $longReasons.Add('地合い強い') }
    if ($market -eq '地合い弱い') { $short += 12; $shortReasons.Add('地合い弱い') }
    if ($breadth -ge 60) { $long += 10; $longReasons.Add('市場のVWAP上比率高め') }
    if ($breadth -le 40) { $short += 10; $shortReasons.Add('市場のVWAP上比率低め') }
    if ($breadth -ge 70) { $long += 5 }
    if ($breadth -le 30) { $short += 5 }

    if ($vwap -gt 0 -and $price -gt $vwap) { $long += 14; $longReasons.Add('VWAP上') }
    if ($vwap -gt 0 -and $price -lt $vwap) { $short += 14; $shortReasons.Add('VWAP下') }
    if ($ema9 -gt 0 -and $ema20 -gt 0 -and $ema9 -gt $ema20) { $long += 8; $longReasons.Add('EMA上向き') }
    if ($ema9 -gt 0 -and $ema20 -gt 0 -and $ema9 -lt $ema20) { $short += 8; $shortReasons.Add('EMA下向き') }
    if ($orHigh -gt 0 -and $price -gt $orHigh) { $long += 12; $longReasons.Add('OR15上抜け') }
    if ($orLow -gt 0 -and $price -lt $orLow) { $short += 12; $shortReasons.Add('OR15下抜け') }

    if ($volumeBurst -ge 1.5) {
        $long += 8; $short += 8
        if ($volumeBurst -ge 2.0) { $long += 4; $short += 4 }
    }
    if ($flowBias -ge 10) { $long += 12; $longReasons.Add('歩み値買い優勢') }
    if ($flowBias -ge 20) { $long += 5 }
    if ($flowBias -le -10) { $short += 12; $shortReasons.Add('歩み値売り優勢') }
    if ($flowBias -le -20) { $short += 5 }

    if ($signal -match '買い|ロング|上抜け|押し目') { $long += 18; $longReasons.Add('買いサイン') }
    if ($signal -match '空売り|ショート|下抜け|戻り') { $short += 18; $shortReasons.Add('売りサイン') }
    if ($strategy -match 'OR15押し目|OR15追随') { $long += 8 }
    if ($strategy -match 'OR15戻り') { $short += 8 }
    if ($commonDecision -match 'LONG|BUY|買い') { $long += 10; $longReasons.Add('共通判定ロング') }
    if ($commonDecision -match 'SHORT|SELL|売り') { $short += 10; $shortReasons.Add('共通判定ショート') }

    $long = Limit $long 0 100
    $short = Limit $short 0 100
    $side = if ($long -ge $short) {'LONG'} else {'SHORT'}
    $score = if ($side -eq 'LONG') {$long} else {$short}
    $opposite = if ($side -eq 'LONG') {$short} else {$long}
    $lead = $score - $opposite
    $reasons = if ($side -eq 'LONG') {@($longReasons)} else {@($shortReasons)}

    $level = 'CALM'
    if ($score -ge 68 -and $lead -ge 15) { $level = 'HOT' }
    elseif ($score -ge 42 -and $lead -ge 8) { $level = 'WATCH' }

    if ($level -eq 'HOT' -and $side -eq 'LONG') {
        $text = '来た。キオクシア、ロング優勢。'
        if ($volumeBurst -ge 1.5) { $text += '出来高、加速。' }
        if ($flowBias -ge 10) { $text += '歩み値も買い優勢。' }
        if ($vwap -gt 0 -and $price -gt $vwap) { $text += 'VWAP上を維持。' }
        $text += 'いけいけムード。ただし、高値追いは禁止。押し目だけ。'
    } elseif ($level -eq 'HOT' -and $side -eq 'SHORT') {
        $text = '来た。キオクシア、ショート優勢。'
        if ($volumeBurst -ge 1.5) { $text += '出来高、加速。' }
        if ($flowBias -le -10) { $text += '歩み値も売り優勢。' }
        if ($vwap -gt 0 -and $price -lt $vwap) { $text += 'VWAP下です。' }
        $text += '下方向の熱量が高い。ただし、追い売りは禁止。戻りを待ってください。'
    } elseif ($level -eq 'WATCH' -and $side -eq 'LONG') {
        $text = 'キオクシア、ロング寄り。'
        if ($vwap -gt 0 -and $price -gt $vwap) { $text += 'VWAP上です。' }
        $text += 'まだ加速確認待ち。飛び乗らないでください。'
    } elseif ($level -eq 'WATCH' -and $side -eq 'SHORT') {
        $text = 'キオクシア、ショート寄り。'
        if ($vwap -gt 0 -and $price -lt $vwap) { $text += 'VWAP下です。' }
        $text += 'まだ加速確認待ち。追い売りはしないでください。'
    } else {
        $text = 'キオクシア、熱量は低めです。今は待ち。無理に入らないでください。'
    }

    return [pscustomobject]@{
        level=$level; side=$side; score=[Math]::Round($score); opposite=[Math]::Round($opposite); lead=[Math]::Round($lead)
        key=($level+':'+$side); reasons=$reasons; text=$text
        volume_burst=$volumeBurst; flow_bias=$flowBias; breadth_pct=$breadth
    }
}

function Should-Speak([object]$state, [datetime]$now) {
    if ($null -eq $state) { return $false }
    if ($lastKey -eq '') {
        # Do not announce an initial CALM state; wait for something actionable to change.
        return ($state.level -ne 'CALM')
    }
    if ($state.key -ne $lastKey -and ($now - $lastSpokenAt).TotalSeconds -ge $CooldownSeconds) { return $true }
    if ($state.level -eq 'HOT' -and ($now - $lastHotAt).TotalSeconds -ge $HotRepeatSeconds -and [Math]::Abs($state.score - $lastScore) -ge 8) { return $true }
    if ($state.level -eq 'DANGER' -and ($now - $lastSpokenAt).TotalSeconds -ge [Math]::Min(45,$CooldownSeconds)) { return $true }
    return $false
}

try {
    while ($true) {
        $now = Get-Date
        if ($now.DayOfWeek -in @([DayOfWeek]::Saturday,[DayOfWeek]::Sunday)) {
            if ($Once) { break }
            Start-Sleep -Seconds 60
            continue
        }
        $clock = $now.TimeOfDay
        if ($clock -lt [TimeSpan]::Parse('09:00:00') -or $clock -gt [TimeSpan]::Parse('15:30:00')) {
            if ($Once) { break }
            Start-Sleep -Seconds 15
            continue
        }

        $data = $null
        if (Test-Path $JsonPath) {
            try { $data = Get-Content -Raw -Encoding UTF8 $JsonPath | ConvertFrom-Json } catch {}
        }
        $state = Get-EmotionState $data $now
        if ($null -ne $state -and $state.key -ne $candidateKey) {
            $candidateKey = [string]$state.key
            $candidateSince = $now
        }
        if ($DryRun -and $null -ne $state) {
            Write-Host ("LEVEL="+$state.level+" SIDE="+$state.side+" SCORE="+$state.score+" LEAD="+$state.lead+" KEY="+$state.key)
            Write-Host ("REASONS="+($state.reasons -join ' / '))
        }

        $stable = ($null -ne $state -and ($state.level -eq 'DANGER' -or ($now - $candidateSince).TotalSeconds -ge $DebounceSeconds))
        if ($stable -and (Should-Speak $state $now)) {
            if (Invoke-Voice ([string]$state.text) ([string]$state.level)) {
                $lastKey = [string]$state.key
                $lastScore = [int]$state.score
                $lastSpokenAt = $now
                if ($state.level -eq 'HOT') { $lastHotAt = $now }
            }
        } elseif ($null -ne $state -and $lastKey -eq '') {
            $lastKey = [string]$state.key
            $lastScore = [int]$state.score
        }

        if ($Once) { break }
        Start-Sleep -Seconds ([Math]::Max(2,$PollSeconds))
    }
}
finally {
    try { if ($hasMutex) { $mutex.ReleaseMutex() } } catch {}
    try { $mutex.Dispose() } catch {}
}
