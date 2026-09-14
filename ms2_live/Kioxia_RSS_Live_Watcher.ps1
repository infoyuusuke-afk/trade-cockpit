$ErrorActionPreference = "Stop"

$bookPath = Join-Path $PSScriptRoot "Kioxia_MS2_RSS_Live_Signals.xlsx"
if (-not (Test-Path $bookPath)) {
    Write-Host "同じフォルダーに Kioxia_MS2_RSS_Live_Signals.xlsx を置いてください。" -ForegroundColor Red
    Read-Host "Enterで終了"
    exit 1
}

function Get-Ema([double[]]$values, [int]$period) {
    if ($values.Count -lt $period) { return 0 }
    $k = 2.0 / ($period + 1.0)
    $ema = ($values[0..($period-1)] | Measure-Object -Average).Average
    for ($i = $period; $i -lt $values.Count; $i++) { $ema = ($values[$i] * $k) + ($ema * (1.0 - $k)) }
    return [double]$ema
}

function Get-Tick([double]$price) {
    if ($price -lt 3000) { return 1 }
    if ($price -lt 5000) { return 5 }
    if ($price -lt 30000) { return 10 }
    if ($price -lt 50000) { return 50 }
    return 100
}

function Get-SafeNumber($value, [double]$minValue, [double]$maxValue) {
    if ($null -eq $value -or $value -is [System.Array]) { return $null }
    try { $number = [Convert]::ToDouble($value) } catch { return $null }
    if ([double]::IsNaN($number) -or [double]::IsInfinity($number)) { return $null }
    if ($number -lt $minValue -or $number -gt $maxValue) { return $null }
    return [double]$number
}

function Set-CellValue($range, $value, [int]$maxAttempts = 4, [int]$delayMs = 150) {
    # Excel COMへの書き込みが原因不明の一時的なキャスト例外で失敗することがある（切り分け済み・単発では成功する）。
    # 少し待って再試行すれば成功するため、書き込みのたびに使うヘルパー。全て失敗した場合のみ例外を投げる。
    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        try {
            $range.Value2 = $value
            return
        } catch {
            if ($attempt -eq $maxAttempts) { throw }
            Start-Sleep -Milliseconds $delayMs
        }
    }
}

function Read-Chart($sheet, [string]$anchor) {
    try {
        $region = $sheet.Range($anchor).CurrentRegion.Value2
        $rows = @()
        if ($region -is [System.Array] -and $region.Rank -eq 2) {
            for ($r = 1; $r -le $region.GetLength(0); $r++) {
                $o = $region[$r,6]; $h = $region[$r,7]; $l = $region[$r,8]; $c = $region[$r,9]; $v = $region[$r,10]
                if ($o -is [double] -and $c -is [double]) {
                    $rawDate = $region[$r,4]; $rawTime = $region[$r,5]
                    try { $dateKey = if ($rawDate -is [double]) { [DateTime]::FromOADate($rawDate).ToString("yyyy-MM-dd") } else { ([DateTime]::Parse([string]$rawDate)).ToString("yyyy-MM-dd") } } catch { $dateKey = [string]$rawDate }
                    try { $timeText = if ($rawTime -is [double]) { [DateTime]::FromOADate($rawTime).ToString("HH:mm") } else { ([DateTime]::Parse([string]$rawTime)).ToString("HH:mm") } } catch { $timeText = [string]$rawTime }
                    $rows += [pscustomobject]@{ DateKey=$dateKey; TimeText=$timeText; SortKey=("$dateKey $timeText"); Open=[double]$o; High=[double]$h; Low=[double]$l; Close=[double]$c; Volume=[double]$v }
                }
            }
        }
        return @($rows | Sort-Object SortKey)
    } catch { return @() }
}

try {
    $excel = [Runtime.InteropServices.Marshal]::GetActiveObject("Excel.Application")
    Write-Host "RSS接続済みのExcelへ接続しました。" -ForegroundColor Green
} catch {
    $excel = New-Object -ComObject Excel.Application
    Write-Host "Excelを起動しました。RSSタブで『接続』を確認してください。" -ForegroundColor Yellow
}
$excel.Visible = $true
$excel.DisplayAlerts = $false
$book = $null
foreach ($candidate in $excel.Workbooks) {
    if ($candidate.FullName -eq $bookPath -or $candidate.Name -eq "Kioxia_MS2_RSS_Live_Signals.xlsx") {
        $book = $candidate
        break
    }
}
if ($null -eq $book) { $book = $excel.Workbooks.Open($bookPath) }
$rss = $book.Worksheets.Item("RSS接続")
$calc = $book.Worksheets.Item("計算")
$dash = $book.Worksheets.Item("DASHBOARD")
$log = $book.Worksheets.Item("検証ログ")

