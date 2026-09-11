param(
    [string]$WorkbookName = "Kioxia_MS2_RSS_Live_Signals.xlsx",
    [string]$WatchlistPath = (Join-Path $PSScriptRoot "watchlist_100.json"),
    [int]$IntervalSeconds = 2,
    [int]$SnapshotSeconds = 10,
    [switch]$StopAfterClose
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)

function Get-SafeNumber($value, [double]$minValue, [double]$maxValue) {
    if ($null -eq $value -or $value -is [System.Array]) { return $null }
    try { $number = [Convert]::ToDouble($value) } catch { return $null }
    if ([double]::IsNaN($number) -or [double]::IsInfinity($number)) { return $null }
    if ($number -lt $minValue -or $number -gt $maxValue) { return $null }
    return [double]$number
}

function Escape-Csv([object]$value) {
    if ($null -eq $value) { return "" }
    return '"' + ([string]$value).Replace('"','""') + '"'
}

function Escape-Html([object]$value) {
    return [System.Net.WebUtility]::HtmlEncode([string]$value)
}

function Get-TimeText($value) {
    if ($null -eq $value) { return "" }
    if ($value -is [double] -or $value -is [int]) {
        try { return [DateTime]::FromOADate([double]$value).ToString("HH:mm:ss") } catch { return "" }
    }
    try { return ([DateTime]::Parse([string]$value)).ToString("HH:mm:ss") } catch { return [string]$value }
}

function Get-DateText($value) {
    if ($null -eq $value) { return "" }
    if ($value -is [double] -or $value -is [int]) {
        try { return [DateTime]::FromOADate([double]$value).ToString("yyyy-MM-dd") } catch { return "" }
    }
    try { return ([DateTime]::Parse([string]$value)).ToString("yyyy-MM-dd") } catch { return "" }
}

function Get-TableValue([object]$table, [int]$row, [int]$column, [int]$columnCount = 31) {
    if ($null -eq $table -or $row -lt 1 -or $column -lt 1) { return $null }
    if ($table -is [System.Array] -and $table.Rank -ge 2) {
        return $table[$row,$column]
    }
    $flatIndex = (($row - 1) * $columnCount) + ($column - 1)
    if ($table -is [System.Array] -and $flatIndex -ge 0 -and $flatIndex -lt $table.Count) {
        return $table[$flatIndex]
    }
    return $null
}

function Write-AtomicUtf8([string]$path, [string]$content) {
    $tmp = "$path.tmp"
    [IO.File]::WriteAllText($tmp, $content, [Text.UTF8Encoding]::new($false))
    Move-Item -Force $tmp $path
}

function Ensure-Csv([string]$path, [string]$header) {
    if (-not (Test-Path $path)) { [IO.File]::WriteAllText($path, $header + [Environment]::NewLine, [Text.UTF8Encoding]::new($true)) }
}

function Write-CsvObjects([string]$path, [object[]]$rows) {
    if ($null -eq $rows -or $rows.Count -eq 0) { return }
    $csv = ($rows | ConvertTo-Csv -NoTypeInformation) -join [Environment]::NewLine
    Write-AtomicUtf8 $path ($csv + [Environment]::NewLine)
}

function Get-OvernightHoldStats([object[]]$rows) {
    $resolved = @($rows | Where-Object { $_.status -eq "検証済み" })
    $wins = @($resolved | Where-Object { $_.result -eq "勝ち" }).Count
    $losses = @($resolved | Where-Object { $_.result -eq "負け" }).Count
    $longRows = @($resolved | Where-Object { $_.side -eq "LONG" })
    $shortRows = @($resolved | Where-Object { $_.side -eq "SHORT" })
    $longWins = @($longRows | Where-Object { $_.result -eq "勝ち" }).Count
    $shortWins = @($shortRows | Where-Object { $_.result -eq "勝ち" }).Count
    $avgReturn = if ($resolved.Count -gt 0) { [Math]::Round((($resolved | Measure-Object -Property return_close_pct -Average).Average),2) } else { $null }
    $longAvg = if ($longRows.Count -gt 0) { [Math]::Round((($longRows | Measure-Object -Property return_close_pct -Average).Average),2) } else { $null }
    $shortAvg = if ($shortRows.Count -gt 0) { [Math]::Round((($shortRows | Measure-Object -Property return_close_pct -Average).Average),2) } else { $null }
    return [pscustomobject]@{
        samples=$resolved.Count; wins=$wins; losses=$losses
        win_rate=if($resolved.Count -gt 0){[Math]::Round($wins/$resolved.Count*100,1)}else{$null}
        avg_return_pct=$avgReturn
        long_samples=$longRows.Count; long_wins=$longWins
        long_win_rate=if($longRows.Count -gt 0){[Math]::Round($longWins/$longRows.Count*100,1)}else{$null}
        long_avg_return_pct=$longAvg
        short_samples=$shortRows.Count; short_wins=$shortWins
        short_win_rate=if($shortRows.Count -gt 0){[Math]::Round($shortWins/$shortRows.Count*100,1)}else{$null}
        short_avg_return_pct=$shortAvg
        recent=@($resolved | Sort-Object @{Expression={[string]$_.evaluation_date};Descending=$true}, @{Expression={[int]$_.rank}} | Select-Object -First 10)
    }
}

function Limit([double]$value, [double]$low, [double]$high) {
    return [Math]::Max($low, [Math]::Min($high, $value))
}

function Get-RegimeFit([string]$regime, [string]$side, [string]$sector, [double]$turnover) {
    if ([string]::IsNullOrWhiteSpace($regime) -or $regime -in @("判定不能","MIXED")) { return $null }
    $fit = 10.0
    if ($regime -in @("FOREIGN RISK-ON","FOREIGN RE-ENTRY")) {
        if ($side -eq "SHORT") { return 0.0 }
        if ($turnover -ge 10000000000) { $fit += 5 }
        if ($sector -match "半導体|電機|重工|金融") { $fit += 5 }
    } elseif ($regime -eq "DOMESTIC SUPPORT") {
        $fit = if($side -eq "LONG"){15.0}else{5.0}
    } elseif ($regime -in @("RETAIL REVERSAL","CREDIT SPECULATION")) {
        $fit = if($side -eq "LONG"){14.0}else{4.0}
    } elseif ($regime -in @("DISTRIBUTION","RISK-OFF")) {
        $fit = if($side -eq "SHORT"){20.0}else{0.0}
    } elseif ($regime -eq "LATE RISK-ON") {
        $fit = if($side -eq "SHORT"){15.0}else{5.0}
    }
    return Limit $fit 0 20
}

function Write-ImmutableJson([string]$path, [object]$payload) {
    $json = $payload | ConvertTo-Json -Depth 12
    try {
        $stream = [IO.File]::Open($path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
        try {
            $bytes = [Text.UTF8Encoding]::new($false).GetBytes($json)
            $stream.Write($bytes,0,$bytes.Length)
        } finally { $stream.Dispose() }
        return $true
    } catch [IO.IOException] { return $false }
}

function Get-EmaValue([object[]]$bars, [int]$period) {
    if ($null -eq $bars -or $bars.Count -lt 3) { return $null }
    $alpha = 2.0 / ($period + 1.0)
    $ema = [double]$bars[0].Close
    foreach ($bar in $bars) { $ema = ([double]$bar.Close * $alpha) + ($ema * (1.0 - $alpha)) }
    return $ema
}

function Get-ObservedTick([object]$samples) {
    $tick = $null
    for ($i=1; $i -lt $samples.Count; $i++) {
        $diff = [Math]::Abs([double]$samples[$i].Price - [double]$samples[$i-1].Price)
        if ($diff -gt 0 -and ($null -eq $tick -or $diff -lt $tick)) { $tick = $diff }
    }
    if ($null -eq $tick -or $tick -le 0) { return 1.0 }
    return [double]$tick
}

function Get-Median([double[]]$values) {
    if ($null -eq $values -or $values.Count -eq 0) { return 0.0 }
    $sorted = @($values | Sort-Object)
    $mid = [Math]::Floor($sorted.Count / 2)
    if (($sorted.Count % 2) -eq 0) { return ([double]$sorted[$mid-1] + [double]$sorted[$mid]) / 2.0 }
    return [double]$sorted[$mid]
}

function Convert-LiveBars([object[]]$bars, [int]$minutes, [double]$currentVwap = 0) {
    if ($null -eq $bars -or $bars.Count -eq 0) { return @() }
    $groups = [ordered]@{}
    foreach ($bar in $bars) {
        $rawTime = if ($null -ne $bar.ts) { [string]$bar.ts } elseif ($null -ne $bar.Key) { [string]$bar.Key } else { "" }
        try { $at = [DateTime]::Parse($rawTime) } catch { continue }
        $open = if ($null -ne $bar.o) { [double]$bar.o } else { [double]$bar.Open }
        $high = if ($null -ne $bar.h) { [double]$bar.h } else { [double]$bar.High }
        $low = if ($null -ne $bar.l) { [double]$bar.l } else { [double]$bar.Low }
        $close = if ($null -ne $bar.c) { [double]$bar.c } else { [double]$bar.Close }
        $volume = if ($null -ne $bar.v) { [double]$bar.v } else { [double]$bar.Volume }
        $bucketMinute = [Math]::Floor($at.Minute / $minutes) * $minutes
        $bucket = [DateTime]::new($at.Year,$at.Month,$at.Day,$at.Hour,$bucketMinute,0)
        $key = $bucket.ToString("yyyy-MM-dd HH:mm:ss")
        if (-not $groups.Contains($key)) {
            $groups[$key] = [pscustomobject]@{
                ts=$key; t=$bucket.ToString("HH:mm"); o=$open; h=$high;
                l=$low; c=$close; v=$volume; vwap=$currentVwap
            }
        } else {
            $x = $groups[$key]
            $x.h = [Math]::Max([double]$x.h,$high)
            $x.l = [Math]::Min([double]$x.l,$low)
            $x.c = $close
            $x.v = [double]$x.v + $volume
            $x.vwap = $currentVwap
        }
    }
    return @($groups.Values | Select-Object -Last 180)
}

function Get-MarketTimeBand([DateTime]$at) {
    $clock = $at.TimeOfDay
    if ($clock -lt [TimeSpan]::Parse("09:00:00")) { return "寄り前" }
    if ($clock -lt [TimeSpan]::Parse("09:15:00")) { return "9時00分から9時15分・OR形成" }
    if ($clock -lt [TimeSpan]::Parse("10:00:00")) { return "9時15分から10時・初動" }
    if ($clock -lt [TimeSpan]::Parse("10:30:00")) { return "10時から10時30分・反転注意" }
    if ($clock -le [TimeSpan]::Parse("11:30:00")) { return "10時30分から前引け" }
    if ($clock -lt [TimeSpan]::Parse("12:30:00")) { return "昼休み" }
    if ($clock -lt [TimeSpan]::Parse("13:00:00")) { return "12時30分から13時・後場初動" }
    if ($clock -lt [TimeSpan]::Parse("14:00:00")) { return "13時から14時" }
    if ($clock -lt [TimeSpan]::Parse("15:00:00")) { return "14時から15時・方向確認" }
    if ($clock -le [TimeSpan]::Parse("15:30:00")) { return "15時から大引け・需給注意" }
    return "ザラバ終了"
}

function Get-UnderRatioAt([object]$samples, [DateTime]$cutoff) {
    $baseline = $null
    foreach ($sample in $samples) {
        if ($sample.At -le $cutoff) { $baseline = $sample.UnderRatio } else { break }
    }
    return $baseline
}

function Get-PriceAt([object]$samples, [DateTime]$cutoff) {
    $baseline = $null
    foreach ($sample in $samples) {
        if ($sample.At -le $cutoff) { $baseline = $sample.Price } else { break }
    }
    return $baseline
}

function Get-TextValue($value) {
    if ($null -eq $value -or $value -is [System.Array]) { return "" }
    return ([string]$value).Trim()
}

function Get-IrMaterialAssessment([string]$title) {
    $text = ([string]$title).Trim()
    $score = 0
    $label = "公式IR"
    $blocked = $false
    if ($text -match '下方修正|減配|無配|第三者割当|新株予約権|希薄化|継続企業の前提|監理銘柄|債務超過') {
        $blocked = $true; $label = "悪材料・希薄化警戒"
    } elseif ($text -match '公開買付|ＴＯＢ|TOB|ＭＢＯ|MBO') {
        $score = 35; $label = "TOB/MBO"
    } elseif ($text -match '上方修正|上方予想修正') {
        $score = 28; $label = "上方修正"
    } elseif ($text -match '増配|記念配当') {
        $score = 25; $label = "増配"
    } elseif ($text -match '自己株式.*取得|自社株買い') {
        $score = 25; $label = "自社株買い"
    } elseif ($text -match '承認|採択|大型受注|受注獲得|契約締結|販売許可') {
        $score = 18; $label = "承認・受注・契約"
    } elseif ($text -match '資本業務提携|業務提携|共同開発') {
        $score = 15; $label = "提携・共同開発"
    } elseif ($text -match '業績予想.*修正|決算短信|決算補足') {
        $score = 5; $label = "決算・業績修正（内容確認）"
    }
    return [pscustomobject]@{ score=$score; label=$label; blocked=$blocked }
}

function Get-TdnetDisclosures([DateTime]$date) {
    # 無料のTDnet閲覧サービスを利用する。公式有料APIの代替ではないため、
    # 取得失敗時は推定せず空配列を返し、画面上で「確認待ち」にする。
    $dateText = $date.ToString('yyyyMMdd')
    $base = 'https://www.release.tdnet.info/inbs/'
    $urls = @()
    try {
        $main = Invoke-WebRequest -UseBasicParsing -TimeoutSec 15 -Uri ($base+'I_main_00.html')
        foreach($match in [regex]::Matches([string]$main.Content,'(?i)(?:src|href)=["'']([^"'']*I_list_[^"'']+\.html[^"'']*)')) {
            $href = [Net.WebUtility]::HtmlDecode($match.Groups[1].Value)
            if($href -notmatch '^https?://'){ $href = $base + $href.TrimStart('./') }
            $urls += $href
        }
    } catch {}
    for($page=1;$page -le 10;$page++) {
        $urls += ($base + ('I_list_{0:D3}_{1}.html' -f $page,$dateText))
    }
    $found = @{}
    foreach($url in @($urls|Select-Object -Unique)) {
        try { $html = [string](Invoke-WebRequest -UseBasicParsing -TimeoutSec 15 -Uri $url).Content } catch { continue }
        foreach($rowMatch in [regex]::Matches($html,'(?is)<tr\b[^>]*>(.*?)</tr>')) {
            $rowHtml = $rowMatch.Groups[1].Value
            $cells = @([regex]::Matches($rowHtml,'(?is)<td\b[^>]*>(.*?)</td>')|ForEach-Object{
                [Net.WebUtility]::HtmlDecode(([regex]::Replace($_.Groups[1].Value,'<[^>]+>',' '))) -replace '\s+',' '
            }|ForEach-Object{$_.Trim()})
            if($cells.Count -lt 3){continue}
            $plain = ($cells -join ' | ')
            $timeMatch = [regex]::Match($plain,'(?<!\d)(\d{2}:\d{2})(?!\d)')
            $codeMatch = [regex]::Match($plain,'(?<![0-9A-Z])([0-9]{4}|[0-9]{3}[A-Z])(?![0-9A-Z])')
            if(-not $timeMatch.Success -or -not $codeMatch.Success){continue}
            $title = @($cells|Where-Object{$_.Length -ge 8 -and $_ -notmatch '^\d{2}:\d{2}$' -and $_ -notmatch '^([0-9]{4}|[0-9]{3}[A-Z])$'}|Sort-Object Length -Descending|Select-Object -First 1)[0]
            if([string]::IsNullOrWhiteSpace($title)){continue}
            $link = $url
            $pdfMatch = [regex]::Match($rowHtml,'(?is)href=["'']([^"'']+\.pdf[^"'']*)')
            if($pdfMatch.Success){
                $link=[Net.WebUtility]::HtmlDecode($pdfMatch.Groups[1].Value)
                if($link -notmatch '^https?://'){ $link=$base+$link.TrimStart('./') }
            }
            $key=$codeMatch.Groups[1].Value+'|'+$timeMatch.Groups[1].Value+'|'+$title
            $found[$key]=[pscustomobject]@{code=$codeMatch.Groups[1].Value;time=$timeMatch.Groups[1].Value;title=$title;url=$link}
        }
    }
    return @($found.Values|Sort-Object time -Descending)
}

function Start-LocalJsonBridge([string]$jsonFile, [int]$port = 28580) {
    return Start-Job -Name ("MS2_JSON_BRIDGE_" + $PID) -ArgumentList $jsonFile,$port -ScriptBlock {
        param($JsonFile,$Port)
        $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,[int]$Port)
        $utf8 = [Text.UTF8Encoding]::new($false)
        try {
            $listener.Start()
            while ($true) {
                $client = $listener.AcceptTcpClient()
                try {
                    $stream = $client.GetStream()
                    $reader = [IO.StreamReader]::new($stream,[Text.Encoding]::ASCII,$false,1024,$true)
                    $requestLine = $reader.ReadLine()
                    while (($line = $reader.ReadLine()) -ne $null -and $line -ne "") {}
                    $method = if ($requestLine) { ($requestLine -split ' ')[0] } else { "GET" }
                    if ($method -eq "OPTIONS") {
                        $bodyBytes = [byte[]]@()
                        $status = "204 No Content"
                        $contentType = "text/plain"
                    } elseif (Test-Path $JsonFile) {
                        $bodyBytes = $utf8.GetBytes([IO.File]::ReadAllText($JsonFile,[Text.Encoding]::UTF8))
                        $status = "200 OK"
                        $contentType = "application/json; charset=utf-8"
                    } else {
                        $bodyBytes = $utf8.GetBytes('{"status":"waiting"}')
                        $status = "503 Service Unavailable"
                        $contentType = "application/json; charset=utf-8"
                    }
                    $headers = "HTTP/1.1 $status`r`nContent-Type: $contentType`r`nContent-Length: $($bodyBytes.Length)`r`nCache-Control: no-store`r`nAccess-Control-Allow-Origin: *`r`nAccess-Control-Allow-Methods: GET, OPTIONS`r`nAccess-Control-Allow-Headers: *`r`nAccess-Control-Allow-Private-Network: true`r`nConnection: close`r`n`r`n"
                    $headerBytes = [Text.Encoding]::ASCII.GetBytes($headers)
                    $stream.Write($headerBytes,0,$headerBytes.Length)
                    if ($bodyBytes.Length -gt 0) { $stream.Write($bodyBytes,0,$bodyBytes.Length) }
                    $stream.Flush()
                } catch {} finally { $client.Close() }
            }
        } finally { $listener.Stop() }
    }
}

