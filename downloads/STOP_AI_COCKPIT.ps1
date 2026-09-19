$ErrorActionPreference="SilentlyContinue"

Write-Host "Stopping AI Cockpit processes..." -ForegroundColor Cyan

$targets = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and (
        $_.CommandLine -match 'MS2_RSS_100_Collector\.ps1' -or
        $_.CommandLine -match 'Kioxia_Safety_Heartbeat\.ps1' -or
        $_.CommandLine -match 'AI_Cockpit_Local_Gateway\.ps1' -or
        $_.CommandLine -match 'server_fastapi\.py'
    )
}

foreach($p in $targets){
    try {
        Stop-Process -Id $p.ProcessId -Force
        Write-Host ("Stopped PID {0}: {1}" -f $p.ProcessId,$p.Name) -ForegroundColor Green
    } catch {}
}

Write-Host "AI Cockpit background processes stopped." -ForegroundColor Green
