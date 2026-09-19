# Resample_Kioxia_Ticks_15s.ps1
#
# 共有シートC-075（GPT提案）への対応。Kioxia_RSS_Live_Watcher.ps1が
# Write-TickLogDiff で蓄積した生ティックログ（kioxia_ticks_YYYYMMDD.csv）を、
# 15秒足OHLCVへ集約してCSV出力する。ザラバ後にいつでも手動実行できる
# オフラインのバッチ処理で、Watcherの監視ループとは無関係に動く。
#
# 入力: ms2_live/kioxia_ticks_YYYYMMDD.csv（recorded_at,tick_time,price,volume,poll_seq）
# 出力: ms2_live/kioxia_15s_YYYYMMDD.csv（bucket_start,open,high,low,close,volume,tick_count）
#
# 正直な制約:
# - ティックはRssTickListの(時刻,価格,出来高)でしか識別できないため、同一秒・同価格・
#   同出来高の複数約定は区別不能（Watcher側のkioxia_tick_diag_YYYYMMDD.csvで
#   suspected_gapの発生頻度を別途確認すること）
# - ティックが1件も無い15秒バケットは出力しない（歯抜けのまま出力し、補完はしない）
# - tick_timeは秒単位までしか無いため、同一バケット内の順序（どれが先の約定か）は
#   ログへの記録順（recorded_at→poll_seq）で近似しているに過ぎない

param(
    [string]$Date = (Get-Date -Format "yyyyMMdd")
)

$ErrorActionPreference = "Stop"

$inputPath = Join-Path $PSScriptRoot ("kioxia_ticks_" + $Date + ".csv")
$outputPath = Join-Path $PSScriptRoot ("kioxia_15s_" + $Date + ".csv")

if (-not (Test-Path $inputPath)) {
    Write-Host ("ティックログが見つかりません: " + $inputPath) -ForegroundColor Red
    exit 1
}

function Get-SecondsSinceMidnight([string]$timeText) {
    $parts = $timeText -split ":"
    if ($parts.Count -ne 3) { return $null }
    return ([int]$parts[0] * 3600) + ([int]$parts[1] * 60) + [int]$parts[2]
}

$rows = Import-Csv -Path $inputPath
$buckets = [ordered]@{}

foreach ($row in $rows) {
    $sec = Get-SecondsSinceMidnight $row.tick_time
    if ($null -eq $sec) { continue }
    $price = [double]$row.price
    $volume = [double]$row.volume
    if ($price -le 0 -or $volume -le 0) { continue }

    $bucketStartSec = [int]([math]::Floor($sec / 15) * 15)
    $h = [int][math]::Floor($bucketStartSec / 3600)
    $m = [int][math]::Floor(($bucketStartSec % 3600) / 60)
    $s = [int]($bucketStartSec % 60)
    $bucketKey = "{0:D2}:{1:D2}:{2:D2}" -f $h, $m, $s

    if (-not $buckets.Contains($bucketKey)) {
        $buckets[$bucketKey] = [pscustomobject]@{
            BucketStart = $bucketKey
            Open        = $price
            High        = $price
            Low         = $price
            Close       = $price
            Volume      = $volume
            TickCount   = 1
        }
    } else {
        $b = $buckets[$bucketKey]
        $b.High = [math]::Max($b.High, $price)
        $b.Low = [math]::Min($b.Low, $price)
        $b.Close = $price
        $b.Volume += $volume
        $b.TickCount += 1
    }
}

$sortedKeys = $buckets.Keys | Sort-Object
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("bucket_start,open,high,low,close,volume,tick_count")
foreach ($key in $sortedKeys) {
    $b = $buckets[$key]
    $lines.Add($b.BucketStart + "," + $b.Open + "," + $b.High + "," + $b.Low + "," + $b.Close + "," + $b.Volume + "," + $b.TickCount)
}
$lines | Out-File -FilePath $outputPath -Encoding utf8

Write-Host ("15秒足 " + $sortedKeys.Count + "本を出力しました: " + $outputPath) -ForegroundColor Green
Write-Host "同じ日のkioxia_tick_diag_YYYYMMDD.csvでsuspected_gap=Trueの件数も確認してください。" -ForegroundColor Yellow
