param(
    [string]$Root = "C:\AI_Cockpit_OneClick_Starter",
    [string]$RuntimeDir = "",
    [switch]$NoLaunch,
    [switch]$NoPause
)

$ErrorActionPreference = "Continue"
$checks = New-Object System.Collections.Generic.List[object]
$startedAt = Get-Date

function Add-Check([string]$Name,[string]$Status,[string]$Detail,[bool]$Critical=$true) {
    $obj = [pscustomobject]@{
        name = $Name
        status = $Status
        detail = $Detail
        critical = $Critical
        observed_at = (Get-Date).ToString("o")
    }
    $checks.Add($obj) | Out-Null
    $color = if($Status -eq "PASS"){"Green"}elseif($Status -eq "WARN"){"Yellow"}else{"Red"}
    Write-Host ("[{0}] {1} - {2}" -f $Status,$Name,$Detail) -ForegroundColor $color
}

function Test-Port([int]$Port,[int]$TimeoutMs=700) {
    $client = New-Object Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect("127.0.0.1",$Port,$null,$null)
        if(-not $async.AsyncWaitHandle.WaitOne($TimeoutMs,$false)){ return $false }
        $client.EndConnect($async)
        return $true
    } catch { return $false }
    finally { $client.Close() }
}

function Resolve-RuntimeDir {
    $roots = @(
        [Environment]::GetFolderPath("Desktop"),
        (Join-Path $env:USERPROFILE "Desktop"),
        (Join-Path $env:USERPROFILE "OneDrive\Desktop")
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique

    $hits = @()
    foreach($rootPath in $roots) {
        $hits += @(Get-ChildItem -LiteralPath $rootPath -Recurse -File -Filter "MS2_RSS_100_Collector.ps1" -ErrorAction SilentlyContinue)
    }
    $preferred = @($hits | Where-Object { $_.FullName -like "*MarketSpeed II RSS\files*" } | Sort-Object LastWriteTime -Descending)
    if($preferred.Count -gt 0){ return $preferred[0].Directory.FullName }
    $any = @($hits | Sort-Object LastWriteTime -Descending)
    if($any.Count -gt 0){ return $any[0].Directory.FullName }
    return ""
}

function Resolve-Workbook([string]$RootDir,[string]$Ms2Dir) {
    $rootExcel = Join-Path $RootDir "Excel"
    $rootCanonical = Join-Path $rootExcel "Kioxia_MS2_RSS_Live_Signals.xlsx"
    $rootFixed = Join-Path $rootExcel "Kioxia_MS2_RSS_Live_Signals_FIXED.xlsx"
    $runtimeCanonical = Join-Path $Ms2Dir "Kioxia_MS2_RSS_Live_Signals.xlsx"
    $runtimeFixed = Join-Path $Ms2Dir "Kioxia_MS2_RSS_Live_Signals_FIXED.xlsx"

    # Mirror START_AI_COCKPIT_V6.ps1 selection order exactly.
    foreach($candidate in @($rootCanonical,$rootFixed,$runtimeCanonical,$runtimeFixed)) {
        if($candidate -and (Test-Path -LiteralPath $candidate)) { return [IO.Path]::GetFullPath($candidate) }
    }
    return ""
}

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;

public static class CockpitDiagRot {
    [DllImport("ole32.dll")]
    private static extern int GetRunningObjectTable(int reserved, out IRunningObjectTable rot);
    [DllImport("ole32.dll")]
    private static extern int CreateBindCtx(int reserved, out IBindCtx bindCtx);

    public static object FindByIdentity(string expectedFullPath, string bookFileName) {
        IRunningObjectTable rot;
        if (GetRunningObjectTable(0, out rot) != 0 || rot == null) return null;
        IEnumMoniker en;
        rot.EnumRunning(out en);
        en.Reset();
        var mk = new IMoniker[1];
        object uniqueNameMatch = null;
        int nameMatchCount = 0;
        while (en.Next(1, mk, IntPtr.Zero) == 0) {
            IBindCtx ctx;
            CreateBindCtx(0, out ctx);
            try {
                string name;
                mk[0].GetDisplayName(ctx, null, out name);
                if (String.IsNullOrEmpty(name)) continue;
                object obj;
                if (name.EndsWith(expectedFullPath, StringComparison.OrdinalIgnoreCase)) {
                    rot.GetObject(mk[0], out obj);
                    return obj;
                }
                if (name.EndsWith(bookFileName, StringComparison.OrdinalIgnoreCase)) {
                    rot.GetObject(mk[0], out obj);
                    uniqueNameMatch = obj;
                    nameMatchCount++;
                }
            } catch { }
        }
        return nameMatchCount == 1 ? uniqueNameMatch : null;
    }

    public static int CountByFileName(string bookFileName) {
        IRunningObjectTable rot;
        if (GetRunningObjectTable(0, out rot) != 0 || rot == null) return 0;
        IEnumMoniker en;
        rot.EnumRunning(out en);
        en.Reset();
        var mk = new IMoniker[1];
        int count = 0;
        while (en.Next(1, mk, IntPtr.Zero) == 0) {
            IBindCtx ctx;
            CreateBindCtx(0, out ctx);
            try {
                string name;
                mk[0].GetDisplayName(ctx, null, out name);
                if (!String.IsNullOrEmpty(name) &&
                    name.EndsWith(bookFileName, StringComparison.OrdinalIgnoreCase)) count++;
            } catch { }
        }
        return count;
    }
}
'@ -ErrorAction SilentlyContinue

function Wait-Workbook([string]$Path,[int]$TimeoutSeconds=60) {
    $fileName = [IO.Path]::GetFileName($Path)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while((Get-Date) -lt $deadline) {
        try {
            $book = [CockpitDiagRot]::FindByIdentity($Path,$fileName)
            if($null -ne $book){ return $book }
        } catch {}
        Start-Sleep -Seconds 2
    }
    return $null
}

$logDir = Join-Path $Root "Logs"
if(-not(Test-Path -LiteralPath $logDir)){ New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$textLog = Join-Path $logDir ("excel_startup_diag_"+$stamp+".log")
$jsonLog = Join-Path $logDir ("excel_startup_diag_"+$stamp+".json")

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " AI COCKPIT V6 - EXCEL STARTUP DIAGNOSTIC" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""

try {
    if([string]::IsNullOrWhiteSpace($RuntimeDir)){ $RuntimeDir = Resolve-RuntimeDir }
    if([string]::IsNullOrWhiteSpace($RuntimeDir) -or -not(Test-Path -LiteralPath $RuntimeDir)) {
        Add-Check "RuntimeDir" "FAIL" "MS2 runtime folder was not found." $true
    } else {
        Add-Check "RuntimeDir" "PASS" $RuntimeDir $true
    }

    $ms2 = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match "MarketSpeed|MARKETSPEED" })
    if($ms2.Count -gt 0){ Add-Check "MarketSpeedII" "PASS" ("process_count="+$ms2.Count) $true }
    else { Add-Check "MarketSpeedII" "FAIL" "MarketSpeed II is not running." $true }

    $workbookPath = ""
    if(-not [string]::IsNullOrWhiteSpace($RuntimeDir)) { $workbookPath = Resolve-Workbook $Root $RuntimeDir }
    if([string]::IsNullOrWhiteSpace($workbookPath)) {
        Add-Check "WorkbookFile" "FAIL" "Kioxia workbook file was not found." $true
    } else {
        $hash = ""
        try { $hash = (Get-FileHash -LiteralPath $workbookPath -Algorithm SHA256).Hash } catch {}
        Add-Check "WorkbookFile" "PASS" ($workbookPath+" sha256="+$hash) $true
    }

    $excelProcesses = @(Get-Process EXCEL -ErrorAction SilentlyContinue)
    if($excelProcesses.Count -le 1){ Add-Check "ExcelProcessCount" "PASS" ("count="+$excelProcesses.Count) $false }
    else { Add-Check "ExcelProcessCount" "WARN" ("count="+$excelProcesses.Count+"; multiple Excel processes can cause ambiguity.") $false }

    $book = $null
    if(-not [string]::IsNullOrWhiteSpace($workbookPath)) {
        $fileName = [IO.Path]::GetFileName($workbookPath)
        $nameCount = 0
        try { $nameCount = [CockpitDiagRot]::CountByFileName($fileName) } catch {}
        if($nameCount -gt 1) {
            Add-Check "WorkbookIdentity" "FAIL" ("duplicate_open_workbooks="+$nameCount) $true
        } else {
            $book = [CockpitDiagRot]::FindByIdentity($workbookPath,$fileName)
            if($null -eq $book -and -not $NoLaunch) {
                Add-Check "WorkbookLaunch" "WARN" "Workbook was not open; requesting normal shell launch." $false
                try { Start-Process -FilePath $workbookPath | Out-Null } catch {}
                $book = Wait-Workbook $workbookPath 60
            }
            if($null -ne $book) {
                $fullName = ""
                try { $fullName = [string]$book.FullName } catch {}
                Add-Check "WorkbookIdentity" "PASS" ("unique workbook attached; FullName="+$fullName) $true
            } else {
                Add-Check "WorkbookIdentity" "FAIL" "Workbook did not register uniquely in Excel ROT." $true
            }
        }
    }

    if($null -ne $book) {
        try {
            $rss = $book.Worksheets.Item("RSS" + [char]0x63A5 + [char]0x7D9A)
            $probeAddresses = @("B3","B4")
            $liveFound = $false
            $probeDetail = New-Object System.Collections.Generic.List[string]
            foreach($addr in $probeAddresses) {
                try {
                    $cell = $rss.Range($addr)
                    $formula = [string]$cell.FormulaLocal
                    $value = $cell.Value2
                    $num = 0.0
                    $ok = ($formula -match "RssMarket") -and [double]::TryParse([string]$value,[ref]$num) -and $num -gt 0
                    $probeDetail.Add(($addr+": formula="+$formula+" value="+[string]$value)) | Out-Null
                    if($ok){ $liveFound = $true }
                } catch {}
            }
            if($liveFound){ Add-Check "Rss285AProbe" "PASS" ($probeDetail -join " | ") $true }
            else { Add-Check "Rss285AProbe" "FAIL" (($probeDetail -join " | ")+"; no positive RssMarket value.") $true }
        } catch {
            Add-Check "Rss285AProbe" "FAIL" ("RSS sheet read failed: "+$_.Exception.Message) $true
        }
    }

    foreach($port in @(28580,28581,28582)) {
        $role = if($port -eq 28580){"Collector"}elseif($port -eq 28581){"Gateway"}else{"ExcelWatcher"}
        if(Test-Port $port){ Add-Check ("Port"+$port) "PASS" ($role+" is listening.") $true }
        else { Add-Check ("Port"+$port) "FAIL" ($role+" is not listening.") $true }
    }

    $processPatterns = [ordered]@{
        Collector = "MS2_RSS_100_Collector\.ps1"
        Watcher = "Kioxia_RSS_Live_Watcher\.ps1"
        Heartbeat = "Kioxia_Safety_Heartbeat\.ps1"
        Gateway = "AI_Cockpit_Local_Gateway\.ps1"
    }
    $allProcesses = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    foreach($key in $processPatterns.Keys) {
        $pattern = $processPatterns[$key]
        $matches = @($allProcesses | Where-Object { ([string]$_.CommandLine) -match $pattern })
        if($matches.Count -gt 0){ Add-Check ("Process"+$key) "PASS" ("count="+$matches.Count) $false }
        else { Add-Check ("Process"+$key) "WARN" "process not found." $false }
    }

    try {
        if(Test-Port 28580) {
            $j = Invoke-RestMethod ("http://127.0.0.1:28580/live_ms2.json?t="+[DateTimeOffset]::Now.ToUnixTimeMilliseconds()) -TimeoutSec 3
            $age = $null
            if($j.updated_at) {
                try { $age = [Math]::Round(((Get-Date)-([DateTime]::Parse([string]$j.updated_at))).TotalSeconds,1) } catch {}
            }
            if($j.schema_version -eq "ms2-common-1.1" -and $null -ne $age -and $age -le 60) {
                Add-Check "CollectorFreshness" "PASS" ("schema="+$j.schema_version+" age_seconds="+$age) $true
            } else {
                Add-Check "CollectorFreshness" "FAIL" ("schema="+[string]$j.schema_version+" age_seconds="+[string]$age) $true
            }
        }
    } catch {
        Add-Check "CollectorFreshness" "FAIL" ("live_ms2 read failed: "+$_.Exception.Message) $true
    }

    try {
        if(Test-Port 28581) {
            $h = Invoke-RestMethod ("http://127.0.0.1:28581/health?t="+[DateTimeOffset]::Now.ToUnixTimeMilliseconds()) -TimeoutSec 3
            if($h.live_json_exists){ Add-Check "GatewayHealth" "PASS" ("live_json_mtime="+[string]$h.live_json_mtime) $true }
            else { Add-Check "GatewayHealth" "FAIL" "Gateway cannot see live_ms2.json." $true }
        }
    } catch {
        Add-Check "GatewayHealth" "FAIL" ("gateway health read failed: "+$_.Exception.Message) $true
    }

    try {
        if(Test-Port 28582) {
            $w = Invoke-RestMethod ("http://127.0.0.1:28582/kioxia_watcher_live.json?t="+[DateTimeOffset]::Now.ToUnixTimeMilliseconds()) -TimeoutSec 3
            $watchAge = $null
            if($w.updated_at) {
                try { $watchAge = [Math]::Round(((Get-Date)-([DateTime]::Parse([string]$w.updated_at))).TotalSeconds,1) } catch {}
            }
            if($null -ne $watchAge -and $watchAge -le 60){ Add-Check "WatcherFreshness" "PASS" ("age_seconds="+$watchAge) $true }
            else { Add-Check "WatcherFreshness" "FAIL" ("age_seconds="+[string]$watchAge) $true }
        }
    } catch {
        Add-Check "WatcherFreshness" "FAIL" ("watcher JSON read failed: "+$_.Exception.Message) $true
    }
}
catch {
    Add-Check "DiagnosticRuntime" "FAIL" $_.Exception.Message $true
}

