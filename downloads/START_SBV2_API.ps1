param(
    [string]$SbV2Root = "C:\\sbv2\\Style-Bert-VITS2",
    [int]$Port = 5000,
    [string]$LogDir = "C:\\AI_Cockpit_OneClick_Starter\\Logs"
)

$ErrorActionPreference="Stop"

function Test-Port([int]$p){
    $c=New-Object Net.Sockets.TcpClient
    try{
        $a=$c.BeginConnect("127.0.0.1",$p,$null,$null)
        if(-not $a.AsyncWaitHandle.WaitOne(500,$false)){return $false}
        $c.EndConnect($a); return $true
    }catch{return $false}finally{$c.Close()}
}

if(Test-Port $Port){
    Write-Host ("SBV2 API already running: 127.0.0.1:{0}" -f $Port) -ForegroundColor Green
    exit 0
}

$pythonw=Join-Path $SbV2Root "venv\Scripts\pythonw.exe"
$python=Join-Path $SbV2Root "venv\Scripts\python.exe"
$server=Join-Path $SbV2Root "server_fastapi.py"

if(-not(Test-Path -LiteralPath $server)){throw "server_fastapi.py not found: $server"}

if(-not(Test-Path -LiteralPath $LogDir)){
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
$stdout=Join-Path $LogDir "sbv2_api_stdout.log"
$stderr=Join-Path $LogDir "sbv2_api_stderr.log"

if(Test-Path -LiteralPath $pythonw){
    Start-Process -FilePath $pythonw -ArgumentList "server_fastapi.py" -WorkingDirectory $SbV2Root -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr | Out-Null
}elseif(Test-Path -LiteralPath $python){
    Start-Process -FilePath $python -ArgumentList "server_fastapi.py" -WorkingDirectory $SbV2Root -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr | Out-Null
}else{
    throw "SBV2 Python not found."
}

$deadline=(Get-Date).AddSeconds(120)
while((Get-Date) -lt $deadline){
    if(Test-Port $Port){
        Write-Host ("SBV2 API READY (hidden): http://127.0.0.1:{0}" -f $Port) -ForegroundColor Green
        exit 0
    }
    Start-Sleep -Seconds 2
}

throw "SBV2 API did not start within 120 seconds. Check: $stderr"
