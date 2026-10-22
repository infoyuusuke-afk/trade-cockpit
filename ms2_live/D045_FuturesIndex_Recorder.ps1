<#
D-045 optional sidecar: six futures/index series, RESEARCH RECORDING ONLY.
DO NOT add to the V10 launcher or scheduler. Existing Collector/Excel safety
contracts are untouched. Probe uses ONE unsaved throwaway Excel workbook.
Install/Once/Run require D-019, D-035 AND the exact OWNER cutover approval.
No broker/order calls, no network/API, no raw market data printed.
#>
[CmdletBinding()]
param(
    [ValidateSet("Probe","Install","Once","Run")][string]$Mode = "Probe",
    [string]$N225MiniMonth = "",
    [string]$TopixMonth = "",
    [string]$GrowthMonth = "",
    [string]$ExpectedWorkbookPath = "",
    [string]$PrivateDir = "",
    [int]$IntervalSeconds = 10,
    [int]$MaxSamples = 1,
    [switch]$V10StoppedConfirmed,
    [switch]$RightsReviewed,
    [switch]$D035Accepted,
    [switch]$OwnerReleaseApproved
)
$ErrorActionPreference = "Stop"
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$script:RealSubmitAllowed = $false
$script:SheetName = "D045_FUTURES_INDEX"
$script:ProbeSheetName = "D045_PROBE"

