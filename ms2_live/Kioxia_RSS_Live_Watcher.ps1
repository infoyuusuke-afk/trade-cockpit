$ErrorActionPreference = "Stop"

$bookPath = Join-Path $PSScriptRoot "Kioxia_MS2_RSS_Live_Signals.xlsx"
if (-not (Test-Path $bookPath)) {
    Write-Host "同じフォルダーに Kioxia_MS2_RSS_Live_Signals.xlsx を置いてください。" -ForegroundColor Red
    Read-Host "Enterで終了"
    exit 1
}

function Write-AtomicUtf8([string]$path, [string]$content) {
    $tmp = "$path.tmp"
    [IO.File]::WriteAllText($tmp, $content, [Text.UTF8Encoding]::new($false))
    # kioxia_watcher_live.json は127.0.0.1経由で他プロセス(ブラウザ)から同時に読まれるため、
    # Move-Item -Force が読み取りロックで失敗することがある。数回だけ短い間隔でリトライする。
    $maxAttempts = 5
    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        try {
            Move-Item -Force $tmp $path -ErrorAction Stop
            return
        } catch {
            if ($attempt -ge $maxAttempts) {
                Write-Host ("Write-AtomicUtf8: " + $path + " への書き込みに" + $maxAttempts + "回失敗: " + $_.Exception.Message) -ForegroundColor Yellow
                if (Test-Path $tmp) { Remove-Item -Force $tmp -ErrorAction SilentlyContinue }
                throw
            }
            Start-Sleep -Milliseconds 150
        }
    }
}

