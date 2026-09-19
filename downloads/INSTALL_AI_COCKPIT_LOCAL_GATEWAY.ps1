param(
    [string]$Root = "C:\AI_Cockpit_OneClick_Starter"
)

$ErrorActionPreference="Stop"
$GatewayUrl="https://raw.githubusercontent.com/infoyuusuke-afk/trade-cockpit/main/downloads/AI_Cockpit_Local_Gateway.ps1"
$Gateway=Join-Path $Root "AI_Cockpit_Local_Gateway.ps1"
$Launcher=Join-Path $Root "START_AI_COCKPIT.ps1"

if(-not(Test-Path -LiteralPath $Launcher)){throw "Launcher not found: $Launcher"}

Invoke-WebRequest -Uri $GatewayUrl -OutFile $Gateway -UseBasicParsing -TimeoutSec 30

$stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$backup="$Launcher.bak_localgateway_$stamp"
Copy-Item -LiteralPath $Launcher -Destination $backup -Force
$c=[IO.File]::ReadAllText($Launcher)
$marker='# AI_COCKPIT_LOCAL_GATEWAY_V1'
if($c -notmatch [regex]::Escape($marker)){
    $needle='Write-Log "Collector port 28580 PASS." "OK"'
    if(-not $c.Contains($needle)){throw "Expected launcher marker not found. Backup: $backup"}
    $patch=@'
Write-Log "Collector port 28580 PASS." "OK"

# AI_COCKPIT_LOCAL_GATEWAY_V1
$GatewayScript = Join-Path $Root "AI_Cockpit_Local_Gateway.ps1"
$GatewayPort = 28581
if (Test-Path -LiteralPath $GatewayScript) {
    if (-not (Test-TcpPort "127.0.0.1" $GatewayPort)) {
        Start-Process powershell.exe -WindowStyle Hidden -ArgumentList ('-NoLogo -NoProfile -ExecutionPolicy Bypass -File "' + $GatewayScript + '"') | Out-Null
        $gwDeadline=(Get-Date).AddSeconds(15)
        while((Get-Date) -lt $gwDeadline){
            if(Test-TcpPort "127.0.0.1" $GatewayPort){break}
            Start-Sleep -Milliseconds 500
        }
    }
    if(Test-TcpPort "127.0.0.1" $GatewayPort){
        Start-Process ("http://127.0.0.1:{0}/?live=1" -f $GatewayPort) | Out-Null
        Write-Log ("Local cockpit gateway opened on port {0}" -f $GatewayPort) "OK"
    } else {
        Write-Log "Local cockpit gateway did not start. Falling back to existing cockpit open behavior." "WARN"
    }
}
'@
    $c=$c.Replace($needle,$patch)
    $utf8bom=New-Object System.Text.UTF8Encoding($true)
    [IO.File]::WriteAllText($Launcher,$c,$utf8bom)
}
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host " Local LIVE Gateway installed" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ("Gateway : "+$Gateway)
Write-Host ("Backup  : "+$backup)
Write-Host "Next launch will open http://127.0.0.1:28581/?live=1" -ForegroundColor Cyan
