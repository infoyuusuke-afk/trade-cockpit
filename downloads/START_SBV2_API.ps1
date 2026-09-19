param(
    [string]$SbV2Root = "C:\\sbv2\\Style-Bert-VITS2",
    [int]$Port = 5000
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

$py=Join-Path $SbV2Root "venv\Scripts\python.exe"
$server=Join-Path $SbV2Root "server_fastapi.py"

if(-not(Test-Path -LiteralPath $py)){throw "SBV2 Python not found: $py"}
if(-not(Test-Path -LiteralPath $server)){throw "server_fastapi.py not found: $server"}

Write-Host "Starting Style-Bert-VITS2 FastAPI..." -ForegroundColor Cyan
Start-Process -FilePath $py -ArgumentList "server_fastapi.py" -WorkingDirectory $SbV2Root -WindowStyle Minimized | Out-Null

$deadline=(Get-Date).AddSeconds(120)
while((Get-Date) -lt $deadline){
    if(Test-Port $Port){
        try{
            $models=Invoke-RestMethod ("http://127.0.0.1:{0}/models/info" -f $Port) -TimeoutSec 5
            Write-Host ("SBV2 API READY: http://127.0.0.1:{0}" -f $Port) -ForegroundColor Green
            Write-Host ("Loaded models: " + (($models.PSObject.Properties.Name) -join ", ")) -ForegroundColor DarkGray
        }catch{
            Write-Host ("SBV2 API port {0} is open." -f $Port) -ForegroundColor Green
        }
        exit 0
    }
    Start-Sleep -Seconds 2
}
throw "SBV2 API did not start within 120 seconds."
