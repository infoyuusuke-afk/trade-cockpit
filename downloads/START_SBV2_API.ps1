param(
    [string]$SbV2Root = "C:\\sbv2\\Style-Bert-VITS2",
    [int]$Port = 5000,
    [string]$LogDir = "C:\\AI_Cockpit_OneClick_Starter\\Logs",
    [int]$TimeoutSeconds = 120
)

$ErrorActionPreference = "Stop"

function Test-Port([int]$p,[int]$timeoutMs=500){
    $c = New-Object Net.Sockets.TcpClient
    try {
        $a = $c.BeginConnect("127.0.0.1",$p,$null,$null)
        if(-not $a.AsyncWaitHandle.WaitOne($timeoutMs,$false)){ return $false }
        $c.EndConnect($a)
        return $true
    } catch { return $false }
    finally { $c.Close() }
}

if(Test-Port $Port){
    Write-Host ("      SBV2 API already READY on port {0}" -f $Port) -ForegroundColor Green
    exit 0
}

$python = Join-Path $SbV2Root "venv\Scripts\python.exe"
$pythonw = Join-Path $SbV2Root "venv\Scripts\pythonw.exe"
$server = Join-Path $SbV2Root "server_fastapi.py"

if(-not(Test-Path -LiteralPath $server)){ throw "server_fastapi.py not found: $server" }
if(-not(Test-Path -LiteralPath $python) -and -not(Test-Path -LiteralPath $pythonw)){ throw "SBV2 Python not found." }

if(-not(Test-Path -LiteralPath $LogDir)){
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
$stdout = Join-Path $LogDir "sbv2_api_stdout.log"
$stderr = Join-Path $LogDir "sbv2_api_stderr.log"

Remove-Item -LiteralPath $stdout,$stderr -Force -ErrorAction SilentlyContinue

$exe = if(Test-Path -LiteralPath $python){ $python } else { $pythonw }

Write-Host "      Launching SBV2 server..." -ForegroundColor DarkCyan
$p = Start-Process -FilePath $exe -ArgumentList "server_fastapi.py" -WorkingDirectory $SbV2Root -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru

$started = Get-Date
$nextNotice = 5

while(((Get-Date)-$started).TotalSeconds -lt $TimeoutSeconds){
    if(Test-Port $Port 700){
        $sec = [int]((Get-Date)-$started).TotalSeconds
        Write-Host ("      SBV2 API READY on port {0} ({1}s)" -f $Port,$sec) -ForegroundColor Green
        exit 0
    }

    if($p.HasExited){
        $err = ""
        if(Test-Path -LiteralPath $stderr){
            $err = (Get-Content -LiteralPath $stderr -Tail 12 -ErrorAction SilentlyContinue) -join " | "
        }
        throw ("SBV2 server exited before port {0} opened. {1}" -f $Port,$err)
    }

    $elapsed = [int]((Get-Date)-$started).TotalSeconds
    if($elapsed -ge $nextNotice){
        Write-Host ("      SBV2 loading model... {0}s / {1}s" -f $elapsed,$TimeoutSeconds) -ForegroundColor DarkGray
        $nextNotice += 5
    }
    Start-Sleep -Seconds 1
}

$tail = ""
if(Test-Path -LiteralPath $stderr){
    $tail = (Get-Content -LiteralPath $stderr -Tail 12 -ErrorAction SilentlyContinue) -join " | "
}
throw ("SBV2 API did not start within {0}s. Log: {1}. {2}" -f $TimeoutSeconds,$stderr,$tail)