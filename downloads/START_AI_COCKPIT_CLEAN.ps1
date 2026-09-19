param(
    [string]$Root = "C:\\AI_Cockpit_OneClick_Starter"
)

$ErrorActionPreference = "Stop"

# AI_COCKPIT_FATAL_TRAP_V1
trap {
    Write-Progress -Activity "AI Cockpit startup" -Completed
    Write-Host ""
    Write-Host "==============================================" -ForegroundColor Red
    Write-Host " AI COCKPIT STARTUP FAILED" -ForegroundColor Red
    Write-Host "==============================================" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Yellow
    Write-Host ""
    Write-Host "This window will stay open so the error can be checked." -ForegroundColor Cyan
    Read-Host "Press Enter to keep this diagnostic window open"
    break
}
$sw = [Diagnostics.Stopwatch]::StartNew()

function Show-Step([int]$Percent,[string]$Message,[ConsoleColor]$Color=[ConsoleColor]::Cyan) {
    $elapsed = [Math]::Round($sw.Elapsed.TotalSeconds,1)
    Write-Host ("[{0,3}%] {1}  ({2}s)" -f $Percent,$Message,$elapsed) -ForegroundColor $Color
    Write-Progress -Activity "AI Cockpit startup" -Status $Message -PercentComplete $Percent
}

function Test-Port([int]$Port,[int]$TimeoutMs=500) {
    $c = New-Object Net.Sockets.TcpClient
    try {
        $a = $c.BeginConnect("127.0.0.1",$Port,$null,$null)
        if(-not $a.AsyncWaitHandle.WaitOne($TimeoutMs,$false)){ return $false }
        $c.EndConnect($a)
        return $true
    } catch { return $false }
    finally { $c.Close() }
}

function Resolve-RuntimeDir {
    $roots = @(
        [Environment]::GetFolderPath("Desktop"),
        (Join-Path $env:USERPROFILE "Desktop"),
        (Join-Path $env:USERPROFILE "OneDrive\Desktop")
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique

    $liveHits = foreach($r in $roots){
        Get-ChildItem -LiteralPath $r -Recurse -File -Filter "live_ms2.json" -ErrorAction SilentlyContinue
    }
    $live = @($liveHits | Sort-Object LastWriteTime -Descending | Select-Object -First 1)
    if($live.Count -gt 0){ return $live[0].Directory.FullName }

    $collectorHits = foreach($r in $roots){
        Get-ChildItem -LiteralPath $r -Recurse -File -Filter "MS2_RSS_100_Collector.ps1" -ErrorAction SilentlyContinue
    }
    $preferred = @($collectorHits | Where-Object { $_.FullName -like "*MarketSpeed II RSS\files*" } | Sort-Object LastWriteTime -Descending | Select-Object -First 1)
    if($preferred.Count -gt 0){ return $preferred[0].Directory.FullName }

    $any = @($collectorHits | Sort-Object LastWriteTime -Descending | Select-Object -First 1)
    if($any.Count -gt 0){ return $any[0].Directory.FullName }

    throw "MS2 runtime folder was not found."
}

function Stop-StaleCockpitProcesses {
    $patterns = @(
        'MS2_RSS_100_Collector\.ps1',
        'Kioxia_Safety_Heartbeat\.ps1',
        'AI_Cockpit_Local_Gateway\.ps1',
        'Kioxia_RSS_Live_Watcher\.ps1',
        'AUTO_START_MS2_100\.ps1',
        'server_fastapi\.py',
        'Style-Bert-VITS2.*app\.py',
        'Style-Bert-VITS2.*App\.bat'
    )
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object {
        $cmd = [string]$_.CommandLine
        if([string]::IsNullOrWhiteSpace($cmd)){ return }
        foreach($p in $patterns){
            if($cmd -match $p){
                try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {}
                break
            }
        }
    }
}

function Resolve-MarketSpeedShortcut {
    $menus = @(
        (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"),
        (Join-Path $env:ProgramData "Microsoft\Windows\Start Menu\Programs")
    ) | Where-Object { Test-Path -LiteralPath $_ }
    foreach($m in $menus){
        $lnk = Get-ChildItem -LiteralPath $m -Filter "*.lnk" -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match "MARKETSPEED" } |
            Select-Object -First 1
        if($lnk){ return $lnk.FullName }
    }
    return $null
}

function Find-LatestWorkbook([string]$RootDir) {
    $excelDir = Join-Path $RootDir "Excel"
    if(Test-Path -LiteralPath $excelDir){
        $hit = Get-ChildItem -LiteralPath $excelDir -File -Filter "*.xlsx" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        if($hit){ return $hit.FullName }
    }
    return $null
}

function Wait-Workbook([string]$BookName,[int]$TimeoutSeconds=120) {
    $deadline=(Get-Date).AddSeconds($TimeoutSeconds)
    while((Get-Date) -lt $deadline){
        try {
            $excel=[Runtime.InteropServices.Marshal]::GetActiveObject("Excel.Application")
            foreach($b in $excel.Workbooks){
                if($b.Name -ieq $BookName -or $b.Name -like "Kioxia_MS2_RSS_Live_Signals*.xlsx"){ return $true }
            }
        } catch {}
        Start-Sleep -Seconds 2
    }
    return $false
}

Clear-Host
Write-Host "==============================================" -ForegroundColor DarkCyan
Write-Host " AI COCKPIT CLEAN STARTUP" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor DarkCyan
Write-Host ""

Show-Step 5 "Resolving runtime folders..."
$RuntimeDir = Resolve-RuntimeDir
$Collector = Join-Path $RuntimeDir "MS2_RSS_100_Collector.ps1"
$Heartbeat = Join-Path $RuntimeDir "Kioxia_Safety_Heartbeat.ps1"
$Gateway = Join-Path $Root "AI_Cockpit_Local_Gateway.ps1"
$SbV2Root = "C:\sbv2\Style-Bert-VITS2"

foreach($p in @($Collector,$Heartbeat,$Gateway)){
    if(-not(Test-Path -LiteralPath $p)){ throw "Required file not found: $p" }
}

Show-Step 10 "Stopping stale AI Cockpit background processes..."
Stop-StaleCockpitProcesses
Start-Sleep -Seconds 1

Show-Step 20 "Checking MarketSpeed II..."
$ms2 = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match "MarketSpeed|MARKETSPEED" })
if($ms2.Count -eq 0){
    $shortcut=Resolve-MarketSpeedShortcut
    if($shortcut){
        Start-Process $shortcut
        Write-Host "      MarketSpeed II launch requested. Complete login if prompted." -ForegroundColor Yellow
        Start-Sleep -Seconds 3
    } else {
        Write-Host "      MarketSpeed II shortcut was not found. Start it manually if needed." -ForegroundColor Yellow
    }
} else {
    Write-Host "      MarketSpeed II already running." -ForegroundColor Green
}