function Assert-D045Months {
    foreach ($m in @($N225MiniMonth,$TopixMonth,$GrowthMonth)) {
        if ($m -cnotmatch '^20\d{2}(03|06|09|12)$') { throw "D045_EXPLICIT_CONTRACT_MONTH_REQUIRED" }
        if ($m -lt (Get-Date).ToString("yyyyMM")) { throw "D045_EXPIRED_CONTRACT_MONTH" }
    }
}
function Assert-D045SingleExcel {
    $procs = @(Get-Process -Name "EXCEL" -ErrorAction SilentlyContinue)
    if ($procs.Count -ne 1) { throw "D023_REQUIRES_EXACTLY_ONE_EXCEL_PROCESS" }
    # The COM object MUST belong to the sole Excel process and workbook.
    $app = [Runtime.InteropServices.Marshal]::GetActiveObject("Excel.Application")
    if ($null -eq $app -or $app.Workbooks.Count -ne 1) { throw "D023_FOREIGN_WORKBOOK_OR_UNVERIFIED_EXCEL" }
    return $app
}
function Assert-D045NoRunningV10 {
    if (-not $V10StoppedConfirmed) { throw "V10_STOP_CONFIRMATION_REQUIRED" }
    try {
        $processes = @(Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe' OR Name = 'pwsh.exe'" -ErrorAction Stop)
        foreach ($proc in $processes) {
            $line = [string]$proc.CommandLine
            if ($line -match '(?i)(AI_COCKPIT_CONTROLLER_V10|MS2_RSS_100_Collector|AI_COCKPIT_GATEWAY_V10)') {
                throw "V10_PROCESS_STILL_RUNNING"
            }
        }
    } catch {
        if ($_.Exception.Message -eq "V10_PROCESS_STILL_RUNNING") { throw }
        throw "V10_PROCESS_STATUS_UNVERIFIED"
    }
}
function Assert-D045LiveGate {
    if (-not ($RightsReviewed -and $D035Accepted -and $OwnerReleaseApproved)) {
        throw "D019_D035_OWNER_RELEASE_GATE_NOT_MET"
    }
    if ([string]::IsNullOrWhiteSpace($PrivateDir)) { throw "PRIVATE_OUTPUT_REQUIRED" }
    if (-not [IO.Path]::IsPathRooted($PrivateDir) -or $PrivateDir.StartsWith('\\')) {
        throw "PRIVATE_OUTPUT_NOT_LOCAL_ABSOLUTE"
    }
    if (-not (Test-Path -LiteralPath $PrivateDir -PathType Container)) {
        throw "PRIVATE_OUTPUT_MUST_PREEXIST"
    }
    if ([string]::IsNullOrWhiteSpace($ExpectedWorkbookPath) -or
        -not [IO.Path]::IsPathRooted($ExpectedWorkbookPath)) {
        throw "CANONICAL_WORKBOOK_PATH_REQUIRED"
    }
    if ([IO.Path]::GetFileName($ExpectedWorkbookPath) -cne "Kioxia_MS2_RSS_Live_Signals.xlsx") {
        throw "WRONG_V10_WORKBOOK_NAME"
    }
}
function Get-D045Workbook {
    param([string]$CurrentMode)
    $app = Assert-D045SingleExcel
    $book = $app.Workbooks.Item(1)
    if ($CurrentMode -eq "Probe") {
        Assert-D045NoRunningV10
        if ([string]$book.Name -eq "Kioxia_MS2_RSS_Live_Signals.xlsx") { throw "PROBE_MUST_NOT_TOUCH_V10_BOOK" }
        # Only an unsaved new workbook. Saving/closing is ALWAYS a human action.
        if ($book.Path -ne "") { throw "PROBE_REQUIRES_UNSAVED_TEMP_WORKBOOK" }
    } else {
        Assert-D045LiveGate
        $actualPath = [IO.Path]::GetFullPath([string]$book.FullName)
        $expectedPath = [IO.Path]::GetFullPath($ExpectedWorkbookPath)
        if (-not [string]::Equals($actualPath,$expectedPath,[StringComparison]::OrdinalIgnoreCase)) {
            throw "WRONG_CANONICAL_WORKBOOK"
        }
    }
    return $book
}
function Initialize-D045Sheet {
    param($Book, [bool]$Probe)
    $name = $(if ($Probe) { $script:ProbeSheetName } else { $script:SheetName })
    $sheet = $null
    try { $sheet = $Book.Worksheets.Item($name) } catch { $sheet = $null }
    if ($null -ne $sheet) { throw "D045_SHEET_ALREADY_EXISTS_REVIEW_BEFORE_REWRITE" }
    $sheet = $Book.Worksheets.Add()
    $sheet.Name = $name
    $headers = @("series_id","name","symbol","contract_month","source_date","price",
                 "source_time","volume","vwap","best_bid","best_ask","best_bid_size","best_ask_size")
    for ($i=0; $i -lt $headers.Count; $i++) { $sheet.Cells.Item(1,$i+1).Value2 = $headers[$i] }
    $items = @(
        @("N225_MINI_F","日経225ミニ先物","N225MF",$N225MiniMonth,"FOP"),
        @("TOPIX_F","TOPIX先物","TOPXF",$TopixMonth,"FOP"),
        @("GROWTH250_F","東証グロース市場250指数先物","MOTF",$GrowthMonth,"FOP"),
        @("N225_I","日経225指数","N225","","INDEX"),
        @("TOPIX_I","TOPIX指数","TOPX","","INDEX"),
        @("GROWTH250_I","東証グロース市場250指数","MTHR","","INDEX")
    )
    for ($i=0; $i -lt 6; $i++) {
        $r=$i+2; $t=$items[$i]
        $sheet.Cells.Item($r,1).Value2=$t[0]
        $sheet.Cells.Item($r,2).Value2=$t[1]
        $sheet.Cells.Item($r,4).Value2=[string]$t[3]
        if ($t[4] -eq "FOP") {
            $sheet.Cells.Item($r,3).FormulaLocal='=RssFOPCode("'+$t[2]+'","'+$t[3]+'")'
            $fields = @("現在日付","現在値","現在値詳細時刻","出来高","出来高加重平均",
                        "最良買気配値1","最良売気配値1","最良買気配数量1","最良売気配数量1")
            for ($j=0; $j -lt $fields.Count; $j++) {
                $sheet.Cells.Item($r,$j+5).FormulaLocal='=RssFOPMarket(C'+$r+',"'+$fields[$j]+'")'
            }
        } else {
            $sheet.Cells.Item($r,3).Value2=$t[2]
            $fields = @("現在日付","現在値","更新時刻","出来高")
            for ($j=0; $j -lt $fields.Count; $j++) {
                $sheet.Cells.Item($r,$j+5).FormulaLocal='=RssIndexMarket(C'+$r+',"'+$fields[$j]+'")'
            }
        }
    }
    # The page is separate from existing 100銘柄RSS/JNX/IR sheets.
    # No workbook.Save, no Excel.Quit, no recalculation, no order formula.
    if (-not $Probe) { $sheet.Visible = 0 }
    return $sheet
}
function Get-D045Cell {
    param($Table, [int]$Row, [int]$Column)
    if ($null -eq $Table -or $Table.Rank -ne 2) { throw "D045_RANGE_INVALID" }
    return $Table.GetValue($Table.GetLowerBound(0)+$Row-1,
                           $Table.GetLowerBound(1)+$Column-1)
}
function Get-D045Date {
    param($Value)
    if ($null -eq $Value) { return "" }
    if ($Value -is [double] -or $Value -is [int]) {
        try { return [DateTime]::FromOADate([double]$Value).ToString("yyyy/MM/dd") } catch { return "" }
    }
    if ([string]$Value -cmatch '^\d{4}/\d\d/\d\d$') { return [string]$Value }
    return ""
}
function Get-D045Time {
    param($Value, [bool]$Futures)
    if ($null -eq $Value) { return "" }
    if ($Value -is [double] -or $Value -is [int]) {
        try {
            $format=$(if ($Futures) { "HH:mm:ss" } else { "HH:mm" })
            return [DateTime]::FromOADate([double]$Value).ToString($format)
        } catch { return "" }
    }
    $v=[string]$Value
    if ($Futures -and $v -cmatch '^\d\d:\d\d:\d\d$') { return $v }
    if (-not $Futures -and $v -cmatch '^\d\d:\d\d$') { return $v }
    return ""
}
function Get-D045Numeric {
    param($Value)
    if ($null -eq $Value -or $Value -is [bool]) { return $null }
    if ($Value -is [string]) { return $null } # Excel error/placeholder must not become a number
    try {
        $d=[double]$Value
        if ([double]::IsNaN($d) -or [double]::IsInfinity($d) -or $d -lt 0) { return $null }
        return $d
    } catch { return $null }
}
function Get-D045Snapshot {
    param($Sheet)
    $table=$Sheet.Range("A2:M7").Value2  # ONE COM read for six instruments
    $tokyo=[TimeZoneInfo]::FindSystemTimeZoneById("Tokyo Standard Time")
    $stamp=[TimeZoneInfo]::ConvertTime([DateTimeOffset]::Now,$tokyo).ToString("yyyy-MM-ddTHH:mm:sszzz")
    $expectedIds=@("N225_MINI_F","TOPIX_F","GROWTH250_F","N225_I","TOPIX_I","GROWTH250_I")
    $rows=@()
    for ($i=1; $i -le 6; $i++) {
        $futures=($i -le 3);$id=[string](Get-D045Cell $table $i 1)
        if ($id -cne $expectedIds[$i-1]) { throw "D045_SHEET_ROW_IDENTITY_MISMATCH" }
        $sym=[string](Get-D045Cell $table $i 3)
        $month=$(if ($futures) { [string](Get-D045Cell $table $i 4) } else { $null })
        $fields=[ordered]@{
            instrument_id=$id; kind=$(if($futures){"FOP"}else{"INDEX"})
            symbol=$sym; contract_month=$month
            source_date=(Get-D045Date (Get-D045Cell $table $i 5))
            price=(Get-D045Numeric (Get-D045Cell $table $i 6))
            source_time=(Get-D045Time (Get-D045Cell $table $i 7) $futures)
            volume=(Get-D045Numeric (Get-D045Cell $table $i 8))
            vwap=$(if($futures){Get-D045Numeric (Get-D045Cell $table $i 9)}else{$null})
            best_bid=$(if($futures){Get-D045Numeric (Get-D045Cell $table $i 10)}else{$null})
            best_ask=$(if($futures){Get-D045Numeric (Get-D045Cell $table $i 11)}else{$null})
            best_bid_size=$(if($futures){Get-D045Numeric (Get-D045Cell $table $i 12)}else{$null})
            best_ask_size=$(if($futures){Get-D045Numeric (Get-D045Cell $table $i 13)}else{$null})
        }
        $rows += [pscustomobject]$fields
    }
    return [ordered]@{
        schema_version="100b-d045-six-series-snapshot-v1"
        observed_at_jst=$stamp; rows=@($rows); real_submit_allowed=$false
    }
}
function Invoke-D045Recorder {
    param($Book)
    $sheet=$null
    try { $sheet=$Book.Worksheets.Item($script:SheetName) } catch { throw "D045_SHEET_NOT_INSTALLED" }
    $snapshot=Get-D045Snapshot $sheet
    $json=$snapshot | ConvertTo-Json -Depth 6 -Compress
    $python=Get-Command python -ErrorAction Stop
    $recorder=Join-Path $PSScriptRoot "d045_futures_index_record.py"
    $argsList=@($recorder,"--write","--rights-reviewed","--d035-accepted",
                "--owner-release-approved","--private-dir",$PrivateDir)
    $result=$json | & $python.Source @argsList
    if ($LASTEXITCODE -notin @(0,2)) { throw "D045_RECORDER_BLOCKED_OR_UNAVAILABLE" }
    # Output contains only record counts and reason codes; never prices.
    return [string]($result | Select-Object -Last 1)
}
if ($IntervalSeconds -lt 10 -or $IntervalSeconds -gt 60) { throw "D045_SAMPLE_INTERVAL_OUT_OF_BOUNDS" }
Assert-D045Months
$book=Get-D045Workbook $Mode
if ($Mode -eq "Probe") {
    $null=Initialize-D045Sheet $book $true
    Write-Output "D045_PROBE_FORMULAS_READY; SIX_SERIES; DO_NOT_SAVE; CLOSE_TEMP_BOOK_WITHOUT_SAVING"
    return
}
if ($Mode -eq "Install") {
    $null=Initialize-D045Sheet $book $false
    Write-Output "D045_SHEET_INSTALLED_IN_MEMORY; NOT_SAVED; NO_LIVE_ACTIVATION"
    return
}
if ($Mode -eq "Once") {
    Write-Output (Invoke-D045Recorder $book)
    return
}
if ($Mode -eq "Run") {
    $mutex=New-Object System.Threading.Mutex($false, "Local\100B_D045_SIX_SERIES_RECORDER")
    if (-not $mutex.WaitOne(0)) { throw "D045_RECORDER_ALREADY_RUNNING" }
    try {
        $count=0
        while ($MaxSamples -le 0 -or $count -lt $MaxSamples) {
            $timer=[Diagnostics.Stopwatch]::StartNew()
            try { Write-Output (Invoke-D045Recorder $book) }
            catch { Write-Warning ("D045_UNAVAILABLE: " + $_.Exception.Message) }
            $timer.Stop()
            if ($timer.ElapsedMilliseconds -gt 2000) { throw "D045_READER_EXCEEDS_2S_PERFORMANCE_ABORT" }
            $count++
            Start-Sleep -Seconds $IntervalSeconds
        }
    } finally { $mutex.ReleaseMutex(); $mutex.Dispose() }
}
