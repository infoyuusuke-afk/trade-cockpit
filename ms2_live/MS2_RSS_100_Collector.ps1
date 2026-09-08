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

function Limit([double]$value, [double]$low, [double]$high) {
    return [Math]::Max($low, [Math]::Min($high, $value))
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
$lastSignal = @{}
$lastSpoken = @{}
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
$browserOpened = $false
$bridgeJob = Start-LocalJsonBridge $jsonPath 28580

Write-Host "100銘柄のRSS監視を開始しました。誤値は保存しません。終了は Ctrl+C。" -ForegroundColor Cyan
Write-Host "統一AIコクピット: $publicCockpitUrl" -ForegroundColor Cyan
Write-Host "予備画面（通常は使用しません）: $htmlPath" -ForegroundColor DarkGray
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
            $previous=@{}; $history=@{}; $preopenHistory=@{}; $preopenState=@{}; $seenTicks=@{}; $creditSaved=@{}; $orHigh=@{}; $orLow=@{}; $lastSignal=@{}
            $kioFlowCandidate=""; $lastKioFlowSpoken=""; $lastKioFlowSpokenAt=Get-Date "2000-01-01"
            $lastPreopenVoice=""; $lastOpenDecisionVoice=""
            $lastPtsBand=0; $lastPtsVoiceAt=Get-Date "2000-01-01"
            $tdnetDisclosures=@(); $lastTdnetFetchAt=Get-Date "2000-01-01"; $tdnetStatus="取得待ち"; $lastIrVoiceCodes=@{}
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
        Ensure-Csv $tickCsv "captured_at,ticker,name,exchange_time,price,direction_estimate,bid,ask,note"
        Ensure-Csv $supplyCsv "captured_at,ticker,name,price,over,under,under_ratio,over_under_change,vwap"
        Ensure-Csv $snapshotCsv "captured_at,ticker,name,price,volume,vwap,bid,ask,bid_qty,ask_qty,market_sell,market_buy,over,under"
        Ensure-Csv $preopenCsv "captured_at,ticker,name,reference_price,quote_center,gap_pct,bid,ask,bid_qty,ask_qty,market_sell,market_buy,market_imbalance,over,under,under_ratio,quote_change_1m_pct,quote_change_5m_pct,special_sell,special_buy,score,plan"
        Ensure-Csv $creditCsv "captured_at,ticker,name,credit_sell,credit_sell_weekly_change,credit_buy,credit_buy_weekly_change,credit_ratio"
        Ensure-Csv $ptsCsv "captured_at,ticker,name,pts_date,exchange_time,price,tse_close,gap_pct,volume,tse_volume,pts_volume_ratio,turnover,vwap,bid,ask,spread_pct,bid_qty,ask_qty,over,under,under_ratio,last_tick,bias_score,expectation_score,stance"
        Ensure-Csv $irPtsCsv "captured_at,code,ticker,name,disclosure_time,material_label,material_score,title,official_url,pts_price,tse_close,gap_pct,turnover,spread_pct,under_ratio,pts_score,total_score,judgement"

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
            if ($null -eq $price) { continue }
            $validCount++
            if ($null -eq $volume) {$volume=0}; if ($null -eq $vwap) {$vwap=0}; if ($null -eq $bid) {$bid=0}; if ($null -eq $ask) {$ask=0}
            if ($null -eq $bidQty) {$bidQty=0}; if ($null -eq $askQty) {$askQty=0}; if ($null -eq $marketSell) {$marketSell=0}; if ($null -eq $marketBuy) {$marketBuy=0}
            if ($null -eq $over) {$over=0}; if ($null -eq $under) {$under=0}
            $underRatio = if (($over+$under) -gt 0) {$under/($over+$under)} else {0.5}
            $prev = $previous[$ticker]
            $volumeDelta = if ($null -ne $prev) {[Math]::Max(0,$volume-$prev.Volume)} else {0}
            $priceDelta = if ($null -ne $prev) {$price-$prev.Price} else {0}
            $uoChange = if ($null -ne $prev) {$underRatio-$prev.UnderRatio} else {0}

            $clock=$now.TimeOfDay; $inOr=($clock -ge [TimeSpan]::Parse("09:00:00") -and $clock -lt [TimeSpan]::Parse("09:15:00"))
            $inPreopen=($clock -ge [TimeSpan]::Parse("08:00:00") -and $clock -lt [TimeSpan]::Parse("09:00:00"))
            $afterOr=($clock -ge [TimeSpan]::Parse("09:15:00")); $inSession=(($clock -ge [TimeSpan]::Parse("09:00:00") -and $clock -le [TimeSpan]::Parse("11:30:00")) -or ($clock -ge [TimeSpan]::Parse("12:30:00") -and $clock -le [TimeSpan]::Parse("15:30:00")))
            if ($inOr) {
                if (-not $orHigh.ContainsKey($ticker) -or $price -gt $orHigh[$ticker]) {$orHigh[$ticker]=$price}
                if (-not $orLow.ContainsKey($ticker) -or $price -lt $orLow[$ticker]) {$orLow[$ticker]=$price}
            }

            if (-not $history.ContainsKey($ticker)) {$history[$ticker]=[Collections.ArrayList]::new()}
            $direction = if ($ask -gt 0 -and $price -ge $ask) {"BUY"} elseif ($bid -gt 0 -and $price -le $bid) {"SELL"} elseif ($priceDelta -gt 0) {"BUY"} elseif ($priceDelta -lt 0) {"SELL"} else {"NEUTRAL"}
            [void]$history[$ticker].Add([pscustomobject]@{At=$now;Price=$price;Vwap=$vwap;UnderRatio=$underRatio;Direction=$direction;VolumeDelta=$volumeDelta})
            while ($history[$ticker].Count -gt 0 -and ($now-$history[$ticker][0].At).TotalMinutes -gt 10) {$history[$ticker].RemoveAt(0)}

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

            $quoteCenter=0.0
            if($bid -gt 0 -and $ask -gt 0){$quoteCenter=($bid+$ask)/2}
            elseif($bid -gt 0){$quoteCenter=$bid}
            elseif($ask -gt 0){$quoteCenter=$ask}
            $reference=if($null -ne $referencePrice -and $referencePrice -gt 0){$referencePrice}else{Get-SafeNumber (Get-TableValue $values $r 3) 0.01 10000000}
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
            if ($burst -ge 1.5) {$score += $(if ($priceDelta -gt 0) {10} elseif ($priceDelta -lt 0) {-10} else {0})}
            if($inPreopen){$score=$preopenScore}
            $whipsaw=($crosses -ge 2)
            $signal="監視"
            if($inPreopen){$signal=$preopenPlan}
            elseif ($inSession -and $whipsaw) {$signal="往復ピンタ回避"}
            elseif ($openDecision -eq "初動買い候補") {$signal="初動買い候補"}
            elseif ($openDecision -eq "初動ショート候補") {$signal="初動ショート候補"}
            elseif ($inSession -and $afterOr -and $orHigh.ContainsKey($ticker) -and $vwap -gt 0 -and $price -gt $orHigh[$ticker] -and $price -gt $vwap -and $underRatio -ge 0.52 -and $flowBias -gt 0.05 -and $burst -ge 1.2) {$signal="買いサイン"}
            elseif ($inSession -and $afterOr -and $orLow.ContainsKey($ticker) -and $vwap -gt 0 -and $price -lt $orLow[$ticker] -and $price -lt $vwap -and $underRatio -le 0.48 -and $flowBias -lt -0.05 -and $burst -ge 1.2) {$signal="空売りサイン"}
            elseif (-not $inSession) {$signal="市場時間外"}

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
            $results += [pscustomobject]@{ticker=$ticker;name=$s.Name;sector=$s.Sector;price=$price;volume=$volume;vwap=$vwap;under_ratio=[Math]::Round($underRatio*100,1);under_change=[Math]::Round($uoChange*100,1);under_change_1m=if($null -eq $underChange1m){$null}else{[Math]::Round($underChange1m*100,1)};under_change_5m=if($null -eq $underChange5m){$null}else{[Math]::Round($underChange5m*100,1)};flow_bias=[Math]::Round($flowBias*100,1);buy_flow=[Math]::Round($buyFlow);sell_flow=[Math]::Round($sellFlow);history_seconds=[Math]::Round($historySeconds);time_band=$timeBand;orderflow_state=$orderflowState;tick_watch="常時監視中";volume_burst=[Math]::Round($burst,2);or_high=$orHighValue;or_low=$orLowValue;credit_sell=$creditSell;credit_sell_change=$creditSellChange;credit_buy=$creditBuy;credit_buy_change=$creditBuyChange;credit_ratio=$creditRatio;reference_price=$reference;preopen_quote=[Math]::Round($quoteCenter,1);preopen_gap_pct=if($null -eq $gapPct){$null}else{[Math]::Round($gapPct,2)};preopen_market_imbalance=[Math]::Round($marketImbalance*100,1);preopen_quote_change_5m=if($null -eq $quoteChange5m){$null}else{[Math]::Round($quoteChange5m,2)};preopen_score=[Math]::Round($preopenScore);preopen_plan=$preopenPlan;special_quote=if($hasSpecialSell){"特売り"}elseif($hasSpecialBuy){"特買い"}else{"なし"};open_price=$openPrice;open_decision=$openDecision;score=[Math]::Round($score);signal=$signal;data="LIVE"}
            $previous[$ticker]=[pscustomobject]@{Price=$price;Volume=$volume;UnderRatio=$underRatio}
        }
        if ($snapshotDue) {$lastSnapshotAt=$now}
        foreach ($key in @($seenTicks.Keys)) {if (($now-$seenTicks[$key]).TotalMinutes -gt 30) {$seenTicks.Remove($key)}}

        $kioxia=$results|Where-Object{$_.ticker -eq "285A.T"}|Select-Object -First 1
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
        $qualified=@($results|Where-Object{$_.signal -in @("買いサイン","空売りサイン","初動買い候補","初動ショート候補","買い準備","ショート準備","監視")}|Sort-Object @{Expression={if($_.signal -in @("買いサイン","空売りサイン")){0}elseif($_.signal -in @("初動買い候補","初動ショート候補")){1}elseif($_.signal -in @("買い準備","ショート準備")){2}else{3}}},@{Expression={[Math]::Abs($_.score)};Descending=$true}|Select-Object -First 5)
        $payload=[ordered]@{updated_at=$now.ToString("yyyy-MM-dd HH:mm:ss");source="MarketSpeed II RSS / local PC";universe=100;valid=$validCount;stale=($validCount -lt 90);notice="UNDER/OVER単独では判定しません。歩み値方向は気配比較による推定です。";tdnet_status=$tdnetStatus;kioxia=$kioxia;kioxia_pts=$kioxiaPts;pts_top5=$ptsTop5;ir_pts_top5=$irPtsTop5;top5=$qualified}
        $jsonText=$payload|ConvertTo-Json -Depth 6
        Write-AtomicUtf8 $jsonPath $jsonText
        if (Test-Path (Join-Path (Split-Path $PSScriptRoot -Parent) "index.html")) { Write-AtomicUtf8 $cockpitJsonPath $jsonText }

        $cards = if ($qualified.Count -eq 0) {'<div class="empty">発動条件を満たす候補なし</div>'} else {($qualified|ForEach-Object{
            $cls=if($_.signal -in @("買いサイン","初動買い候補","買い準備")){"buy"}elseif($_.signal -in @("空売りサイン","初動ショート候補","ショート準備")){"sell"}elseif($_.signal -eq "往復ピンタ回避"){"block"}else{"watch"}
            $priorPtsText=if($null -eq $_.prior_pts_gap_pct){"なし"}else{("{0:+0.00;-0.00;0.00}% / 加点 {1:+0;-0;0}" -f $_.prior_pts_gap_pct,$_.prior_pts_boost)}
            '<article class="pick '+$cls+'"><div class="head"><span>'+ (Escape-Html $_.signal) +'</span><b>'+ (Escape-Html $_.name) +'</b><strong>'+([string]$_.score)+'</strong></div><div class="price">'+("{0:N1}" -f $_.price)+'円</div><div class="metrics"><span>VWAP<br><b>'+([string]$_.vwap)+'</b></span><span>UNDER<br><b>'+([string]$_.under_ratio)+'%</b></span><span>板変化<br><b>'+([string]$_.under_change)+'pt</b></span><span>約定偏り<br><b>'+([string]$_.flow_bias)+'%</b></span><span>出来高加速<br><b>'+([string]$_.volume_burst)+'倍</b></span><span>前夜PTS<br><b>'+ (Escape-Html $priorPtsText) +'</b></span></div><small>OR15 '+([string]$_.or_low)+'–'+([string]$_.or_high)+' / '+(Escape-Html $_.sector)+'</small></article>'
        }) -join "`n"}
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
            $orText=if($kioxia.or_high -gt 0){'OR15 '+([string]$kioxia.or_low)+'–'+([string]$kioxia.or_high)}else{'OR15未取得・正式サイン待機'}
            $historyText='蓄積中 '+([string]$kioxia.completed_stat_days)+'/10日'
            if ($null -ne $kioxia.historical_prediction) {$historyText=([string]$kioxia.historical_prediction.prediction)+' 上'+([string]$kioxia.historical_prediction.up_rate_5m)+'%／下'+([string]$kioxia.historical_prediction.down_rate_5m)+'%'}
            $ptsPriceText=if($null -eq $ptsPrice){"取得待ち"}else{("{0:N1}円" -f $ptsPrice)}
            $ptsGapText=if($null -eq $ptsGap){"算出待ち"}else{("{0:+0.00;-0.00;0.00}%" -f $ptsGap)}
            $ptsUnderText=if($null -eq $ptsUnderRatio){"取得待ち"}else{("{0:0.0}%" -f $ptsUnderRatio)}
            $kioxiaCard='<section class="focus '+$kioxiaClass+'"><div class="focus-title"><span>キオクシア専用・常時監視</span><b>'+ (Escape-Html $kioxia.open_decision) +'</b><strong>'+([string]$kioxia.score)+'</strong></div><div class="focus-body"><div class="price">'+("{0:N1}" -f $kioxia.price)+'円</div><div class="metrics"><span>8:55作戦<br><b>'+ (Escape-Html $kioxia.preopen_plan) +'</b></span><span>寄り前気配<br><b>'+([string]$kioxia.preopen_quote)+'円</b></span><span>GU/GD<br><b>'+([string]$kioxia.preopen_gap_pct)+'%</b></span><span>成行偏り<br><b>'+([string]$kioxia.preopen_market_imbalance)+'%</b></span><span>特別気配<br><b>'+ (Escape-Html $kioxia.special_quote) +'</b></span><span>VWAP<br><b>'+([string]$kioxia.vwap)+'</b></span><span>UNDER<br><b>'+([string]$kioxia.under_ratio)+'%</b></span><span>歩み値偏り<br><b>'+([string]$kioxia.flow_bias)+'%</b></span><span>時間帯統計<br><b>'+ (Escape-Html $historyText) +'</b></span><span>JNX夜間PTS<br><b>'+ (Escape-Html $ptsPriceText) +'</b></span><span>東証終値比<br><b>'+ (Escape-Html $ptsGapText) +'</b></span><span>PTS出来高<br><b>'+([string]$ptsVolume)+'</b></span><span>PTS UNDER<br><b>'+ (Escape-Html $ptsUnderText) +'</b></span><span>PTS判定<br><b>'+ (Escape-Html $ptsState) +'</b></span></div></div><small>'+ (Escape-Html $orText) +' / PTSは参考判定。翌朝の気配と出来高で必ず再確認 / 成行禁止</small></section>'
        }
        $html='<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta http-equiv="refresh" content="3"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MS2 LIVE TOP5</title><style>body{margin:0;background:#05090d;color:#edf5fa;font-family:Segoe UI,Yu Gothic,sans-serif}main{max-width:1300px;margin:auto;padding:22px}header{display:flex;justify-content:space-between;align-items:end;border-bottom:1px solid #253541;padding-bottom:16px}h1{margin:0;font-size:29px}h2{margin:28px 0 2px;font-size:22px}.sub{margin:0;color:#8296a5;font-size:12px}header span,.note{color:#8296a5}.status{color:#4be0b6}.focus{margin-top:16px;padding:18px;background:linear-gradient(135deg,#102433,#0b151d);border:1px solid #39708e;border-left:6px solid #42b8f5;border-radius:14px}.focus.buy{border-left-color:#36dfa9}.focus.sell{border-left-color:#ff6370}.focus.block{border-left-color:#f5c451}.focus-title{display:grid;grid-template-columns:1fr auto auto;gap:14px;align-items:center}.focus-title span{font-size:20px;font-weight:800}.focus-title b{padding:7px 12px;border-radius:99px;background:#172630}.focus-title strong{font-size:26px}.focus-body{display:grid;grid-template-columns:210px 1fr;gap:14px;align-items:center}.focus small{display:block;color:#8eb3c8;margin-top:10px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px;margin-top:16px}.pick{background:#0d161e;border:1px solid #253744;border-left:4px solid #789;border-radius:12px;padding:15px}.pick.buy{border-left-color:#36dfa9}.pick.sell{border-left-color:#ff6370}.pick.block{border-left-color:#f5c451}.head{display:grid;grid-template-columns:auto 1fr auto;gap:10px;align-items:center}.head span{font-size:11px;border-radius:99px;background:#172630;padding:5px 8px}.head b{font-size:16px}.head strong{font-size:22px}.price{font-size:29px;font-weight:800;margin:12px 0}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(105px,1fr));gap:5px}.metrics span{background:#111f29;border-radius:7px;padding:8px;color:#8296a5;font-size:10px}.metrics b{color:#e9f3f8;font-size:14px}.pick small{display:block;color:#758895;margin-top:12px}.pick a{color:#55c8ff}.note{margin-top:18px;padding:12px;background:#10171d;border-radius:8px}.empty{padding:50px;text-align:center;color:#8ca0ae}@media(max-width:650px){header{align-items:start;flex-direction:column}.focus-body{grid-template-columns:1fr}.focus-title{grid-template-columns:1fr auto}.metrics{grid-template-columns:1fr 1fr}}</style></head><body><main><header><div><span>MARKETSPEED II RSS</span><h1>デイトレ100銘柄 LIVE TOP5</h1></div><div><b class="status">有効 '+$validCount+'/100</b><br>'+ (Escape-Html $now.ToString("yyyy-MM-dd HH:mm:ss")) +'</div></header>'+$kioxiaCard+'<section class="grid">'+$cards+'</section>'+$ptsSection+$irPtsSection+'<p class="note">UNDER/OVERだけでは売買しません。通常TOP5には翌朝9:15まで前夜PTSを最大±15点加減します。IR急騰PTSはTDnet原文を確認できた監視100銘柄だけを採用し、翌朝は高寄り後の押し目と出来高を再確認します。</p></main></body></html>'
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
                $speaker.Speak(($x.name+"、"+$side+"。現在値"+$x.price+"円。板だけで判断せず、ローソク足を確認してください。"),1)|Out-Null
                $lastSpoken[$key]=$now
            }
            $lastSignal[$key]=$x.signal
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
