param([string]$Root = "C:\AI_Cockpit_OneClick_Starter")

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

function Find-Workbook([string]$RootDir){
    $d=Join-Path $RootDir "Excel"
    if(-not(Test-Path -LiteralPath $d)){ return $null }
    $canonical=Join-Path $d "Kioxia_MS2_RSS_Live_Signals.xlsx"
    $fixed=Join-Path $d "Kioxia_MS2_RSS_Live_Signals_FIXED.xlsx"
    # FIXED is the validated newer workbook. Prefer it so an older canonical file
    # cannot silently win just because both files exist.
    if(Test-Path -LiteralPath $fixed){ return $fixed }
    if(Test-Path -LiteralPath $canonical){ return $canonical }
    return $null
}

function Wait-Workbook([string]$BookName,[int]$TimeoutSeconds=120){
    $deadline=(Get-Date).AddSeconds($TimeoutSeconds)
    while((Get-Date) -lt $deadline){
        try{
            $excel=[Runtime.InteropServices.Marshal]::GetActiveObject("Excel.Application")
            foreach($b in $excel.Workbooks){
                if($b.Name -ieq $BookName -or $b.Name -like "Kioxia_MS2_RSS_Live_Signals*.xlsx"){ return $true }
            }
        }catch{}
        Start-Sleep -Seconds 2
    }
    return $false
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
    $Gateway=Join-Path $Root "AI_Cockpit_Local_Gateway.ps1"

    foreach($p in @($Collector,$Heartbeat,$Gateway)){
        if(-not(Test-Path -LiteralPath $p)){ throw "Required file not found: $p" }
    }

    Show-Step 10 "Stopping old AI Cockpit processes..."
    Stop-Managed
    Start-Sleep -Seconds 1

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
    $WorkbookPath=Find-Workbook $Root
    if(-not $WorkbookPath){ throw "No xlsx file found under C:\AI_Cockpit_OneClick_Starter\Excel" }
    $WorkbookName=Split-Path $WorkbookPath -Leaf
    if($WorkbookName -ieq "Kioxia_MS2_RSS_Live_Signals_FIXED.xlsx"){
        $canonical=Join-Path (Split-Path $WorkbookPath -Parent) "Kioxia_MS2_RSS_Live_Signals.xlsx"
        if(Test-Path -LiteralPath $canonical){
            $backup=$canonical+".bak."+((Get-Date).ToString("yyyyMMdd_HHmmss"))
            Copy-Item -LiteralPath $canonical -Destination $backup -Force
        }
        Copy-Item -LiteralPath $WorkbookPath -Destination $canonical -Force
        $WorkbookPath=$canonical
        $WorkbookName=Split-Path $WorkbookPath -Leaf
        Write-Host "      Updated workbook promoted to canonical name; previous copy backed up." -ForegroundColor Green
    }
    if($WorkbookName -ine "Kioxia_MS2_RSS_Live_Signals.xlsx"){ throw "Unexpected workbook selected: $WorkbookName" }
    $open=$false
    $excel=$null
    try{
        $excel=[Runtime.InteropServices.Marshal]::GetActiveObject("Excel.Application")
        foreach($b in $excel.Workbooks){ if($b.Name -ieq $WorkbookName){ $open=$true; break } }
    }catch{}
    if($null -eq $excel){
        $excel=New-Object -ComObject Excel.Application
        $excel.Visible=$true
    }
    if(-not $open){
        # Open through the exact COM instance the Collector will attach to.
        # Start-Process can create/use another Excel instance, making
        # GetActiveObject("Excel.Application") see zero relevant workbooks.
        $opened=$excel.Workbooks.Open($WorkbookPath)
        $open=($null -ne $opened)
    }
    if(-not $open -or -not(Wait-Workbook $WorkbookName 120)){ throw "Excel workbook was not ready in the active COM instance within 120 seconds." }
    Write-Host ("      Workbook: "+$WorkbookName+" / Excel COM instance verified") -ForegroundColor Green

    Show-Step 45 "Verifying MarketSpeed II RSS add-in..."
    # Opening the workbook is not enough: Excel may show cached RSS values while
    # the MarketSpeed II COM/XLL add-in has not initialized in this Excel instance.
    $rssReady=$false
    $rssDeadline=(Get-Date).AddSeconds(45)
    while((Get-Date) -lt $rssDeadline -and -not $rssReady){
        try{
            $rssSheet=$excel.Worksheets.Item("RSS接続")
            $rssSheet.Range("B3").FormulaLocal='=RssMarket("285A.T","現在値")'
            $rssSheet.Calculate()
            Start-Sleep -Milliseconds 800
            $v=$rssSheet.Range("B3").Value2
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
                if(([string]$addin.Name -match "RSS|MarketSpeed|マーケットスピード") -and -not $addin.Installed){
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

    Show-Step 50 "Starting local gateway..."
    Start-Process powershell.exe -WindowStyle Hidden -ArgumentList ('-NoLogo -NoProfile -ExecutionPolicy Bypass -File "'+$Gateway+'" -RuntimeDir "'+$RuntimeDir+'"') | Out-Null
    $deadline=(Get-Date).AddSeconds(30)
    while((Get-Date) -lt $deadline -and -not(Test-Port 28581 500)){ Start-Sleep -Milliseconds 500 }
    if(-not(Test-Port 28581 500)){ throw "Gateway port 28581 did not open." }

    Show-Step 60 "Starting safety heartbeat..."
    Start-Process powershell.exe -WindowStyle Hidden -ArgumentList ('-NoLogo -NoProfile -ExecutionPolicy Bypass -File "'+$Heartbeat+'"') | Out-Null

    Show-Step 65 "Starting Collector..."
    Start-Process powershell.exe -ArgumentList ('-NoLogo -NoProfile -ExecutionPolicy Bypass -NoExit -File "'+$Collector+'"') | Out-Null

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
                $kx=@($j.all_targets | Where-Object { $_.ticker -eq "285A" -or $_.code -eq "285A" } | Select-Object -First 1)
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

    Show-Step 100 "READY - opening one cockpit page."
    Write-Progress -Activity "AI Cockpit startup" -Completed
    Start-Process "http://127.0.0.1:28581/?live=1"
    Write-Host ""
    Write-Host ("Startup completed in {0:N1}s." -f $sw.Elapsed.TotalSeconds) -ForegroundColor Green
    Write-Host "Visible: Collector + one browser page" -ForegroundColor Cyan
    Write-Host "Hidden : Heartbeat + Gateway + SBV2" -ForegroundColor DarkCyan
    Start-Sleep -Seconds 1
    [Environment]::Exit(0)
}catch{
    Write-Progress -Activity "AI Cockpit startup" -Completed
    Write-Host ""
    Write-Host "==============================================" -ForegroundColor Red
    Write-Host " AI COCKPIT STARTUP FAILED" -ForegroundColor Red
    Write-Host "==============================================" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Yellow
    Write-Host ""
    Write-Host "This window is intentionally left open." -ForegroundColor Cyan
    Write-Host ""
    Read-Host "Press Enter to close this startup window"
    [Environment]::Exit(1)
}