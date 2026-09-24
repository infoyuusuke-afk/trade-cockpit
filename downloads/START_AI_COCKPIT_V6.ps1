param([string]$Root = "C:\AI_Cockpit_OneClick_Starter")

$LauncherBuild = "V6-PS51-ASCII-20260925-01"

$ErrorActionPreference = "Stop"
$sw = [Diagnostics.Stopwatch]::StartNew()

function Show-Step([int]$Pct,[string]$Msg){
    $sec=[Math]::Round($sw.Elapsed.TotalSeconds,1)
    Write-Host ("[{0,3}%] {1} ({2}s)" -f $Pct,$Msg,$sec) -ForegroundColor Cyan
    Write-Progress -Activity "AI Cockpit startup" -Status $Msg -PercentComplete $Pct
}

function Test-Port([int]$Port,[int]$TimeoutMs=500){
    $c=New-Object Net.Sockets.TcpClient
    try{
        $a=$c.BeginConnect("127.0.0.1",$Port,$null,$null)
        if(-not $a.AsyncWaitHandle.WaitOne($TimeoutMs,$false)){ return $false }
        $c.EndConnect($a)
        return $true
    }catch{ return $false }
    finally{ $c.Close() }
}

function Resolve-RuntimeDir {
    $roots=@(
        [Environment]::GetFolderPath("Desktop"),
        (Join-Path $env:USERPROFILE "Desktop"),
        (Join-Path $env:USERPROFILE "OneDrive\Desktop")
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique
    $hits=foreach($r in $roots){
        Get-ChildItem -LiteralPath $r -Recurse -File -Filter "MS2_RSS_100_Collector.ps1" -ErrorAction SilentlyContinue
    }
    $preferred=@($hits | Where-Object { $_.FullName -like "*MarketSpeed II RSS\files*" } | Sort-Object LastWriteTime -Descending | Select-Object -First 1)
    if($preferred.Count -gt 0){ return $preferred[0].Directory.FullName }
    $any=@($hits | Sort-Object LastWriteTime -Descending | Select-Object -First 1)
    if($any.Count -gt 0){ return $any[0].Directory.FullName }
    throw "Runtime folder not found."
}

function Stop-Managed {
    $patterns=@(
        "MS2_RSS_100_Collector\.ps1",
        "Kioxia_Safety_Heartbeat\.ps1",
        "Kioxia_RSS_Live_Watcher\.ps1",
        "AI_Cockpit_Local_Gateway\.ps1"
    )
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object {
        $cmd=[string]$_.CommandLine
        if([string]::IsNullOrWhiteSpace($cmd)){ return }
        foreach($p in $patterns){
            if($cmd -match $p){
                try{ Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop }catch{}
                break
            }
        }
    }
}

function Stop-ExcelBoundManaged {
    $patterns=@(
        "MS2_RSS_100_Collector\.ps1",
        "Kioxia_Safety_Heartbeat\.ps1",
        "Kioxia_RSS_Live_Watcher\.ps1"
    )
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object {
        $cmd=[string]$_.CommandLine
        if([string]::IsNullOrWhiteSpace($cmd)){ return }
        foreach($p in $patterns){
            if($cmd -match $p){
                try{ Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop }catch{}
                break
            }
        }
    }
}

function Release-ComObjectSafe($obj){
    if($null -eq $obj){ return }
    try{
        if([Runtime.InteropServices.Marshal]::IsComObject($obj)){
            [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($obj)
        }
    }catch{}
}

function Close-EmptyExcelApplication {
    $app=$null
    $books=$null
    try{
        $app=[Runtime.InteropServices.Marshal]::GetActiveObject("Excel.Application")
        $books=$app.Workbooks
        $count=[int]$books.Count
        if($count -eq 0){
            Write-Host "      Closing orphan Excel instance with zero workbooks..." -ForegroundColor Yellow
            try{$app.DisplayAlerts=$false}catch{}
            try{$app.Quit()}catch{}
        }
    }catch{
    }finally{
        Release-ComObjectSafe $books
        Release-ComObjectSafe $app
        $books=$null
        $app=$null
        [GC]::Collect()
        [GC]::WaitForPendingFinalizers()
    }
}

function Find-Workbook([string]$RootDir,[string]$RuntimeDir){
    $rootExcel=Join-Path $RootDir "Excel"
    $rootCanonical=Join-Path $rootExcel "Kioxia_MS2_RSS_Live_Signals.xlsx"
    $rootFixed=Join-Path $rootExcel "Kioxia_MS2_RSS_Live_Signals_FIXED.xlsx"
    $runtimeCanonical=Join-Path $RuntimeDir "Kioxia_MS2_RSS_Live_Signals.xlsx"
    $runtimeFixed=Join-Path $RuntimeDir "Kioxia_MS2_RSS_Live_Signals_FIXED.xlsx"

    # The canonical name is the only runtime identity. Never overwrite an
    # existing canonical workbook with FIXED on every startup.
    if(Test-Path -LiteralPath $rootCanonical){ return $rootCanonical }

    # FIXED is recovery-only. Promote the Root copy once when Root has no
    # canonical workbook; never overwrite an existing canonical workbook.
    if(Test-Path -LiteralPath $rootFixed){
        if(-not(Test-Path -LiteralPath $rootExcel)){ New-Item -ItemType Directory -Path $rootExcel -Force | Out-Null }
        Copy-Item -LiteralPath $rootFixed -Destination $rootCanonical -Force
        return $rootCanonical
    }

    # Legacy runtime canonical is the next safe fallback.
    if(Test-Path -LiteralPath $runtimeCanonical){ return $runtimeCanonical }

    # Legacy FIXED is the last recovery source and is promoted to Root canonical.
    if(Test-Path -LiteralPath $runtimeFixed){
        if(-not(Test-Path -LiteralPath $rootExcel)){ New-Item -ItemType Directory -Path $rootExcel -Force | Out-Null }
        Copy-Item -LiteralPath $runtimeFixed -Destination $rootCanonical -Force
        return $rootCanonical
    }
    return $null
}

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;

public static class CockpitWorkbookRotFinder {
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
                // OneDrive may register an Office cloud URL rather than the local
                // path. Accept a file-name match only when it is unique.
                if (name.EndsWith(bookFileName, StringComparison.OrdinalIgnoreCase)) {
                    rot.GetObject(mk[0], out obj);
                    uniqueNameMatch = obj;
                    nameMatchCount++;
                }
            } catch { }
        }
        return nameMatchCount == 1 ? uniqueNameMatch : null;
    }
}
'@ -ErrorAction SilentlyContinue

