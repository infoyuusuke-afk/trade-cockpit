
param(
    [string]$Root="C:\AI_Cockpit_OneClick_Starter",
    [string]$RuntimeDir="C:\Users\yusuk\Desktop\デイトレ\MarketSpeed II RSS\files"
)

$ErrorActionPreference="Stop"
$Build="V7-RUNTIME-SUPERVISOR-20260925-01"
$RemoteBase="https://raw.githubusercontent.com/infoyuusuke-afk/trade-cockpit/refs/heads/fix/runtime-supervisor-v7"
$sw=[Diagnostics.Stopwatch]::StartNew()

function Show-Step([int]$Pct,[string]$Message,[ConsoleColor]$Color=[ConsoleColor]::Cyan){
    $sec=[Math]::Round($sw.Elapsed.TotalSeconds,1)
    Write-Host ("[{0,3}%] {1} ({2}s)" -f $Pct,$Message,$sec) -ForegroundColor $Color
    Write-Progress -Activity "AI Cockpit V7 startup" -Status $Message -PercentComplete $Pct
}

function Test-Port([int]$Port,[int]$TimeoutMs=400){
    $c=New-Object Net.Sockets.TcpClient
    try{
        $a=$c.BeginConnect("127.0.0.1",$Port,$null,$null)
        if(-not $a.AsyncWaitHandle.WaitOne($TimeoutMs,$false)){return $false}
        $c.EndConnect($a)
        return $true
    }catch{
        return $false
    }finally{
        try{$c.Close()}catch{}
    }
}

function Wait-Port([int]$Port,[int]$Seconds){
    $deadline=(Get-Date).AddSeconds($Seconds)
    while((Get-Date) -lt $deadline){
        if(Test-Port $Port 400){return $true}
        Start-Sleep -Milliseconds 250
    }
    return $false
}

