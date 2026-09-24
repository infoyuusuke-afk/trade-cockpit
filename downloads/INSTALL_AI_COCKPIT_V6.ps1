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
$diag=Join-Path $Root "DIAG_AI_COCKPIT_V6_EXCEL.ps1"

# Windows PowerShell 5.1 treats UTF-8 without BOM as the active ANSI code page.
# GitHub raw files are UTF-8 without BOM, so Japanese string literals can be
# misparsed and produce fake syntax errors. Always normalize downloaded .ps1
# files to UTF-8 with BOM before parsing or executing them.
function Save-RemotePowerShellUtf8Bom([string]$Url,[string]$Destination) {
    $raw = $Destination + ".download"
    Invoke-WebRequest $Url -OutFile $raw -UseBasicParsing
    try {
        $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        $utf8Bom = New-Object System.Text.UTF8Encoding($true)
        $text = [IO.File]::ReadAllText($raw,$utf8NoBom)
        [IO.File]::WriteAllText($Destination,$text,$utf8Bom)
    } finally {
        Remove-Item -LiteralPath $raw -Force -ErrorAction SilentlyContinue
    }
}

if(-not(Test-Path -LiteralPath $Root)){ New-Item -ItemType Directory -Path $Root -Force | Out-Null }

Write-Host "[1/6] Downloading V6 launcher, gateway, and Excel diagnostic..." -ForegroundColor Cyan
Save-RemotePowerShellUtf8Bom ($base+"/downloads/START_AI_COCKPIT_V6.ps1"+$cache) $launcher
Save-RemotePowerShellUtf8Bom ($base+"/downloads/AI_Cockpit_Local_Gateway.ps1"+$cache) $gateway
Save-RemotePowerShellUtf8Bom ($base+"/downloads/DIAG_AI_COCKPIT_V6_EXCEL.ps1"+$cache) $diag

Write-Host "[2/6] Validating launcher/gateway/diagnostic syntax..." -ForegroundColor Cyan
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
$dt=$null
$de=$null
[System.Management.Automation.Language.Parser]::ParseFile($diag,[ref]$dt,[ref]$de) | Out-Null
if($de.Count -gt 0){
    $de | ForEach-Object { Write-Host $_.Message -ForegroundColor Red }
    throw "Excel diagnostic syntax validation failed."
}

$marker=Join-Path $Root "V6_INSTALL_CHANNEL.txt"
@(
    "channel="+$Channel
    "ref="+$ref
    "installed_at="+(Get-Date -Format "yyyy-MM-ddTHH:mm:sszzz")
    "launcher="+$launcher
) | Set-Content -LiteralPath $marker -Encoding UTF8

Write-Host "[3/6] Updating coherent MS2 runtime scripts..." -ForegroundColor Cyan
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
    Save-RemotePowerShellUtf8Bom ($base+"/ms2_live/"+$name+$cache) $tmp
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

Write-Host "[4/6] Replacing startup shortcut..." -ForegroundColor Cyan
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

Write-Host "[5/6] Creating Excel diagnostic shortcut..." -ForegroundColor Cyan
$diagLnk=Join-Path $desktop "AI Cockpit DIAG V6.lnk"
$d=$ws.CreateShortcut($diagLnk)
$d.TargetPath="$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$d.Arguments='-NoLogo -NoProfile -ExecutionPolicy Bypass -NoExit -File "'+$diag+'"'
$d.WorkingDirectory=$Root
$d.WindowStyle=1
$d.Description="AI Cockpit V6 Excel startup diagnostic"
$d.Save()

Write-Host "[6/6] Install metadata complete." -ForegroundColor Cyan
Write-Host ""
Write-Host ("V6 INSTALL COMPLETE / "+$Channel) -ForegroundColor Green
Write-Host "Startup: AI Cockpit START V6" -ForegroundColor Yellow
Write-Host "Diagnostic: AI Cockpit DIAG V6" -ForegroundColor Yellow