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

$script:diagLogPath = Join-Path $PSScriptRoot "com_error_diag.csv"
if (-not (Test-Path $script:diagLogPath)) {
    "日時,セル,シート,試行,例外型,HResult,InnerException型,InnerExceptionメッセージ,値の型,値,ApartmentState" | Out-File -FilePath $script:diagLogPath -Encoding utf8
}
$script:comApartmentState = [System.Threading.Thread]::CurrentThread.GetApartmentState()

function Write-ComErrorDiag($range, $value, [int]$attempt, $errorRecord) {
    # C-006対応: InvalidCastExceptionとCOMException（ビジー等）を混同しないよう、
    # 例外の型・HResult・InnerExceptionを都度記録する。ここでの失敗は握りつぶす（診断用のため）。
    try {
        $ex = $errorRecord.Exception
        $cellAddr = try { $range.Address() } catch { "不明" }
        $sheetName = try { $range.Worksheet.Name } catch { "不明" }
        $valueType = if ($null -eq $value) { "null" } else { $value.GetType().FullName }
        $innerType = if ($null -ne $ex.InnerException) { $ex.InnerException.GetType().FullName } else { "" }
        $innerMsg = if ($null -ne $ex.InnerException) { $ex.InnerException.Message } else { "" }
        $hresultHex = try { "0x{0:X8}" -f $ex.HResult } catch { "" }
        $row = @(
            (Get-Date).ToString('yyyy-MM-dd HH:mm:ss.fff'), $cellAddr, $sheetName, $attempt,
            $ex.GetType().FullName, $hresultHex, $innerType, $innerMsg, $valueType, $value, $script:comApartmentState
        ) -join ","
        Add-Content -Path $script:diagLogPath -Value $row -Encoding utf8
    } catch {}
}

function Set-CellValue($range, $value, [int]$maxAttempts = 4, [int]$delayMs = 150) {
    # Excel COMへの書き込みが原因不明の一時的なキャスト例外で失敗することがある（切り分け済み・単発では成功する）。
    # 少し待って再試行すれば成功するため、書き込みのたびに使うヘルパー。全て失敗した場合のみ例外を投げる。
    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        try {
            $range.Value2 = $value
            return
        } catch {
            Write-ComErrorDiag $range $value $attempt $_
            if ($attempt -eq $maxAttempts) { throw }
            Start-Sleep -Milliseconds $delayMs
        }
    }
}

function Set-CellFormula($range, $formula, [int]$maxAttempts = 4, [int]$delayMs = 150) {
    # Set-CellValueと同じ理由（起動時の数式設定も同じCOM書き込みの脆さの影響を受けることが実機で判明。
    # 特にDASHBOARD!B5の安全ゲート数式が無音で設定に失敗する事例があったため、起動時の数式設定も
    # 必ずこちらを使う）。
    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        try {
            $range.FormulaLocal = $formula
            return
        } catch {
            Write-ComErrorDiag $range $formula $attempt $_
            if ($attempt -eq $maxAttempts) { throw }
            Start-Sleep -Milliseconds $delayMs
        }
    }
}

