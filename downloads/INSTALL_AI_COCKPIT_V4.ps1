param([string]$Root = "C:\AI_Cockpit_OneClick_Starter")

$ErrorActionPreference="Stop"
$base="https://raw.githubusercontent.com/infoyuusuke-afk/trade-cockpit/main"

function Resolve-RuntimeDir {
    $roots=@([Environment]::GetFolderPath("Desktop"),(Join-Path $env:USERPROFILE "Desktop"),(Join-Path $env:USERPROFILE "OneDrive\Desktop")) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique
    $hits=foreach($r in $roots){ Get-ChildItem -LiteralPath $r -Recurse -File -Filter "MS2_RSS_100_Collector.ps1" -ErrorAction SilentlyContinue }
    $preferred=@($hits | Where-Object { $_.FullName -like "*MarketSpeed II RSS\files*" } | Sort-Object LastWriteTime -Descending | Select-Object -First 1)
    if($preferred.Count -gt 0){ return $preferred[0].Directory.FullName }
    $any=@($hits | Sort-Object LastWriteTime -Descending | Select-Object -First 1)
    if($any.Count -gt 0){ return $any[0].Directory.FullName }
    throw "Runtime folder not found."
}

$RuntimeDir=Resolve-RuntimeDir
$cache="?x="+(Get-Date -Format "yyyyMMddHHmmss")

if(-not(Test-Path -LiteralPath $Root)){ New-Item -ItemType Directory -Path $Root -Force | Out-Null }

Write-Host "[1/4] Downloading V4 launcher..." -ForegroundColor Cyan
Invoke-WebRequest ($base+"/downloads/START_AI_COCKPIT_V4.ps1"+$cache) -OutFile (Join-Path $Root "START_AI_COCKPIT_V4.ps1") -UseBasicParsing

Write-Host "[2/4] Refreshing runtime components..." -ForegroundColor Cyan
Invoke-WebRequest ($base+"/ms2_live/MS2_RSS_100_Collector.ps1"+$cache) -OutFile (Join-Path $RuntimeDir "MS2_RSS_100_Collector.ps1") -UseBasicParsing
Invoke-WebRequest ($base+"/ms2_live/Kioxia_Safety_Heartbeat.ps1"+$cache) -OutFile (Join-Path $RuntimeDir "Kioxia_Safety_Heartbeat.ps1") -UseBasicParsing
Invoke-WebRequest ($base+"/downloads/AI_Cockpit_Local_Gateway.ps1"+$cache) -OutFile (Join-Path $Root "AI_Cockpit_Local_Gateway.ps1") -UseBasicParsing

Write-Host "[3/4] Validating launcher syntax..." -ForegroundColor Cyan
$tokens=$null
$errors=$null
[System.Management.Automation.Language.Parser]::ParseFile((Join-Path $Root "START_AI_COCKPIT_V4.ps1"),[ref]$tokens,[ref]$errors) | Out-Null
if($errors.Count -gt 0){
    $errors | ForEach-Object { Write-Host $_.Message -ForegroundColor Red }
    throw "V4 launcher syntax validation failed."
}

Write-Host "[4/4] Creating new shortcut..." -ForegroundColor Cyan
$desktop=[Environment]::GetFolderPath("Desktop")
$lnk=Join-Path $desktop "AI Cockpit START V4.lnk"
$ws=New-Object -ComObject WScript.Shell
$s=$ws.CreateShortcut($lnk)
$s.TargetPath="$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$s.Arguments='-NoLogo -NoProfile -ExecutionPolicy Bypass -NoExit -File "'+(Join-Path $Root "START_AI_COCKPIT_V4.ps1")+'"'
$s.WorkingDirectory=$Root
$s.WindowStyle=1
$s.Description="AI Cockpit V4 startup"
$s.Save()

Write-Host ""
Write-Host "V4 INSTALL COMPLETE" -ForegroundColor Green
Write-Host $lnk -ForegroundColor Cyan
Write-Host "Use only: AI Cockpit START V4" -ForegroundColor Yellow