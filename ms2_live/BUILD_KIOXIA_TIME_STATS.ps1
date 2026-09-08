param(
    [string]$RecordsRoot = (Join-Path $PSScriptRoot "records"),
    [string]$OutputJson = (Join-Path $PSScriptRoot "kioxia_time_stats.json"),
    [string]$OutputCsv = (Join-Path $PSScriptRoot "kioxia_time_stats.csv")
)

$ErrorActionPreference = "Stop"

function Get-TimeBand([DateTime]$at) {
    $clock = $at.TimeOfDay
    if ($clock -lt [TimeSpan]::Parse("09:15:00")) { return "9時00分から9時15分・OR形成" }
    if ($clock -lt [TimeSpan]::Parse("10:00:00")) { return "9時15分から10時・初動" }
    if ($clock -lt [TimeSpan]::Parse("10:30:00")) { return "10時から10時30分・反転注意" }
    if ($clock -le [TimeSpan]::Parse("11:30:00")) { return "10時30分から前引け" }
    if ($clock -lt [TimeSpan]::Parse("12:30:00")) { return "昼休み" }
    if ($clock -lt [TimeSpan]::Parse("13:00:00")) { return "12時30分から13時・後場初動" }
    if ($clock -lt [TimeSpan]::Parse("14:00:00")) { return "13時から14時" }
    if ($clock -lt [TimeSpan]::Parse("15:00:00")) { return "14時から15時・方向確認" }
    return "15時から大引け・需給注意"
}

function Get-Condition([double]$ratio, [double]$change1m) {
    if ($ratio -ge 0.54 -and $change1m -ge 0.015) { return "買い傾斜" }
    if ($ratio -le 0.46 -and $change1m -le -0.015) { return "売り傾斜" }
    return "均衡"
}

function Add-Sample([hashtable]$table, [string]$key, [object]$sample) {
    if (-not $table.ContainsKey($key)) { $table[$key] = [Collections.ArrayList]::new() }
    [void]$table[$key].Add($sample)
}

function Summarize([string]$band, [string]$condition, [object[]]$samples) {
    $valid5 = @($samples | Where-Object { $null -ne $_.Return5m })
    $valid15 = @($samples | Where-Object { $null -ne $_.Return15m })
    $days = @($samples | Select-Object -ExpandProperty Day -Unique)
    $up5 = @($valid5 | Where-Object { $_.Return5m -gt 0.0015 }).Count
    $down5 = @($valid5 | Where-Object { $_.Return5m -lt -0.0015 }).Count
    $avg5 = if ($valid5.Count) { ($valid5 | Measure-Object Return5m -Average).Average } else { 0 }
    $avg15 = if ($valid15.Count) { ($valid15 | Measure-Object Return15m -Average).Average } else { 0 }
    $upRate = if ($valid5.Count) { 100 * $up5 / $valid5.Count } else { 0 }
    $downRate = if ($valid5.Count) { 100 * $down5 / $valid5.Count } else { 0 }
    $ready = ($days.Count -ge 10 -and $valid5.Count -ge 50)
    $direction = "統計蓄積中"
    if ($ready) {
        if ($upRate -ge 58 -and $avg5 -gt 0.0008) { $direction = "上方向優位" }
        elseif ($downRate -ge 58 -and $avg5 -lt -0.0008) { $direction = "下方向優位" }
        else { $direction = "レンジ優位" }
    }
    return [pscustomobject]@{
        time_band = $band
        condition = $condition
        sample_days = $days.Count
        sample_count = $valid5.Count
        up_rate_5m = [Math]::Round($upRate,1)
        down_rate_5m = [Math]::Round($downRate,1)
        average_return_5m = [Math]::Round($avg5*100,3)
        average_return_15m = [Math]::Round($avg15*100,3)
        prediction = $direction
        ready = $ready
    }
}