function Start-LocalJsonBridge([string]$jsonFile, [int]$port) {
    # MS2_RSS_100_Collector.ps1と同じ方式のローカルHTTPサーバー。ブラウザ(公開コクピット)が
    # 同一PC上から直接このJSONを読みに来られるようにする（キオクシアタブの一本化のため）。
    return Start-Job -Name ("KIOXIA_WATCHER_JSON_BRIDGE_" + $PID) -ArgumentList $jsonFile,$port -ScriptBlock {
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

# ユーザー方針（2026-09-15）: 「大口が入った値段・足跡」「個人の損切りを誘発しそうな価格帯」の
# 分析依頼への対応。既存の1分足データ・OR15・VWAPだけを使い、表示専用の参考情報として追加する
# （$buy/$shortの条件式・音声通知には一切使わない）。
#
# 大口フットプリント: 完成済み1分足を1本ずつ、直前20本の平均出来高と比較し、出来高が
# しきい値(倍率)以上だった足を「大口の可能性がある出来高」として検出する。あくまで出来高が
# 平常時より大きかった、という事実の検知であり、実際に大口（機関・仕手筋等）の注文だったと
# identifyできるわけではない（歩み値の個別約定明細までは現状取得していないため）。
function Get-VolumeFootprints($bars, [int]$window = 20, [double]$ratioThreshold = 2.5, [int]$maxResults = 3) {
    $results = @()
    if ($null -eq $bars -or $bars.Count -le $window) { return $results }
    for ($i = $window; $i -lt $bars.Count; $i++) {
        $windowBars = $bars[($i - $window)..($i - 1)]
        $avgVol = ($windowBars | Measure-Object Volume -Average).Average
        if ($avgVol -le 0) { continue }
        $ratio = $bars[$i].Volume / $avgVol
        if ($ratio -ge $ratioThreshold) {
            $dir = if ($bars[$i].Close -gt $bars[$i].Open) { "買い優勢" } elseif ($bars[$i].Close -lt $bars[$i].Open) { "売り優勢" } else { "拮抗" }
            $results += [pscustomobject]@{ Time = $bars[$i].TimeText; Price = $bars[$i].Close; Ratio = $ratio; Dir = $dir }
        }
    }
    return @($results | Select-Object -Last $maxResults)
}

# 損切り誘発想定ゾーン: 個人投資家の損切り注文が集中しやすいと一般的に言われる価格帯
# （OR15高値/安値、VWAP、キリの良い節目の価格）を機械的にリストアップするだけの参考情報。
# 実際にその価格帯に損切り注文が集積しているかは板の厚み等からは確認できておらず、
# 一般的な経験則に基づく仮説的な目安に過ぎない点に注意。
function Get-StopClusterZones([double]$price, [double]$orHigh, [double]$orLow, [double]$vwap) {
    $zones = @()
    if ($orHigh -gt 0) { $zones += [pscustomobject]@{ Level = $orHigh; Label = "OR15高値" } }
    if ($orLow -gt 0) { $zones += [pscustomobject]@{ Level = $orLow; Label = "OR15安値" } }
    if ($vwap -gt 0) { $zones += [pscustomobject]@{ Level = $vwap; Label = "VWAP" } }
    if ($price -gt 0) {
        $roundStep = 500.0
        $nearestRound = [math]::Round($price / $roundStep) * $roundStep
        foreach ($mult in @(-1, 0, 1)) {
            $lvl = $nearestRound + ($mult * $roundStep)
            if ([math]::Abs($lvl - $price) -le ($price * 0.02) -and $lvl -gt 0) {
                $zones += [pscustomobject]@{ Level = $lvl; Label = "節目" }
            }
        }
    }
    return @($zones | Sort-Object Level)
}

# ユーザー指摘（2026-09-15）: 「全体的に音声が聞き取りづらい」への対応。
# Watcher・Heartbeat・AUTO_START・100銘柄収集器はそれぞれ別プロセスで独立したSAPI音声を
# 持っているため、複数の音声通知がほぼ同時に鳴ると別々の音声出力が重なって聞き取りづらくなる。
# システム全体で共有する名前付きMutex（Global\KioxiaVoiceMutex）を使い、他プロセスの発話が
# 終わるまで待ってから同期的に(Speak flag=0)話すことで、重なりを防ぐ。
function Invoke-SerializedSpeak($speaker, [string]$text, [int]$timeoutMs = 20000) {
    if ([string]::IsNullOrWhiteSpace($text)) { return }
    try {
        $encoded = [Uri]::EscapeDataString($text)
        $uri = "http://127.0.0.1:28583/announce?level=WATCH&text=" + $encoded
        $r = Invoke-WebRequest -UseBasicParsing -Uri $uri -TimeoutSec ([Math]::Max(3,[int]($timeoutMs/1000)))
        if ($r.StatusCode -ne 200) { throw "Voice bridge HTTP " + $r.StatusCode }
    } catch {
        Write-Host ("[WATCHER VOICE] SBV2 bridge unavailable; no legacy SAPI fallback: " + $_.Exception.Message) -ForegroundColor DarkYellow
    }
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

function Set-CellValue($range, $value, [int]$maxAttempts = 20, [int]$delayMs = 300) {
    # Excel COMへの書き込みが原因不明の一時的なキャスト例外で失敗することがある（切り分け済み・単発では成功する）。
    # 少し待って再試行すれば成功するため、書き込みのたびに使うヘルパー。全て失敗した場合のみ例外を投げる。
    # 既定値は元々4回・150ms（最大600ms）だったが、2026-09-15実機で10本板追加（40セルの一括書込み）に
    # 伴い起動シーケンスが長くなったところ、Heartbeat・100銘柄収集器との同時COMアクセスにより
    # 起動時のセル書き込みが4回リトライを使い切って落ちる事例を2回連続で実機確認した（RssTickList数式、
    # 直後のデータ鮮度セルと、失敗箇所が毎回変わる＝この関数自体の耐性不足が根本原因と判断）。
    # 100銘柄収集器のInvoke-ExcelCom（最大240回・250ms間隔=最大60秒）ほどではないが、
    # 20回・300ms間隔（最大6秒）まで引き上げる（この時点では未検証、これから実機確認する）。
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

function Set-CellFormula($range, $formula, [int]$maxAttempts = 20, [int]$delayMs = 300) {
    # Set-CellValueと同じ理由（起動時の数式設定も同じCOM書き込みの脆さの影響を受けることが実機で判明。
    # 特にDASHBOARD!B5の安全ゲート数式が無音で設定に失敗する事例があったため、起動時の数式設定も
    # 必ずこちらを使う）。既定値は2026-09-15実機検証でSet-CellValueと同じ理由により20回・300msへ引き上げ。
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

# ユーザー方針（2026-09-15）: RssMarketの「歩み1〜4」は価格・時刻のみで約定数量を含まないため、
# 出来高急増（1分足ベース）だけでは「本当の大口注文」か「小口の積み重ね」かを区別できないという
# 限界があった。MS2 RSSには`RssTickList`という別関数があり、直近最大300件のティック（時刻・出来高・
# 約定値）を個別に取得できることを実機で確認した（例: 引け時点で408,700株の単一ティックと、
# その直前の100株刻みの小口ティックを明確に区別できた）。この関数を使い、本当の意味での
# 大口ティック検知と、ティック単位の方向（気配との比較）による歩み値偏りを追加する。
function Read-TickList($sheet, [string]$headerAnchor) {
    try {
        $region = $sheet.Range($headerAnchor).CurrentRegion.Value2
        $rows = @()
        if ($region -is [System.Array] -and $region.Rank -eq 2) {
            for ($r = 2; $r -le $region.GetLength(0); $r++) {
                $rawTime = $region[$r,1]; $vol = $region[$r,2]; $price = $region[$r,3]
                if ($vol -is [double] -and $price -is [double] -and $vol -gt 0 -and $price -gt 0) {
                    try { $timeText = if ($rawTime -is [double]) { [DateTime]::FromOADate($rawTime).ToString("HH:mm:ss") } else { [string]$rawTime } } catch { $timeText = [string]$rawTime }
                    $rows += [pscustomobject]@{ TimeText=$timeText; Volume=[double]$vol; Price=[double]$price }
                }
            }
        }
        return @($rows)
    } catch { return @() }
}

# 15秒足バックテスト用の生ティック永続化（共有シートC-075、GPT提案への対応・2026-09-19）。
# RssTickListは直近最大300件のローリングウィンドウしか保持しないため、既存の2秒間隔ループに
# 便乗して毎回差分（前回まだ見ていないティック）だけを追記し、ザラバ中の全ティックを
# 失わずに蓄積する。ティックは(時刻,価格,出来高)の組でしか識別できず、MS2側に個別約定IDが
# 無いため、同一秒・同価格・同出来高の複数約定は理論上区別不能（GPTが懸念していた重複排除・
# 時刻精度の制約そのもの）。この関数はその制約を回避しようとせず、代わりに「前回ポーリングの
# ティックが今回のウィンドウに1件も残っていない」状態を欠損の疑いとして診断ログに記録する
# ことで、実機で実際にどの程度発生するかを後から検証できるようにする（未検証・要実機確認）。
function Write-TickLogDiff($ticks) {
    $script:tickPollSeq++
    $now = Get-Date
    $windowSize = $ticks.Count
    $currentPollKeys = [System.Collections.Generic.HashSet[string]]::new()
    $newLines = New-Object System.Collections.Generic.List[string]
    foreach ($t in $ticks) {
        $key = $t.TimeText + "|" + $t.Price + "|" + $t.Volume
        [void]$currentPollKeys.Add($key)
        if (-not $script:recentTickKeySet.Contains($key)) {
            [void]$script:recentTickKeySet.Add($key)
            $script:recentTickKeyOrder.Add($key)
            $newLines.Add($now.ToString("yyyy-MM-dd HH:mm:ss") + "," + $t.TimeText + "," + $t.Price + "," + $t.Volume + "," + $script:tickPollSeq)
        }
    }
    # 直近キー保持数を350件程度に制限（300件ウィンドウより少し余裕を持たせた上限、メモリ・比較コスト対策）。
    while ($script:recentTickKeyOrder.Count -gt 350) {
        $oldest = $script:recentTickKeyOrder[0]
        $script:recentTickKeyOrder.RemoveAt(0)
        [void]$script:recentTickKeySet.Remove($oldest)
    }
    if ($newLines.Count -gt 0) {
        $newLines | Out-File -FilePath $script:tickLogPath -Append -Encoding utf8
    }
    $overlap = 0
    foreach ($k in $script:prevPollTickKeys) { if ($currentPollKeys.Contains($k)) { $overlap++ } }
    # 前回ポーリング時点のティックが今回のウィンドウに1件も残っていない＝2秒間で300件が
    # 丸ごと入れ替わった可能性（欠損の疑い）。初回ループ（前回が空）は対象外。
    $suspectedGap = ($script:prevPollTickKeys.Count -gt 0 -and $overlap -eq 0 -and $windowSize -gt 0)
    ($now.ToString("yyyy-MM-dd HH:mm:ss") + "," + $windowSize + "," + $overlap + "," + $newLines.Count + "," + $suspectedGap) | Out-File -FilePath $script:tickDiagLogPath -Append -Encoding utf8
    $script:prevPollTickKeys = $currentPollKeys
}

# 実際に約定した個別ティックのうち、直近ティック群の中央値出来高の$multiplier倍以上のものを
# 「大口ティック候補」として抽出する。歩み1〜4ベースの推定(Get-VolumeFootprints)と異なり、
# これは個々の約定の出来高そのものを見ているため、単一の大口注文であった可能性がより高い
# （それでも複数の小口が同一ティックで約定した結果である可能性はゼロではない）。
function Get-TickFootprints($ticks, [double]$multiplier = 8.0, [int]$maxResults = 3) {
    if ($null -eq $ticks -or $ticks.Count -lt 10) { return @() }
    $sortedVol = @($ticks | ForEach-Object { $_.Volume } | Sort-Object)
    $mid = [int]([math]::Floor($sortedVol.Count / 2))
    $median = if ($sortedVol.Count % 2 -eq 0) { ($sortedVol[$mid-1] + $sortedVol[$mid]) / 2.0 } else { $sortedVol[$mid] }
    if ($median -le 0) { return @() }
    return @($ticks | Where-Object { $_.Volume -ge $median * $multiplier } | Select-Object -First $maxResults)
}

# ティックの約定値を最良気配（買/売）と比較し、買い方主導/売り方主導を出来高で重み付けして
# 歩み値の方向偏りを-100〜+100で算出する。100銘柄収集器の板比率ベースの推定より、実際の
# 約定に基づくため精度が高い。ただし「気配との比較による推定」である点は変わらない。
function Get-TickFlowBias($ticks, [double]$bid, [double]$ask) {
    if ($null -eq $ticks -or $ticks.Count -eq 0 -or $bid -le 0 -or $ask -le 0) { return $null }
    $buyVol = 0.0; $sellVol = 0.0; $mid = ($bid + $ask) / 2.0
    foreach ($t in $ticks) {
        if ($t.Price -ge $ask) { $buyVol += $t.Volume }
        elseif ($t.Price -le $bid) { $sellVol += $t.Volume }
        elseif ($t.Price -gt $mid) { $buyVol += $t.Volume * 0.5 }
        elseif ($t.Price -lt $mid) { $sellVol += $t.Volume * 0.5 }
    }
    $total = $buyVol + $sellVol
    if ($total -le 0) { return $null }
    return [math]::Round((($buyVol - $sellVol) / $total) * 100, 1)
}

# 10本板を読み取る（A870:D879）。$sheet.Range().CurrentRegionは使わず、固定範囲を
# 直接読む（この範囲は隣接する空セルがなく、CurrentRegionが意図せず広い範囲を拾う
# リスクを避けるため）。売買判定には使わない、板圧力の参考表示専用。
function Read-BoardDepth($sheet) {
    $levels = @()
    for ($lvl = 1; $lvl -le 10; $lvl++) {
        try {
            $row = 869 + $lvl
            $askPrice = Get-SafeNumber $sheet.Cells.Item($row,1).Value2 0.01 10000000
            $askQty = Get-SafeNumber $sheet.Cells.Item($row,2).Value2 0 1000000000
            $bidPrice = Get-SafeNumber $sheet.Cells.Item($row,3).Value2 0.01 10000000
            $bidQty = Get-SafeNumber $sheet.Cells.Item($row,4).Value2 0 1000000000
            $levels += [pscustomobject]@{ Level=$lvl; AskPrice=$askPrice; AskQty=$askQty; BidPrice=$bidPrice; BidQty=$bidQty }
        } catch { continue }
    }
    return @($levels)
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
# 実機確認済み（2026-09-15）: A530に数式を置くと、ヘッダー行(時刻/出来高/約定値)がA531に、
# データがA532以降300行に展開される（1M/5Mチャートの表示範囲より十分下のため衝突しない）。
Set-CellFormula $rss.Range("A530") '=RssTickList(,"285A.T",300)'
# 実機確認済み（2026-09-15）: 「RssBoard」という独立関数は存在しない（#NAME?エラーで実機確認）。
# 10本板は既存のRssMarketに「最良売気配値1〜10」「最良買気配値1〜10」（と各数量）という
# 項目名が用意されており、これで取得できることを楽天証券公式ヘルプで確認・実機でも動作確認済み
# （例: 2本目の買いに16,100株の大口壁を実データで検出）。A870〜A879(4列)に配置。
# 40セルを一括で書き込むため、起動直後は他プロセス（Heartbeat・100銘柄収集器）とのCOM競合で
# Set-CellFormula（4回リトライ）を使い切って起動時クラッシュすることを実機で確認した
# （1回目失敗・2回目は正常起動という再現性のあるパターン）。より粘り強いInvoke-ComRetry
# （8回リトライ・500ms間隔、他の起動時COM呼び出しと同じもの）に変更して解消する。
for ($boardLevel = 1; $boardLevel -le 10; $boardLevel++) {
    $boardRow = 869 + $boardLevel
    Invoke-ComRetry { $rss.Range("A$boardRow").FormulaLocal = '=RssMarket("285A.T","最良売気配値' + $boardLevel + '")' } | Out-Null
    Invoke-ComRetry { $rss.Range("B$boardRow").FormulaLocal = '=RssMarket("285A.T","最良売気配数量' + $boardLevel + '")' } | Out-Null
    Invoke-ComRetry { $rss.Range("C$boardRow").FormulaLocal = '=RssMarket("285A.T","最良買気配値' + $boardLevel + '")' } | Out-Null
    Invoke-ComRetry { $rss.Range("D$boardRow").FormulaLocal = '=RssMarket("285A.T","最良買気配数量' + $boardLevel + '")' } | Out-Null
}
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
# ユーザー方針（2026-09-15未明・次フェーズ開始）: 「その日の状況に適応する売買サイン」構築の
# 第一歩として、まずは$buy/$shortの条件式には一切手を加えず、気配値比率(UNDER比率)を
# 単純な固定しきい値(0.4/0.6)で言語化した参考表示のみを追加する。ChatGPTへも共有済み
# （docs/AI_SHARED_SHEET.md C-017）：気配値ログの蓄積が今夜の夜間PTS帯のみでまだ検証材料が
# なく、本格的な適応型モデルは今日のザラバ実データが揃ってから設計する。このしきい値自体は
# 未検証の暫定値であり、あくまでユーザー自身の判断を助ける参考情報として位置づける
# （売買サイン・音声通知・発動条件には一切使わない）。
# A26:L27は既存の結合セルで、アンカーはA26。ラベルと値を分けてB26等へ書こうとすると
# 過去のA5/B5と同じ理由（非アンカーセルへの書き込みは無音で無視される）で表示されないため、
# ラベルと値を1つの文字列に結合してA26へ毎ループ書き込む。

$speaker = $true # V9 voice goes only through the SBV2 bridge on 28583; no Windows SAPI
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

# 15秒足バックテスト用の生ティックログ（共有シートC-075）。ms2_live/*.csvは.gitignore対象
# のためローカル専用、公開リポジトリへは一切アップロードしない（気配値ログ.csvと同じ扱い）。
$script:tickLogPath = Join-Path $PSScriptRoot ("kioxia_ticks_" + (Get-Date -Format "yyyyMMdd") + ".csv")
if (-not (Test-Path $script:tickLogPath)) {
    "recorded_at,tick_time,price,volume,poll_seq" | Out-File -FilePath $script:tickLogPath -Encoding utf8
}
$script:tickDiagLogPath = Join-Path $PSScriptRoot ("kioxia_tick_diag_" + (Get-Date -Format "yyyyMMdd") + ".csv")
if (-not (Test-Path $script:tickDiagLogPath)) {
    "poll_time,window_size,overlap_with_prev,new_appended,suspected_gap" | Out-File -FilePath $script:tickDiagLogPath -Encoding utf8
}
# 途中再起動時に同じティックを二重記録しないよう、既存ログの末尾から直近キーを復元する。
$script:recentTickKeyOrder = [System.Collections.Generic.List[string]]::new()
if (Test-Path $script:tickLogPath) {
    try {
        foreach ($line in (Get-Content $script:tickLogPath -Tail 350)) {
            if ($line -eq "recorded_at,tick_time,price,volume,poll_seq") { continue }
            $cols = $line -split ","
            if ($cols.Count -ge 4) { $script:recentTickKeyOrder.Add($cols[1] + "|" + $cols[2] + "|" + $cols[3]) }
        }
    } catch {}
}
$script:recentTickKeySet = [System.Collections.Generic.HashSet[string]]::new([string[]]$script:recentTickKeyOrder)
$script:prevPollTickKeys = [System.Collections.Generic.HashSet[string]]::new()
$script:tickPollSeq = 0

# キオクシアタブの一本化（ユーザー指示・2026-09-15）: これまでExcelのDASHBOARDシートと
# 公開コクピットのキオクシアタブが別々の計算式で似た指標を出しており「どちらを見ればいいか
# わからない」状態だった。WatcherのDASHBOARD計算結果をJSONとして書き出し、ローカルHTTP
# （127.0.0.1:28582）で配信することで、ブラウザ側がこのJSONを直接読みに行けるようにする。
# Excelは裏で動かしたまま、PC上ではブラウザだけを見ればよい構成にするための土台。
#
# ポート28582（2026-09-25修正・V8）: 以前は28581を使っていたが、AI_COCKPIT_GATEWAY_V8.ps1
# が公開ページ全体をローカルから配信するために同じ28581を使うため、同時起動すると
# 片方がbindに失敗して無言で壊れていた（Start-Jobの例外はここでは検知されない）。
# Watcher専用ポートを28582へ分離し、Controller側の生存監視にも使えるようにした。
$watcherJsonPath = Join-Path $PSScriptRoot "kioxia_watcher_live.json"
$watcherBridgeJob = Start-LocalJsonBridge $watcherJsonPath 28582
Write-Host "キオクシアWatcher連携: http://127.0.0.1:28582/kioxia_watcher_live.json" -ForegroundColor Cyan

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
        #
        # 2026-09-16診断（Heartbeatと同根の問題）: RPC_E_CALL_REJECTED(0x80010001)・
        # VBA_E_IGNORE(0x800AC472)は、Watcher・Heartbeat・100銘柄収集器の同時COMアクセス
        # 競合による一時的なビジー状態が原因と判明した。このCalculate()はループ本体の一番
        # 最初にあり、ここで失敗すると（このtry/catchの外側の仕様どおり）以降の全処理が
        # スキップされ2秒後の次サイクルまで持ち越される。再計算自体は何度呼んでも安全（副作用
        # なし）なため、ここだけはHeartbeatと同様に外側の2秒サイクルを待たず短時間で
        # その場再試行する。ループ本体の残り（ログ書き込み・音声通知等、副作用を伴う処理）は
        # 冪等でないため、丸ごとのリトライはせず既存の「失敗したら次サイクルへ」のままにする。
        for ($calcAttempt = 1; $calcAttempt -le 3; $calcAttempt++) {
            try { $rss.Calculate(); break }
            catch { if ($calcAttempt -eq 3) { throw }; Start-Sleep -Milliseconds 400 }
        }
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
        $ticks = @(Read-TickList $rss "A531")
        Write-TickLogDiff $ticks
        $board = @(Read-BoardDepth $rss)
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
        # $ptsChangeText等は$ptsPriceがnullの分岐では代入されないため、JSON出力用に
        # 毎ループ明示的にリセットする（stale変数バグの再発防止）。
        $ptsChangeText = ""; $ptsQuoteText = ""; $ptsTimeText = ""
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
        # 参考表示のみ（売買判定には使わない）。しきい値0.4/0.6は暫定・未検証（C-017参照）。
        $boardBiasLabel = if (($over + $under) -le 0) { "データなし" } elseif ($underRatio -ge 0.6) { "買い気配優勢" } elseif ($underRatio -le 0.4) { "売り気配優勢" } else { "中立" }

        $signal = "待機"
        $entry = 0; $stop = 0; $target1 = 0; $target2 = 0
        $state = if ($inSession) { "監視中" } elseif ($inNightPts) { "東証終了・JNX夜間PTS時間帯（PTS参考価格はDASHBOARD下部・売買サインには使わない）" } elseif ($inDayPts) { "東証寄付前・JNXデイタイムPTS時間帯（PTS参考価格はDASHBOARD下部・売買サインには使わない）" } else { "市場時間外" }
        $condPrice = "データ待ち"; $condVol = "データ待ち"; $condEma = "データ待ち"; $condOr = "データ待ち"
        $close1 = 0; $open1 = 0; $volRatio = 0; $ema9 = 0; $ema20 = 0; $orHigh = 0; $orLow = 0; $crosses = 0; $barTime = "-"
        $footprintText = "データ待ち"; $stopZoneText = "データ待ち"
        # 実データの個別ティック（RssTickList）ベース。1分足25本の蓄積を待つ必要がないため、
        # 寄り直後から機能する（歩み1〜4ベースの$footprintTextとは別に併記する）。
        # $biasは条件付きでしか代入されないため、JSON出力(kioxia_watcher_live.json)用に
        # 毎ループ明示的にリセットする（100銘柄収集器で見つけた同種のstale変数バグの再発防止）。
        $tickFootprintText = "データ待ち"; $tickFlowBiasText = "データ待ち"; $bias = $null
        if ($ticks.Count -ge 10) {
            $tickFootprints = Get-TickFootprints $ticks 8.0 3
            $tickFootprintText = if ($tickFootprints.Count -eq 0) { "検出なし（直近" + $ticks.Count + "ティック中）" } else { ($tickFootprints | ForEach-Object { "$($_.TimeText) $([math]::Round($_.Price,0))円 $([math]::Round($_.Volume,0))株" }) -join " / " }
            if ($askQuote -gt 0 -and $bidQuote -gt 0) {
                $bias = Get-TickFlowBias $ticks $bidQuote $askQuote
                if ($null -ne $bias) {
                    $biasLabel = if ($bias -ge 20) { "買い優勢" } elseif ($bias -le -20) { "売り優勢" } else { "拮抗" }
                    $tickFlowBiasText = "$biasLabel（$bias、直近$($ticks.Count)ティック）"
                }
            }
        }

        # 10本板（実データ）。売買判定には使わない、板圧力の参考表示専用。
        # $pct等も条件付きでしか代入されないためJSON出力用に毎ループリセットする（上と同じ理由）。
        $boardDepthText = "データ待ち"
        $pct = $null; $totalBidQty = $null; $totalAskQty = $null; $maxBidLevel = $null; $maxAskLevel = $null
        $validLevels = @($board | Where-Object { $null -ne $_.AskQty -or $null -ne $_.BidQty })
        if ($validLevels.Count -ge 3) {
            $totalAskQty = ($validLevels | Measure-Object -Property AskQty -Sum).Sum
            $totalBidQty = ($validLevels | Measure-Object -Property BidQty -Sum).Sum
            $totalQty = $totalAskQty + $totalBidQty
            $pressureText = if ($totalQty -gt 0) { $pct = [math]::Round(($totalBidQty / $totalQty) * 100, 1); "買い厚み比率${pct}%（買計" + [math]::Round($totalBidQty,0) + "株/売計" + [math]::Round($totalAskQty,0) + "株）" } else { "厚み算出不可" }
            $maxBidLevel = $validLevels | Sort-Object BidQty -Descending | Select-Object -First 1
            $maxAskLevel = $validLevels | Sort-Object AskQty -Descending | Select-Object -First 1
            $wallText = "壁: 買$($maxBidLevel.Level)本目$([math]::Round($maxBidLevel.BidPrice,0))円$([math]::Round($maxBidLevel.BidQty,0))株 / 売$($maxAskLevel.Level)本目$([math]::Round($maxAskLevel.AskPrice,0))円$([math]::Round($maxAskLevel.AskQty,0))株"
            $boardDepthText = "$pressureText / $wallText"
        }

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

            # 参考表示のみ（売買判定には使わない）。ユーザー依頼: 大口出来高フットプリント・損切り誘発想定ゾーン
            $footprints = Get-VolumeFootprints $one 20 2.5 3
            $footprintText = if ($footprints.Count -eq 0) { "検出なし（過去約" + $one.Count + "分）" } else { ($footprints | ForEach-Object { "$($_.Time) $([math]::Round($_.Price,0))円 出来高比$([math]::Round($_.Ratio,1))倍($($_.Dir))" }) -join " / " }
            $stopZones = Get-StopClusterZones $price $orHigh $orLow $vwap
            $stopZoneText = if ($stopZones.Count -eq 0) { "データ待ち" } else { (($stopZones | Select-Object -Unique -Property Level,Label | ForEach-Object { "$([math]::Round($_.Level,0))円($($_.Label))" }) -join " / ") }
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
        Set-CellValue $dash.Range("A26") ("気配地合い(参考・未検証): " + $boardBiasLabel + "（UNDER " + [math]::Round($underRatio*100,1) + "%）")
        # A28・A32は非結合セル（既存レイアウトで空いている行）。
        Set-CellValue $dash.Range("A28") ("大口出来高フットプリント(参考・出来高比2.5倍以上・未検証): " + $footprintText)
        Set-CellValue $dash.Range("A32") ("損切り誘発想定ゾーン(参考・経験則・未検証): " + $stopZoneText)
        # A34・A35も非結合セル。RssTickList（実ティック・数量あり）ベースの検知で、
        # 上のA28（歩み1〜4ベースの推定）より個々の約定出来高そのものを見ているため精度が高い。
        Set-CellValue $dash.Range("A34") ("大口ティック検知(実ティック・数量あり・未検証): " + $tickFootprintText)
        Set-CellValue $dash.Range("A35") ("歩み値偏り(実ティックベース・未検証): " + $tickFlowBiasText)
        Set-CellValue $dash.Range("A37") ("10本板(実データ): " + $boardDepthText)
        $dash.Range("A5:H9").Interior.Color = if ($signal -eq "買いサイン") { 0x62B14C } elseif ($signal -eq "空売りサイン") { 0x4E4EFF } elseif ($signal -eq "往復ピンタ回避") { 0x2A8CFF } else { 0x483117 }

        # キオクシアタブ一本化: DASHBOARDへ書いた内容と同じ生の値をJSONでも出力する。
        # ブラウザ側(公開コクピットのキオクシアタブ)がこのJSONを読むことで、Excelを直接
        # 開かなくても同じ内容を見られるようにする。書き込み失敗は監視ループを止めない。
        try {
            $watcherPayload = [ordered]@{
                schema_version = "kioxia-watcher-1.0"
                updated_at = $now.ToString("yyyy-MM-dd HH:mm:ss")
                source = "Kioxia_RSS_Live_Watcher (Excel RSS)"
                state = $state
                signal = $signal
                price = $price
                entry_price = $(if ($entry -ne 0) { $entry } else { $null })
                stop_price = $(if ($stop -ne 0) { $stop } else { $null })
                target1 = $(if ($target1 -ne 0) { $target1 } else { $null })
                target2 = $(if ($target2 -ne 0) { $target2 } else { $null })
                close_1m = $(if ($close1 -ne 0) { $close1 } else { $null })
                open_1m = $(if ($open1 -ne 0) { $open1 } else { $null })
                vwap = $vwap
                ema9 = $(if ($ema9 -ne 0) { $ema9 } else { $null })
                ema20 = $(if ($ema20 -ne 0) { $ema20 } else { $null })
                or15_high = $(if ($orHigh -ne 0) { $orHigh } else { $null })
                or15_low = $(if ($orLow -ne 0) { $orLow } else { $null })
                under_ratio_pct = [math]::Round($underRatio*100,1)
                volume_ratio = $(if ($volRatio -ne 0) { [math]::Round($volRatio,2) } else { $null })
                bar_time = $barTime
                conditions = [ordered]@{ price=$condPrice; volume=$condVol; ema=$condEma; or15=$condOr }
                board_bias_label = $boardBiasLabel
                footprint_text = $footprintText
                stop_zone_text = $stopZoneText
                tick_footprint_text = $tickFootprintText
                tick_flow_bias_text = $tickFlowBiasText
                tick_flow_bias_score = $bias
                board_depth_text = $boardDepthText
                board_bid_ratio_pct = $pct
                board_total_bid_qty = $totalBidQty
                board_total_ask_qty = $totalAskQty
                pts_price = $ptsPrice
                pts_change_pct_text = $ptsChangeText
                pts_quote_text = $ptsQuoteText
                pts_time_text = $ptsTimeText
                tick_count = $ticks.Count
            }
            $watcherJsonText = $watcherPayload | ConvertTo-Json -Depth 4
            Write-AtomicUtf8 $watcherJsonPath $watcherJsonText
        } catch {
            Write-Host ("kioxia_watcher_live.json書き込み失敗（継続します）: " + $_.Exception.Message) -ForegroundColor Yellow
        }

        if ($inSession -and ($signal -eq "買いサイン" -or $signal -eq "空売りサイン") -and (($signal -ne $lastSpokenSignal) -or (((Get-Date) - $lastSpokenAt).TotalMinutes -ge 10))) {
            $spoken = if ($signal -eq "買いサイン") { "キオクシア、買いサイン点灯。発動価格 $entry 円。損切り $stop 円。" } else { "キオクシア、空売りサイン点灯。発動価格 $entry 円。損切り $stop 円。" }
            Invoke-SerializedSpeak $speaker $spoken
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