Show-Step 30 "Starting SBV2 voice engine in background..."
$sbvPy = Join-Path $SbV2Root "venv\Scripts\pythonw.exe"
if(-not(Test-Path -LiteralPath $sbvPy)){
    $sbvPy = Join-Path $SbV2Root "venv\Scripts\python.exe"
}
$sbvServer = Join-Path $SbV2Root "server_fastapi.py"
if(-not(Test-Path -LiteralPath $sbvPy)){ throw "SBV2 Python not found: $sbvPy" }
if(-not(Test-Path -LiteralPath $sbvServer)){ throw "SBV2 server_fastapi.py not found: $sbvServer" }

if(-not(Test-Port 5000 700)){
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $sbvPy
    $psi.Arguments = "server_fastapi.py"
    $psi.WorkingDirectory = $SbV2Root
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $sbvProc = [Diagnostics.Process]::Start($psi)

    $sbvStarted = Get-Date
    $sbvNextNotice = 5
    while(-not(Test-Port 5000 700)){
        $elapsed = [int]((Get-Date)-$sbvStarted).TotalSeconds
        Write-Progress -Activity "AI Cockpit startup" -Status ("SBV2 model loading... {0}s" -f $elapsed) -PercentComplete 30
        if($elapsed -ge $sbvNextNotice){
            Write-Host ("      SBV2 model loading... {0}s / 120s" -f $elapsed) -ForegroundColor DarkGray
            $sbvNextNotice += 5
        }
        if($sbvProc.HasExited){
            throw ("SBV2 process exited before port 5000 opened. ExitCode=" + $sbvProc.ExitCode)
        }
        if($elapsed -ge 120){
            try { Stop-Process -Id $sbvProc.Id -Force -ErrorAction SilentlyContinue } catch {}
            throw "SBV2 API did not become ready on port 5000 within 120 seconds."
        }
        Start-Sleep -Seconds 1
    }
}
Write-Host "      SBV2 voice: READY (port 5000)" -ForegroundColor Green

Show-Step 40 "Opening latest RSS workbook..."
$WorkbookPath = Find-LatestWorkbook $Root
if(-not $WorkbookPath){ throw "No .xlsx workbook was found under $Root\Excel" }
$WorkbookName = Split-Path $WorkbookPath -Leaf