$rss.Range("B4").FormulaLocal = '=RssMarket("285A.T","現在値")'
$rss.Range("B5").FormulaLocal = '=RssMarket("285A.T","出来高加重平均")'
$rss.Range("B6").FormulaLocal = '=RssMarket("285A.T","出来高")'
$rss.Range("B7").FormulaLocal = '=RssMarket("285A.T","最良売気配値")'
$rss.Range("B8").FormulaLocal = '=RssMarket("285A.T","最良買気配値")'
$rss.Range("B9").FormulaLocal = '=RssMarket("285A.T","OVER気配数量")'
$rss.Range("B10").FormulaLocal = '=RssMarket("285A.T","UNDER気配数量")'
$rss.Range("B11").FormulaLocal = '=RssMarket("285A.T","売成行数量")'
$rss.Range("B12").FormulaLocal = '=RssMarket("285A.T","買成行数量")'
$rss.Range("B13").Value2 = "RSS対象外"
$rss.Range("B14").Value2 = "RSS対象外"
$rss.Range("B15").Value2 = "週次データを別取得"
$rss.Range("A20").FormulaLocal = '=RssChart(,"285A.T","1M",500)'
$rss.Range("L20").FormulaLocal = '=RssChart(,"285A.T","5M",200)'
$rss.Range("B16").Value2 = "接続中"
# Issue #17追記（2026-09-14・JNX発見を受けて追加）: 夜間PTS(JNX)価格は参考表示専用。
# MS2_RSS_100_Collector.ps1のKIOXIA_JNXシートで実データ取得を確認済み（285A.JNX形式）。
# 売買サイン($buy/$short/$inSession)には一切使わない。DASHBOARDの参考表示にのみ使う。
$rss.Range("B18").FormulaLocal = '=RssMarket("285A.JNX","現在値")'
$rss.Range("B19").FormulaLocal = '=RssMarket("285A.JNX","前日比率")'
$rss.Range("B20").FormulaLocal = '=RssMarket("285A.JNX","最良買気配値")'
$rss.Range("B21").FormulaLocal = '=RssMarket("285A.JNX","最良売気配値")'
$rss.Range("B22").FormulaLocal = '=RssMarket("285A.JNX","現在値詳細時刻")'
$excel.CalculateFull()

# Issue #17対応: 「最終更新」「足時刻」がExcelのシリアル数値に化けないよう、明示的に日時書式を固定する。
$calc.Range("B18").NumberFormat = "mm/dd hh:mm:ss"
$calc.Range("B19").NumberFormat = "mm/dd hh:mm"
$dash.Range("B22").NumberFormat = "mm/dd hh:mm:ss"
$dash.Range("D22").NumberFormat = "mm/dd hh:mm"
# データ鮮度: スクリプトが停止していてもExcel側のNOW()で判定できるよう、書式でなく数式で持たせる。
$dash.Range("A24").Value2 = "データ鮮度"
$dash.Range("B24").FormulaLocal = '=IF(計算!B18=0,"未取得",IF((NOW()-計算!B18)*1440>1,"古いデータ("&TEXT((NOW()-計算!B18)*1440,"0")&"分前)","最新"))'
# 東証RSSの現在値・気配は夜間PTS(JNX)の価格ではないため、時間帯ラベルにその旨を明記する（売買判定は変更しない）。
$dash.Range("H17").Value2 = "9:00–11:30 / 12:30–15:30（夜間PTSは別時間帯・参考表示のみ）"
# 夜間PTS(JNX)参考表示欄（売買サインには使わない・表示専用）
$dash.Range("A25").Value2 = "JNX参考"
$dash.Range("B25").NumberFormat = "#,##0"
$dash.Range("C25").Value2 = "前日比"
$dash.Range("E25").Value2 = "気配(買/売)"
$dash.Range("G25").Value2 = "時刻"
$dash.Range("G25").NumberFormat = "hh:mm:ss"

