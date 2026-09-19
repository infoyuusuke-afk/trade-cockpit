param(
    [string]$BaseUrl = "http://127.0.0.1:5000",
    [string]$ModelName = "amitaro",
    [string]$SpeakerName = "あみたろ",
    [string]$Style = "Neutral",
    [double]$StyleWeight = 0.4,
    [double]$Length = 1.2,
    [double]$SplitInterval = 0.7
)

$ErrorActionPreference = 'Stop'

function To-Invariant([double]$value) {
    return $value.ToString([System.Globalization.CultureInfo]::InvariantCulture)
}

function Normalize-SpeechText([string]$text) {
    $result = $text
    $replacements = [ordered]@{
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
    }
    foreach ($entry in $replacements.GetEnumerator()) {
        $result = $result.Replace([string]$entry.Key, [string]$entry.Value)
    }
    return $result
}

$text = @"
9時55分です。
10時前の転換警戒に入ります。
キオクシアは、VWAP上です。
出来高は増加しています。
新規ロングは慎重に。
"@
$text = Normalize-SpeechText $text

$status = Invoke-WebRequest -UseBasicParsing -Uri ($BaseUrl.TrimEnd('/') + '/status') -TimeoutSec 3
if ($status.StatusCode -ne 200) { throw "SBV2 /status failed: $($status.StatusCode)" }

$query = [ordered]@{
    text = $text
    model_name = $ModelName
    speaker_name = $SpeakerName
    language = 'JP'
    length = (To-Invariant $Length)
    auto_split = 'true'
    split_interval = (To-Invariant $SplitInterval)
    style = $Style
    style_weight = (To-Invariant $StyleWeight)
}
$pairs = @()
foreach ($entry in $query.GetEnumerator()) {
    $pairs += ([System.Uri]::EscapeDataString([string]$entry.Key) + '=' + [System.Uri]::EscapeDataString([string]$entry.Value))
}
$uri = $BaseUrl.TrimEnd('/') + '/voice?' + ($pairs -join '&')
$wav = Join-Path $env:TEMP 'ai_cockpit_sbv2_test.wav'
Invoke-WebRequest -UseBasicParsing -Uri $uri -OutFile $wav -TimeoutSec 30

$player = New-Object System.Media.SoundPlayer $wav
$player.Load()
$player.PlaySync()
$player.Dispose()

Write-Host "SBV2 voice test: OK" -ForegroundColor Green
Write-Host "WAV: $wav"