function Invoke-ComRetry([scriptblock]$Action, [int]$maxAttempts = 8, [int]$delayMs = 500) {
    # 2026-09-15実機で判明: 起動直後（RSS接続・再計算がまだ進行中の間）はExcel自体がCOM呼び出しを
    # 拒否することがあり（HRESULT 0x80010001 RPC_E_CALL_REJECTED、いわゆる「サーバーがビジー」）、
    # $excel.Visible = $trueのような起動時の単発呼び出しがこれで丸ごと落ちて$ErrorActionPreference=Stop
    # によりスクリプト自体が終了する事例を確認した。Set-CellValue/Set-CellFormula同様のリトライを
    # 起動時の一連のCOM呼び出しにも適用する。
    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        try {
            return & $Action
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
    # 2026-09-14深夜の実機検証で判明: New-Object -ComObject Excel.Applicationで生成した
    # Excelインスタンスは、MS2 RSSアドイン（COMアドイン）が読み込まれずRssMarket等が
    # #NAME?エラーになり、RSSリボンタブ自体も存在しないことを確認した。ファイルを通常どおり
    # 開く（シェル経由でExcel.exeを起動する）必要があるため、Start-Processでファイルを開き、
    # Excelプロセスが起動するのを待ってからGetActiveObjectで接続し直す。
    Write-Host "Excelが起動していません。ファイルを開いてアドインを正しく読み込みます。" -ForegroundColor Yellow
    Start-Process $bookPath
    $excel = $null
    $connectDeadline = (Get-Date).AddSeconds(60)
    while ($null -eq $excel -and (Get-Date) -lt $connectDeadline) {
        Start-Sleep -Seconds 2
        try { $excel = [Runtime.InteropServices.Marshal]::GetActiveObject("Excel.Application") } catch {}
    }
    if ($null -eq $excel) {
        Write-Host "Excelの起動を確認できませんでした。" -ForegroundColor Red
        Read-Host "Enterで終了"
        exit 1
    }
    Write-Host "Excelへ接続しました。RSSタブで『接続』を確認してください。" -ForegroundColor Yellow
}
Invoke-ComRetry { $excel.Visible = $true } | Out-Null
Invoke-ComRetry { $excel.DisplayAlerts = $false } | Out-Null
$book = Invoke-ComRetry {
    $found = $null
    foreach ($candidate in $excel.Workbooks) {
        if ($candidate.FullName -eq $bookPath -or $candidate.Name -eq "Kioxia_MS2_RSS_Live_Signals.xlsx") {
            $found = $candidate
            break
        }
    }
    if ($null -eq $found) { $found = $excel.Workbooks.Open($bookPath) }
    return $found
}
$rss = Invoke-ComRetry { $book.Worksheets.Item("RSS接続") }
$calc = Invoke-ComRetry { $book.Worksheets.Item("計算") }
$dash = Invoke-ComRetry { $book.Worksheets.Item("DASHBOARD") }
$log = Invoke-ComRetry { $book.Worksheets.Item("検証ログ") }

Set-CellFormula $rss.Range("B4") '=RssMarket("285A.T","現在値")'
Set-CellFormula $rss.Range("B5") '=RssMarket("285A.T","出来高加重平均")'
Set-CellFormula $rss.Range("B6") '=RssMarket("285A.T","出来高")'
Set-CellFormula $rss.Range("B7") '=RssMarket("285A.T","最良売気配値")'
Set-CellFormula $rss.Range("B8") '=RssMarket("285A.T","最良買気配値")'
Set-CellFormula $rss.Range("B9") '=RssMarket("285A.T","OVER気配数量")'
Set-CellFormula $rss.Range("B10") '=RssMarket("285A.T","UNDER気配数量")'
Set-CellFormula $rss.Range("B11") '=RssMarket("285A.T","売成行数量")'
Set-CellFormula $rss.Range("B12") '=RssMarket("285A.T","買成行数量")'
Set-CellValue $rss.Range("B13") "RSS対象外"
Set-CellValue $rss.Range("B14") "RSS対象外"
Set-CellValue $rss.Range("B15") "週次データを別取得"
Set-CellFormula $rss.Range("A20") '=RssChart(,"285A.T","1M",500)'
Set-CellFormula $rss.Range("L20") '=RssChart(,"285A.T","5M",200)'
Set-CellValue $rss.Range("B16") "接続中"
# Issue #17追記（2026-09-14・JNX発見を受けて追加）: 夜間PTS(JNX)価格は参考表示専用。
# MS2_RSS_100_Collector.ps1のKIOXIA_JNXシートで実データ取得を確認済み（285A.JNX形式）。
# 売買サイン($buy/$short/$inSession)には一切使わない。DASHBOARDの参考表示にのみ使う。
Set-CellFormula $rss.Range("B18") '=RssMarket("285A.JNX","現在値")'
Set-CellFormula $rss.Range("B19") '=RssMarket("285A.JNX","前日比率")'
Set-CellFormula $rss.Range("B20") '=RssMarket("285A.JNX","最良買気配値")'
Set-CellFormula $rss.Range("B21") '=RssMarket("285A.JNX","最良売気配値")'
Set-CellFormula $rss.Range("B22") '=RssMarket("285A.JNX","現在値詳細時刻")'
# 2026-09-14深夜の実機検証で判明: CalculateFull()はワークブック全体（100銘柄収集器の
# 100銘柄RSS・KIOXIA_JNXシート、合計数千セルのRssMarket数式を含む）を再計算するため、
# 非常に重く、これが原因でWatcherがCPU使用率ゼロのままハングする事例を確認した。
# 必要なのはRSS接続シートの値だけなので、そのシートだけに絞って再計算する。
$rss.Calculate()

# Issue #17対応: 「最終更新」「足時刻」がExcelのシリアル数値に化けないよう、明示的に日時書式を固定する。
$calc.Range("B18").NumberFormat = "mm/dd hh:mm:ss"
$calc.Range("B19").NumberFormat = "mm/dd hh:mm"
$dash.Range("B22").NumberFormat = "mm/dd hh:mm:ss"
$dash.Range("D22").NumberFormat = "mm/dd hh:mm"
# データ鮮度: スクリプトが停止していてもExcel側のNOW()で判定できるよう、書式でなく数式で持たせる。
Set-CellValue $dash.Range("A24") "データ鮮度"
Set-CellFormula $dash.Range("B24") '=IF(計算!B18=0,"未取得",IF((NOW()-計算!B18)*1440>1,"古いデータ("&TEXT((NOW()-計算!B18)*1440,"0")&"分前)","最新"))'
# 安全対策（C-005/C-006対応・最優先）: COM書き込み失敗時、DASHBOARDの売買サイン表示が
# 古い値のまま「有効な現在のサイン」に見えてしまう問題への対処。計算!B18（最終更新）は
# 計算!B2（サイン）と同じ書き込みバッチの一部で、B2の書き込みが失敗すればbatch全体が
# 中断されB18も更新されない（コードレビューで確認済み）。そのためB18の鮮度をそのまま
# サイン表示のゲートとして使う。PowerShell側の書き込みに一切依存せず、Excel自身のNOW()
# だけで判定するため、監視ループが完全に停止していても機能する。
# 2026-09-14深夜: 実機検証で判明した重大な誤り訂正。DASHBOARD!B5はA5:H9の結合セルの
# 非アンカーセルで、非アンカーセルへの書き込みはExcelが無音で無視する（エラーにもならない）。
# 実際に画面へ表示されるのは結合セルの左上(アンカー)であるA5であり、B5への設定はずっと
# 無効だった。安全ゲートは必ずA5へ設定する。
# また、このFormulaLocal設定自体が無音で失敗する事例も実機で確認したため、
# 必ずSet-CellFormula（リトライ付き）で設定する。安全ゲートが無いと本末転倒のため最重要。
Set-CellFormula $dash.Range("A5") '=IF(計算!B18=0,"未取得",IF((NOW()-計算!B18)*1440>1,"古い・使用不可",計算!B2))'
# 東証RSSの現在値・気配は夜間PTS(JNX)の価格ではないため、時間帯ラベルにその旨を明記する（売買判定は変更しない）。
Set-CellValue $dash.Range("H17") "9:00–11:30 / 12:30–15:30（夜間PTSは別時間帯・参考表示のみ）"
# ゆうすけの指摘（2026-09-14深夜）: 画面右上の「現在値」ラベルが東証(285A.T)専用であることが
# 伝わらず、夜間PTS時間帯にJNX参考価格と乖離して見えて紛らわしかった。東証の立会時間外は
# 直近の東証確定値（引け値等）のまま凍結される仕様（意図的・Issue #17対応どおり）だが、
# ラベルにその旨を明記して誤解を防ぐ。
Set-CellValue $dash.Range("I5") "現在値(東証)"
# 夜間PTS(JNX)参考表示欄（売買サインには使わない・表示専用）
Set-CellValue $dash.Range("A25") "JNX参考"
$dash.Range("B25").NumberFormat = "#,##0"
Set-CellValue $dash.Range("C25") "前日比"
Set-CellValue $dash.Range("E25") "気配(買/売)"
Set-CellValue $dash.Range("G25") "時刻"
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
        # 2026-09-14深夜: $excel.Calculate()はExcelの仕様上「開いている全ブックを再計算」する
        # （Microsoft公式ドキュメント）。100銘柄収集器のシートを含む全体再計算は非常に重く、
        # ハング・COMエラーの一因と見て、このシート単体の再計算に変更した。
        $rss.Calculate()
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
                Set-CellValue $dash.Range("B25") ([string]$ptsPrice)
                $ptsChangeText = if ($null -ne $ptsChangePct) { ([string][math]::Round($ptsChangePct,2)) + "%" } else { "" }
                $ptsQuoteText = if ($null -ne $ptsBid -and $null -ne $ptsAsk) { "$ptsBid / $ptsAsk" } else { "" }
                Set-CellValue $dash.Range("D25") $ptsChangeText
                Set-CellValue $dash.Range("F25") $ptsQuoteText
                $ptsTimeRaw = $rss.Range("B22").Value2
                $ptsTimeText = ""
                try {
                    if ($ptsTimeRaw -is [double]) { $ptsTimeText = [DateTime]::FromOADate($ptsTimeRaw).ToString("HH:mm:ss") }
                    elseif ($null -ne $ptsTimeRaw) { $ptsTimeText = [string]$ptsTimeRaw }
                } catch { $ptsTimeText = "" }
                Set-CellValue $dash.Range("H25") $ptsTimeText
            }
        } catch {
            Write-Host ("JNX参考表示の更新に失敗（次のループで再試行）: " + $_.Exception.Message) -ForegroundColor DarkYellow
        }

        # ゆうすけの指摘（2026-09-14深夜）: ラベルを「現在値(東証)」に変えるだけでは、
        # 夜間PTS時間帯に画面の目立つ位置（I5/I7）が古い東証値のまま止まって見えて
        # 実用上わかりにくいとの指摘を受けた。表示だけを、今の時間帯で実際に意味のある
        # 値（東証立会中は東証値、それ以外はJNX参考値）に切り替える。
        # 重要: これは表示のみの変更。$buy/$short等の売買判定は引き続き$price（東証値）
        # だけを使い、このブロックの影響を一切受けない（下のシグナル計算ブロックは変更していない）。
        try {
            if ($inSession -and $null -ne $price) {
                Set-CellValue $dash.Range("I5") "現在値(東証)"
                Set-CellValue $dash.Range("I7") ([string]$price)
            } elseif ($null -ne $ptsPrice) {
                $ptsLabel = if ($inNightPts) { "現在値(JNX夜間PTS参考)" } elseif ($inDayPts) { "現在値(JNXデイタイムPTS参考)" } else { "現在値(JNX参考)" }
                Set-CellValue $dash.Range("I5") $ptsLabel
                Set-CellValue $dash.Range("I7") ([string]$ptsPrice)
            } elseif ($null -ne $price) {
                Set-CellValue $dash.Range("I5") "現在値(東証)"
                Set-CellValue $dash.Range("I7") ([string]$price)
            } else {
                Set-CellValue $dash.Range("I5") "現在値(未取得)"
                Set-CellValue $dash.Range("I7") "—"
            }
        } catch {
            Write-Host ("現在値表示の更新に失敗（次のループで再試行）: " + $_.Exception.Message) -ForegroundColor DarkYellow
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
