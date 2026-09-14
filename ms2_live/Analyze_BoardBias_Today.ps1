# 気配地合い参考表示(DASHBOARD!A26、UNDER比率の暫定しきい値0.6/0.4)が今日のザラバで
# 実際に機能したかを、引け後すぐに検証するための分析スクリプト（2026-09-15未明・C-017/C-018対応）。
#
# 気配値ログ.csv（ローカル専用・非公開）の「最良売気配値」「最良買気配値」の中値を
# 価格の代理指標として使い、地合いラベルごとに数分後の値動きを集計する。
#
# 正直な制約（結果を見る前に必ず理解しておくこと）：
# - 気配値ログ.csvには実際の約定価格・出来高は含まれない。中値はあくまで代理指標であり、
#   実際の売買コストや板の厚み・見せ玉の影響は反映されない。
# - n=1日分のみの検証であり、統計的な結論を出せる段階ではない。あくまで「今日1日で
#   何が言えたか」を正直に見るための最初の一歩。
# - UNDER比率のしきい値(0.6/0.4)は完全に暫定・未検証の値。今日の結果次第で見直す前提。
#
# 使い方: 引け後（15:30以降）にこのスクリプトを実行するだけ。
#   powershell.exe -ExecutionPolicy Bypass -File .\Analyze_BoardBias_Today.ps1

param(
    [int[]]$ForwardMinutes = @(5, 15),
    [double]$UpperThreshold = 0.6,
    [double]$LowerThreshold = 0.4
)

$csvPath = Join-Path $PSScriptRoot "気配値ログ.csv"
if (-not (Test-Path $csvPath)) {
    Write-Host "気配値ログ.csvが見つかりません: $csvPath" -ForegroundColor Red
    exit 1
}

$today = (Get-Date).ToString("yyyy-MM-dd")
$rows = Import-Csv -Path $csvPath -Encoding UTF8 | Where-Object { $_.日付 -eq $today }
if ($rows.Count -eq 0) {
    Write-Host "本日（$today）のデータがまだありません。ザラバ中〜引け後に再実行してください。" -ForegroundColor Yellow
    exit 0
}

Write-Host "本日（$today）のデータ件数: $($rows.Count)" -ForegroundColor Cyan

# 時刻をDateTimeに変換し、中値・地合いラベルを付与する
$parsed = @()
foreach ($r in $rows) {
    try {
        $dt = [DateTime]::ParseExact("$($r.日付) $($r.時刻)", "yyyy-MM-dd HH:mm", $null)
        $ask = [double]$r.最良売気配値
        $bid = [double]$r.最良買気配値
        if ($ask -le 0 -or $bid -le 0) { continue }
        $mid = ($ask + $bid) / 2.0
        $ratio = [double]$r.UNDER比率
        $label = if ($ratio -ge $UpperThreshold) { "買い気配優勢" } elseif ($ratio -le $LowerThreshold) { "売り気配優勢" } else { "中立" }
        $parsed += [pscustomobject]@{ Time = $dt; Mid = $mid; Ratio = $ratio; Label = $label }
    } catch { continue }
}
$parsed = @($parsed | Sort-Object Time)
Write-Host "有効データ件数（気配値0除外後）: $($parsed.Count)"

if ($parsed.Count -lt 2) {
    Write-Host "有効データが少なすぎて集計できません。" -ForegroundColor Yellow
    exit 0
}

foreach ($fwdMin in $ForwardMinutes) {
    Write-Host "`n=== ${fwdMin}分後の値動き（中値ベース・代理指標） ===" -ForegroundColor Green
    $groups = @{ "買い気配優勢" = @(); "売り気配優勢" = @(); "中立" = @() }
    for ($i = 0; $i -lt $parsed.Count; $i++) {
        $cur = $parsed[$i]
        $targetTime = $cur.Time.AddMinutes($fwdMin)
        # targetTime以降で最も近い行を探す（前後2分以内の許容）
        $future = $parsed | Where-Object { $_.Time -ge $targetTime -and $_.Time -le $targetTime.AddMinutes(2) } | Select-Object -First 1
        if ($null -eq $future) { continue }
        $retPct = (($future.Mid - $cur.Mid) / $cur.Mid) * 100
        $groups[$cur.Label] += $retPct
    }
    foreach ($label in @("買い気配優勢", "売り気配優勢", "中立")) {
        $vals = $groups[$label]
        if ($vals.Count -eq 0) { Write-Host "  $label : データなし(n=0)"; continue }
        $avg = ($vals | Measure-Object -Average).Average
        $posCount = @($vals | Where-Object { $_ -gt 0 }).Count
        Write-Host ("  {0} : n={1}  平均変化率={2:N4}%  上昇した割合={3:N1}%" -f $label, $vals.Count, $avg, (100.0*$posCount/$vals.Count))
    }
}

Write-Host "`n【重要】これはn=1日分のみの結果です。統計的な優位性の証明ではありません。" -ForegroundColor Yellow
Write-Host "中値は実際の約定価格ではなく代理指標です。傾向の当たり外れだけを見る参考情報として扱ってください。" -ForegroundColor Yellow
