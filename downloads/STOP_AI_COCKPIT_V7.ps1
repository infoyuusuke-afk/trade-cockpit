
param([string]$Root="C:\AI_Cockpit_OneClick_Starter")

$ErrorActionPreference="SilentlyContinue"
$stateFile=Join-Path $Root "V7_SESSION.json"

function Stop-Pid([int]$Pid){
    if($Pid -le 0 -or $Pid -eq $PID){return}
    try{Stop-Process -Id $Pid -Force -ErrorAction SilentlyContinue}catch{}
}

if(Test-Path -LiteralPath $stateFile){
    try{
        $s=Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
        foreach($name in @("collector_pid","collector_starter_pid","watcher_pid","heartbeat_pid","bridge_pid","gateway_pid","supervisor_pid")){
            try{
                $value=$s.PSObject.Properties[$name].Value
                if($null -ne $value){Stop-Pid ([int]$value)}
            }catch{}
        }
        try{
            $excelPid=[int]$s.excel_pid
            $xp=Get-Process -Id $excelPid -ErrorAction SilentlyContinue
            if($null -ne $xp -and ($xp.MainWindowHandle -eq 0 -or $xp.MainWindowTitle -like "*Kioxia_MS2_RSS_Live_Signals*")){
                Stop-Pid $excelPid
            }
        }catch{}
    }catch{}
}

$patterns=@(
    "Kioxia_RSS_Live_Watcher.ps1",
    "Kioxia_Safety_Heartbeat.ps1",
    "MS2_RSS_100_Collector.ps1",
    "V7_JSON_BRIDGE.ps1",
    "V7_COLLECTOR_STARTER.ps1",
    "V7_SESSION_SUPERVISOR.ps1",
    "AI_Cockpit_Local_Gateway.ps1"
)
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object{
    $cmd=[string]$_.CommandLine
    if([string]::IsNullOrWhiteSpace($cmd)){return}
    foreach($p in $patterns){
        if($cmd -match [regex]::Escape($p)){
            Stop-Pid ([int]$_.ProcessId)
            break
        }
    }
}

Remove-Item -LiteralPath $stateFile -Force -ErrorAction SilentlyContinue
Write-Host "AI Cockpit V7 managed processes stopped." -ForegroundColor Green
