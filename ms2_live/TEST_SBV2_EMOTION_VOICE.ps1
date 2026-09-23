param(
    [ValidateSet('ALL','CALM','WATCH','HOT','DANGER')]
    [string]$Level = 'ALL',
    [string]$BaseUrl = 'http://127.0.0.1:5000',
    [string]$ModelName = 'amitaro',
    [string]$SpeakerName = 'あみたろ',
    [string]$Style = 'Neutral'
)

$ErrorActionPreference = 'Stop'

function To-Invariant([double]$value) {
    return $value.ToString([System.Globalization.CultureInfo]::InvariantCulture)
}

function Speak-Sample([string]$name, [string]$text, [double]$length, [double]$styleWeight, [double]$split) {
    Write-Host ("--- " + $name + " ---") -ForegroundColor Cyan
    Write-Host $text
    $q = [ordered]@{
        text = $text
        model_name = $ModelName
        speaker_name = $SpeakerName
        language = 'JP'
        length = (To-Invariant $length)
        auto_split = 'true'
        split_interval = (To-Invariant $split)
        style = $Style
        style_weight = (To-Invariant $styleWeight)
    }
    $pairs = @()
    foreach ($entry in $q.GetEnumerator()) {
        $pairs += ([Uri]::EscapeDataString([string]$entry.Key) + '=' + [Uri]::EscapeDataString([string]$entry.Value))
    }
    $uri = $BaseUrl.TrimEnd('/') + '/voice?' + ($pairs -join '&')
    $wav = Join-Path $env:TEMP ("ai_cockpit_emotion_test_" + $name + '.wav')
    Invoke-WebRequest -UseBasicParsing -Uri $uri -OutFile $wav -TimeoutSec 30
    $player = New-Object System.Media.SoundPlayer $wav
    $player.Load()
    $player.PlaySync()
    $player.Dispose()
}

$status = Invoke-WebRequest -UseBasicParsing -Uri ($BaseUrl.TrimEnd('/') + '/status') -TimeoutSec 3
if ($status.StatusCode -ne 200) { throw 'SBV2 API is not ready.' }

$samples = @(
    [pscustomobject]@{name='CALM'; length=1.20; weight=0.35; split=0.60; text='きおくしあ、熱量は低めです。今は待ち。無理に入らないでください。'},
    [pscustomobject]@{name='WATCH'; length=1.13; weight=0.50; split=0.50; text='きおくしあ、ロング寄り。ぶいわっぷ、うえです。まだ加速確認待ち。飛び乗らないでください。'},
    [pscustomobject]@{name='HOT'; length=1.03; weight=0.70; split=0.35; text='来た。きおくしあ、ロング優勢。出来高、加速。あゆみねも買い優勢。ぶいわっぷ、うえを維持。いけいけムード。ただし、高値追いは禁止。押し目だけ。'},
    [pscustomobject]@{name='DANGER'; length=1.10; weight=0.80; split=0.45; text='危ない。きおくしあ、往復警戒です。いったん追わない。ぶいわっぷと板、あゆみねが、落ち着くまで待ってください。'}
)

$targets = if ($Level -eq 'ALL') { $samples } else { @($samples | Where-Object { $_.name -eq $Level }) }
foreach ($sample in $targets) {
    Speak-Sample $sample.name $sample.text $sample.length $sample.weight $sample.split
    Start-Sleep -Milliseconds 500
}

Write-Host 'Emotion voice test completed.' -ForegroundColor Green