function Summarize-Preopen([string]$gapBucket, [string]$plan, [object[]]$samples) {
    $valid = @($samples | Where-Object { $null -ne $_.Return5m -and $null -ne $_.Return15m })
    $days = @($valid | Select-Object -ExpandProperty Day -Unique)
    $up5 = @($valid | Where-Object { $_.Return5m -gt 0.0015 }).Count
    $down5 = @($valid | Where-Object { $_.Return5m -lt -0.0015 }).Count
    $avg5 = if($valid.Count){($valid|Measure-Object Return5m -Average).Average}else{0}
    $avg15 = if($valid.Count){($valid|Measure-Object Return15m -Average).Average}else{0}
    $ready = ($days.Count -ge 10)
    $result = "統計蓄積中"
    if($ready){
        $upRate=100*$up5/$valid.Count; $downRate=100*$down5/$valid.Count
        if($upRate -ge 58 -and $avg15 -gt 0.0008){$result="寄り後上方向優位"}
        elseif($downRate -ge 58 -and $avg15 -lt -0.0008){$result="寄り後下方向優位"}
        else{$result="寄り後レンジ・見送り"}
    }
    return [pscustomobject]@{gap_bucket=$gapBucket;plan=$plan;sample_days=$days.Count;sample_count=$valid.Count;up_rate_5m=if($valid.Count){[Math]::Round(100*$up5/$valid.Count,1)}else{0};down_rate_5m=if($valid.Count){[Math]::Round(100*$down5/$valid.Count,1)}else{0};average_return_5m=[Math]::Round($avg5*100,3);average_return_15m=[Math]::Round($avg15*100,3);prediction=$result;ready=$ready}
}

function Get-GapBucket([double]$gap) {
    if($gap -le -5){return "GD5%以上"}
    if($gap -le -2){return "GD2–5%"}
    if($gap -lt 0){return "小幅GD"}
    if($gap -lt 2){return "小幅GU"}
    if($gap -lt 5){return "GU2–5%"}
    return "GU5%以上"
}

$samplesByKey = @{}
$preopenByKey = @{}
$completedDays = [Collections.ArrayList]::new()
$today = (Get-Date).Date
$includeToday = ((Get-Date).TimeOfDay -ge [TimeSpan]::Parse("15:35:00"))