function Release-ComObjectSafe($obj){
    if($null -eq $obj){return}
    try{
        if([Runtime.InteropServices.Marshal]::IsComObject($obj)){
            [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($obj)
        }
    }catch{}
}

function Tail-Log([string]$Path){
    if(Test-Path -LiteralPath $Path){
        return ((Get-Content -LiteralPath $Path -Tail 20 -ErrorAction SilentlyContinue) -join " | ")
    }
    return ""
}

$WorkbookPath=Join-Path $Root "Excel\Kioxia_MS2_RSS_Live_Signals.xlsx"
$WorkbookName=[IO.Path]::GetFileName($WorkbookPath)
$Watcher=Join-Path $RuntimeDir "Kioxia_RSS_Live_Watcher.ps1"
$Heartbeat=Join-Path $RuntimeDir "Kioxia_Safety_Heartbeat.ps1"
$Collector=Join-Path $RuntimeDir "MS2_RSS_100_Collector.ps1"
$Gateway=Join-Path $Root "AI_Cockpit_Local_Gateway.ps1"
$Bridge=Join-Path $Root "V7_JSON_BRIDGE.ps1"
$CollectorStarter=Join-Path $Root "V7_COLLECTOR_STARTER.ps1"
$Supervisor=Join-Path $Root "V7_SESSION_SUPERVISOR.ps1"
$StopScript=Join-Path $Root "STOP_AI_COCKPIT_V7.ps1"
$StateFile=Join-Path $Root "V7_SESSION.json"
$LogDir=Join-Path $Root "Logs\V7"
$LiveJson=Join-Path $RuntimeDir "live_ms2.json"

if(-not(Test-Path -LiteralPath $LogDir)){New-Item -ItemType Directory -Path $LogDir -Force | Out-Null}

$state=[ordered]@{
    build=$Build
    started_at=(Get-Date).ToString("o")
    workbook_name=$WorkbookName
    workbook_path=$WorkbookPath
    runtime_dir=$RuntimeDir
    excel_pid=0
    watcher_pid=0
    heartbeat_pid=0
    bridge_pid=0
    gateway_pid=0
    collector_starter_pid=0
    collector_pid=0
    collector_status="NOT_STARTED"
    supervisor_pid=0
}

function Save-State {
    $tmp=$StateFile+".tmp"
    [IO.File]::WriteAllText($tmp,($state|ConvertTo-Json -Depth 6),[Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $tmp -Destination $StateFile -Force
}

function Start-PsWorker {
    param(
        [string]$Name,
        [string]$Script,
        [string]$ExtraArgs=""
    )
    $stdout=Join-Path $LogDir ($Name+"_stdout.log")
    $stderr=Join-Path $LogDir ($Name+"_stderr.log")
    Remove-Item -LiteralPath $stdout,$stderr -Force -ErrorAction SilentlyContinue
    $args='-NoLogo -NoProfile -ExecutionPolicy Bypass -File "'+$Script+'"'
    if(-not [string]::IsNullOrWhiteSpace($ExtraArgs)){$args+=" "+$ExtraArgs}
    return Start-Process -FilePath "powershell.exe" -ArgumentList $args -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
}

function Stop-LegacyManaged {
    $patterns=@(
        "MS2_RSS_100_Collector.ps1",
        "Kioxia_Safety_Heartbeat.ps1",
        "Kioxia_RSS_Live_Watcher.ps1",
        "AI_Cockpit_Local_Gateway.ps1",
        "V7_JSON_BRIDGE.ps1",
        "V7_COLLECTOR_STARTER.ps1",
        "V7_SESSION_SUPERVISOR.ps1"
    )
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object{
        if($_.ProcessId -eq $PID){return}
        $cmd=[string]$_.CommandLine
        if([string]::IsNullOrWhiteSpace($cmd)){return}
        foreach($p in $patterns){
            if($cmd -match [regex]::Escape($p)){
                try{Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue}catch{}
                break
            }
        }
    }
}

try{
    Clear-Host
    Write-Host "==================================================" -ForegroundColor DarkCyan
    Write-Host " AI COCKPIT START V7" -ForegroundColor Cyan
    Write-Host (" "+$Build) -ForegroundColor DarkCyan
    Write-Host "==================================================" -ForegroundColor DarkCyan
    Write-Host ""

    Show-Step 5 "Validating installation..."
    foreach($p in @($WorkbookPath,$Watcher,$Heartbeat,$Collector,$Gateway,$Bridge,$CollectorStarter,$Supervisor,$StopScript)){
        if(-not(Test-Path -LiteralPath $p)){throw "Required file not found: $p"}
    }

    Show-Step 10 "Cleaning previous managed session..."
    if(Test-Path -LiteralPath $StopScript){
        & $StopScript -Root $Root | Out-Null
    }
    Stop-LegacyManaged
    Start-Sleep -Seconds 1

    $foreign=@()
    foreach($xp in @(Get-Process EXCEL -ErrorAction SilentlyContinue)){
        if($xp.MainWindowHandle -eq 0 -or $xp.MainWindowTitle -like ("*"+$WorkbookName+"*")){
            try{Stop-Process -Id $xp.Id -Force -ErrorAction SilentlyContinue}catch{}
        }else{
            $foreign+=$xp
        }
    }
    if($foreign.Count -gt 0){
        $titles=($foreign|ForEach-Object{$_.MainWindowTitle}) -join " | "
        throw "Another visible Excel workbook is open. Close it before V7 so MarketSpeed II RSS can start in a clean Excel process. Open Excel: $titles"
    }

    $deadline=(Get-Date).AddSeconds(8)
    while((Get-Date) -lt $deadline -and @(Get-Process EXCEL -ErrorAction SilentlyContinue).Count -gt 0){
        Start-Sleep -Milliseconds 250
    }
    if(@(Get-Process EXCEL -ErrorAction SilentlyContinue).Count -gt 0){
        throw "EXCEL.EXE did not reach a clean zero-process state."
    }
    Write-Host "      Excel process state: CLEAN (0 EXCEL.EXE)" -ForegroundColor Green

    Show-Step 15 "Checking MarketSpeed II..."
    $ms2=@(Get-Process -ErrorAction SilentlyContinue | Where-Object{$_.ProcessName -match "MarketSpeed|MARKETSPEED"})
    if($ms2.Count -eq 0){throw "MarketSpeed II is not running. Start/login to MarketSpeed II, then launch V7 again."}
    Write-Host "      MarketSpeed II: READY" -ForegroundColor Green

    Show-Step 20 "Starting voice engine if needed..."
    if(Test-Port 5000 500){
        Write-Host "      SBV2: READY" -ForegroundColor Green
    }else{
        $SbV2Root="C:\sbv2\Style-Bert-VITS2"
        $py=Join-Path $SbV2Root "venv\Scripts\python.exe"
        $server=Join-Path $SbV2Root "server_fastapi.py"
        if((Test-Path -LiteralPath $py) -and (Test-Path -LiteralPath $server)){
            Start-Process -FilePath $py -ArgumentList @("-u","server_fastapi.py") -WorkingDirectory $SbV2Root -WindowStyle Hidden | Out-Null
            Write-Host "      SBV2: STARTING in background" -ForegroundColor Yellow
        }else{
            Write-Host "      SBV2: unavailable; startup continues without blocking" -ForegroundColor Yellow
        }
    }

    Show-Step 30 "Opening canonical RSS workbook..."
    Start-Process -FilePath $WorkbookPath | Out-Null
    $excelProc=$null
    $deadline=(Get-Date).AddSeconds(35)
    while((Get-Date) -lt $deadline){
        $excelProc=@(Get-Process EXCEL -ErrorAction SilentlyContinue | Where-Object{
            $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -like ("*"+$WorkbookName+"*") -and $_.Responding
        } | Select-Object -First 1)
        if($excelProc.Count -eq 1){$excelProc=$excelProc[0];break}
        Start-Sleep -Milliseconds 300
    }
    if($null -eq $excelProc -or $excelProc.Count -eq 0){throw "Canonical workbook did not open in a visible responsive Excel process."}
    $state.excel_pid=[int]$excelProc.Id
    Save-State
    Write-Host ("      Excel PID: "+$state.excel_pid) -ForegroundColor Green

    Show-Step 40 "Verifying MarketSpeed II RSS function..."
    $app=$null;$book=$null;$sheet=$null;$cell=$null
    $rssValue=0.0
    try{
        $app=[Runtime.InteropServices.Marshal]::GetActiveObject("Excel.Application")
        foreach($b in @($app.Workbooks)){
            if($b.Name -ieq $WorkbookName){$book=$b;break}
            Release-ComObjectSafe $b
        }
        if($null -eq $book){throw "Canonical workbook not found through Excel COM."}
        $sheet=$book.Worksheets.Item("RSS接続")
        $cell=$sheet.Range("B3")
        $cell.FormulaLocal='=RssMarket("285A.T","現在値")'
        $sheet.Calculate()
        Start-Sleep -Milliseconds 700
        $formula=[string]$cell.FormulaLocal
        $text=[string]$cell.Text
        [void][double]::TryParse([string]$cell.Value2,[ref]$rssValue)
        if($formula -notmatch "RssMarket"){throw "RssMarket formula was not accepted by Excel."}
        if($text -match "#NAME\?"){throw "RssMarket is not registered in this Excel instance."}
    }finally{
        Release-ComObjectSafe $cell
        Release-ComObjectSafe $sheet
        Release-ComObjectSafe $book
        Release-ComObjectSafe $app
        $cell=$null;$sheet=$null;$book=$null;$app=$null
        [GC]::Collect()
        [GC]::WaitForPendingFinalizers()
    }
    if($rssValue -gt 0){
        Write-Host ("      RSS FUNCTION READY / quote="+$rssValue) -ForegroundColor Green
    }else{
        Write-Host "      RSS FUNCTION READY / quote WAIT_DATA (0)" -ForegroundColor Yellow
    }

    Show-Step 50 "Starting Excel Watcher..."
    $watcherArgs='-WorkbookPath "'+$WorkbookPath+'"'
    $watcherProc=Start-PsWorker -Name "watcher" -Script $Watcher -ExtraArgs $watcherArgs
    $state.watcher_pid=[int]$watcherProc.Id
    Save-State
    if(-not(Wait-Port 28582 25)){
        if($watcherProc.HasExited){
            $err=Tail-Log (Join-Path $LogDir "watcher_stderr.log")
            $out=Tail-Log (Join-Path $LogDir "watcher_stdout.log")
            throw "Watcher exited before port 28582 opened. stderr=$err stdout=$out"
        }
        throw "Watcher port 28582 did not open within 25 seconds."
    }
    Write-Host "      Watcher: READY / 28582" -ForegroundColor Green

    Show-Step 58 "Starting dedicated LIVE bridge..."
    $bridgeArgs='-JsonFile "'+$LiveJson+'" -Port 28580'
    $bridgeProc=Start-PsWorker -Name "bridge" -Script $Bridge -ExtraArgs $bridgeArgs
    $state.bridge_pid=[int]$bridgeProc.Id
    Save-State
    if(-not(Wait-Port 28580 8)){
        $err=Tail-Log (Join-Path $LogDir "bridge_stderr.log")
        throw "V7 JSON bridge failed to open port 28580. $err"
    }
    Write-Host "      LIVE bridge: READY / 28580" -ForegroundColor Green

    Show-Step 65 "Starting local cockpit gateway..."
    $gatewayArgs='-RuntimeDir "'+$RuntimeDir+'" -RemoteBase "'+$RemoteBase+'"'
    $gatewayProc=Start-PsWorker -Name "gateway" -Script $Gateway -ExtraArgs $gatewayArgs
    $state.gateway_pid=[int]$gatewayProc.Id
    Save-State
    if(-not(Wait-Port 28581 15)){
        $err=Tail-Log (Join-Path $LogDir "gateway_stderr.log")
        throw "Cockpit gateway failed to open port 28581. $err"
    }
    Write-Host "      Gateway: READY / 28581" -ForegroundColor Green

    Show-Step 72 "Starting safety heartbeat..."
    $heartbeatProc=Start-PsWorker -Name "heartbeat" -Script $Heartbeat
    $state.heartbeat_pid=[int]$heartbeatProc.Id
    Save-State

    Show-Step 78 "Opening cockpit UI fail-closed first..."
    Start-Process "http://127.0.0.1:28581/?live=1"
    Write-Host "      Cockpit UI: OPEN" -ForegroundColor Green

    Show-Step 84 "Starting deferred Collector..."
    $starterArgs='-WorkbookPath "'+$WorkbookPath+'" -CollectorPath "'+$Collector+'" -StateFile "'+$StateFile+'" -LogDir "'+$LogDir+'"'
    $starterProc=Start-PsWorker -Name "collector_starter" -Script $CollectorStarter -ExtraArgs $starterArgs
    $state.collector_starter_pid=[int]$starterProc.Id
    $state.collector_status=if($rssValue -gt 0){"STARTING"}else{"WAIT_DATA"}
    Save-State
    if($rssValue -gt 0){
        Write-Host "      Collector: starting now" -ForegroundColor Green
    }else{
        Write-Host "      Collector: WAIT_DATA; will start automatically when 285A quote becomes positive" -ForegroundColor Yellow
    }

    Show-Step 92 "Starting session supervisor..."
    $supervisorArgs='-StateFile "'+$StateFile+'"'
    $supervisorProc=Start-PsWorker -Name "supervisor" -Script $Supervisor -ExtraArgs $supervisorArgs
    $state.supervisor_pid=[int]$supervisorProc.Id
    Save-State
    Write-Host "      Supervisor: READY" -ForegroundColor Green

    Show-Step 100 "V7 READY" Green
    Write-Progress -Activity "AI Cockpit V7 startup" -Completed
    Write-Host ""
    Write-Host "V7 READY" -ForegroundColor Green
    Write-Host "Excel close is supervised: managed workers will stop, then the cockpit Excel PID will be cleared if it remains orphaned." -ForegroundColor Cyan
    Write-Host "Trading remains fail-closed until fresh LIVE data is produced." -ForegroundColor Yellow
    Start-Sleep -Seconds 3
    exit 0
}catch{
    Write-Progress -Activity "AI Cockpit V7 startup" -Completed
    Write-Host ""
    Write-Host "==================================================" -ForegroundColor Red
    Write-Host " AI COCKPIT V7 STARTUP FAILED" -ForegroundColor Red
    Write-Host "==================================================" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Yellow
    try{if(Test-Path -LiteralPath $StopScript){& $StopScript -Root $Root | Out-Null}}catch{}
    Write-Host ""
    Read-Host "Press Enter to close"
    exit 1
}