function Invoke-ExcelCom {
    param(
        [Parameter(Mandatory=$true)][scriptblock]$Action,
        [string]$Label = "Excel操作",
        [int]$Retries = 240,
        [int]$DelayMilliseconds = 250
    )
    for ($attempt = 1; $attempt -le $Retries; $attempt++) {
        try { return (& $Action) }
        catch {
            $errorCode = $_.Exception.HResult
            if ($null -ne $_.Exception.InnerException) { $errorCode = $_.Exception.InnerException.HResult }
            $excelIsBusy = ($errorCode -eq -2147418111 -or $errorCode -eq -2147417846 -or $errorCode -eq -2146777998)
            if ($excelIsBusy -and $attempt -lt $Retries) {
                if ($attempt -eq 1) {
                    Write-Host ($Label + "：ExcelのRSS更新完了を待っています...") -ForegroundColor Yellow
                }
                Start-Sleep -Milliseconds $DelayMilliseconds
                continue
            }
            throw
        }
    }
    throw ($Label + "：Excelが応答しません。数秒後にもう一度実行してください。")
}

if (-not (Test-Path $WatchlistPath)) { throw "watchlist_100.json がありません: $WatchlistPath" }
$watch = Get-Content -Raw -Encoding UTF8 $WatchlistPath | ConvertFrom-Json
$stocks = @($watch.stocks.PSObject.Properties | ForEach-Object {
    [pscustomobject]@{ Name=$_.Name; Ticker=$_.Value.ticker; Sector=$_.Value.sector }
} | Select-Object -First 100)
if ($stocks.Count -ne 100) { throw "監視銘柄は100件必要です。現在: $($stocks.Count)件" }

try { $excel = [Runtime.InteropServices.Marshal]::GetActiveObject("Excel.Application") }
catch { throw "RSS接続済みのExcelが見つかりません。MarketSpeed IIへログインし、ExcelのRSSタブで接続してから実行してください。" }

$book = $null
$openBookNames = @()
foreach ($candidate in $excel.Workbooks) {
    $openBookNames += [string]$candidate.Name
    if ($candidate.Name -ieq $WorkbookName) { $book = $candidate; break }
}
if ($null -eq $book) {
    foreach ($candidate in $excel.Workbooks) {
        if ($candidate.Name -like "Kioxia_MS2_RSS_Live_Signals*.xlsx") { $book = $candidate; break }
    }
}
if ($null -eq $book) {
    foreach ($candidate in $excel.Workbooks) {
        try {
            if ($null -ne $candidate.Worksheets.Item("DASHBOARD")) { $book = $candidate; break }
        } catch {}
    }
}
if ($null -eq $book) {
    $names = if ($openBookNames.Count -gt 0) { $openBookNames -join ", " } else { "認識なし" }
    throw "$WorkbookName を認識できません。Excelで認識したブック: $names"
}
Write-Host ("接続ブック: " + $book.Name) -ForegroundColor Green
Start-Sleep -Milliseconds 500

$sheet = $null
try {
    $sheet = Invoke-ExcelCom -Label "100銘柄RSSシート確認" -Action { $book.Worksheets.Item("100銘柄RSS") }
} catch {
    $sheet = Invoke-ExcelCom -Label "100銘柄RSSシート作成" -Action { $book.Worksheets.Add() }
    Invoke-ExcelCom -Label "100銘柄RSSシート命名" -Action { $sheet.Name = "100銘柄RSS" } | Out-Null
}
Invoke-ExcelCom -Label "画面更新停止" -Action { $excel.ScreenUpdating = $false } | Out-Null
$headers = @("順位","コード","会社名","分類","現在値","時刻","前日終値","前日比率","出来高","VWAP","買気配","売気配","買気配数量","売気配数量","売成行","買成行","OVER","UNDER","歩み1","歩み1時刻","歩み2","歩み2時刻","歩み3","歩み3時刻","歩み4","歩み4時刻","信用売残","信用売残前週比","信用買残","信用買残前週比","信用倍率","当日基準値","特別売気配","特別買気配","始値")
for ($c=0; $c -lt $headers.Count; $c++) {
    $headerColumn = $c + 1
    $headerText = [string]$headers[$c]
    Invoke-ExcelCom -Label "見出し設定" -Action { $sheet.Cells.Item(1,$headerColumn).Value2 = $headerText } | Out-Null
}
$items = @("現在値","現在値詳細時刻","前日終値","前日比率","出来高","出来高加重平均","最良買気配値","最良売気配値","最良買気配数量1","最良売気配数量1","売成行数量","買成行数量","OVER気配数量","UNDER気配数量","歩み1","歩み1詳細時刻","歩み2","歩み2詳細時刻","歩み3","歩み3詳細時刻","歩み4","歩み4詳細時刻","信用売残","信用売残前週比","信用買残","信用買残前週比","信用倍率","当日基準値","特別売気配フラグ","特別買気配フラグ","始値")
$formulaColumns = @("E","F","G","H","I","J","K","L","M","N","O","P","Q","R","S","T","U","V","W","X","Y","Z","AA","AB","AC","AD","AE","AF","AG","AH","AI")
for ($i=0; $i -lt $stocks.Count; $i++) {
    $row = $i + 2; $stock = $stocks[$i]
    $rankText = [string]($i + 1)
    $tickerText = [string]$stock.Ticker
    $nameText = [string]$stock.Name
    $sectorText = [string]$stock.Sector
    Invoke-ExcelCom -Label "順位設定" -Action { $sheet.Cells.Item($row,1).Value2 = $rankText } | Out-Null
    Invoke-ExcelCom -Label "コード設定" -Action { $sheet.Cells.Item($row,2).Value2 = $tickerText } | Out-Null
    Invoke-ExcelCom -Label "会社名設定" -Action { $sheet.Cells.Item($row,3).Value2 = $nameText } | Out-Null
    Invoke-ExcelCom -Label "分類設定" -Action { $sheet.Cells.Item($row,4).Value2 = $sectorText } | Out-Null
    for ($j=0; $j -lt $items.Count; $j++) {
        $cellAddress = $formulaColumns[$j] + [string]$row
        $formulaText = '=RssMarket("' + [string]$stock.Ticker + '","' + [string]$items[$j] + '")'
        Invoke-ExcelCom -Label ("RSS式設定 " + $cellAddress) -Action { $sheet.Range($cellAddress).FormulaLocal = [string]$formulaText } | Out-Null
    }
}
Invoke-ExcelCom -Label "見出し強調" -Action { $sheet.Rows.Item(1).Font.Bold = $true } | Out-Null
Invoke-ExcelCom -Label "フィルター設定" -Action { $sheet.Range("A1:AI101").AutoFilter() } | Out-Null
Invoke-ExcelCom -Label "列幅設定" -Action { $sheet.Range("A:AI").ColumnWidth = 13 } | Out-Null
Invoke-ExcelCom -Label "会社名列幅設定" -Action { $sheet.Range("C:D").ColumnWidth = 28 } | Out-Null
Invoke-ExcelCom -Label "RSSシート非表示" -Action { $sheet.Visible = 0 } | Out-Null
Invoke-ExcelCom -Label "画面更新再開" -Action { $excel.ScreenUpdating = $true } | Out-Null

# キオクシア夜間PTS（JNX）は東証データと混ぜず、専用行で取得する。
$jnxSheet = $null
try {
    $jnxSheet = Invoke-ExcelCom -Label "JNXシート確認" -Action { $book.Worksheets.Item("KIOXIA_JNX") }
} catch {
    $jnxSheet = Invoke-ExcelCom -Label "JNXシート作成" -Action { $book.Worksheets.Add() }
    Invoke-ExcelCom -Label "JNXシート命名" -Action { $jnxSheet.Name = "KIOXIA_JNX" } | Out-Null
}
$jnxHeaders = @("コード","現在値","時刻","前日終値","前日比率","出来高","VWAP","買気配","売気配","買数量","売数量","OVER","UNDER","歩み1","歩み1時刻","現在日付")
$jnxItems = @("現在値","現在値詳細時刻","前日終値","前日比率","出来高","出来高加重平均","最良買気配値","最良売気配値","最良買気配数量1","最良売気配数量1","OVER気配数量","UNDER気配数量","歩み1","歩み1詳細時刻","現在日付")
for ($c=0; $c -lt $jnxHeaders.Count; $c++) {
    $jnxCol = $c + 1
    $jnxHeader = [string]$jnxHeaders[$c]
    Invoke-ExcelCom -Label "JNX見出し設定" -Action { $jnxSheet.Cells.Item(1,$jnxCol).Value2 = $jnxHeader } | Out-Null
}
for ($i=0; $i -lt $stocks.Count; $i++) {
    $jnxRow = $i + 2
    $jnxTicker = (([string]$stocks[$i].Ticker) -replace '\.T$','') + '.JNX'
    Invoke-ExcelCom -Label "JNXコード設定" -Action { $jnxSheet.Cells.Item($jnxRow,1).Value2 = [string]$jnxTicker } | Out-Null
    for ($j=0; $j -lt $jnxItems.Count; $j++) {
        $jnxCol = $j + 2
        $jnxFormula = '=RssMarket("' + [string]$jnxTicker + '","' + [string]$jnxItems[$j] + '")'
        Invoke-ExcelCom -Label "JNX RSS式設定" -Action { $jnxSheet.Cells.Item($jnxRow,$jnxCol).FormulaLocal = [string]$jnxFormula } | Out-Null
    }
}
Invoke-ExcelCom -Label "JNX見出し強調" -Action { $jnxSheet.Rows.Item(1).Font.Bold = $true } | Out-Null
Invoke-ExcelCom -Label "JNX列幅設定" -Action { $jnxSheet.Range("A:P").ColumnWidth = 14 } | Out-Null
Invoke-ExcelCom -Label "JNXシート非表示" -Action { $jnxSheet.Visible = 0 } | Out-Null

$dataRoot = Join-Path $PSScriptRoot "records"
New-Item -ItemType Directory -Force -Path $dataRoot | Out-Null
$holdHistoryPath = Join-Path $PSScriptRoot "overnight_hold_history.csv"
$holdStatsPath = Join-Path $PSScriptRoot "overnight_hold_stats.json"
$actualFillsPath = Join-Path $PSScriptRoot "overnight_actual_fills.csv"
$auditV2Path = Join-Path $PSScriptRoot "overnight_hold_results_v2.csv"
$holdHistoryHeader = "decision_date,finalized_at,rank,ticker,name,side,hold_score,reference_price_1525,entry_close_price,entry_date,evaluation_date,next_open,next_close,next_high,next_low,return_open_pct,return_close_pct,mfe_pct,mae_pct,result,status"
Ensure-Csv $holdHistoryPath $holdHistoryHeader
Ensure-Csv $actualFillsPath "decision_date,ticker,side,actual_fill_price,actual_fill_time,quantity,fee_yen,note"
Ensure-Csv $auditV2Path "decision_date,rank,ticker,name,side,model_version,snapshot_sha256,reference_price_1525,actual_fill_price,fill_source,cost_bps,benchmark,next_trade_date,next_open,next_high,next_low,next_close,return_open_pct,return_close_pct,excess_open_pct,excess_close_pct,mfe_pct,mae_pct,result,missing_reason"
$regimePath = Join-Path (Split-Path $PSScriptRoot -Parent) "investor_regime.json"
if(-not (Test-Path $regimePath)){
    $regimePath = Join-Path $PSScriptRoot "investor_regime.json"
}
$investorRegime = $null
try { if(Test-Path $regimePath){$investorRegime=Get-Content -Raw -Encoding UTF8 $regimePath|ConvertFrom-Json} } catch {}
$statsScript = Join-Path $PSScriptRoot "BUILD_KIOXIA_TIME_STATS.ps1"
$statsJsonPath = Join-Path $PSScriptRoot "kioxia_time_stats.json"
if (Test-Path $statsScript) {
    try { & $statsScript -RecordsRoot $dataRoot -OutputJson $statsJsonPath -OutputCsv (Join-Path $PSScriptRoot "kioxia_time_stats.csv") }
    catch { Write-Host ("時間帯統計の更新を保留: "+$_.Exception.Message) -ForegroundColor Yellow }
}
$kioxiaStats = $null
if (Test-Path $statsJsonPath) {
    try { $kioxiaStats = Get-Content -Raw -Encoding UTF8 $statsJsonPath | ConvertFrom-Json }
    catch { Write-Host "時間帯統計JSONを読み込めません。統計は表示せず監視を続けます。" -ForegroundColor Yellow }
}
$jsonPath = Join-Path $PSScriptRoot "live_ms2.json"
$cockpitJsonPath = Join-Path (Split-Path $PSScriptRoot -Parent) "live_ms2.json"
$htmlPath = Join-Path $PSScriptRoot "AI_Cockpit_MS2_LIVE.html"
$publicCockpitUrl = "https://infoyuusuke-afk.github.io/trade-cockpit/?live=1"
$speaker = New-Object -ComObject SAPI.SpVoice
$previous = @{}
$history = @{}
$seenTicks = @{}
$creditSaved = @{}
$orHigh = @{}
$orLow = @{}
$or5High = @{}
$or5Low = @{}
$minuteBars = @{}
$currentMinuteBars = @{}
$dayHigh = @{}
$dayLow = @{}
$pmAboveSince = @{}
$pmBelowSince = @{}
$lastSignal = @{}
$lastSpoken = @{}
$lastHoldSpoken = @{}
$loggedSignals = @{}
$kioFlowCandidate = ""
$kioFlowCandidateSince = Get-Date
$lastKioFlowSpoken = ""
$lastKioFlowSpokenAt = Get-Date "2000-01-01"
$preopenHistory = @{}
$preopenState = @{}
$lastPreopenVoice = ""
$lastOpenDecisionVoice = ""
$lastPtsBand = 0
$lastPtsVoiceAt = Get-Date "2000-01-01"
$tdnetDisclosures = @()
$lastTdnetFetchAt = Get-Date "2000-01-01"
$tdnetStatus = "取得待ち"
$lastIrVoiceCodes = @{}
$lastSnapshotAt = Get-Date "2000-01-01"
$activeDay = (Get-Date).ToString("yyyy-MM-dd")
$loadedHoldDay = ""
$holdFinalized = $false
$holdFinalizedAt = $null
$holdEntryCaptured = $false
$finalHoldTop5 = @()
$holdHistory = @()
try { $holdHistory = @(Import-Csv -Encoding UTF8 $holdHistoryPath) } catch { $holdHistory = @() }
$holdStats = Get-OvernightHoldStats $holdHistory
$browserOpened = $false
$bridgeJob = Start-LocalJsonBridge $jsonPath 28580