$excel = $null
try { $excel=[Runtime.InteropServices.Marshal]::GetActiveObject("Excel.Application") } catch {}
$alreadyOpen=$false
if($excel){
    foreach($b in $excel.Workbooks){
        if($b.Name -ieq $WorkbookName -or $b.Name -like "Kioxia_MS2_RSS_Live_Signals*.xlsx"){ $alreadyOpen=$true; break }
    }
}
if(-not $alreadyOpen){
    Start-Process $WorkbookPath
}
if(-not (Wait-Workbook $WorkbookName 120)){
    throw "Excel workbook did not become ready within 120 seconds."
}
Write-Host ("      Workbook: " + $WorkbookName) -ForegroundColor Green

Show-Step 50 "Starting local gateway..."
Start-Process powershell.exe -WindowStyle Hidden -ArgumentList ('-NoLogo -NoProfile -ExecutionPolicy Bypass -File "'+$Gateway+'" -RuntimeDir "'+$RuntimeDir+'"') | Out-Null
$gatewayDeadline=(Get-Date).AddSeconds(30)
while((Get-Date) -lt $gatewayDeadline -and -not(Test-Port 28581 500)){ Start-Sleep -Milliseconds 500 }
if(-not(Test-Port 28581 500)){ throw "Local Gateway did not start on port 28581." }

Show-Step 60 "Starting safety heartbeat..."
Start-Process powershell.exe -WindowStyle Hidden -ArgumentList ('-NoLogo -NoProfile -ExecutionPolicy Bypass -File "'+$Heartbeat+'"') | Out-Null

Show-Step 65 "Starting 100-stock Collector..."
Start-Process powershell.exe -ArgumentList ('-NoLogo -NoProfile -ExecutionPolicy Bypass -NoExit -File "'+$Collector+'"') | Out-Null

$collectorStart=Get-Date
$lastNotice=-999
while(-not(Test-Port 28580 500)){
    $elapsed=[int]((Get-Date)-$collectorStart).TotalSeconds
    $pct=[Math]::Min(89,65+[int]($elapsed/4))
    Write-Progress -Activity "AI Cockpit startup" -Status ("Collector / Excel RSS initialization... {0}s" -f $elapsed) -PercentComplete $pct
    if($elapsed -ge ($lastNotice+10)){
        Write-Host ("      Collector initializing... {0}s elapsed" -f $elapsed) -ForegroundColor DarkGray
        $lastNotice=$elapsed
    }
    $proc=@(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match 'MS2_RSS_100_Collector\.ps1' })
    if($proc.Count -eq 0){ throw "Collector stopped before port 28580 became ready. Check the Collector window." }
    if($elapsed -ge 180){ throw "Collector did not become ready within 180 seconds." }
    Start-Sleep -Seconds 1
}

Show-Step 90 "Collector LIVE bridge is ready."
$liveDeadline=(Get-Date).AddSeconds(30)
$liveOk=$false
while((Get-Date) -lt $liveDeadline){
    try{
        $j=Invoke-RestMethod ("http://127.0.0.1:28580/live_ms2.json?t="+[DateTimeOffset]::Now.ToUnixTimeMilliseconds()) -TimeoutSec 3
        if($j.updated_at){ $liveOk=$true; break }
    }catch{}
    Start-Sleep -Seconds 1
}
if(-not $liveOk){ throw "LIVE JSON did not become ready." }

Show-Step 95 "Checking local cockpit gateway..."
try{
    $h=Invoke-RestMethod ("http://127.0.0.1:28581/health?t="+[DateTimeOffset]::Now.ToUnixTimeMilliseconds()) -TimeoutSec 5
    if(-not $h.live_json_exists){ throw "Gateway cannot see live_ms2.json." }
}catch{
    throw ("Gateway health check failed: "+$_.Exception.Message)
}

Show-Step 100 "READY - opening one AI Cockpit page." Green
Write-Progress -Activity "AI Cockpit startup" -Completed
Start-Process "http://127.0.0.1:28581/?live=1"
Write-Host ""
Write-Host ("Startup completed in {0:N1} seconds." -f $sw.Elapsed.TotalSeconds) -ForegroundColor Green
Write-Host "Visible: Collector + AI Cockpit browser" -ForegroundColor Cyan
Write-Host "Hidden : Heartbeat + Gateway + SBV2 API" -ForegroundColor DarkCyan
Start-Sleep -Seconds 3
exit 0