$speaker = New-Object -ComObject SAPI.SpVoice
$lastSpokenSignal = ""
$lastSpokenAt = Get-Date "2000-01-01"
$lastLoggedBar = ""
$pendingEvaluations = @()

# 気配値比率ログ: 寄り前（現在値がまだ無い時間帯）でも記録できるよう、同じフォルダーにCSVで保存する。
# このファイルはローカル専用（.gitignore管理外の場所）。公開リポジトリへは一切アップロードしない。
$boardLogPath = Join-Path $PSScriptRoot "気配値ログ.csv"
if (-not (Test-Path $boardLogPath)) {
    "日付,時刻,OVER気配数量,UNDER気配数量,UNDER比率,最良売気配値,最良買気配値,状態" | Out-File -FilePath $boardLogPath -Encoding utf8
}
$lastBoardLoggedMinute = ""

Write-Host "キオクシアLIVE監視を開始しました。終了はこの画面で Ctrl+C。" -ForegroundColor Cyan
$dash.Activate()

try {
    while ($true) {
      # 100銘柄収集器等との同時COMアクセスで、書き込みが一時的にキャスト例外を起こすことがあるため、
      # 監視ループ本体を丸ごとtry/catchで守る（1回失敗しても次のループで復帰する。売買サインの状態が
      # 更新されないまま古い値で残るのを避けるため、失敗時は短く待って次のループへ）。
      try {
        $excel.Calculate()
        $now = Get-Date
        $t = $now.TimeOfDay
        $inSession = (($t -ge [TimeSpan]::Parse("09:00:00") -and $t -le [TimeSpan]::Parse("11:30:00")) -or ($t -ge [TimeSpan]::Parse("12:30:00") -and $t -le [TimeSpan]::Parse("15:30:00")))
        $afterOR = ($t -ge [TimeSpan]::Parse("09:15:00"))
        # Issue #17対応: 東証RSSの現在値は夜間PTS(JNX)の価格を返さないため、時間帯の「表示」のみを分けて明示する。
        # 売買サイン($buy/$short/$inSession)には一切使わない。時間帯は一般公開情報に基づく目安であり、
        # 証券会社ごとの実際の受付時間・MS2 RSSでのPTS取得可否は実機未検証（Issue #17参照）。
        $inNightPts = ($t -ge [TimeSpan]::Parse("16:30:00") -or $t -le [TimeSpan]::Parse("06:00:00"))
        $inDayPts = ($t -ge [TimeSpan]::Parse("08:20:00") -and $t -lt [TimeSpan]::Parse("09:00:00"))
        $cutoff1 = $now.ToString("yyyy-MM-dd HH:mm")
        $bucket5 = Get-Date -Year $now.Year -Month $now.Month -Day $now.Day -Hour $now.Hour -Minute ([math]::Floor($now.Minute / 5) * 5) -Second 0
        $cutoff5 = $bucket5.ToString("yyyy-MM-dd HH:mm")
        $one = @(Read-Chart $rss "A20" | Where-Object { $_.SortKey -lt $cutoff1 })
        $five = @(Read-Chart $rss "L20" | Where-Object { $_.SortKey -lt $cutoff5 })
        $price = Get-SafeNumber $rss.Range("B4").Value2 0.01 10000000
        $vwap = Get-SafeNumber $rss.Range("B5").Value2 0 10000000
        $over = Get-SafeNumber $rss.Range("B9").Value2 0 1000000000000
        $under = Get-SafeNumber $rss.Range("B10").Value2 0 1000000000000

        # 気配値比率ログ: $price(現在値)が寄り前で未取得でも、気配数量が取れていれば1分に1回記録する。
        # 他プロセスとのCOM同時アクセスで一時的に失敗することがあるため、監視ループを止めないよう保護する。
        try {
            $askQuote = Get-SafeNumber $rss.Range("B7").Value2 0.01 10000000
            $bidQuote = Get-SafeNumber $rss.Range("B8").Value2 0.01 10000000
            $boardMinuteKey = $now.ToString("yyyy-MM-dd HH:mm")
            if (($null -ne $over -or $null -ne $under) -and $boardMinuteKey -ne $lastBoardLoggedMinute) {
                $ou = if ($null -eq $over) { 0 } else { $over }
                $un = if ($null -eq $under) { 0 } else { $under }
                $ratioText = if (($ou + $un) -gt 0) { [string][math]::Round($un / ($ou + $un), 4) } else { "" }
                $boardState = if ($null -eq $price) { "寄り前/未約定" } else { "約定あり" }
                $row = "$($now.ToString('yyyy-MM-dd')),$($now.ToString('HH:mm')),$ou,$un,$ratioText,$askQuote,$bidQuote,$boardState"
                Add-Content -Path $boardLogPath -Value $row -Encoding utf8
                $lastBoardLoggedMinute = $boardMinuteKey
            }
        } catch {
            Write-Host ("気配値ログの記録に失敗（次のループで再試行）: " + $_.Exception.Message) -ForegroundColor DarkYellow
        }

        # 夜間PTS(JNX)参考表示。東証現在値の有無に関わらず更新する（表示専用・売買サインには使わない）。
        # COM経由の書き込みは他プロセス（100銘柄収集器等）との同時アクセスで一時的に失敗することがあるため、
        # ここでの失敗が監視ループ全体を止めないようtry/catchで守る（次のループでまた更新される）。
        try {
            $ptsPrice = Get-SafeNumber $rss.Range("B18").Value2 0.01 10000000
            $ptsChangePct = Get-SafeNumber $rss.Range("B19").Value2 -100 100
            $ptsBid = Get-SafeNumber $rss.Range("B20").Value2 0.01 10000000
            $ptsAsk = Get-SafeNumber $rss.Range("B21").Value2 0.01 10000000
            if ($null -eq $ptsPrice) {
                Set-CellValue $dash.Range("B25") "—"
                Set-CellValue $dash.Range("D25") ""
                Set-CellValue $dash.Range("F25") ""
                Set-CellValue $dash.Range("H25") "未取得"
            } else {
                Set-CellValue $dash.Range("B25") $ptsPrice
                $ptsChangeText = if ($null -ne $ptsChangePct) { ([string][math]::Round($ptsChangePct,2)) + "%" } else { "" }
                $ptsQuoteText = if ($null -ne $ptsBid -and $null -ne $ptsAsk) { "$ptsBid / $ptsAsk" } else { "" }
                Set-CellValue $dash.Range("D25") $ptsChangeText
                Set-CellValue $dash.Range("F25") $ptsQuoteText
                $ptsTimeRaw = $rss.Range("B22").Value2
                $ptsTimeText = try { if ($ptsTimeRaw -is [double]) { [DateTime]::FromOADate($ptsTimeRaw).ToString("HH:mm:ss") } else { [string]$ptsTimeRaw } } catch { [string]$ptsTimeRaw }
                Set-CellValue $dash.Range("H25") $ptsTimeText
            }
        } catch {
            Write-Host ("JNX参考表示の更新に失敗（次のループで再試行）: " + $_.Exception.Message) -ForegroundColor DarkYellow
        }

        if ($null -eq $price) {
            $rss.Range("B16").Value2 = "RSS取得エラー"
            $calc.Range("B2").Value2 = "売買禁止"
            $calc.Range("B3").Value2 = "—"
            $calc.Range("B25").Value2 = if ($inNightPts -or $inDayPts) { "現在値が未取得（JNX PTS時間帯は東証RSSの対象外。PTS参考価格はDASHBOARD下部を参照・売買サインには使わない）" } else { "現在値が未取得。MS2ログイン→ExcelのRSSタブ→接続を確認" }
            $dash.Range("A5:H9").Interior.Color = 0x2A8CFF
            Write-Host "現在値はExcelエラーまたは未取得です。誤データは保存しません。" -ForegroundColor Yellow
            Start-Sleep -Seconds 3
            continue
        }
        if ($null -eq $vwap) { $vwap = 0 }
        if ($null -eq $over) { $over = 0 }
        if ($null -eq $under) { $under = 0 }
        $underRatio = if (($over + $under) -gt 0) { $under / ($over + $under) } else { 0.5 }

        $signal = "待機"
        $entry = 0; $stop = 0; $target1 = 0; $target2 = 0
        $state = if ($inSession) { "監視中" } elseif ($inNightPts) { "東証終了・JNX夜間PTS時間帯（PTS参考価格はDASHBOARD下部・売買サインには使わない）" } elseif ($inDayPts) { "東証寄付前・JNXデイタイムPTS時間帯（PTS参考価格はDASHBOARD下部・売買サインには使わない）" } else { "市場時間外" }
        $condPrice = "データ待ち"; $condVol = "データ待ち"; $condEma = "データ待ち"; $condOr = "データ待ち"
        $close1 = 0; $open1 = 0; $volRatio = 0; $ema9 = 0; $ema20 = 0; $orHigh = 0; $orLow = 0; $crosses = 0; $barTime = "-"

        if ($one.Count -ge 25 -and $five.Count -ge 21 -and $price -gt 0 -and $vwap -gt 0) {
            $completedOne = $one | Select-Object -Last 21
            $last = $completedOne[-1]
            $close1 = $last.Close; $open1 = $last.Open; $barTime = $last.SortKey
            $avgVol = (($completedOne | Select-Object -First 20 | Measure-Object Volume -Average).Average)
            if ($avgVol -gt 0) { $volRatio = $last.Volume / $avgVol }
            $fiveCloses = @($five | ForEach-Object { [double]$_.Close })
            $ema9 = Get-Ema $fiveCloses 9
            $ema20 = Get-Ema $fiveCloses 20
            $latestDate = $one[-1].DateKey
            $orRows = @($one | Where-Object { $_.DateKey -eq $latestDate -and $_.TimeText -ge "09:00" -and $_.TimeText -lt "09:15" })
            if ($orRows.Count -gt 0) {
                $orHigh = ($orRows | Measure-Object High -Maximum).Maximum
                $orLow = ($orRows | Measure-Object Low -Minimum).Minimum
            }
            $recent10 = @($one | Select-Object -Last 10)
            for ($i = 1; $i -lt $recent10.Count; $i++) {
                if ((($recent10[$i-1].Close - $vwap) * ($recent10[$i].Close - $vwap)) -lt 0) { $crosses++ }
            }
            $emaCompressed = if ($price -gt 0) { ([math]::Abs($ema9 - $ema20) / $price) -lt 0.0015 } else { $true }
            $whipsaw = ($crosses -ge 2 -or $emaCompressed)
            $buy = ($inSession -and $afterOR -and -not $whipsaw -and $close1 -gt $vwap -and $close1 -gt $open1 -and $volRatio -ge 1.5 -and $ema9 -gt $ema20 -and $price -gt $orHigh)
            $short = ($inSession -and $afterOR -and -not $whipsaw -and $close1 -lt $vwap -and $close1 -lt $open1 -and $volRatio -ge 1.5 -and $ema9 -lt $ema20 -and $price -lt $orLow)
            $tick = Get-Tick $price
            if ($whipsaw -and $inSession) { $signal = "往復ピンタ回避"; $state = "新規注文禁止" }
            elseif ($buy) { $signal = "買いサイン"; $entry = $last.High + $tick; $stop = $last.Low - $tick }
            elseif ($short) { $signal = "空売りサイン"; $entry = $last.Low - $tick; $stop = $last.High + $tick }
            if ($entry -gt 0) {
                $risk = [math]::Abs($entry - $stop)
                if ($signal -eq "買いサイン") { $target1 = $entry + $risk; $target2 = $entry + 2*$risk }
                if ($signal -eq "空売りサイン") { $target1 = $entry - $risk; $target2 = $entry - 2*$risk }
            }
            $condPrice = if ($close1 -gt $vwap) { "VWAP上" } elseif ($close1 -lt $vwap) { "VWAP下" } else { "VWAP同値" }
            $condVol = if ($volRatio -ge 1.5) { "出来高OK" } else { "出来高不足" }
            $condEma = if ($ema9 -gt $ema20) { "上向き" } elseif ($ema9 -lt $ema20) { "下向き" } else { "収束" }
            $condOr = if ($price -gt $orHigh) { "OR15上" } elseif ($price -lt $orLow) { "OR15下" } else { "OR15内" }
        }

        Set-CellValue $calc.Range("B2") $signal
        Set-CellValue $calc.Range("B3") ([string]$price)
        Set-CellValue $calc.Range("B4") ([string]$entry)
        Set-CellValue $calc.Range("B5") ([string]$stop)
        Set-CellValue $calc.Range("B6") ([string]$target1)
        Set-CellValue $calc.Range("B7") ([string]$target2)
        Set-CellValue $calc.Range("B8") ([string]$close1)
        Set-CellValue $calc.Range("B9") ([string]$vwap)
        Set-CellValue $calc.Range("B10") ([string]$open1)
        Set-CellValue $calc.Range("B11") ([string]$volRatio)
        Set-CellValue $calc.Range("B12") ([string]$ema9)
        Set-CellValue $calc.Range("B13") ([string]$ema20)
        Set-CellValue $calc.Range("B14") ([string]$orHigh)
        Set-CellValue $calc.Range("B15") ([string]$orLow)
        Set-CellValue $calc.Range("B16") ([string]$underRatio)
        Set-CellValue $calc.Range("B17") ([string]$crosses)
        Set-CellValue $calc.Range("B18") ($now.ToString("yyyy-MM-dd HH:mm:ss"))
        Set-CellValue $calc.Range("B19") $barTime
        Set-CellValue $calc.Range("B20") $condPrice
        Set-CellValue $calc.Range("B21") $condVol
        Set-CellValue $calc.Range("B22") $condEma
        Set-CellValue $calc.Range("B23") $condOr
        Set-CellValue $calc.Range("B24") ("UNDER " + [math]::Round($underRatio*100,1) + "%")
        Set-CellValue $calc.Range("B25") $state
        $dash.Range("A5:H9").Interior.Color = if ($signal -eq "買いサイン") { 0x62B14C } elseif ($signal -eq "空売りサイン") { 0x4E4EFF } elseif ($signal -eq "往復ピンタ回避") { 0x2A8CFF } else { 0x483117 }

        if ($inSession -and ($signal -eq "買いサイン" -or $signal -eq "空売りサイン") -and (($signal -ne $lastSpokenSignal) -or (((Get-Date) - $lastSpokenAt).TotalMinutes -ge 10))) {
            $spoken = if ($signal -eq "買いサイン") { "キオクシア、買いサイン点灯。発動価格 $entry 円。損切り $stop 円。" } else { "キオクシア、空売りサイン点灯。発動価格 $entry 円。損切り $stop 円。" }
            $speaker.Speak($spoken) | Out-Null
            $lastSpokenSignal = $signal; $lastSpokenAt = Get-Date
        }

        if ($barTime -ne "-" -and $barTime -ne $lastLoggedBar) {
            $row = $log.Cells($log.Rows.Count,1).End(-4162).Row + 1
            $log.Cells($row,1).Value2 = $now.ToString("yyyy-MM-dd HH:mm:ss")
            $log.Cells($row,2).Value2 = $barTime
            $log.Cells($row,3).Value2 = [string]$price
            $log.Cells($row,4).Value2 = $signal
            $log.Cells($row,5).Value2 = [string]$entry
            $log.Cells($row,6).Value2 = [string]$stop
            $log.Cells($row,7).Value2 = [string]$underRatio
            $log.Cells($row,8).Value2 = [string]$volRatio
            $log.Cells($row,9).Value2 = [string]($ema9 - $ema20)
            $lastLoggedBar = $barTime
            $pendingEvaluations += @{ Row=$row; Started=$now; BasePrice=$price; Done1=$false; Done5=$false; Done15=$false }
            $book.Save()
        }

        foreach ($item in @($pendingEvaluations)) {
            $mins = ($now - $item.Started).TotalMinutes
            if (-not $item.Done1 -and $mins -ge 1) { $log.Cells($item.Row,10).Value2 = [string]($price - $item.BasePrice); $item.Done1 = $true }
            if (-not $item.Done5 -and $mins -ge 5) { $log.Cells($item.Row,11).Value2 = [string]($price - $item.BasePrice); $item.Done5 = $true }
            if (-not $item.Done15 -and $mins -ge 15) { $log.Cells($item.Row,12).Value2 = [string]($price - $item.BasePrice); $item.Done15 = $true }
        }
        $pendingEvaluations = @($pendingEvaluations | Where-Object { -not $_.Done15 })
      } catch {
          Write-Host ("監視ループ内でエラー（継続します）: " + $_.Exception.Message + " | 行: " + $_.InvocationInfo.ScriptLineNumber + " | " + $_.InvocationInfo.Line.Trim()) -ForegroundColor DarkYellow
      }
      Start-Sleep -Seconds 2
    }
} finally {
    $rss.Range("B16").Value2 = "停止"
    $book.Save()
    Write-Host "監視を停止しました。Excelは開いたままです。" -ForegroundColor Yellow
}