Write-Host "100銘柄のRSS監視を開始しました。誤値は保存しません。終了は Ctrl+C。" -ForegroundColor Cyan
Write-Host "統一AIコクピット: $publicCockpitUrl" -ForegroundColor Cyan
Write-Host "予備画面: $htmlPath" -ForegroundColor DarkGray
Write-Host "AIコクピット連携: http://127.0.0.1:28580/live_ms2.json" -ForegroundColor Cyan
$speaker.Speak("キオクシアを含む、100銘柄の音声監視を開始しました。",1) | Out-Null

try {
    while ($true) {
        # RssMarket関数はアドイン側から自動更新されるため、2秒ごとの強制再計算は行わない。
        # 強制再計算するとRSS更新と衝突し、Excel固有の0x800AC472が発生する。
        $now = Get-Date
        if ($StopAfterClose -and $now.TimeOfDay -ge [TimeSpan]::Parse("23:59:00")) {
            if (Test-Path $statsScript) {
                try { & $statsScript -RecordsRoot $dataRoot -OutputJson $statsJsonPath -OutputCsv (Join-Path $PSScriptRoot "kioxia_time_stats.csv") }
                catch { Write-Host ("引け後統計の更新を保留: "+$_.Exception.Message) -ForegroundColor Yellow }
            }
            $speaker.Speak("東証と夜間PTSの記録を終了し、キオクシアの時間帯統計を更新しました。",1) | Out-Null
            break
        }
        if ($now.ToString("yyyy-MM-dd") -ne $activeDay) {
            $activeDay=$now.ToString("yyyy-MM-dd")
            $previous=@{}; $history=@{}; $preopenHistory=@{}; $preopenState=@{}; $seenTicks=@{}; $creditSaved=@{}; $orHigh=@{}; $orLow=@{}; $or5High=@{}; $or5Low=@{}; $minuteBars=@{}; $currentMinuteBars=@{}; $dayHigh=@{}; $dayLow=@{}; $pmAboveSince=@{}; $pmBelowSince=@{}; $lastSignal=@{}; $lastHoldSpoken=@{}; $loggedSignals=@{}
            $kioFlowCandidate=""; $lastKioFlowSpoken=""; $lastKioFlowSpokenAt=Get-Date "2000-01-01"
            $lastPreopenVoice=""; $lastOpenDecisionVoice=""
            $lastPtsBand=0; $lastPtsVoiceAt=Get-Date "2000-01-01"
            $tdnetDisclosures=@(); $lastTdnetFetchAt=Get-Date "2000-01-01"; $tdnetStatus="取得待ち"; $lastIrVoiceCodes=@{}
            $loadedHoldDay=""; $holdFinalized=$false; $holdFinalizedAt=$null; $holdEntryCaptured=$false; $finalHoldTop5=@()
        }
        $dayDir = Join-Path $dataRoot $now.ToString("yyyy-MM-dd")
        New-Item -ItemType Directory -Force -Path $dayDir | Out-Null
        $tickCsv = Join-Path $dayDir "ticks.csv"
        $supplyCsv = Join-Path $dayDir "under_over.csv"
        $snapshotCsv = Join-Path $dayDir "market_snapshots.csv"
        $preopenCsv = Join-Path $dayDir "preopen.csv"
        $creditCsv = Join-Path $dayDir "credit_supply.csv"
        $ptsCsv = Join-Path $dayDir "kioxia_jnx_pts.csv"
        $irPtsCsv = Join-Path $dayDir "ir_pts_snapshots.csv"
        $signalCsv = Join-Path $dayDir "trade_signals.csv"
        $holdFinalCsv = Join-Path $dayDir "overnight_hold_final.csv"
        $holdFinalMarker = Join-Path $dayDir "overnight_hold_finalized.json"
        $holdImmutableJson = Join-Path $dayDir "overnight_hold_immutable.json"
        Ensure-Csv $tickCsv "captured_at,ticker,name,exchange_time,price,direction_estimate,bid,ask,note"
        Ensure-Csv $supplyCsv "captured_at,ticker,name,price,over,under,under_ratio,over_under_change,vwap"
        Ensure-Csv $snapshotCsv "captured_at,ticker,name,price,volume,vwap,bid,ask,bid_qty,ask_qty,market_sell,market_buy,over,under"
        Ensure-Csv $preopenCsv "captured_at,ticker,name,reference_price,quote_center,gap_pct,bid,ask,bid_qty,ask_qty,market_sell,market_buy,market_imbalance,over,under,under_ratio,quote_change_1m_pct,quote_change_5m_pct,special_sell,special_buy,score,plan"
        Ensure-Csv $creditCsv "captured_at,ticker,name,credit_sell,credit_sell_weekly_change,credit_buy,credit_buy_weekly_change,credit_ratio"
        Ensure-Csv $ptsCsv "captured_at,ticker,name,pts_date,exchange_time,price,tse_close,gap_pct,volume,tse_volume,pts_volume_ratio,turnover,vwap,bid,ask,spread_pct,bid_qty,ask_qty,over,under,under_ratio,last_tick,bias_score,expectation_score,stance"
        Ensure-Csv $irPtsCsv "captured_at,code,ticker,name,disclosure_time,material_label,material_score,title,official_url,pts_price,tse_close,gap_pct,turnover,spread_pct,under_ratio,pts_score,total_score,judgement"
        Ensure-Csv $signalCsv "captured_at,ticker,name,signal,strategy,signal_bar,entry,stop,target1,target2,market_state,breadth_pct,sector_breadth_pct,hold_signal,hold_score"
        Ensure-Csv $holdFinalCsv "finalized_at,rank,ticker,name,hold_signal,hold_score,reference_price_1525,vwap,or15_high,or15_low,pm_above_minutes,pm_below_minutes,close_location_pct,market_state,breadth_pct,sector_breadth_pct,flow_bias,under_ratio"
        if($loadedHoldDay -ne $activeDay){
            $loadedHoldDay=$activeDay
            try {
                $savedFinal=@(Import-Csv -Encoding UTF8 $holdFinalCsv | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_.ticker) })
                if($savedFinal.Count -gt 0){
                    $finalHoldTop5=@($savedFinal|ForEach-Object{
                        $_|Add-Member -NotePropertyName price -NotePropertyValue $_.reference_price_1525 -Force
                        $_|Add-Member -NotePropertyName or_high -NotePropertyValue $_.or15_high -Force
                        $_|Add-Member -NotePropertyName or_low -NotePropertyValue $_.or15_low -Force
                        $_
                    })
                }
            } catch {}
            if(Test-Path $holdFinalMarker){
                try{$marker=Get-Content -Raw -Encoding UTF8 $holdFinalMarker|ConvertFrom-Json;$holdFinalized=$true;$holdFinalizedAt=[string]$marker.finalized_at}catch{}
            }
            try { $holdHistory=@(Import-Csv -Encoding UTF8 $holdHistoryPath) } catch { $holdHistory=@() }
            $holdStats=Get-OvernightHoldStats $holdHistory
        }

        if(($now-$lastTdnetFetchAt).TotalSeconds -ge 120) {
            try {
                $freshTdnet = @(Get-TdnetDisclosures $now)
                if($freshTdnet.Count -gt 0){$tdnetDisclosures=$freshTdnet; $tdnetStatus=("TDnet確認済み "+$freshTdnet.Count+"件")}
                else{$tdnetStatus="TDnet取得0件・確認待ち"}
            } catch {
                $tdnetStatus="TDnet取得失敗・推定禁止"
            }
            $lastTdnetFetchAt=$now
        }

        $valuePacket = Invoke-ExcelCom -Label "リアルタイム値取得" -Action {
            [pscustomobject]@{ Data = $sheet.Range("E2:AI101").Value2 }
        }
        $values = $valuePacket.Data
        $jnxPacket = Invoke-ExcelCom -Label "JNXリアルタイム値取得" -Action {
            [pscustomobject]@{ Data = $jnxSheet.Range("B2:P101").Value2 }
        }
        $jnxValues = $jnxPacket.Data
        $results = @()
        $validCount = 0
        $preopenQuoteCount = 0
        $snapshotDue = (($now - $lastSnapshotAt).TotalSeconds -ge $SnapshotSeconds)

        for ($i=0; $i -lt $stocks.Count; $i++) {
            $r=$i+1; $s=$stocks[$i]; $ticker=$s.Ticker
            $price=Get-SafeNumber (Get-TableValue $values $r 1) 0.01 10000000
            $volume=Get-SafeNumber (Get-TableValue $values $r 5) 0 1000000000000
            $vwap=Get-SafeNumber (Get-TableValue $values $r 6) 0 10000000
            $bid=Get-SafeNumber (Get-TableValue $values $r 7) 0 10000000
            $ask=Get-SafeNumber (Get-TableValue $values $r 8) 0 10000000
            $bidQty=Get-SafeNumber (Get-TableValue $values $r 9) 0 1000000000000
            $askQty=Get-SafeNumber (Get-TableValue $values $r 10) 0 1000000000000
            $marketSell=Get-SafeNumber (Get-TableValue $values $r 11) 0 1000000000000
            $marketBuy=Get-SafeNumber (Get-TableValue $values $r 12) 0 1000000000000
            $over=Get-SafeNumber (Get-TableValue $values $r 13) 0 1000000000000
            $under=Get-SafeNumber (Get-TableValue $values $r 14) 0 1000000000000
            $creditSell=Get-SafeNumber (Get-TableValue $values $r 23) 0 1000000000000
            $creditSellChange=Get-SafeNumber (Get-TableValue $values $r 24) -1000000000000 1000000000000
            $creditBuy=Get-SafeNumber (Get-TableValue $values $r 25) 0 1000000000000
            $creditBuyChange=Get-SafeNumber (Get-TableValue $values $r 26) -1000000000000 1000000000000
            $creditRatio=Get-SafeNumber (Get-TableValue $values $r 27) 0 1000000
            $referencePrice=Get-SafeNumber (Get-TableValue $values $r 28) 0.01 10000000
            $specialSell=Get-TextValue (Get-TableValue $values $r 29)
            $specialBuy=Get-TextValue (Get-TableValue $values $r 30)
            $openPrice=Get-SafeNumber (Get-TableValue $values $r 31) 0.01 10000000
            $clock=$now.TimeOfDay
            $inOr5=($clock -ge [TimeSpan]::Parse("09:00:00") -and $clock -lt [TimeSpan]::Parse("09:05:00"))
            $afterOr5=($clock -ge [TimeSpan]::Parse("09:05:00"))
            $inOr=($clock -ge [TimeSpan]::Parse("09:00:00") -and $clock -lt [TimeSpan]::Parse("09:15:00"))
            $inPreopen=($clock -ge [TimeSpan]::Parse("08:00:00") -and $clock -lt [TimeSpan]::Parse("09:00:00"))
            $afterOr=($clock -ge [TimeSpan]::Parse("09:15:00")); $inSession=(($clock -ge [TimeSpan]::Parse("09:00:00") -and $clock -le [TimeSpan]::Parse("11:30:00")) -or ($clock -ge [TimeSpan]::Parse("12:30:00") -and $clock -le [TimeSpan]::Parse("15:30:00")))

            # Before the opening auction, RSS may leave Current Price blank even
            # though bid/ask and the reference price are already populated.  Do
            # not discard those rows: the pre-open model is driven by the quote.
            $quoteCenter=0.0
            if($bid -gt 0 -and $ask -gt 0){$quoteCenter=($bid+$ask)/2}
            elseif($bid -gt 0){$quoteCenter=$bid}
            elseif($ask -gt 0){$quoteCenter=$ask}
            if($inPreopen -and $quoteCenter -gt 0){$preopenQuoteCount++}
            $reference=if($null -ne $referencePrice -and $referencePrice -gt 0){$referencePrice}else{Get-SafeNumber (Get-TableValue $values $r 3) 0.01 10000000}
            if ($null -eq $price) {
                if($inPreopen -and $quoteCenter -gt 0){$price=$quoteCenter}
                elseif($inPreopen -and $null -ne $reference -and $reference -gt 0){$price=$reference}
                else{continue}
            }
            $validCount++
            if ($null -eq $volume) {$volume=0}; if ($null -eq $vwap) {$vwap=0}; if ($null -eq $bid) {$bid=0}; if ($null -eq $ask) {$ask=0}
            if ($null -eq $bidQty) {$bidQty=0}; if ($null -eq $askQty) {$askQty=0}; if ($null -eq $marketSell) {$marketSell=0}; if ($null -eq $marketBuy) {$marketBuy=0}
            if ($null -eq $over) {$over=0}; if ($null -eq $under) {$under=0}
            $underRatio = if (($over+$under) -gt 0) {$under/($over+$under)} else {0.5}
            $prev = $previous[$ticker]
            $volumeDelta = if ($null -ne $prev) {[Math]::Max(0,$volume-$prev.Volume)} else {0}
            $priceDelta = if ($null -ne $prev) {$price-$prev.Price} else {0}
            $uoChange = if ($null -ne $prev) {$underRatio-$prev.UnderRatio} else {0}

            if ($inOr) {
                if (-not $orHigh.ContainsKey($ticker) -or $price -gt $orHigh[$ticker]) {$orHigh[$ticker]=$price}
                if (-not $orLow.ContainsKey($ticker) -or $price -lt $orLow[$ticker]) {$orLow[$ticker]=$price}
            }
            if ($inOr5) {
                if (-not $or5High.ContainsKey($ticker) -or $price -gt $or5High[$ticker]) {$or5High[$ticker]=$price}
                if (-not $or5Low.ContainsKey($ticker) -or $price -lt $or5Low[$ticker]) {$or5Low[$ticker]=$price}
            }
            if ($clock -ge [TimeSpan]::Parse("09:00:00") -and $clock -le [TimeSpan]::Parse("15:30:00")) {
                if (-not $dayHigh.ContainsKey($ticker) -or $price -gt $dayHigh[$ticker]) {$dayHigh[$ticker]=$price}
                if (-not $dayLow.ContainsKey($ticker) -or $price -lt $dayLow[$ticker]) {$dayLow[$ticker]=$price}
            }

            if (-not $history.ContainsKey($ticker)) {$history[$ticker]=[Collections.ArrayList]::new()}
            $direction = if ($ask -gt 0 -and $price -ge $ask) {"BUY"} elseif ($bid -gt 0 -and $price -le $bid) {"SELL"} elseif ($priceDelta -gt 0) {"BUY"} elseif ($priceDelta -lt 0) {"SELL"} else {"NEUTRAL"}
            [void]$history[$ticker].Add([pscustomobject]@{At=$now;Price=$price;Vwap=$vwap;UnderRatio=$underRatio;Direction=$direction;VolumeDelta=$volumeDelta})
            while ($history[$ticker].Count -gt 0 -and ($now-$history[$ticker][0].At).TotalMinutes -gt 10) {$history[$ticker].RemoveAt(0)}

            if (-not $minuteBars.ContainsKey($ticker)) {$minuteBars[$ticker]=[Collections.ArrayList]::new()}
            $minuteKey=$now.ToString("yyyy-MM-dd HH:mm")
            $building=$currentMinuteBars[$ticker]
            if ($null -eq $building -or $building.Key -ne $minuteKey) {
                if ($null -ne $building) {
                    [void]$minuteBars[$ticker].Add($building)
                    # Keep one full TSE session.  This gives the 15-minute panel enough
                    # history to remain useful in the afternoon without changing the
                    # raw CSV retention policy.
                    while ($minuteBars[$ticker].Count -gt 390) {$minuteBars[$ticker].RemoveAt(0)}
                }
                $building=[pscustomobject]@{Key=$minuteKey;At=$now;Open=$price;High=$price;Low=$price;Close=$price;Volume=0.0}
                $currentMinuteBars[$ticker]=$building
            }
            if ($price -gt $building.High) {$building.High=$price}
            if ($price -lt $building.Low) {$building.Low=$price}
            $building.Close=$price
            $building.Volume=[double]$building.Volume+[double]$volumeDelta

            $crosses=0; $buyFlow=0; $sellFlow=0; $deltas=@()
            for ($h=0; $h -lt $history[$ticker].Count; $h++) {
                $x=$history[$ticker][$h]; if ($x.VolumeDelta -gt 0) {$deltas += $x.VolumeDelta}
                if ($x.Direction -eq "BUY") {$buyFlow += $x.VolumeDelta}; if ($x.Direction -eq "SELL") {$sellFlow += $x.VolumeDelta}
                if ($h -gt 0 -and $x.Vwap -gt 0 -and $history[$ticker][$h-1].Vwap -gt 0) {
                    if ((($x.Price-$x.Vwap)*($history[$ticker][$h-1].Price-$history[$ticker][$h-1].Vwap)) -lt 0) {$crosses++}
                }
            }
            $avgDelta=if ($deltas.Count -gt 2) {($deltas|Measure-Object -Average).Average} else {0}
            $burst=if ($avgDelta -gt 0) {$volumeDelta/$avgDelta} else {0}
            $flowTotal=$buyFlow+$sellFlow; $flowBias=if ($flowTotal -gt 0) {($buyFlow-$sellFlow)/$flowTotal} else {0}
            $historySeconds=if($history[$ticker].Count -gt 1){($now-$history[$ticker][0].At).TotalSeconds}else{0}
            $under1mBase=if($historySeconds -ge 60){Get-UnderRatioAt $history[$ticker] $now.AddMinutes(-1)}else{$null}
            $under5mBase=if($historySeconds -ge 300){Get-UnderRatioAt $history[$ticker] $now.AddMinutes(-5)}else{$null}
            $underChange1m=if($null -ne $under1mBase){$underRatio-$under1mBase}else{$null}
            $underChange5m=if($null -ne $under5mBase){$underRatio-$under5mBase}else{$null}

            $completedBars=@($minuteBars[$ticker])
            $lastBar=if($completedBars.Count -gt 0){$completedBars[-1]}else{$null}
            $ema9=Get-EmaValue $completedBars 9
            $ema20=Get-EmaValue $completedBars 20
            $emaReady=($completedBars.Count -ge 20)
            $barBurst=0.0; $atr1m=0.0; $medianBody=0.0; $chaseGuard=$false; $observedTick=Get-ObservedTick $history[$ticker]
            if($completedBars.Count -ge 3 -and $null -ne $lastBar){
                $priorBars=@($completedBars|Select-Object -SkipLast 1|Select-Object -Last 10)
                $avgBarVolume=($priorBars|Measure-Object -Property Volume -Average).Average
                if($avgBarVolume -gt 0){$barBurst=[double]$lastBar.Volume/[double]$avgBarVolume}
                $ranges=@($completedBars|Select-Object -Last 14|ForEach-Object{[double]$_.High-[double]$_.Low})
                if($ranges.Count -gt 0){$atr1m=($ranges|Measure-Object -Average).Average}
                $bodies=@($priorBars|ForEach-Object{[Math]::Abs([double]$_.Close-[double]$_.Open)})
                $medianBody=Get-Median $bodies
                $lastBody=[Math]::Abs([double]$lastBar.Close-[double]$lastBar.Open)
                $tooLong=($medianBody -gt 0 -and $lastBody -gt $medianBody*1.5)
                $tooFar=($atr1m -gt 0 -and $vwap -gt 0 -and [Math]::Abs([double]$lastBar.Close-$vwap) -gt $atr1m)
                $chaseGuard=($tooLong -or $tooFar)
            }
            $trendLong=($vwap -gt 0 -and $null -ne $lastBar -and [double]$lastBar.Close -gt $vwap -and (($emaReady -and $ema9 -gt $ema20) -or (-not $emaReady -and [double]$lastBar.Close -gt [double]$completedBars[0].Close)))
            $trendShort=($vwap -gt 0 -and $null -ne $lastBar -and [double]$lastBar.Close -lt $vwap -and (($emaReady -and $ema9 -lt $ema20) -or (-not $emaReady -and [double]$lastBar.Close -lt [double]$completedBars[0].Close)))

            $gapPct=if($null -ne $reference -and $reference -gt 0 -and $quoteCenter -gt 0){(($quoteCenter/$reference)-1)*100}else{$null}
            $marketTotal=$marketBuy+$marketSell
            $marketImbalance=if($marketTotal -gt 0){($marketBuy-$marketSell)/$marketTotal}else{0}
            $spreadPct=if($null -ne $reference -and $reference -gt 0 -and $bid -gt 0 -and $ask -gt 0){[Math]::Abs($ask-$bid)/$reference*100}else{$null}
            if(-not $preopenHistory.ContainsKey($ticker)){$preopenHistory[$ticker]=[Collections.ArrayList]::new()}
            if($inPreopen -and $quoteCenter -gt 0){
                [void]$preopenHistory[$ticker].Add([pscustomobject]@{At=$now;Price=$quoteCenter})
                while($preopenHistory[$ticker].Count -gt 0 -and ($now-$preopenHistory[$ticker][0].At).TotalMinutes -gt 10){$preopenHistory[$ticker].RemoveAt(0)}
            }
            $quote1mBase=if($preopenHistory[$ticker].Count -gt 1){Get-PriceAt $preopenHistory[$ticker] $now.AddMinutes(-1)}else{$null}
            $quote5mBase=if($preopenHistory[$ticker].Count -gt 1){Get-PriceAt $preopenHistory[$ticker] $now.AddMinutes(-5)}else{$null}
            $quoteChange1m=if($null -ne $quote1mBase -and $quote1mBase -gt 0 -and $quoteCenter -gt 0){(($quoteCenter/$quote1mBase)-1)*100}else{$null}
            $quoteChange5m=if($null -ne $quote5mBase -and $quote5mBase -gt 0 -and $quoteCenter -gt 0){(($quoteCenter/$quote5mBase)-1)*100}else{$null}
            $preopenScore=0.0
            $preopenScore += Limit ($marketImbalance*35) -35 35
            $preopenScore += Limit (($underRatio-0.5)*40) -20 20
            if($null -ne $quoteChange5m){$preopenScore += Limit ($quoteChange5m*4) -20 20}
            $hasSpecialSell=(-not [string]::IsNullOrWhiteSpace($specialSell) -and $specialSell -notin @("0","False","FALSE"))
            $hasSpecialBuy=(-not [string]::IsNullOrWhiteSpace($specialBuy) -and $specialBuy -notin @("0","False","FALSE"))
            $preopenPlan="寄り待ち"
            if($hasSpecialSell){$preopenPlan="特売り・寄り待ち"}
            elseif($hasSpecialBuy){$preopenPlan="特買い・寄り待ち"}
            elseif($null -eq $gapPct -or $quoteCenter -le 0){$preopenPlan="気配不足・見送り"}
            elseif($null -ne $spreadPct -and $spreadPct -gt 1){$preopenPlan="気配幅過大・見送り"}
            elseif([Math]::Abs($gapPct) -ge 5){$preopenPlan="大幅GU/GD・寄り後確認"}
            elseif($preopenScore -ge 15){$preopenPlan="買い準備"}
            elseif($preopenScore -le -15){$preopenPlan="ショート準備"}
            if($inPreopen){
                $preopenState[$ticker]=[pscustomobject]@{Quote=$quoteCenter;GapPct=$gapPct;MarketImbalance=$marketImbalance;QuoteChange5m=$quoteChange5m;Score=$preopenScore;Plan=$preopenPlan;SpecialSell=$hasSpecialSell;SpecialBuy=$hasSpecialBuy;CapturedAt=$now}
            } elseif($preopenState.ContainsKey($ticker)) {
                $savedPreopen=$preopenState[$ticker]
                $quoteCenter=$savedPreopen.Quote; $gapPct=$savedPreopen.GapPct; $marketImbalance=$savedPreopen.MarketImbalance
                $quoteChange5m=$savedPreopen.QuoteChange5m; $preopenScore=$savedPreopen.Score; $preopenPlan=$savedPreopen.Plan
                $hasSpecialSell=$savedPreopen.SpecialSell; $hasSpecialBuy=$savedPreopen.SpecialBuy
            }

            $openDecision="OR15形成待ち"
            if($clock -lt [TimeSpan]::Parse("09:00:00")){$openDecision="寄り前・発注禁止"}
            elseif($clock -lt [TimeSpan]::Parse("09:01:00")){$openDecision="寄り直後60秒待機"}
            elseif($clock -lt [TimeSpan]::Parse("09:15:00")){
                if($hasSpecialSell -or $hasSpecialBuy -or ($null -ne $gapPct -and [Math]::Abs($gapPct) -ge 5)){$openDecision="大幅窓・OR15待ち"}
                elseif($preopenPlan -eq "買い準備" -and $null -ne $openPrice -and $price -ge $openPrice -and ($vwap -le 0 -or $price -ge $vwap) -and $flowBias -ge 0.05 -and $null -ne $underChange1m -and $underChange1m -gt 0){$openDecision="初動買い候補"}
                elseif($preopenPlan -eq "ショート準備" -and $null -ne $openPrice -and $price -le $openPrice -and ($vwap -le 0 -or $price -le $vwap) -and $flowBias -le -0.05 -and $null -ne $underChange1m -and $underChange1m -lt 0){$openDecision="初動ショート候補"}
                else{$openDecision="初動不一致・見送り"}
            }
            $timeBand=Get-MarketTimeBand $now
            $orderflowState="蓄積中"
            if($historySeconds -ge 60){
                if($underRatio -ge 0.54 -and $underChange1m -ge 0.015 -and $flowBias -ge 0.05){$orderflowState="買い優勢"}
                elseif($underRatio -le 0.46 -and $underChange1m -le -0.015 -and $flowBias -le -0.05){$orderflowState="売り優勢"}
                elseif(($underChange1m -gt 0.015 -and $flowBias -lt -0.05) -or ($underChange1m -lt -0.015 -and $flowBias -gt 0.05)){$orderflowState="板・歩み値不一致"}
                else{$orderflowState="均衡"}
            }
            $score=0.0
            if ($vwap -gt 0) {$score += $(if ($price -gt $vwap) {15} else {-15})}
            $score += (Limit (($underRatio-0.5)*75) -15 15)
            $score += (Limit ($flowBias*25) -25 25)
            if ($afterOr -and $orHigh.ContainsKey($ticker) -and $price -gt $orHigh[$ticker]) {$score+=25}
            if ($afterOr -and $orLow.ContainsKey($ticker) -and $price -lt $orLow[$ticker]) {$score-=25}
            if ($barBurst -ge 1.2 -and $null -ne $lastBar) {$score += $(if ([double]$lastBar.Close -gt [double]$lastBar.Open) {10} elseif ([double]$lastBar.Close -lt [double]$lastBar.Open) {-10} else {0})}
            if($inPreopen){$score=$preopenScore}
            $whipsaw=($crosses -ge 2)
            $signal="監視"
            $strategy="条件待ち"
            $rawDirection=""
            $signalBarTime=if($null -ne $lastBar){[string]$lastBar.Key}else{""}
            $entryPrice=$null; $stopPrice=$null; $target1=$null; $target2=$null
            if($inPreopen){$signal=$preopenPlan}
            elseif ($inSession -and $whipsaw) {$signal="往復ピンタ回避"}
            elseif ($openDecision -eq "初動買い候補") {$signal="初動買い候補"}
            elseif ($openDecision -eq "初動ショート候補") {$signal="初動ショート候補"}
            elseif($inSession -and $null -ne $lastBar){
                $bullBar=([double]$lastBar.Close -gt [double]$lastBar.Open)
                $bearBar=([double]$lastBar.Close -lt [double]$lastBar.Open)
                $or5Long=($clock -ge [TimeSpan]::Parse("09:06:00") -and $clock -lt [TimeSpan]::Parse("09:15:00") -and $or5High.ContainsKey($ticker) -and [double]$lastBar.Close -gt [double]$or5High[$ticker] -and $bullBar -and $trendLong -and $flowBias -gt 0.05 -and $barBurst -ge 1.2)
                $or5Short=($clock -ge [TimeSpan]::Parse("09:06:00") -and $clock -lt [TimeSpan]::Parse("09:15:00") -and $or5Low.ContainsKey($ticker) -and [double]$lastBar.Close -lt [double]$or5Low[$ticker] -and $bearBar -and $trendShort -and $flowBias -lt -0.05 -and $barBurst -ge 1.2)
                $or15Long=($afterOr -and $orHigh.ContainsKey($ticker) -and [double]$lastBar.Close -gt [double]$orHigh[$ticker] -and $bullBar -and $trendLong -and $flowBias -gt 0.05 -and $barBurst -ge 1.2)
                $or15Short=($afterOr -and $orLow.ContainsKey($ticker) -and [double]$lastBar.Close -lt [double]$orLow[$ticker] -and $bearBar -and $trendShort -and $flowBias -lt -0.05 -and $barBurst -ge 1.2)
                $pullbackLong=($afterOr -and $orHigh.ContainsKey($ticker) -and [double]$lastBar.Low -le [double]$orHigh[$ticker]*1.001 -and [double]$lastBar.Close -gt [double]$orHigh[$ticker] -and $bullBar -and $trendLong -and $flowBias -gt 0.05)
                $pullbackShort=($afterOr -and $orLow.ContainsKey($ticker) -and [double]$lastBar.High -ge [double]$orLow[$ticker]*0.999 -and [double]$lastBar.Close -lt [double]$orLow[$ticker] -and $bearBar -and $trendShort -and $flowBias -lt -0.05)
                if($chaseGuard -and ($or5Long -or $or15Long)){$signal="押し目待ち";$strategy="飛び乗り防止"}
                elseif($chaseGuard -and ($or5Short -or $or15Short)){$signal="戻り待ち";$strategy="追い売り防止"}
                elseif($or5Long){$rawDirection="BUY";$strategy="OR5初動"}
                elseif($or5Short){$rawDirection="SELL";$strategy="OR5初動"}
                elseif($pullbackLong){$rawDirection="BUY";$strategy="OR15押し目"}
                elseif($pullbackShort){$rawDirection="SELL";$strategy="OR15戻り"}
                elseif($or15Long){$rawDirection="BUY";$strategy="OR15追随"}
                elseif($or15Short){$rawDirection="SELL";$strategy="OR15追随"}
                if(-not [string]::IsNullOrWhiteSpace($rawDirection)){
                    if($rawDirection -eq "BUY"){
                        $entryPrice=[Math]::Max([double]$lastBar.High+$observedTick,$ask)
                        $stopPrice=[double]$lastBar.Low-$observedTick
                    }else{
                        $entryPrice=if($bid -gt 0){[Math]::Min([double]$lastBar.Low-$observedTick,$bid)}else{[double]$lastBar.Low-$observedTick}
                        $stopPrice=[double]$lastBar.High+$observedTick
                    }
                    $risk=[Math]::Abs($entryPrice-$stopPrice)
                    if($risk -gt 0){$target1=if($rawDirection -eq "BUY"){$entryPrice+$risk}else{$entryPrice-$risk};$target2=if($rawDirection -eq "BUY"){$entryPrice+2*$risk}else{$entryPrice-2*$risk}}
                }
            }
            elseif (-not $inSession) {$signal="市場時間外"}

            if($clock -ge [TimeSpan]::Parse("12:30:00") -and $orHigh.ContainsKey($ticker) -and $price -gt $orHigh[$ticker]){
                if(-not $pmAboveSince.ContainsKey($ticker)){$pmAboveSince[$ticker]=$now}
            }else{$pmAboveSince.Remove($ticker)}
            if($clock -ge [TimeSpan]::Parse("12:30:00") -and $orLow.ContainsKey($ticker) -and $price -lt $orLow[$ticker]){
                if(-not $pmBelowSince.ContainsKey($ticker)){$pmBelowSince[$ticker]=$now}
            }else{$pmBelowSince.Remove($ticker)}

            if ($inSession) {
                for ($w=0; $w -lt 4; $w++) {
                    $tickPrice=Get-SafeNumber (Get-TableValue $values $r (15+$w*2)) 0.01 10000000
                    $tickTime=Get-TimeText (Get-TableValue $values $r (16+$w*2))
                    if ($null -eq $tickPrice -or [string]::IsNullOrWhiteSpace($tickTime)) {continue}
                    $tickKey="$ticker|$tickTime|$tickPrice"
                    if (-not $seenTicks.ContainsKey($tickKey)) {
                        $tickDir=if ($ask -gt 0 -and $tickPrice -ge $ask) {"BUY_EST"} elseif ($bid -gt 0 -and $tickPrice -le $bid) {"SELL_EST"} else {"UNKNOWN"}
                        $line=@($now.ToString("yyyy-MM-dd HH:mm:ss.fff"),$ticker,$s.Name,$tickTime,$tickPrice,$tickDir,$bid,$ask,"方向は気配との比較による推定") | ForEach-Object {Escape-Csv $_}
                        Add-Content -Encoding UTF8 -Path $tickCsv -Value ($line -join ',')
                        $seenTicks[$tickKey]=$now
                    }
                }
            }

            if ($snapshotDue -and $inSession) {
                $line=@($now.ToString("yyyy-MM-dd HH:mm:ss"),$ticker,$s.Name,$price,$over,$under,[Math]::Round($underRatio,5),[Math]::Round($uoChange,5),$vwap)|ForEach-Object{Escape-Csv $_}
                Add-Content -Encoding UTF8 -Path $supplyCsv -Value ($line -join ',')
                $line=@($now.ToString("yyyy-MM-dd HH:mm:ss"),$ticker,$s.Name,$price,$volume,$vwap,$bid,$ask,$bidQty,$askQty,$marketSell,$marketBuy,$over,$under)|ForEach-Object{Escape-Csv $_}
                Add-Content -Encoding UTF8 -Path $snapshotCsv -Value ($line -join ',')
                if (-not $creditSaved.ContainsKey($ticker)) {
                    $line=@($now.ToString("yyyy-MM-dd HH:mm:ss"),$ticker,$s.Name,$creditSell,$creditSellChange,$creditBuy,$creditBuyChange,$creditRatio)|ForEach-Object{Escape-Csv $_}
                    Add-Content -Encoding UTF8 -Path $creditCsv -Value ($line -join ',')
                    $creditSaved[$ticker]=$true
                }
            }
            if($snapshotDue -and $inPreopen){
                $line=@($now.ToString("yyyy-MM-dd HH:mm:ss"),$ticker,$s.Name,$reference,$quoteCenter,$gapPct,$bid,$ask,$bidQty,$askQty,$marketSell,$marketBuy,[Math]::Round($marketImbalance*100,2),$over,$under,[Math]::Round($underRatio*100,2),$quoteChange1m,$quoteChange5m,$specialSell,$specialBuy,[Math]::Round($preopenScore,1),$preopenPlan)|ForEach-Object{Escape-Csv $_}
                Add-Content -Encoding UTF8 -Path $preopenCsv -Value ($line -join ',')
            }

            $orHighValue=if($orHigh.ContainsKey($ticker)){$orHigh[$ticker]}else{0}
            $orLowValue=if($orLow.ContainsKey($ticker)){$orLow[$ticker]}else{0}
            $results += [pscustomobject]@{
                ticker=$ticker;name=$s.Name;sector=$s.Sector;price=$price;volume=$volume;vwap=$vwap
                under_ratio=[Math]::Round($underRatio*100,1);under_change=[Math]::Round($uoChange*100,1)
                under_change_1m=if($null -eq $underChange1m){$null}else{[Math]::Round($underChange1m*100,1)}
                under_change_5m=if($null -eq $underChange5m){$null}else{[Math]::Round($underChange5m*100,1)}
                flow_bias=[Math]::Round($flowBias*100,1);buy_flow=[Math]::Round($buyFlow);sell_flow=[Math]::Round($sellFlow)
                history_seconds=[Math]::Round($historySeconds);time_band=$timeBand;orderflow_state=$orderflowState;tick_watch="常時監視中"
                volume_burst=[Math]::Round($barBurst,2);or5_high=if($or5High.ContainsKey($ticker)){$or5High[$ticker]}else{0};or5_low=if($or5Low.ContainsKey($ticker)){$or5Low[$ticker]}else{0}
                or_high=$orHighValue;or_low=$orLowValue;ema9=if($null -eq $ema9){$null}else{[Math]::Round($ema9,2)};ema20=if($null -eq $ema20){$null}else{[Math]::Round($ema20,2)};ema_ready=$emaReady
                chase_guard=$chaseGuard;whipsaw=$whipsaw;raw_direction=$rawDirection;strategy=$strategy;signal_bar_time=$signalBarTime
                entry_price=if($null -eq $entryPrice){$null}else{[Math]::Round($entryPrice,2)};stop_price=if($null -eq $stopPrice){$null}else{[Math]::Round($stopPrice,2)}
                target1=if($null -eq $target1){$null}else{[Math]::Round($target1,2)};target2=if($null -eq $target2){$null}else{[Math]::Round($target2,2)}
                day_high=if($dayHigh.ContainsKey($ticker)){$dayHigh[$ticker]}else{$price};day_low=if($dayLow.ContainsKey($ticker)){$dayLow[$ticker]}else{$price}
                pm_above_minutes=if($pmAboveSince.ContainsKey($ticker)){[Math]::Round(($now-$pmAboveSince[$ticker]).TotalMinutes,1)}else{0}
                pm_below_minutes=if($pmBelowSince.ContainsKey($ticker)){[Math]::Round(($now-$pmBelowSince[$ticker]).TotalMinutes,1)}else{0}
                credit_sell=$creditSell;credit_sell_change=$creditSellChange;credit_buy=$creditBuy;credit_buy_change=$creditBuyChange;credit_ratio=$creditRatio
                reference_price=$reference;preopen_quote=[Math]::Round($quoteCenter,1);preopen_gap_pct=if($null -eq $gapPct){$null}else{[Math]::Round($gapPct,2)}
                preopen_market_imbalance=[Math]::Round($marketImbalance*100,1);preopen_quote_change_5m=if($null -eq $quoteChange5m){$null}else{[Math]::Round($quoteChange5m,2)}
                preopen_score=[Math]::Round($preopenScore);preopen_plan=$preopenPlan;special_quote=if($hasSpecialSell){"特売り"}elseif($hasSpecialBuy){"特買い"}else{"なし"}
                open_price=$openPrice;open_decision=$openDecision;score=[Math]::Round($score);signal=$signal;hold_signal="持ち越し判定前";hold_score=0;data="LIVE"
            }
            $previous[$ticker]=[pscustomobject]@{Price=$price;Volume=$volume;UnderRatio=$underRatio}
        }
        $preopenRecordingStatus=if($now.TimeOfDay -ge [TimeSpan]::Parse("08:00:00") -and $now.TimeOfDay -lt [TimeSpan]::Parse("09:00:00")){
            if($preopenQuoteCount -gt 0){"記録中 $preopenQuoteCount/100"}else{"RSS気配未取得"}
        }else{"時間外"}
        if($snapshotDue -and $preopenRecordingStatus -eq "RSS気配未取得"){
            Write-Host "警告: 寄り前の売買気配をまだ取得できません。MS2ログイン、ExcelのRSS接続、買気配・売気配セルを確認してください。" -ForegroundColor Red
        }
        if ($snapshotDue) {$lastSnapshotAt=$now}
        foreach ($key in @($seenTicks.Keys)) {if (($now-$seenTicks[$key]).TotalMinutes -gt 30) {$seenTicks.Remove($key)}}

        $kioxia=$results|Where-Object{$_.ticker -eq "285A.T"}|Select-Object -First 1
        if ($null -ne $kioxia) {
            $kioxiaBars = @()
            if ($minuteBars.ContainsKey("285A.T")) { $kioxiaBars += @($minuteBars["285A.T"]) }
            if ($currentMinuteBars.ContainsKey("285A.T") -and $null -ne $currentMinuteBars["285A.T"]) { $kioxiaBars += $currentMinuteBars["285A.T"] }
            $kioxia | Add-Member -NotePropertyName bars_1m -NotePropertyValue @(Convert-LiveBars $kioxiaBars 1 ([double]$kioxia.vwap)) -Force
            $kioxia | Add-Member -NotePropertyName bars_3m -NotePropertyValue @(Convert-LiveBars $kioxiaBars 3 ([double]$kioxia.vwap)) -Force
            $kioxia | Add-Member -NotePropertyName bars_5m -NotePropertyValue @(Convert-LiveBars $kioxiaBars 5 ([double]$kioxia.vwap)) -Force
            $kioxia | Add-Member -NotePropertyName bars_15m -NotePropertyValue @(Convert-LiveBars $kioxiaBars 15 ([double]$kioxia.vwap)) -Force
        }
        $inPts=($now.TimeOfDay -ge [TimeSpan]::Parse("16:30:00") -and $now.TimeOfDay -lt [TimeSpan]::Parse("23:59:00"))
        $tseIndex=@{}
        foreach($item in $results){$tseIndex[[string]$item.ticker]=$item}
        $ptsResults=@()
        for($i=0;$i -lt $stocks.Count;$i++){
            $row=$i+1; $stock=$stocks[$i]; $tseTicker=[string]$stock.Ticker
            $ptsTicker=($tseTicker -replace '\.T$','')+'.JNX'
            $ptsPrice=Get-SafeNumber (Get-TableValue $jnxValues $row 1 15) 0.01 10000000
            $ptsTime=Get-TimeText (Get-TableValue $jnxValues $row 2 15)
            $ptsVolume=Get-SafeNumber (Get-TableValue $jnxValues $row 5 15) 0 1000000000000
            $ptsVwap=Get-SafeNumber (Get-TableValue $jnxValues $row 6 15) 0 10000000
            $ptsBid=Get-SafeNumber (Get-TableValue $jnxValues $row 7 15) 0 10000000
            $ptsAsk=Get-SafeNumber (Get-TableValue $jnxValues $row 8 15) 0 10000000
            $ptsBidQty=Get-SafeNumber (Get-TableValue $jnxValues $row 9 15) 0 1000000000000
            $ptsAskQty=Get-SafeNumber (Get-TableValue $jnxValues $row 10 15) 0 1000000000000
            $ptsOver=Get-SafeNumber (Get-TableValue $jnxValues $row 11 15) 0 1000000000000
            $ptsUnder=Get-SafeNumber (Get-TableValue $jnxValues $row 12 15) 0 1000000000000
            $ptsTick=Get-SafeNumber (Get-TableValue $jnxValues $row 13 15) 0.01 10000000
            $ptsDate=Get-DateText (Get-TableValue $jnxValues $row 15 15)
            if($null -eq $ptsPrice -or $null -eq $ptsVolume -or $ptsVolume -le 0 -or [string]::IsNullOrWhiteSpace($ptsDate)){continue}
            $dateAge=999
            try{$dateAge=[Math]::Abs((([DateTime]::Parse($now.ToString("yyyy-MM-dd")))-([DateTime]::Parse($ptsDate))).TotalDays)}catch{}
            $usable=($inPts -and $ptsDate -eq $now.ToString("yyyy-MM-dd")) -or ((-not $inPts) -and $dateAge -le 4)
            if(-not $usable){continue}
            $tse=$tseIndex[$tseTicker]
            if($null -eq $tse -or [double]$tse.price -le 0){continue}
            $tseClose=[double]$tse.price; $tseVolume=[double]$tse.volume
            $ptsGap=(($ptsPrice/$tseClose)-1)*100
            $ptsUnderRatio=if($null -ne $ptsOver -and $null -ne $ptsUnder -and ($ptsOver+$ptsUnder)-gt 0){$ptsUnder/($ptsOver+$ptsUnder)*100}else{50.0}
            $ptsVolumeRatio=if($tseVolume -gt 0){$ptsVolume/$tseVolume*100}else{0}
            $turnover=$ptsPrice*$ptsVolume
            $mid=if($ptsBid -gt 0 -and $ptsAsk -gt 0){($ptsBid+$ptsAsk)/2}else{$ptsPrice}
            $spreadPct=if($mid -gt 0 -and $ptsBid -gt 0 -and $ptsAsk -gt 0){($ptsAsk-$ptsBid)/$mid*100}else{99}
            $vwapBias=if($ptsVwap -gt 0){(($ptsPrice/$ptsVwap)-1)*100}else{0}
            $directionScore=(Limit ($ptsGap*10) -35 35)+(Limit ($vwapBias*15) -15 15)+(Limit (($ptsUnderRatio-50)*1.2) -15 15)
            $activityScore=(Limit ([Math]::Log10(1+[Math]::Max(0,$turnover/1000000))*12) 0 30)+(Limit ([Math]::Log10(1+[Math]::Max(0,$ptsVolumeRatio))*10) 0 20)
            $spreadPenalty=Limit ($spreadPct*18) 0 30
            $signedActivity=if($directionScore -gt 0){$activityScore*0.55}elseif($directionScore -lt 0){-$activityScore*0.55}else{0}
            $biasScore=Limit ($directionScore+$signedActivity-($(if($directionScore -ge 0){$spreadPenalty}else{-$spreadPenalty}))) -100 100
            $expectation=[Math]::Abs($biasScore)
            $stance=if($turnover -lt 10000000){"薄商い・対象外"}elseif($spreadPct -gt 1){"スプレッド過大"}elseif($biasScore -ge 25){"翌日上方向注目"}elseif($biasScore -le -25){"翌日下方向警戒"}else{"方向確認待ち"}
            $ptsRow=[pscustomobject]@{ticker=$ptsTicker;tse_ticker=$tseTicker;name=$stock.Name;sector=$stock.Sector;pts_date=$ptsDate;exchange_time=$ptsTime;price=$ptsPrice;tse_close=$tseClose;gap_pct=[Math]::Round($ptsGap,2);volume=$ptsVolume;tse_volume=$tseVolume;pts_volume_ratio=[Math]::Round($ptsVolumeRatio,2);turnover=[Math]::Round($turnover);vwap=$ptsVwap;bid=$ptsBid;ask=$ptsAsk;spread_pct=[Math]::Round($spreadPct,3);over=$ptsOver;under=$ptsUnder;under_ratio=[Math]::Round($ptsUnderRatio,1);last_tick=$ptsTick;bias_score=[Math]::Round($biasScore);expectation_score=[Math]::Round($expectation);stance=$stance;state=if($inPts){"LIVE"}else{"前夜PTS"}}
            $ptsResults += $ptsRow
            if($snapshotDue -and $inPts){
                $line=@($now.ToString("yyyy-MM-dd HH:mm:ss"),$ptsTicker,$stock.Name,$ptsDate,$ptsTime,$ptsPrice,$tseClose,$ptsGap,$ptsVolume,$tseVolume,$ptsVolumeRatio,$turnover,$ptsVwap,$ptsBid,$ptsAsk,$spreadPct,$ptsBidQty,$ptsAskQty,$ptsOver,$ptsUnder,$ptsUnderRatio,$ptsTick,$biasScore,$expectation,$stance)|ForEach-Object{Escape-Csv $_}
                Add-Content -Encoding UTF8 -Path $ptsCsv -Value ($line -join ',')
            }
        }
        $ptsTop5=@($ptsResults|Where-Object{$_.turnover -ge 10000000 -and $_.spread_pct -le 1 -and $_.stance -ne "方向確認待ち"}|Sort-Object expectation_score -Descending|Select-Object -First 5)
        $irPtsCandidates=@()
        foreach($disclosure in @($tdnetDisclosures)) {
            if([string]$disclosure.time -lt "15:30"){continue}
            $assessment=Get-IrMaterialAssessment ([string]$disclosure.title)
            if($assessment.blocked -or [double]$assessment.score -le 0){continue}
            $ptsMatch=$ptsResults|Where-Object{($_.tse_ticker -replace '\.T$','') -eq [string]$disclosure.code}|Select-Object -First 1
            if($null -eq $ptsMatch){continue}
            if([double]$ptsMatch.turnover -lt 10000000 -or [double]$ptsMatch.spread_pct -gt 1.5 -or [double]$ptsMatch.gap_pct -lt 1 -or [double]$ptsMatch.bias_score -le 0){continue}
            $total=Limit (([double]$assessment.score*1.4)+[double]$ptsMatch.expectation_score) 0 100
            $judgement=if([double]$ptsMatch.gap_pct -ge 15){"急騰過熱・翌朝飛び乗り禁止"}elseif([double]$ptsMatch.gap_pct -ge 7){"高寄り警戒・押し目確認"}else{"公式材料＋PTS反応"}
            $irPtsCandidates += [pscustomobject]@{code=$disclosure.code;ticker=$ptsMatch.ticker;name=$ptsMatch.name;disclosure_time=$disclosure.time;material_label=$assessment.label;material_score=$assessment.score;title=$disclosure.title;official_url=$disclosure.url;pts_price=$ptsMatch.price;tse_close=$ptsMatch.tse_close;gap_pct=$ptsMatch.gap_pct;turnover=$ptsMatch.turnover;spread_pct=$ptsMatch.spread_pct;under_ratio=$ptsMatch.under_ratio;pts_score=$ptsMatch.expectation_score;total_score=[Math]::Round($total);judgement=$judgement}
        }
        $irPtsTop5=@($irPtsCandidates|Sort-Object total_score -Descending|Select-Object -First 5)
        if($snapshotDue -and $inPts){
            foreach($ir in $irPtsTop5){
                $line=@($now.ToString("yyyy-MM-dd HH:mm:ss"),$ir.code,$ir.ticker,$ir.name,$ir.disclosure_time,$ir.material_label,$ir.material_score,$ir.title,$ir.official_url,$ir.pts_price,$ir.tse_close,$ir.gap_pct,$ir.turnover,$ir.spread_pct,$ir.under_ratio,$ir.pts_score,$ir.total_score,$ir.judgement)|ForEach-Object{Escape-Csv $_}
                Add-Content -Encoding UTF8 -Path $irPtsCsv -Value ($line -join ',')
            }
        }
        $kioxiaPts=$ptsResults|Where-Object{$_.tse_ticker -eq "285A.T"}|Select-Object -First 1
        if($null -eq $kioxiaPts){$kioxiaPts=[pscustomobject]@{ticker="285A.JNX";price=$null;gap_pct=$null;volume=$null;under_ratio=$null;stance="取得待ち";state="取得待ち"}}
        $ptsPrice=$kioxiaPts.price; $ptsGap=$kioxiaPts.gap_pct; $ptsVolume=$kioxiaPts.volume; $ptsUnderRatio=$kioxiaPts.under_ratio; $ptsState=$kioxiaPts.stance
        if ($null -ne $kioxia) {
            $historical=$null
            if ($null -ne $kioxiaStats) {
                $condition=if($kioxia.orderflow_state -eq "買い優勢"){"買い傾斜"}elseif($kioxia.orderflow_state -eq "売り優勢"){"売り傾斜"}else{"均衡"}
                $historical=$kioxiaStats.rows|Where-Object{$_.time_band -eq $kioxia.time_band -and $_.condition -eq $condition}|Select-Object -First 1
                if ($null -eq $historical) {$historical=$kioxiaStats.rows|Where-Object{$_.time_band -eq $kioxia.time_band -and $_.condition -eq "全体"}|Select-Object -First 1}
            }
            $kioxia|Add-Member -NotePropertyName historical_prediction -NotePropertyValue $historical -Force
            $preopenHistorical=$null
            if($null -ne $kioxiaStats -and $null -ne $kioxia.preopen_gap_pct){
                $g=[double]$kioxia.preopen_gap_pct
                $gapBucket=if($g -le -5){"GD5%以上"}elseif($g -le -2){"GD2–5%"}elseif($g -lt 0){"小幅GD"}elseif($g -lt 2){"小幅GU"}elseif($g -lt 5){"GU2–5%"}else{"GU5%以上"}
                $preopenHistorical=$kioxiaStats.preopen_rows|Where-Object{$_.gap_bucket -eq $gapBucket -and $_.plan -eq $kioxia.preopen_plan}|Select-Object -First 1
            }
            $kioxia|Add-Member -NotePropertyName preopen_historical -NotePropertyValue $preopenHistorical -Force
            $kioxia|Add-Member -NotePropertyName completed_stat_days -NotePropertyValue $(if($null -ne $kioxiaStats){$kioxiaStats.completed_days}else{0}) -Force
        }
        foreach($result in $results){
            $matchedPts=$ptsResults|Where-Object{$_.tse_ticker -eq $result.ticker}|Select-Object -First 1
            $ptsBoost=0
            if($null -ne $matchedPts -and (-not $inPts) -and $now.TimeOfDay -lt [TimeSpan]::Parse("09:15:00")){
                $ptsBoost=Limit ([double]$matchedPts.bias_score*0.15) -15 15
                $result.score=[Math]::Round(([double]$result.score)+$ptsBoost)
            }
            $result|Add-Member -NotePropertyName prior_pts_gap_pct -NotePropertyValue $(if($null -ne $matchedPts){$matchedPts.gap_pct}else{$null}) -Force
            $result|Add-Member -NotePropertyName prior_pts_bias -NotePropertyValue $(if($null -ne $matchedPts){$matchedPts.bias_score}else{$null}) -Force
            $result|Add-Member -NotePropertyName prior_pts_boost -NotePropertyValue ([Math]::Round($ptsBoost)) -Force
        }

        # 地合いと業種の確認を、OR5/OR15の最終点灯条件に使う。
        # UNDER/OVERは補助情報に留め、板の見せ玉だけでサインを出さない。
        $breadthBase=@($results|Where-Object{$_.vwap -gt 0})
        $breadthPct=if($breadthBase.Count -ge 20){[Math]::Round((@($breadthBase|Where-Object{$_.price -gt $_.vwap}).Count/$breadthBase.Count)*100,1)}else{$null}
        $marketState=if($null -eq $breadthPct){"地合い確認待ち"}elseif($breadthPct -ge 60){"地合い強い"}elseif($breadthPct -le 40){"地合い弱い"}else{"地合い中立"}
        $sectorBreadth=@{}
        foreach($sectorGroup in @($results|Where-Object{$_.vwap -gt 0}|Group-Object sector)){
            $sectorItems=@($sectorGroup.Group)
            $sectorBreadth[[string]$sectorGroup.Name]=if($sectorItems.Count -ge 2){[Math]::Round((@($sectorItems|Where-Object{$_.price -gt $_.vwap}).Count/$sectorItems.Count)*100,1)}else{$null}
        }
        foreach($result in $results){
            $sectorPct=$sectorBreadth[[string]$result.sector]
            $longSupport=($marketState -eq "地合い強い" -or ($null -ne $sectorPct -and [double]$sectorPct -ge 60))
            $shortSupport=($marketState -eq "地合い弱い" -or ($null -ne $sectorPct -and [double]$sectorPct -le 40))
            if([string]$result.raw_direction -eq "BUY"){
                if([string]$result.strategy -eq "OR5初動"){
                    $result.signal=if($longSupport){"買いサイン"}else{"OR5上抜け・地合待ち"}
                }elseif([string]$result.strategy -eq "OR15追随"){
                    $result.signal=if($longSupport){"買いサイン"}else{"OR15利確警戒"}
                }elseif([string]$result.strategy -eq "OR15押し目"){
                    $result.signal=if($marketState -eq "地合い弱い"){"押し目・地合待ち"}else{"買いサイン"}
                }
            }elseif([string]$result.raw_direction -eq "SELL"){
                if([string]$result.strategy -eq "OR5初動"){
                    $result.signal=if($shortSupport){"空売りサイン"}else{"OR5下抜け・地合待ち"}
                }elseif([string]$result.strategy -eq "OR15追随"){
                    $result.signal=if($shortSupport){"空売りサイン"}else{"OR15戻り警戒"}
                }elseif([string]$result.strategy -eq "OR15戻り"){
                    $result.signal=if($marketState -eq "地合い強い"){"戻り・地合待ち"}else{"空売りサイン"}
                }
            }
            if($validCount -lt 90){$result.signal="データ不足・売買禁止"}
            elseif([string]$result.special_quote -ne "なし"){$result.signal="特別気配・売買禁止"}

            $range=[double]$result.day_high-[double]$result.day_low
            $closeLocation=if($range -gt 0){Limit (([double]$result.price-[double]$result.day_low)/$range) 0 1}else{0.5}
            $longHold=0.0; $shortHold=0.0
            if([double]$result.vwap -gt 0 -and [double]$result.price -gt [double]$result.vwap){$longHold+=20}else{$shortHold+=20}
            if($result.ema_ready -and [double]$result.ema9 -gt [double]$result.ema20){$longHold+=15}
            elseif($result.ema_ready -and [double]$result.ema9 -lt [double]$result.ema20){$shortHold+=15}
            if([double]$result.pm_above_minutes -ge 30){$longHold+=15}
            if([double]$result.pm_below_minutes -ge 30){$shortHold+=15}
            if($closeLocation -ge 0.8){$longHold+=15}; if($closeLocation -le 0.2){$shortHold+=15}
            if([double]$result.flow_bias -ge 5){$longHold+=10}; if([double]$result.flow_bias -le -5){$shortHold+=10}
            if([double]$result.under_ratio -ge 52){$longHold+=10}; if([double]$result.under_ratio -le 48){$shortHold+=10}
            if($longSupport){$longHold+=10}; if($shortSupport){$shortHold+=10}
            if($result.whipsaw){$longHold-=20;$shortHold-=20}
            if($result.chase_guard){$longHold-=10;$shortHold-=10}
            $longHold=Limit $longHold 0 100; $shortHold=Limit $shortHold 0 100
            $regimeName=if($null -ne $investorRegime){[string]$investorRegime.regime.name}else{"判定不能"}
            $regimePeriod=if($null -ne $investorRegime){[string]$investorRegime.asof.period_end}else{""}
            $regimeRetrieved=if($null -ne $investorRegime){[string]$investorRegime.asof.retrieved_at}else{""}
            $regimeObservedAt=$null
            try{$regimeObservedAt=[DateTimeOffset]::Parse($regimeRetrieved)}catch{}
            $regimeUsable=($null -ne $investorRegime -and [string]$investorRegime.type_filter.status -eq "利用可" -and $null -ne $regimeObservedAt -and $regimeObservedAt -le [DateTimeOffset]$now)
            $turnover=[double]$result.price*[double]$result.volume
            $longRegimeFit=if($regimeUsable){Get-RegimeFit $regimeName "LONG" ([string]$result.sector) $turnover}else{$null}
            $shortRegimeFit=if($regimeUsable){Get-RegimeFit $regimeName "SHORT" ([string]$result.sector) $turnover}else{$null}
            if($null -ne $longRegimeFit){$longHold=Limit (($longHold*.70)+[double]$longRegimeFit) 0 100}
            if($null -ne $shortRegimeFit){$shortHold=Limit (($shortHold*.70)+[double]$shortRegimeFit) 0 100}
            $holdSignal="15時判定待ち"; $holdScore=[Math]::Max($longHold,$shortHold)
            if($now.TimeOfDay -ge [TimeSpan]::Parse("15:00:00")){
                if($longHold -ge 70 -and $longHold -ge $shortHold+15){$holdSignal="持ち越しロング候補";$holdScore=$longHold}
                elseif($shortHold -ge 70 -and $shortHold -ge $longHold+15){$holdSignal="持ち越しショート候補";$holdScore=$shortHold}
                else{$holdSignal="日中限定・持ち越し禁止"}
            }
            $result.hold_signal=$holdSignal; $result.hold_score=[Math]::Round($holdScore)
            $result|Add-Member -NotePropertyName market_state -NotePropertyValue $marketState -Force
            $result|Add-Member -NotePropertyName breadth_pct -NotePropertyValue $breadthPct -Force
            $result|Add-Member -NotePropertyName sector_breadth_pct -NotePropertyValue $sectorPct -Force
            $result|Add-Member -NotePropertyName close_location_pct -NotePropertyValue ([Math]::Round($closeLocation*100,1)) -Force
            $result|Add-Member -NotePropertyName event_check_required -NotePropertyValue $true -Force
            $result|Add-Member -NotePropertyName regime_name -NotePropertyValue $regimeName -Force
            $result|Add-Member -NotePropertyName regime_period_end -NotePropertyValue $regimePeriod -Force
            $result|Add-Member -NotePropertyName regime_retrieved_at -NotePropertyValue $regimeRetrieved -Force
            $result|Add-Member -NotePropertyName regime_fit_long_20 -NotePropertyValue $longRegimeFit -Force
            $result|Add-Member -NotePropertyName regime_fit_short_20 -NotePropertyValue $shortRegimeFit -Force
            $result|Add-Member -NotePropertyName subject_sensitivity_10 -NotePropertyValue $null -Force

            if($result.signal -in @("買いサイン","空売りサイン") -and -not [string]::IsNullOrWhiteSpace([string]$result.signal_bar_time)){
                $logKey=([string]$result.ticker+'|'+[string]$result.strategy+'|'+[string]$result.signal_bar_time)
                if(-not $loggedSignals.ContainsKey($logKey)){
                    $line=@($now.ToString("yyyy-MM-dd HH:mm:ss"),$result.ticker,$result.name,$result.signal,$result.strategy,$result.signal_bar_time,$result.entry_price,$result.stop_price,$result.target1,$result.target2,$marketState,$breadthPct,$sectorPct,$holdSignal,$result.hold_score)|ForEach-Object{Escape-Csv $_}
                    Add-Content -Encoding UTF8 -Path $signalCsv -Value ($line -join ',')
                    $loggedSignals[$logKey]=$true
                }
            }
        }
        $kioxia=$results|Where-Object{$_.ticker -eq "285A.T"}|Select-Object -First 1
        $provisionalHoldTop5=@($results|Where-Object{$validCount -ge 90 -and $_.special_quote -eq "なし" -and $_.hold_signal -in @("持ち越しロング候補","持ち越しショート候補")}|Sort-Object hold_score -Descending|Select-Object -First 5)
        if(-not $holdFinalized -and $now.TimeOfDay -ge [TimeSpan]::Parse("15:25:00") -and $now.TimeOfDay -lt [TimeSpan]::Parse("15:26:00")){
            $rank=0
            $finalHoldTop5=@($provisionalHoldTop5|ForEach-Object{
                $rank++
                [pscustomobject]@{
                    finalized_at=$now.ToString("yyyy-MM-dd HH:mm:ss");rank=$rank;ticker=$_.ticker;name=$_.name
                    hold_signal=if($_.hold_signal -match "ロング"){"持ち越しロング確定"}else{"持ち越しショート確定"}
                    hold_score=$_.hold_score;price=$_.price;reference_price_1525=$_.price;vwap=$_.vwap
                    or_high=$_.or_high;or_low=$_.or_low;pm_above_minutes=$_.pm_above_minutes;pm_below_minutes=$_.pm_below_minutes
                    close_location_pct=$_.close_location_pct;market_state=$_.market_state;breadth_pct=$_.breadth_pct
                    sector_breadth_pct=$_.sector_breadth_pct;flow_bias=$_.flow_bias;under_ratio=$_.under_ratio
                    model_version="ms2-hold-2.0+investor-regime-1.1.0";regime_name=$_.regime_name
                    regime_period_end=$_.regime_period_end;regime_retrieved_at=$_.regime_retrieved_at
                    regime_fit_20=if($_.hold_signal -match "ロング"){$_.regime_fit_long_20}else{$_.regime_fit_short_20}
                    subject_sensitivity_10=$null;score_coverage=if($null -ne $_.regime_fit_long_20){90}else{70}
                    feature_snapshot=[ordered]@{sector=$_.sector;price=$_.price;volume=$_.volume;vwap=$_.vwap;ema9=$_.ema9;ema20=$_.ema20;or15_high=$_.or_high;or15_low=$_.or_low;day_high=$_.day_high;day_low=$_.day_low;flow_bias=$_.flow_bias;under_ratio=$_.under_ratio;pm_above_minutes=$_.pm_above_minutes;pm_below_minutes=$_.pm_below_minutes;close_location_pct=$_.close_location_pct;market_state=$_.market_state;sector_breadth_pct=$_.sector_breadth_pct}
                }
            })
            if($finalHoldTop5.Count -gt 0){
                $snapshotRows=@($finalHoldTop5|Select-Object finalized_at,rank,ticker,name,hold_signal,hold_score,reference_price_1525,vwap,@{Name='or15_high';Expression={$_.or_high}},@{Name='or15_low';Expression={$_.or_low}},pm_above_minutes,pm_below_minutes,close_location_pct,market_state,breadth_pct,sector_breadth_pct,flow_bias,under_ratio)
                Write-CsvObjects $holdFinalCsv $snapshotRows
                foreach($item in $finalHoldTop5){
                    $exists=@($holdHistory|Where-Object{$_.decision_date -eq $activeDay -and $_.ticker -eq $item.ticker}).Count -gt 0
                    if(-not $exists){
                        $holdHistory += [pscustomobject]@{decision_date=$activeDay;finalized_at=$item.finalized_at;rank=$item.rank;ticker=$item.ticker;name=$item.name;side=if($item.hold_signal -match "ロング"){"LONG"}else{"SHORT"};hold_score=$item.hold_score;reference_price_1525=$item.reference_price_1525;entry_close_price="";entry_date="";evaluation_date="";next_open="";next_close="";next_high="";next_low="";return_open_pct="";return_close_pct="";mfe_pct="";mae_pct="";result="";status="大引け値待ち"}
                    }
                }
                Write-CsvObjects $holdHistoryPath $holdHistory
            }
            $holdFinalized=$true
            $holdFinalizedAt=$now.ToString("yyyy-MM-dd HH:mm:ss")
            $immutable=[ordered]@{decision_at=$now.ToString("yyyy-MM-ddTHH:mm:sszzz");decision_price_type="15:25参照価格（実約定ではない）";model_version="ms2-hold-2.0+investor-regime-1.1.0";regime=[ordered]@{name=$regimeName;period_end=$regimePeriod;retrieved_at=$regimeRetrieved;future_boundary="retrieved_atがdecision_at以前の版のみ"};cost_assumption=[ordered]@{fee_bps=0;slippage_bps_per_side=5;round_trip_cost_bps=10};benchmark="TOPIX（未接続時は超過収益を未取得表示）";candidates=$finalHoldTop5}
            $created=Write-ImmutableJson $holdImmutableJson $immutable
            $snapshotHash=if(Test-Path $holdImmutableJson){(Get-FileHash -Algorithm SHA256 $holdImmutableJson).Hash.ToLower()}else{""}
            Write-AtomicUtf8 $holdFinalMarker (([ordered]@{finalized_at=$holdFinalizedAt;candidate_count=$finalHoldTop5.Count;immutable_created=$created;snapshot_sha256=$snapshotHash;model_version=$immutable.model_version}|ConvertTo-Json))
            $speaker.Speak(("15時25分、翌日持ち越しTOP5を確定しました。候補数"+$finalHoldTop5.Count+"。銘柄と方向を保存しました。注文前に決算とイベントを確認してください。"),1)|Out-Null
        }
        $holdTop5=if($holdFinalized){@($finalHoldTop5)}else{@($provisionalHoldTop5)}

        # 15:25の候補リストは固定し、15:30以降の東証終値だけを実際の持ち越し基準値として追記する。
        if($holdFinalized -and -not $holdEntryCaptured -and $now.TimeOfDay -ge [TimeSpan]::Parse("15:30:00")){
            $changed=$false
            foreach($record in $holdHistory|Where-Object{$_.decision_date -eq $activeDay -and $_.status -eq "大引け値待ち"}){
                $live=$results|Where-Object{$_.ticker -eq $record.ticker}|Select-Object -First 1
                if($null -ne $live -and [double]$live.price -gt 0){$record.entry_close_price=[Math]::Round([double]$live.price,2);$record.entry_date=$activeDay;$record.status="翌日検証待ち";$changed=$true}
            }
            if($changed){Write-CsvObjects $holdHistoryPath $holdHistory}
            $holdEntryCaptured=$true
        }

        # 次にコレクターが稼働した取引日の大引け後、方向別の終値損益とMFE/MAEを採点する。
        if($now.TimeOfDay -ge [TimeSpan]::Parse("15:30:00")){
            $auditChanged=$false
            try{$actualFills=@(Import-Csv -Encoding UTF8 $actualFillsPath)}catch{$actualFills=@()}
            try{$auditV2=@(Import-Csv -Encoding UTF8 $auditV2Path)}catch{$auditV2=@()}
            foreach($record in $holdHistory|Where-Object{$_.status -eq "翌日検証待ち" -and $_.decision_date -lt $activeDay}){
                $live=$results|Where-Object{$_.ticker -eq $record.ticker}|Select-Object -First 1
                $entry=Get-SafeNumber $record.entry_close_price 0.01 10000000
                if($null -eq $entry -or $null -eq $live){continue}
                $open=Get-SafeNumber $live.open_price 0.01 10000000; $close=Get-SafeNumber $live.price 0.01 10000000
                $high=Get-SafeNumber $live.day_high 0.01 10000000; $low=Get-SafeNumber $live.day_low 0.01 10000000
                if($null -eq $open -or $null -eq $close -or $null -eq $high -or $null -eq $low){continue}
                if($record.side -eq "LONG"){$retOpen=($open/$entry-1)*100;$retClose=($close/$entry-1)*100;$mfe=($high/$entry-1)*100;$mae=($low/$entry-1)*100}
                else{$retOpen=($entry/$open-1)*100;$retClose=($entry/$close-1)*100;$mfe=($entry/$low-1)*100;$mae=($entry/$high-1)*100}
                $record.evaluation_date=$activeDay;$record.next_open=[Math]::Round($open,2);$record.next_close=[Math]::Round($close,2);$record.next_high=[Math]::Round($high,2);$record.next_low=[Math]::Round($low,2)
                $record.return_open_pct=[Math]::Round($retOpen,2);$record.return_close_pct=[Math]::Round($retClose,2);$record.mfe_pct=[Math]::Round($mfe,2);$record.mae_pct=[Math]::Round($mae,2)
                $record.result=if($retClose -gt 0){"勝ち"}elseif($retClose -lt 0){"負け"}else{"引分"};$record.status="検証済み";$auditChanged=$true
                $already=@($auditV2|Where-Object{$_.decision_date -eq $record.decision_date -and $_.ticker -eq $record.ticker}).Count -gt 0
                if(-not $already){
                    $fill=$actualFills|Where-Object{$_.decision_date -eq $record.decision_date -and $_.ticker -eq $record.ticker -and $_.side -eq $record.side}|Select-Object -First 1
                    $actual=if($null -ne $fill){Get-SafeNumber $fill.actual_fill_price 0.01 10000000}else{$null}
                    $auditEntry=if($null -ne $actual){$actual}else{$entry}
                    $fillSource=if($null -ne $actual){"実約定入力"}else{"15:30終値代理（実約定未入力）"}
                    if($record.side -eq "LONG"){$v2Open=($open/$auditEntry-1)*100-.10;$v2Close=($close/$auditEntry-1)*100-.10;$v2Mfe=($high/$auditEntry-1)*100-.10;$v2Mae=($low/$auditEntry-1)*100-.10}
                    else{$v2Open=($auditEntry/$open-1)*100-.10;$v2Close=($auditEntry/$close-1)*100-.10;$v2Mfe=($auditEntry/$low-1)*100-.10;$v2Mae=($auditEntry/$high-1)*100-.10}
                    $daySnapshot=Join-Path (Join-Path $dataRoot $record.decision_date) "overnight_hold_finalized.json"
                    $markerV2=$null;try{if(Test-Path $daySnapshot){$markerV2=Get-Content -Raw -Encoding UTF8 $daySnapshot|ConvertFrom-Json}}catch{}
                    $auditV2 += [pscustomobject]@{decision_date=$record.decision_date;rank=$record.rank;ticker=$record.ticker;name=$record.name;side=$record.side;model_version=if($null -ne $markerV2){$markerV2.model_version}else{"legacy"};snapshot_sha256=if($null -ne $markerV2){$markerV2.snapshot_sha256}else{""};reference_price_1525=$record.reference_price_1525;actual_fill_price=if($null -ne $actual){$actual}else{""};fill_source=$fillSource;cost_bps=10;benchmark="TOPIX未接続";next_trade_date=$activeDay;next_open=$open;next_high=$high;next_low=$low;next_close=$close;return_open_pct=[Math]::Round($v2Open,2);return_close_pct=[Math]::Round($v2Close,2);excess_open_pct="";excess_close_pct="";mfe_pct=[Math]::Round($v2Mfe,2);mae_pct=[Math]::Round($v2Mae,2);result=if($v2Close -gt 0){"勝ち"}elseif($v2Close -lt 0){"負け"}else{"引分"};missing_reason=if($null -eq $actual){"実約定未入力・ベンチマーク未接続"}else{"ベンチマーク未接続"}}
                }
            }
            if($auditChanged){Write-CsvObjects $holdHistoryPath $holdHistory;Write-CsvObjects $auditV2Path $auditV2}
        }
        $holdStats=Get-OvernightHoldStats $holdHistory
        Write-AtomicUtf8 $holdStatsPath (($holdStats|ConvertTo-Json -Depth 6))
        $qualified=@($results|Where-Object{$_.signal -in @("買いサイン","空売りサイン","OR5上抜け・地合待ち","OR5下抜け・地合待ち","OR15利確警戒","OR15戻り警戒","押し目待ち","戻り待ち","初動買い候補","初動ショート候補","買い準備","ショート準備","監視")}|Sort-Object @{Expression={if($_.signal -in @("買いサイン","空売りサイン")){0}elseif($_.signal -in @("OR5上抜け・地合待ち","OR5下抜け・地合待ち","OR15利確警戒","OR15戻り警戒","押し目待ち","戻り待ち")){1}elseif($_.signal -in @("初動買い候補","初動ショート候補")){2}elseif($_.signal -in @("買い準備","ショート準備")){3}else{4}}},@{Expression={[Math]::Abs($_.score)};Descending=$true}|Select-Object -First 5)
        $payload=[ordered]@{updated_at=$now.ToString("yyyy-MM-dd HH:mm:ss");source="MarketSpeed II RSS / local PC";universe=100;valid=$validCount;stale=($validCount -lt 90);preopen_quote_count=$preopenQuoteCount;preopen_recording_status=$preopenRecordingStatus;market_state=$marketState;breadth_pct=$breadthPct;notice="Ver.1試運転。確定1分足・VWAP・EMA・出来高・地合いを確認。UNDER/OVER単独では判定しません。注文は武蔵で手動です。";tdnet_status=$tdnetStatus;kioxia=$kioxia;kioxia_pts=$kioxiaPts;pts_top5=$ptsTop5;ir_pts_top5=$irPtsTop5;hold_top5=$holdTop5;hold_finalized=$holdFinalized;hold_finalized_at=$holdFinalizedAt;hold_stats=$holdStats;top5=$qualified}
        $jsonText=$payload|ConvertTo-Json -Depth 6
        Write-AtomicUtf8 $jsonPath $jsonText
        if (Test-Path (Join-Path (Split-Path $PSScriptRoot -Parent) "index.html")) { Write-AtomicUtf8 $cockpitJsonPath $jsonText }

        $cards = if ($qualified.Count -eq 0) {'<div class="empty">発動条件を満たす候補なし</div>'} else {($qualified|ForEach-Object{
            $cls=if($_.signal -in @("買いサイン","初動買い候補","買い準備")){"buy"}elseif($_.signal -in @("空売りサイン","初動ショート候補","ショート準備")){"sell"}elseif($_.signal -eq "往復ピンタ回避"){"block"}else{"watch"}
            $priorPtsText=if($null -eq $_.prior_pts_gap_pct){"なし"}else{("{0:+0.00;-0.00;0.00}% / 加点 {1:+0;-0;0}" -f $_.prior_pts_gap_pct,$_.prior_pts_boost)}
            $orderText=if($null -eq $_.entry_price){"条件未完成"}else{("発動 {0} / 損切 {1} / 1R {2}" -f $_.entry_price,$_.stop_price,$_.target1)}
            '<article class="pick '+$cls+'"><div class="head"><span>'+ (Escape-Html $_.signal) +'</span><b>'+ (Escape-Html $_.name) +'</b><strong>'+([string]$_.score)+'</strong></div><div class="price">'+("{0:N1}" -f $_.price)+'円</div><div class="metrics"><span>戦略<br><b>'+ (Escape-Html $_.strategy) +'</b></span><span>注文目安<br><b>'+ (Escape-Html $orderText) +'</b></span><span>VWAP<br><b>'+([string]$_.vwap)+'</b></span><span>EMA9/20<br><b>'+([string]$_.ema9)+' / '+([string]$_.ema20)+'</b></span><span>地合い<br><b>'+ (Escape-Html $_.market_state) +'</b></span><span>業種強度<br><b>'+([string]$_.sector_breadth_pct)+'%</b></span><span>UNDER<br><b>'+([string]$_.under_ratio)+'%</b></span><span>約定偏り<br><b>'+([string]$_.flow_bias)+'%</b></span><span>出来高加速<br><b>'+([string]$_.volume_burst)+'倍</b></span><span>前夜PTS<br><b>'+ (Escape-Html $priorPtsText) +'</b></span></div><small>OR5 '+([string]$_.or5_low)+'–'+([string]$_.or5_high)+' / OR15 '+([string]$_.or_low)+'–'+([string]$_.or_high)+' / 確定1分足だけで判定</small></article>'
        }) -join "`n"}
        $holdCards=if($holdTop5.Count -eq 0){'<div class="empty">'+$(if($holdFinalized){'15:25確定候補なし・持ち越し禁止'}else{'15:25確定待ち、または条件未達'})+'</div>'}else{($holdTop5|ForEach-Object{
            $holdCls=if([string]$_.hold_signal -match "ロング"){"buy"}else{"sell"}
            '<article class="pick '+$holdCls+'"><div class="head"><span>'+ (Escape-Html $_.hold_signal) +'</span><b>'+ (Escape-Html $_.name) +' ('+ (Escape-Html $_.ticker) +')</b><strong>'+([string]$_.hold_score)+'</strong></div><div class="price">'+([string]$(if($null -ne $_.reference_price_1525){$_.reference_price_1525}else{$_.price}))+'円</div><div class="metrics"><span>現在値/VWAP<br><b>'+([string]$_.price)+' / '+([string]$_.vwap)+'</b></span><span>後場OR上維持<br><b>'+([string]$_.pm_above_minutes)+'分</b></span><span>後場OR下維持<br><b>'+([string]$_.pm_below_minutes)+'分</b></span><span>日中位置<br><b>'+([string]$_.close_location_pct)+'%</b></span><span>地合い<br><b>'+ (Escape-Html $_.market_state) +'</b></span></div><small>'+$(if($holdFinalized){'15:25候補固定。15:30終値取得後、翌取引日引けで採点します。'}else{'暫定候補。15:25までは注文しません。'})+'</small></article>'
        }) -join "`n"}
        $statPct={param($v) if($null -eq $v){'—'}else{([string]$v)+'%'}}
        $holdStatsCard='<article class="pick watch"><div class="head"><span>翌日終値基準</span><b>持ち越し成績</b><strong>'+([string]$holdStats.samples)+'件</strong></div><div class="metrics"><span>累積勝率<br><b>'+(& $statPct $holdStats.win_rate)+'</b></span><span>平均損益<br><b>'+(& $statPct $holdStats.avg_return_pct)+'</b></span><span>LONG勝率<br><b>'+(& $statPct $holdStats.long_win_rate)+' ('+([string]$holdStats.long_samples)+'件)</b></span><span>SHORT勝率<br><b>'+(& $statPct $holdStats.short_win_rate)+' ('+([string]$holdStats.short_samples)+'件)</b></span></div><small>当日15:30終値から翌取引日15:30終値まで。MFE・MAEもCSVへ保存。</small></article>'
        $holdRecentCards=@($holdStats.recent|Select-Object -First 5|ForEach-Object{
            $resultCls=if($_.result -eq '勝ち'){'buy'}elseif($_.result -eq '負け'){'sell'}else{'watch'}
            '<article class="pick '+$resultCls+'"><div class="head"><span>'+ (Escape-Html $_.result) +'</span><b>'+ (Escape-Html $_.name) +' ('+ (Escape-Html $_.ticker) +')</b><strong>'+([string]$_.return_close_pct)+'%</strong></div><small>'+ (Escape-Html $_.decision_date) +' '+ (Escape-Html $_.side) +' → '+ (Escape-Html $_.evaluation_date) +' / MFE '+([string]$_.mfe_pct)+'%・MAE '+([string]$_.mae_pct)+'%</small></article>'
        }) -join "`n"
        $holdStatusText=if($holdFinalized){'確定済み '+[string]$holdFinalizedAt+'。この候補と方向は翌日検証まで固定。'}else{'15:00から暫定採点、15:25に銘柄と方向を固定。'}
        $holdSection='<h2>15:25確定・翌日持ち越しTOP5</h2><p class="sub">'+(Escape-Html $holdStatusText)+' 後場OR15、VWAP、EMA、引け位置、歩み値、板、地合いを採点。</p><section class="grid">'+$holdCards+'</section><section class="grid">'+$holdStatsCard+'</section><section class="grid">'+$holdRecentCards+'</section>'
        $ptsCards=if($ptsTop5.Count -eq 0){'<div class="empty">売買代金・スプレッド条件を満たすPTS候補なし</div>'}else{($ptsTop5|ForEach-Object{
            $ptsCls=if($_.bias_score -gt 0){"buy"}elseif($_.bias_score -lt 0){"sell"}else{"watch"}
            '<article class="pick '+$ptsCls+'"><div class="head"><span>'+ (Escape-Html $_.stance) +'</span><b>'+ (Escape-Html $_.name) +'</b><strong>'+([string]$_.expectation_score)+'</strong></div><div class="price">'+("{0:N1}" -f $_.price)+'円</div><div class="metrics"><span>東証終値比<br><b>'+(("{0:+0.00;-0.00;0.00}%" -f $_.gap_pct))+'</b></span><span>PTS売買代金<br><b>'+([Math]::Round($_.turnover/1000000,1))+'百万円</b></span><span>東証出来高比<br><b>'+([string]$_.pts_volume_ratio)+'%</b></span><span>スプレッド<br><b>'+([string]$_.spread_pct)+'%</b></span><span>UNDER<br><b>'+([string]$_.under_ratio)+'%</b></span><span>状態<br><b>'+ (Escape-Html $_.state) +'</b></span></div><small>値上がり率だけで選ばず、流動性と板・VWAPの一致を採点</small></article>'
        }) -join "`n"}
        $ptsSection='<h2>夜間PTS期待TOP5</h2><p class="sub">翌日上方向注目と下方向警戒を同じ基準で表示。PTSは翌朝8:55気配で再判定します。</p><section class="grid">'+$ptsCards+'</section>'
        $irPtsCards=if($irPtsTop5.Count -eq 0){'<div class="empty">公式IR＋PTS急騰＋流動性の三条件を満たす候補なし<br><small>'+ (Escape-Html $tdnetStatus) +' / 推定銘柄は表示しません</small></div>'}else{($irPtsTop5|ForEach-Object{
            '<article class="pick buy"><div class="head"><span>'+ (Escape-Html $_.material_label) +'</span><b>'+ (Escape-Html $_.name) +' ('+ (Escape-Html $_.code) +')</b><strong>'+([string]$_.total_score)+'</strong></div><div class="price">'+("{0:N1}" -f $_.pts_price)+'円</div><div class="metrics"><span>開示時刻<br><b>'+ (Escape-Html $_.disclosure_time) +'</b></span><span>東証終値比<br><b>'+("{0:+0.00;-0.00;0.00}%" -f $_.gap_pct)+'</b></span><span>PTS売買代金<br><b>'+([Math]::Round($_.turnover/1000000,1))+'百万円</b></span><span>スプレッド<br><b>'+([string]$_.spread_pct)+'%</b></span><span>UNDER<br><b>'+([string]$_.under_ratio)+'%</b></span><span>判定<br><b>'+ (Escape-Html $_.judgement) +'</b></span></div><small>'+ (Escape-Html $_.title) +' <a href="'+ (Escape-Html $_.official_url) +'" target="_blank" rel="noopener">TDnet原文</a></small></article>'
        }) -join "`n"}
        $irPtsSection='<h2>IR急騰PTS TOP5</h2><p class="sub">15:30以降のTDnet公式開示と、JNXの上昇・売買代金・スプレッドを照合。IRタイトルだけでは採用しません。</p><section class="grid">'+$irPtsCards+'</section>'
        if ($null -eq $kioxia) {
            $kioxiaCard='<section class="focus missing"><b>キオクシア（285A）常時監視</b><strong>データ確認待ち</strong></section>'
        } else {
            $kioxiaClass=if($kioxia.signal -in @("買いサイン","初動買い候補")){"buy"}elseif($kioxia.signal -in @("空売りサイン","初動ショート候補")){"sell"}elseif($kioxia.signal -eq "往復ピンタ回避"){"block"}else{"watch"}
            $orText=if($kioxia.or_high -gt 0){'OR5 '+([string]$kioxia.or5_low)+'–'+([string]$kioxia.or5_high)+' / OR15 '+([string]$kioxia.or_low)+'–'+([string]$kioxia.or_high)}else{'OR15未取得・正式サイン待機'}
            $historyText='蓄積中 '+([string]$kioxia.completed_stat_days)+'/10日'
            if ($null -ne $kioxia.historical_prediction) {$historyText=([string]$kioxia.historical_prediction.prediction)+' 上'+([string]$kioxia.historical_prediction.up_rate_5m)+'%／下'+([string]$kioxia.historical_prediction.down_rate_5m)+'%'}
            $ptsPriceText=if($null -eq $ptsPrice){"取得待ち"}else{("{0:N1}円" -f $ptsPrice)}
            $ptsGapText=if($null -eq $ptsGap){"算出待ち"}else{("{0:+0.00;-0.00;0.00}%" -f $ptsGap)}
            $ptsUnderText=if($null -eq $ptsUnderRatio){"取得待ち"}else{("{0:0.0}%" -f $ptsUnderRatio)}
            $entryText=if($null -eq $kioxia.entry_price){"条件未完成"}else{("発動 {0} / 損切 {1} / 1R {2} / 2R {3}" -f $kioxia.entry_price,$kioxia.stop_price,$kioxia.target1,$kioxia.target2)}
            $kioxiaCard='<section class="focus '+$kioxiaClass+'"><div class="focus-title"><span>キオクシア専用・常時監視</span><b>'+ (Escape-Html $kioxia.signal) +' / '+ (Escape-Html $kioxia.strategy) +'</b><strong>'+([string]$kioxia.score)+'</strong></div><div class="focus-body"><div class="price">'+("{0:N1}" -f $kioxia.price)+'円</div><div class="metrics"><span>注文目安<br><b>'+ (Escape-Html $entryText) +'</b></span><span>地合い<br><b>'+ (Escape-Html $kioxia.market_state) +' '+([string]$kioxia.breadth_pct)+'%</b></span><span>持ち越し<br><b>'+ (Escape-Html $kioxia.hold_signal) +' '+([string]$kioxia.hold_score)+'</b></span><span>8:55作戦<br><b>'+ (Escape-Html $kioxia.preopen_plan) +'</b></span><span>寄り前気配<br><b>'+([string]$kioxia.preopen_quote)+'円</b></span><span>GU/GD<br><b>'+([string]$kioxia.preopen_gap_pct)+'%</b></span><span>特別気配<br><b>'+ (Escape-Html $kioxia.special_quote) +'</b></span><span>VWAP<br><b>'+([string]$kioxia.vwap)+'</b></span><span>EMA9/20<br><b>'+([string]$kioxia.ema9)+' / '+([string]$kioxia.ema20)+'</b></span><span>UNDER<br><b>'+([string]$kioxia.under_ratio)+'%</b></span><span>歩み値偏り<br><b>'+([string]$kioxia.flow_bias)+'%</b></span><span>時間帯統計<br><b>'+ (Escape-Html $historyText) +'</b></span><span>JNX夜間PTS<br><b>'+ (Escape-Html $ptsPriceText) +'</b></span><span>東証終値比<br><b>'+ (Escape-Html $ptsGapText) +'</b></span><span>PTS判定<br><b>'+ (Escape-Html $ptsState) +'</b></span></div></div><small>'+ (Escape-Html $orText) +' / 確定1分足で判定 / PTSは参考 / 注文は武蔵で手動 / 成行禁止</small></section>'
        }
        $html='<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta http-equiv="refresh" content="3"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MS2 LIVE TOP5 Ver.1</title><style>body{margin:0;background:#05090d;color:#edf5fa;font-family:Segoe UI,Yu Gothic,sans-serif}main{max-width:1300px;margin:auto;padding:22px}header{display:flex;justify-content:space-between;align-items:end;border-bottom:1px solid #253541;padding-bottom:16px}h1{margin:0;font-size:29px}h2{margin:28px 0 2px;font-size:22px}.sub{margin:0;color:#8296a5;font-size:12px}header span,.note{color:#8296a5}.status{color:#4be0b6}.focus{margin-top:16px;padding:18px;background:linear-gradient(135deg,#102433,#0b151d);border:1px solid #39708e;border-left:6px solid #42b8f5;border-radius:14px}.focus.buy{border-left-color:#36dfa9}.focus.sell{border-left-color:#ff6370}.focus.block{border-left-color:#f5c451}.focus-title{display:grid;grid-template-columns:1fr auto auto;gap:14px;align-items:center}.focus-title span{font-size:20px;font-weight:800}.focus-title b{padding:7px 12px;border-radius:99px;background:#172630}.focus-title strong{font-size:26px}.focus-body{display:grid;grid-template-columns:210px 1fr;gap:14px;align-items:center}.focus small{display:block;color:#8eb3c8;margin-top:10px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px;margin-top:16px}.pick{background:#0d161e;border:1px solid #253744;border-left:4px solid #789;border-radius:12px;padding:15px}.pick.buy{border-left-color:#36dfa9}.pick.sell{border-left-color:#ff6370}.pick.block{border-left-color:#f5c451}.head{display:grid;grid-template-columns:auto 1fr auto;gap:10px;align-items:center}.head span{font-size:11px;border-radius:99px;background:#172630;padding:5px 8px}.head b{font-size:16px}.head strong{font-size:22px}.price{font-size:29px;font-weight:800;margin:12px 0}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(125px,1fr));gap:5px}.metrics span{background:#111f29;border-radius:7px;padding:8px;color:#8296a5;font-size:10px}.metrics b{color:#e9f3f8;font-size:14px}.pick small{display:block;color:#758895;margin-top:12px}.pick a{color:#55c8ff}.note{margin-top:18px;padding:12px;background:#10171d;border-radius:8px}.empty{padding:50px;text-align:center;color:#8ca0ae}@media(max-width:650px){header{align-items:start;flex-direction:column}.focus-body{grid-template-columns:1fr}.focus-title{grid-template-columns:1fr auto}.metrics{grid-template-columns:1fr 1fr}}</style></head><body><main><header><div><span>MARKETSPEED II RSS・試運転 Ver.1</span><h1>デイトレ100銘柄 LIVE TOP5</h1></div><div><b class="status">'+ (Escape-Html $marketState) +' / VWAP上 '+([string]$breadthPct)+'%</b><br>有効 '+$validCount+'/100<br>'+ (Escape-Html $now.ToString("yyyy-MM-dd HH:mm:ss")) +'</div></header>'+$kioxiaCard+'<section class="grid">'+$cards+'</section>'+$holdSection+$ptsSection+$irPtsSection+'<p class="note">確定1分足だけを使用。OR5は初動、OR15は地合いが弱ければ利確警戒、押し戻りは反転足を確認します。UNDER/OVER単独では売買しません。注文は武蔵で手動、特別気配・往復ピンタ・データ不足時は売買禁止です。</p></main></body></html>'
        Write-AtomicUtf8 $htmlPath $html
        if (-not $browserOpened) { Start-Process $publicCockpitUrl; $browserOpened=$true }

        if($inPts){
            foreach($ir in @($irPtsTop5|Select-Object -First 3)){
                $irVoiceKey=[string]$ir.code+'|'+[string]$ir.disclosure_time+'|'+[string]$ir.title
                if(-not $lastIrVoiceCodes.ContainsKey($irVoiceKey)){
                    $speaker.Speak(("IR急騰PTS候補。"+$ir.name+"、"+$ir.material_label+"。PTSは東証終値比プラス"+[Math]::Round([double]$ir.gap_pct,2)+"パーセント。"+$ir.judgement+"。TDnet原文と翌朝の気配を確認してください。"),1)|Out-Null
                    $lastIrVoiceCodes[$irVoiceKey]=$now
                }
            }
        }

        $voiceCandidates=@()
        if ($null -ne $kioxia) {$voiceCandidates += $kioxia}
        $voiceCandidates += @($qualified|Where-Object{$_.ticker -ne "285A.T"}|Select-Object -First 3)
        foreach ($x in $voiceCandidates) {
            $key=$x.ticker; $old=$lastSignal[$key]; $spokenAt=$lastSpoken[$key]
            $isKioxia=($key -eq "285A.T")
            $speakable=($x.signal -in @("買いサイン","空売りサイン") -or ($isKioxia -and $x.signal -eq "往復ピンタ回避"))
            if ($speakable -and $old -ne $x.signal -and ($null -eq $spokenAt -or ($now-$spokenAt).TotalMinutes -ge 10)) {
                $side=if($x.signal -eq "買いサイン"){"買いサイン点灯"}elseif($x.signal -eq "空売りサイン"){"空売りサイン点灯"}else{"往復ピンタ警戒"}
                $orderVoice=if($null -eq $x.entry_price){"注文条件は未完成です"}else{"発動価格"+$x.entry_price+"円。損切り"+$x.stop_price+"円。第一目標"+$x.target1+"円"}
                $speaker.Speak(($x.name+"、"+$x.strategy+"、"+$side+"。"+$orderVoice+"。"+$x.market_state+"。確定ローソク足を確認し、注文は武蔵で手動です。"),1)|Out-Null
                $lastSpoken[$key]=$now
            }
            $lastSignal[$key]=$x.signal
        }
        if($now.TimeOfDay -ge [TimeSpan]::Parse("15:00:00") -and $now.TimeOfDay -lt [TimeSpan]::Parse("15:25:00")){
            foreach($x in @($holdTop5|Select-Object -First 3)){
                $holdKey=[string]$x.ticker+'|'+[string]$x.hold_signal
                $holdAt=$lastHoldSpoken[$holdKey]
                if($null -eq $holdAt -or ($now-$holdAt).TotalMinutes -ge 20){
                    $speaker.Speak(($x.name+"、"+$x.hold_signal+"、評価"+$x.hold_score+"点。後場のOR15維持と引け位置を確認しました。決算、IR、PTS、米国市場が未確認なら持ち越し禁止です。"),1)|Out-Null
                    $lastHoldSpoken[$holdKey]=$now
                }
            }
        }
        if ($null -ne $kioxia) {
            if($inPts -and $null -ne $ptsGap -and $null -ne $ptsUnderRatio -and $ptsVolume -ge 1000){
                $ptsBand=if($ptsGap -ge 2){2}elseif($ptsGap -ge 1){1}elseif($ptsGap -le -2){-2}elseif($ptsGap -le -1){-1}else{0}
                if($ptsBand -ne 0 -and ($ptsBand -ne $lastPtsBand -or ($now-$lastPtsVoiceAt).TotalMinutes -ge 30)){
                    $ptsDirection=if($ptsBand -gt 0){"上昇"}else{"下落"}
                    $speaker.Speak(("キオクシア夜間PTS。東証終値から"+$ptsDirection+"、"+[Math]::Abs([Math]::Round($ptsGap,2))+"パーセント。現在値"+$ptsPrice+"円。出来高"+$ptsVolume+"株。アンダー比率"+[Math]::Round($ptsUnderRatio,1)+"パーセント。PTSは参考値です。翌朝の気配で再確認してください。"),1)|Out-Null
                    $lastPtsBand=$ptsBand
                    $lastPtsVoiceAt=$now
                }
            }
            if($now.TimeOfDay -ge [TimeSpan]::Parse("08:55:00") -and $now.TimeOfDay -lt [TimeSpan]::Parse("09:00:00") -and $lastPreopenVoice -ne [string]$kioxia.preopen_plan){
                $gapVoice=if($null -eq $kioxia.preopen_gap_pct){"GU、GDは算出不能"}else{"GU、GD、"+$kioxia.preopen_gap_pct+"パーセント"}
                $speaker.Speak(("キオクシア、8時55分判定。"+$kioxia.preopen_plan+"。"+$gapVoice+"。成行偏り"+$kioxia.preopen_market_imbalance+"パーセント。これは準備判定です。寄った直後は注文せず、実価格と歩み値を確認してください。"),1)|Out-Null
                $lastPreopenVoice=[string]$kioxia.preopen_plan
            }
            if($now.TimeOfDay -ge [TimeSpan]::Parse("09:01:00") -and $now.TimeOfDay -lt [TimeSpan]::Parse("09:15:00") -and $kioxia.open_decision -in @("初動買い候補","初動ショート候補") -and $lastOpenDecisionVoice -ne [string]$kioxia.open_decision){
                $speaker.Speak(("キオクシア、"+$kioxia.open_decision+"。現在値"+$kioxia.price+"円。始値"+$kioxia.open_price+"円。歩み値とローソク足を確認し、逆指値で発動してください。"),1)|Out-Null
                $lastOpenDecisionVoice=[string]$kioxia.open_decision
            }
            $flowState=[string]$kioxia.orderflow_state
            if ($flowState -in @("買い優勢","売り優勢")) {
                if ($kioFlowCandidate -ne $flowState) {
                    $kioFlowCandidate=$flowState
                    $kioFlowCandidateSince=$now
                } elseif (($now-$kioFlowCandidateSince).TotalSeconds -ge 30 -and ($lastKioFlowSpoken -ne $flowState -or ($now-$lastKioFlowSpokenAt).TotalMinutes -ge 5)) {
                    $directionText=if($flowState -eq "買い優勢"){"買い優勢です"}else{"売り優勢です"}
                    $oneMinuteText=if($null -eq $kioxia.under_change_1m){"変化未算出"}else{"1分変化"+$kioxia.under_change_1m+"ポイント"}
                    $statText="過去統計は蓄積中です"
                    if ($null -ne $kioxia.historical_prediction -and $kioxia.historical_prediction.ready) {
                        $statText="同時間帯の過去統計は"+$kioxia.historical_prediction.prediction+"。5分後の上昇率"+$kioxia.historical_prediction.up_rate_5m+"パーセント、下落率"+$kioxia.historical_prediction.down_rate_5m+"パーセントです"
                    }
                    $speaker.Speak(("キオクシア。"+$kioxia.time_band+"。"+$directionText+"。アンダー比率"+$kioxia.under_ratio+"パーセント。"+$oneMinuteText+"。歩み値偏り"+$kioxia.flow_bias+"パーセント。"+$statText+"。"),1)|Out-Null
                    $lastKioFlowSpoken=$flowState
                    $lastKioFlowSpokenAt=$now
                }
            } else {
                $kioFlowCandidate=""
            }
        }
        Start-Sleep -Seconds $IntervalSeconds
    }
} finally {
    if ($null -ne $bridgeJob) { Stop-Job $bridgeJob -ErrorAction SilentlyContinue; Remove-Job $bridgeJob -Force -ErrorAction SilentlyContinue }
    Write-Host "監視を停止しました。日別CSVは records フォルダーに残っています。" -ForegroundColor Yellow
}