function Wait-Workbook([string]$WorkbookPath,[int]$TimeoutSeconds=120){
    $expected=[IO.Path]::GetFullPath($WorkbookPath)
    $deadline=(Get-Date).AddSeconds($TimeoutSeconds)
    while((Get-Date) -lt $deadline){
        try{
            $book=[CockpitWorkbookRotFinder]::FindByIdentity($expected,[IO.Path]::GetFileName($expected))
            if($null -ne $book){ return $book }
        }catch{}
        Start-Sleep -Seconds 2
    }
    return $null
}

function Invoke-ExcelCom {
    param(
        [Parameter(Mandatory=$true)][scriptblock]$Action,
        [string]$Label="Excel operation",
        [int]$Retries=120,
        [int]$DelayMilliseconds=250
    )
    for($attempt=1;$attempt -le $Retries;$attempt++){
        try{ return (& $Action) }catch{
            $code=$_.Exception.HResult
            if($null -ne $_.Exception.InnerException){$code=$_.Exception.InnerException.HResult}
            $busy=($code -eq -2147418111 -or $code -eq -2147417846 -or $code -eq -2146777998)
            if($busy -and $attempt -lt $Retries){Start-Sleep -Milliseconds $DelayMilliseconds;continue}
            throw
        }
    }
    throw ($Label+": Excel did not become ready.")
}

