param(
    [string]$Root = "C:\AI_Cockpit_OneClick_Starter",
    [ValidateSet("main","fix/live-session-state-v1")]
    [string]$Channel = "main"
)

$ErrorActionPreference="Stop"
$ref = if($Channel -eq "main"){"main"}else{"fix/live-session-state-v1"}
$base="https://raw.githubusercontent.com/infoyuusuke-afk/trade-cockpit/"+$ref
$cache="?x="+(Get-Date -Format "yyyyMMddHHmmss")
Write-Host ("Install channel: "+$Channel+" / ref: "+$ref) -ForegroundColor Yellow
$launcher=Join-Path $Root "START_AI_COCKPIT_V6.ps1"
$gateway=Join-Path $Root "AI_Cockpit_Local_Gateway.ps1"

if(-not(Test-Path -LiteralPath $Root)){ New-Item -ItemType Directory -Path $Root -Force | Out-Null }

Write-Host "[1/5] Downloading V6 launcher and local gateway..." -ForegroundColor Cyan
Invoke-WebRequest ($base+"/downloads/START_AI_COCKPIT_V6.ps1"+$cache) -OutFile $launcher -UseBasicParsing
Invoke-WebRequest ($base+"/downloads/AI_Cockpit_Local_Gateway.ps1"+$cache) -OutFile $gateway -UseBasicParsing

Write-Host "[2/5] Validating launcher/gateway syntax..." -ForegroundColor Cyan
$tokens=$null
$errors=$null
[System.Management.Automation.Language.Parser]::ParseFile($launcher,[ref]$tokens,[ref]$errors) | Out-Null
if($errors.Count -gt 0){
    $errors | ForEach-Object { Write-Host $_.Message -ForegroundColor Red }
    throw "V6 launcher syntax validation failed."
}
$gt=$null
$ge=$null
[System.Management.Automation.Language.Parser]::ParseFile($gateway,[ref]$gt,[ref]$ge) | Out-Null
if($ge.Count -gt 0){
    $ge | ForEach-Object { Write-Host $_.Message -ForegroundColor Red }
    throw "Local gateway syntax validation failed."
}

$marker=Join-Path $Root "V6_INSTALL_CHANNEL.txt"
@(
    "channel="+$Channel
    "ref="+$ref
    "installed_at="+(Get-Date -Format "yyyy-MM-ddTHH:mm:sszzz")
    "launcher="+$launcher
) | Set-Content -LiteralPath $marker -Encoding UTF8

Write-Host "[3/5] Updating coherent MS2 runtime scripts..." -ForegroundColor Cyan
$desktop=[Environment]::GetFolderPath("Desktop")
$collectorCandidates=@(Get-ChildItem -Path $desktop -Filter "MS2_RSS_100_Collector.ps1" -File -Recurse -ErrorAction SilentlyContinue | Where-Object { $_.FullName -like "*MarketSpeed II RSS*files*" })
if($collectorCandidates.Count -ne 1){ throw ("MS2 runtime path must resolve uniquely. found="+$collectorCandidates.Count) }
$runtimeDir=$collectorCandidates[0].Directory.FullName
$runtimeFiles=@(
    "MS2_RSS_100_Collector.ps1",
    "Kioxia_Safety_Heartbeat.ps1",
    "Kioxia_RSS_Live_Watcher.ps1"
)
foreach($name in $runtimeFiles){
    $target=Join-Path $runtimeDir $name
    $tmp=$target+".new"
    Invoke-WebRequest ($base+"/ms2_live/"+$name+$cache) -OutFile $tmp -UseBasicParsing
    $rt=$null; $re=$null
    [System.Management.Automation.Language.Parser]::ParseFile($tmp,[ref]$rt,[ref]$re) | Out-Null
    if($re.Count -gt 0){ Remove-Item $tmp -Force -ErrorAction SilentlyContinue; throw ($name+" syntax validation failed.") }
    if(Test-Path -LiteralPath $target){
        $backup=$target+".bak."+(Get-Date -Format "yyyyMMddHHmmss")
        Copy-Item -LiteralPath $target -Destination $backup -Force
    }
    Move-Item -LiteralPath $tmp -Destination $target -Force
    Write-Host ("      Updated: "+$name) -ForegroundColor Green
}

Write-Host "[4/5] Replacing startup shortcut..." -ForegroundColor Cyan
$desktop=[Environment]::GetFolderPath("Desktop")
$old=Join-Path $desktop "AI Cockpit START V5.lnk"
if(Test-Path -LiteralPath $old){ Remove-Item -LiteralPath $old -Force }
$lnk=Join-Path $desktop "AI Cockpit START V6.lnk"
$ws=New-Object -ComObject WScript.Shell
$s=$ws.CreateShortcut($lnk)
$s.TargetPath="$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$s.Arguments='-NoLogo -NoProfile -ExecutionPolicy Bypass -File "'+$launcher+'"'
$s.WorkingDirectory=$Root
$s.WindowStyle=1
$s.Description="AI Cockpit V6 startup - auto closes on success"
$s.Save()

Write-Host "[5/5] Install metadata complete." -ForegroundColor Cyan
Write-Host ""
Write-Host ("V6 INSTALL COMPLETE / "+$Channel) -ForegroundColor Green
Write-Host "Use only: AI Cockpit START V6" -ForegroundColor Yellow