if (Test-Path $RecordsRoot) {
    foreach ($directory in @(Get-ChildItem -Path $RecordsRoot -Directory | Sort-Object Name)) {
        try { $dayDate = [DateTime]::ParseExact($directory.Name,"yyyy-MM-dd",[Globalization.CultureInfo]::InvariantCulture) }
        catch { continue }
        if ($dayDate.Date -gt $today -or ($dayDate.Date -eq $today -and -not $includeToday)) { continue }
        $uoPath = Join-Path $directory.FullName "under_over.csv"
        $marketPath = Join-Path $directory.FullName "market_snapshots.csv"
        $preopenPath = Join-Path $directory.FullName "preopen.csv"
        if (-not (Test-Path $uoPath) -or -not (Test-Path $marketPath)) { continue }

        $snapByMinute = @{}
        foreach ($row in @(Import-Csv -Path $marketPath | Where-Object { $_.ticker -eq "285A.T" })) {
            $at = $null; $price = 0.0
            if (-not [DateTime]::TryParse($row.captured_at,[ref]$at)) { continue }
            if (-not [Double]::TryParse($row.price,[Globalization.NumberStyles]::Any,[Globalization.CultureInfo]::InvariantCulture,[ref]$price)) { continue }
            if ($price -le 0) { continue }
            $snapByMinute[$at.ToString("yyyyMMddHHmm")] = $price
        }

        $minuteRows = @{}
        foreach ($row in @(Import-Csv -Path $uoPath | Where-Object { $_.ticker -eq "285A.T" })) {
            $at = $null; $ratio = 0.0
            if (-not [DateTime]::TryParse($row.captured_at,[ref]$at)) { continue }
            if (-not [Double]::TryParse($row.under_ratio,[Globalization.NumberStyles]::Any,[Globalization.CultureInfo]::InvariantCulture,[ref]$ratio)) { continue }
            if ($at.TimeOfDay -lt [TimeSpan]::Parse("09:00:00") -or $at.TimeOfDay -gt [TimeSpan]::Parse("15:30:00")) { continue }
            if ($at.TimeOfDay -gt [TimeSpan]::Parse("11:30:00") -and $at.TimeOfDay -lt [TimeSpan]::Parse("12:30:00")) { continue }
            $minuteRows[$at.ToString("yyyyMMddHHmm")] = [pscustomobject]@{At=$at;Ratio=$ratio}
        }
        $ordered = @($minuteRows.Values | Sort-Object At)
        if ($ordered.Count -lt 30) { continue }
        if ($ordered[0].At.TimeOfDay -gt [TimeSpan]::Parse("09:05:00")) { continue }
        if ($ordered[-1].At.TimeOfDay -lt [TimeSpan]::Parse("15:20:00")) { continue }
        [void]$completedDays.Add($directory.Name)
        if(Test-Path $preopenPath){
            $preRows=@(Import-Csv -Path $preopenPath|Where-Object{$_.ticker -eq "285A.T"}|ForEach-Object{
                $at=$null; $gap=0.0; $quote=0.0
                if([DateTime]::TryParse($_.captured_at,[ref]$at) -and [Double]::TryParse($_.gap_pct,[Globalization.NumberStyles]::Any,[Globalization.CultureInfo]::InvariantCulture,[ref]$gap) -and [Double]::TryParse($_.quote_center,[Globalization.NumberStyles]::Any,[Globalization.CultureInfo]::InvariantCulture,[ref]$quote)){
                    [pscustomobject]@{At=$at;Gap=$gap;Quote=$quote;Plan=[string]$_.plan}
                }
            }|Where-Object{$null -ne $_ -and $_.At.TimeOfDay -le [TimeSpan]::Parse("08:58:59")}|Sort-Object At)
            if($preRows.Count -gt 0){
                $p=$preRows[-1]
                $price5=$snapByMinute[$dayDate.ToString("yyyyMMdd")+"0905"]
                $price15=$snapByMinute[$dayDate.ToString("yyyyMMdd")+"0915"]
                $ret5=if($null -ne $price5 -and $p.Quote -gt 0){($price5/$p.Quote)-1}else{$null}
                $ret15=if($null -ne $price15 -and $p.Quote -gt 0){($price15/$p.Quote)-1}else{$null}
                Add-Sample $preopenByKey ((Get-GapBucket $p.Gap)+"|"+$p.Plan) ([pscustomobject]@{Day=$directory.Name;Return5m=$ret5;Return15m=$ret15})
            }
        }
        for ($i=1; $i -lt $ordered.Count; $i++) {
            $x = $ordered[$i]
            $previous = @($ordered | Where-Object { $_.At -le $x.At.AddMinutes(-1) } | Select-Object -Last 1)
            if ($previous.Count -eq 0) { continue }
            $basePrice = $snapByMinute[$x.At.ToString("yyyyMMddHHmm")]
            if ($null -eq $basePrice -or $basePrice -le 0) { continue }
            $price5 = $snapByMinute[$x.At.AddMinutes(5).ToString("yyyyMMddHHmm")]
            $price15 = $snapByMinute[$x.At.AddMinutes(15).ToString("yyyyMMddHHmm")]
            $return5 = if ($null -ne $price5) { ($price5/$basePrice)-1 } else { $null }
            $return15 = if ($null -ne $price15) { ($price15/$basePrice)-1 } else { $null }
            $band = Get-TimeBand $x.At
            $condition = Get-Condition $x.Ratio ($x.Ratio-$previous[-1].Ratio)
            $sample = [pscustomobject]@{Day=$directory.Name;Return5m=$return5;Return15m=$return15}
            Add-Sample $samplesByKey ($band+"|全体") $sample
            Add-Sample $samplesByKey ($band+"|"+$condition) $sample
        }
    }
}

$summary = [Collections.ArrayList]::new()
foreach ($key in @($samplesByKey.Keys | Sort-Object)) {
    $parts = $key -split '\|',2
    [void]$summary.Add((Summarize $parts[0] $parts[1] @($samplesByKey[$key])))
}
$preopenSummary = [Collections.ArrayList]::new()
foreach($key in @($preopenByKey.Keys|Sort-Object)){
    $parts=$key -split '\|',2
    [void]$preopenSummary.Add((Summarize-Preopen $parts[0] $parts[1] @($preopenByKey[$key])))
}
$payload = [ordered]@{
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    ticker = "285A.T"
    completed_days = @($completedDays | Select-Object -Unique).Count
    minimum_days = 10
    minimum_samples = 50
    methodology = "ザラバは1分間隔のUNDER比率と1分変化を5分後・15分後で検証。寄り前は8:55前後のGU/GD帯と準備判定を9:05・9:15で検証。ザラバは10日・50標本、寄り前は10日未満で方向を出さない。"
    rows = @($summary)
    preopen_rows = @($preopenSummary)
}
$json = $payload | ConvertTo-Json -Depth 6
[IO.File]::WriteAllText($OutputJson,$json,[Text.UTF8Encoding]::new($false))
@($summary) | Export-Csv -Path $OutputCsv -NoTypeInformation -Encoding UTF8
Write-Host ("キオクシア時間帯統計: 完了日 " + $payload.completed_days + "日 / 行 " + $summary.Count) -ForegroundColor Green