$criticalFails = @($checks | Where-Object { $_.critical -and $_.status -eq "FAIL" })
$summary = [ordered]@{
    schema_version = "excel-startup-diag-1.0"
    started_at = $startedAt.ToString("o")
    completed_at = (Get-Date).ToString("o")
    root = $Root
    runtime_dir = $RuntimeDir
    pass = ($criticalFails.Count -eq 0)
    critical_fail_count = $criticalFails.Count
    checks = @($checks)
}

$summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $jsonLog -Encoding UTF8
@(
    "AI COCKPIT V6 EXCEL STARTUP DIAGNOSTIC"
    "completed_at="+$summary.completed_at
    "pass="+$summary.pass
    "critical_fail_count="+$summary.critical_fail_count
    ""
    ($checks | ForEach-Object { "["+$_.status+"] "+$_.name+" - "+$_.detail })
) | Set-Content -LiteralPath $textLog -Encoding UTF8

Write-Host ""
Write-Host ("Diagnostic log: "+$textLog) -ForegroundColor Cyan
Write-Host ("JSON log      : "+$jsonLog) -ForegroundColor Cyan
$exitCode = 0
if($criticalFails.Count -eq 0) {
    Write-Host "DIAGNOSTIC PASS" -ForegroundColor Green
} else {
    $exitCode = 2
    Write-Host ("DIAGNOSTIC FAIL - critical failures: "+$criticalFails.Count) -ForegroundColor Red
    Write-Host "Send the newest excel_startup_diag_*.log if troubleshooting is needed." -ForegroundColor Yellow
}
if(-not $NoPause) {
    Write-Host ""
    Read-Host "Press Enter to close this diagnostic window" | Out-Null
}
if($NoPause) { exit $exitCode }