try{
    Clear-Host
    Write-Host "==============================================" -ForegroundColor DarkCyan
    Write-Host " AI COCKPIT START V6" -ForegroundColor Cyan
    Write-Host "==============================================" -ForegroundColor DarkCyan
    Write-Host ""

    Show-Step 5 "Resolving runtime..."
    $RuntimeDir=Resolve-RuntimeDir
    $Collector=Join-Path $RuntimeDir "MS2_RSS_100_Collector.ps1"
    $Heartbeat=Join-Path $RuntimeDir "Kioxia_Safety_Heartbeat.ps1"
    $Watcher=Join-Path $RuntimeDir "Kioxia_RSS_Live_Watcher.ps1"
    $Gateway=Join-Path $Root "AI_Cockpit_Local_Gateway.ps1"

    foreach($p in @($Collector,$Heartbeat,$Watcher,$Gateway)){
        if(-not(Test-Path -LiteralPath $p)){ throw "Required file not found: $p" }
    }

    Show-Step 10 "Stopping old AI Cockpit processes..."
    Stop-Managed
    Start-Sleep -Seconds 1
    Close-EmptyExcelApplication

    Show-Step 20 "Checking MarketSpeed II..."
    $ms2=@(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match "MarketSpeed|MARKETSPEED" })
    if($ms2.Count -eq 0){
        Write-Host "      MarketSpeed II is not running. Start it and login, then run this shortcut again." -ForegroundColor Yellow
        throw "MarketSpeed II is not running."
    }
    Write-Host "      MarketSpeed II: READY" -ForegroundColor Green

    Show-Step 30 "Checking SBV2 voice engine..."
    $SbV2Root="C:\sbv2\Style-Bert-VITS2"
    $py=Join-Path $SbV2Root "venv\Scripts\python.exe"
    $server=Join-Path $SbV2Root "server_fastapi.py"
    if(-not(Test-Path -LiteralPath $py)){ throw "SBV2 python.exe not found: $py" }
    if(-not(Test-Path -LiteralPath $server)){ throw "SBV2 server_fastapi.py not found: $server" }

    if(Test-Port 5000 700){
        Write-Host "      SBV2: already READY on port 5000; keeping existing server." -ForegroundColor Green
    } else {
        $logDir=Join-Path $Root "Logs"
        if(-not(Test-Path -LiteralPath $logDir)){ New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
        $stdout=Join-Path $logDir "sbv2_v5_stdout.log"
        $stderr=Join-Path $logDir "sbv2_v5_stderr.log"
        Remove-Item $stdout,$stderr -Force -ErrorAction SilentlyContinue

        Write-Host "      SBV2 port 5000 is down; starting server_fastapi.py..." -ForegroundColor Yellow
        $proc=Start-Process -FilePath $py -ArgumentList @("-u","server_fastapi.py") -WorkingDirectory $SbV2Root -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru

        $started=Get-Date
        $next=5
        while(-not(Test-Port 5000 700)){
            $elapsed=[int]((Get-Date)-$started).TotalSeconds
            Write-Progress -Activity "AI Cockpit startup" -Status ("SBV2 loading... {0}s" -f $elapsed) -PercentComplete 30
            if($elapsed -ge $next){
                Write-Host ("      SBV2 loading... {0}s / 120s" -f $elapsed) -ForegroundColor DarkGray
                $next+=5
            }
            if($proc.HasExited){
                $err=""
                if(Test-Path -LiteralPath $stderr){ $err=(Get-Content -LiteralPath $stderr -Tail 30 -ErrorAction SilentlyContinue) -join " | " }
                if([string]::IsNullOrWhiteSpace($err) -and (Test-Path -LiteralPath $stdout)){ $err=(Get-Content -LiteralPath $stdout -Tail 30 -ErrorAction SilentlyContinue) -join " | " }
                throw ("SBV2 exited early. ExitCode="+$proc.ExitCode+" Log="+$err)
            }
            if($elapsed -ge 120){
                try{ Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }catch{}
                $err=""
                if(Test-Path -LiteralPath $stderr){ $err=(Get-Content -LiteralPath $stderr -Tail 30 -ErrorAction SilentlyContinue) -join " | " }
                throw ("SBV2 did not become ready within 120 seconds. Log="+$err)
            }
            Start-Sleep -Seconds 1
        }
        Write-Host "      SBV2: READY on port 5000" -ForegroundColor Green
    }

    Show-Step 40 "Opening RSS workbook..."
    $WorkbookPath=Find-Workbook $Root $RuntimeDir
    if(-not $WorkbookPath){ throw "Kioxia_MS2_RSS_Live_Signals.xlsx was not found in Root\\Excel or the MS2 runtime folder." }
    $WorkbookPath=[IO.Path]::GetFullPath($WorkbookPath)
    $WorkbookName=Split-Path $WorkbookPath -Leaf
    if($WorkbookName -ine "Kioxia_MS2_RSS_Live_Signals.xlsx"){ throw "Unexpected workbook selected: $WorkbookName" }

    # Reuse only the exact workbook path. GetActiveObject can bind to the wrong
    # Excel instance when multiple Excel processes exist.
    $book=Wait-Workbook $WorkbookPath 3
    if($null -eq $book){
        # Do not create Excel through New-Object -ComObject here. Real-machine
        # testing showed that a COM-created Excel instance can start without the
        # MarketSpeed II RSS add-in. Shell-opening the workbook loads Excel normally.
        Start-Process -FilePath $WorkbookPath | Out-Null
        $book=Wait-Workbook $WorkbookPath 120
    }
    if($null -eq $book){ throw "The exact RSS workbook did not register in Excel within 120 seconds: $WorkbookPath" }

    $excel=Invoke-ExcelCom -Label "Excel application attach" -Action { $book.Application }
    Invoke-ExcelCom -Label "Excel visible" -Action { $excel.Visible=$true } | Out-Null
    Invoke-ExcelCom -Label "Excel alerts" -Action { $excel.DisplayAlerts=$false } | Out-Null
    $actualPath=Invoke-ExcelCom -Label "Workbook identity" -Action { [string]$book.FullName }
    Write-Host ("      Workbook: "+$WorkbookName) -ForegroundColor Green
    Write-Host ("      Path    : "+$actualPath) -ForegroundColor DarkGray
    try{ Write-Host ("      SHA256  : "+(Get-FileHash -LiteralPath $WorkbookPath -Algorithm SHA256).Hash) -ForegroundColor DarkGray }catch{}

    Show-Step 45 "Verifying MarketSpeed II RSS add-in..."
    # Opening the workbook is not enough: Excel may show cached RSS values while
    # the MarketSpeed II COM/XLL add-in has not initialized in this Excel instance.
    $rssReady=$false
    $rssSheetName = "RSS" + [char]0x63A5 + [char]0x7D9A
    $rssCurrentPriceItem = [string]([char]0x73FE)+[char]0x5728+[char]0x5024
    $marketSpeedJp = [string]([char]0x30DE)+[char]0x30FC+[char]0x30B1+[char]0x30C3+[char]0x30C8+[char]0x30B9+[char]0x30D4+[char]0x30FC+[char]0x30C9
    $rssDeadline=(Get-Date).AddSeconds(45)
    while((Get-Date) -lt $rssDeadline -and -not $rssReady){
        try{
            $rssSheet=Invoke-ExcelCom -Label "RSS sheet" -Action { $book.Worksheets.Item($rssSheetName) }
            $rssFormula='=RssMarket("285A.T","'+$rssCurrentPriceItem+'")'
            Invoke-ExcelCom -Label "RSS probe formula" -Action { $rssSheet.Range("B3").FormulaLocal=$rssFormula } | Out-Null
            Invoke-ExcelCom -Label "RSS probe calculate" -Action { $rssSheet.Calculate() } | Out-Null
            Start-Sleep -Milliseconds 800
            $v=Invoke-ExcelCom -Label "RSS probe value" -Action { $rssSheet.Range("B3").Value2 }
            $n=0.0
            $formula=[string]$rssSheet.Range("B3").FormulaLocal
            if($formula -match "RssMarket" -and [double]::TryParse([string]$v,[ref]$n) -and $n -gt 0){
                $rssReady=$true
                break
            }
        }catch{}
        try{
            # Trigger registered Excel add-ins without guessing an install path.
            foreach($addin in $excel.AddIns){
                if((([string]$addin.Name -match "RSS|MarketSpeed") -or ([string]$addin.Name -like ("*"+$marketSpeedJp+"*"))) -and -not $addin.Installed){
                    $addin.Installed=$true
                }
            }
        }catch{}
        Start-Sleep -Seconds 2
    }
    if(-not $rssReady){
        throw "LIVE DATA INVALID: MarketSpeed II RSS add-in did not initialize in the active Excel instance."
    }
    Write-Host ("      MarketSpeed II RSS: READY / 285A="+$n) -ForegroundColor Green

    # Launcher no longer needs Excel COM after validation. Release it before
    # long-running Watcher/Collector processes attach to the workbook.
    Release-ComObjectSafe $rssSheet
    Release-ComObjectSafe $book
    Release-ComObjectSafe $excel
    $rssSheet=$null
    $book=$null
    $excel=$null
    $addin=$null
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()

    Show-Step 48 "Starting Excel Watcher..."
    Start-Process powershell.exe -WindowStyle Hidden -ArgumentList ('-NoLogo -NoProfile -ExecutionPolicy Bypass -File "'+$Watcher+'" -WorkbookPath "'+$WorkbookPath+'"') | Out-Null
    $watcherDeadline=(Get-Date).AddSeconds(120)
    while((Get-Date) -lt $watcherDeadline -and -not(Test-Port 28582 500)){ Start-Sleep -Milliseconds 500 }
    if(-not(Test-Port 28582 500)){ throw "Excel Watcher port 28582 did not open. The workbook path/add-in state is invalid." }
    Write-Host "      Excel Watcher: READY on port 28582" -ForegroundColor Green

    Show-Step 50 "Starting local gateway..."
    $installChannel="main"
    $channelMarker=Join-Path $Root "V6_INSTALL_CHANNEL.txt"
    if(Test-Path -LiteralPath $channelMarker){
        try{
            $channelLine=Get-Content -LiteralPath $channelMarker -ErrorAction Stop | Where-Object { $_ -like "channel=*" } | Select-Object -First 1
            if($channelLine){$installChannel=([string]$channelLine).Substring(8)}
        }catch{}
    }
    $cockpitRemoteBase=if($installChannel -eq "fix/live-session-state-v1"){"https://raw.githubusercontent.com/infoyuusuke-afk/trade-cockpit/refs/heads/fix/live-session-state-v1"}else{"https://infoyuusuke-afk.github.io/trade-cockpit"}
    Write-Host ("      UI source: "+$installChannel+" / "+$cockpitRemoteBase) -ForegroundColor DarkCyan
    Start-Process powershell.exe -WindowStyle Hidden -ArgumentList ('-NoLogo -NoProfile -ExecutionPolicy Bypass -File "'+$Gateway+'" -RuntimeDir "'+$RuntimeDir+'" -RemoteBase "'+$cockpitRemoteBase+'"') | Out-Null
    $deadline=(Get-Date).AddSeconds(30)
    while((Get-Date) -lt $deadline -and -not(Test-Port 28581 500)){ Start-Sleep -Milliseconds 500 }
    if(-not(Test-Port 28581 500)){ throw "Gateway port 28581 did not open." }

    # UI availability is independent from LIVE-data readiness. Open the cockpit
    # as soon as the gateway is reachable. Until Collector validates, the UI
    # remains fail-closed and must show data unavailable / trading prohibited.
    Show-Step 55 "Opening cockpit UI in fail-closed mode..."
    $cockpitUrl="http://127.0.0.1:28581/?live=1"
    Start-Process $cockpitUrl
    Write-Host "      Cockpit UI: OPEN / waiting for LIVE validation" -ForegroundColor Yellow

    Show-Step 60 "Starting safety heartbeat..."
    Start-Process powershell.exe -WindowStyle Hidden -ArgumentList ('-NoLogo -NoProfile -ExecutionPolicy Bypass -File "'+$Heartbeat+'"') | Out-Null

    Show-Step 65 "Starting Collector..."
    Start-Process powershell.exe -ArgumentList ('-NoLogo -NoProfile -ExecutionPolicy Bypass -File "'+$Collector+'" -WorkbookPath "'+$WorkbookPath+'"') | Out-Null

    $started=Get-Date
    $next=10
    while(-not(Test-Port 28580 500)){
        $elapsed=[int]((Get-Date)-$started).TotalSeconds
        $pct=[Math]::Min(89,65+[int]($elapsed/4))
        Write-Progress -Activity "AI Cockpit startup" -Status ("Collector initializing... {0}s" -f $elapsed) -PercentComplete $pct
        if($elapsed -ge $next){
            Write-Host ("      Collector initializing... {0}s / 180s" -f $elapsed) -ForegroundColor DarkGray
            $next+=10
        }
        $p=@(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match "MS2_RSS_100_Collector\.ps1" })
        if($p.Count -eq 0){ throw "Collector stopped before port 28580 opened." }
        if($elapsed -ge 180){ throw "Collector did not become ready within 180 seconds." }
        Start-Sleep -Seconds 1
    }

    Show-Step 90 "Collector LIVE bridge ready."
    $liveOk=$false
    $deadline=(Get-Date).AddSeconds(30)
    while((Get-Date) -lt $deadline){
        try{
            $j=Invoke-RestMethod ("http://127.0.0.1:28580/live_ms2.json?t="+[DateTimeOffset]::Now.ToUnixTimeMilliseconds()) -TimeoutSec 3
            if($j.updated_at -and $j.schema_version -eq "ms2-common-1.1"){
                $kx=@($j.all_targets | Where-Object {
                    ([string]$_.ticker -eq "285A.T") -or
                    ([string]$_.ticker -eq "285A") -or
                    ([string]$_.code -eq "285A")
                } | Select-Object -First 1)
                if($kx.Count -gt 0 -and $kx[0].live_quote_valid -eq $true -and [double]$kx[0].live_price -gt 0){ $liveOk=$true; break }
            }
        }catch{}
        Start-Sleep -Seconds 1
    }
    if(-not $liveOk){ throw "LIVE DATA INVALID: Collector 1.1 / 285A live_price verification failed." }

    $jnxState = if($null -ne $j.jnx_status){ [string]$j.jnx_status } else { "UNKNOWN" }
    $statsState = if($null -ne $j.stats_status){ [string]$j.stats_status } else { "UNKNOWN" }
    $statsCompleted = 0
    $statsScanned = 0
    $statsIncomplete = 0
    if($null -ne $j.kioxia_stats_meta){
        if($null -ne $j.kioxia_stats_meta.completed_days){ $statsCompleted = [int]$j.kioxia_stats_meta.completed_days }
        if($null -ne $j.kioxia_stats_meta.scanned_days){ $statsScanned = [int]$j.kioxia_stats_meta.scanned_days }
        if($null -ne $j.kioxia_stats_meta.incomplete_day_count){ $statsIncomplete = [int]$j.kioxia_stats_meta.incomplete_day_count }
    }
    Write-Host ("      JNX   : " + $jnxState) -ForegroundColor $(if($jnxState -like "WARN*"){"Yellow"}else{"Green"})
    Write-Host ("      STATS : " + $statsState + " / completed=" + $statsCompleted + " scanned=" + $statsScanned + " incomplete=" + $statsIncomplete) -ForegroundColor Cyan

    Show-Step 95 "Checking cockpit gateway..."
    $h=Invoke-RestMethod ("http://127.0.0.1:28581/health?t="+[DateTimeOffset]::Now.ToUnixTimeMilliseconds()) -TimeoutSec 5
    if(-not $h.live_json_exists){ throw "Gateway cannot see live_ms2.json." }

    Show-Step 100 "READY - cockpit LIVE validated."
    Write-Progress -Activity "AI Cockpit startup" -Completed
    Write-Host ""
    Write-Host ("Startup completed in {0:N1}s." -f $sw.Elapsed.TotalSeconds) -ForegroundColor Green
    Write-Host "Visible: Collector + one browser page" -ForegroundColor Cyan
    Write-Host "Hidden : Heartbeat + Gateway + SBV2" -ForegroundColor DarkCyan
    Start-Sleep -Seconds 1
    [Environment]::Exit(0)
}catch{
    Stop-ExcelBoundManaged
    Start-Sleep -Milliseconds 800
    Release-ComObjectSafe $rssSheet
    Release-ComObjectSafe $book
    Release-ComObjectSafe $excel
    $rssSheet=$null
    $book=$null
    $excel=$null
    $addin=$null
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
    Start-Sleep -Milliseconds 500
    Close-EmptyExcelApplication
    Write-Progress -Activity "AI Cockpit startup" -Completed
    Write-Host ""
    Write-Host "==============================================" -ForegroundColor Red
    Write-Host " AI COCKPIT STARTUP FAILED" -ForegroundColor Red
    Write-Host "==============================================" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Yellow
    Write-Host ""
    if(Test-Port 28581 500){
        Write-Host "Cockpit UI remains available in FAIL-CLOSED mode at http://127.0.0.1:28581/?live=1" -ForegroundColor Yellow
        Write-Host "Do not use LIVE trading data until the startup error is resolved." -ForegroundColor Red
    }
    Write-Host "This window is intentionally left open." -ForegroundColor Cyan
    Write-Host ""
    Read-Host "Press Enter to close this startup window"
    [Environment]::Exit(1)
}