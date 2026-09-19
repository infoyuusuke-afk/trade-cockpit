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
$utf8bom=New-Object System.Text.UTF8Encoding($true)

Write-Host "[1/5] Downloading V5 launcher..." -ForegroundColor Cyan
$launcher=Join-Path $Root "START_AI_COCKPIT_V5.ps1"
Invoke-WebRequest ($base+"/downloads/START_AI_COCKPIT_V5.ps1"+$cache) -OutFile $launcher -UseBasicParsing

Write-Host "[2/5] Refreshing all runtime components..." -ForegroundColor Cyan
$downloads=@{
    "MS2_RSS_100_Collector.ps1"="/ms2_live/MS2_RSS_100_Collector.ps1";
    "Kioxia_Safety_Heartbeat.ps1"="/ms2_live/Kioxia_Safety_Heartbeat.ps1";
    "BUILD_KIOXIA_TIME_STATS.ps1"="/ms2_live/BUILD_KIOXIA_TIME_STATS.ps1";
    "MS2_Common_Engine.ps1"="/ms2_live/MS2_Common_Engine.ps1";
    "watchlist_100.json"="/ms2_live/watchlist_100.json"
}
foreach($name in $downloads.Keys){
    Invoke-WebRequest ($base+$downloads[$name]+$cache) -OutFile (Join-Path $RuntimeDir $name) -UseBasicParsing
}
Invoke-WebRequest ($base+"/downloads/AI_Cockpit_Local_Gateway.ps1"+$cache) -OutFile (Join-Path $Root "AI_Cockpit_Local_Gateway.ps1") -UseBasicParsing

Write-Host "[3/5] Re-saving PowerShell files as UTF-8 BOM..." -ForegroundColor Cyan
$psFiles=@(
    $launcher,
    (Join-Path $Root "AI_Cockpit_Local_Gateway.ps1"),
    (Join-Path $RuntimeDir "MS2_RSS_100_Collector.ps1"),
    (Join-Path $RuntimeDir "Kioxia_Safety_Heartbeat.ps1"),
    (Join-Path $RuntimeDir "BUILD_KIOXIA_TIME_STATS.ps1"),
    (Join-Path $RuntimeDir "MS2_Common_Engine.ps1")
)
foreach($p in $psFiles){
    $txt=[IO.File]::ReadAllText($p,[Text.Encoding]::UTF8)
    [IO.File]::WriteAllText($p,$txt,$utf8bom)
}

Write-Host "[4/5] Validating PowerShell syntax..." -ForegroundColor Cyan
foreach($p in $psFiles){
    $tokens=$null
    $errors=$null
    [System.Management.Automation.Language.Parser]::ParseFile($p,[ref]$tokens,[ref]$errors) | Out-Null
    if($errors.Count -gt 0){
        Write-Host ("Syntax errors in: "+$p) -ForegroundColor Red
        $errors | ForEach-Object { Write-Host $_.Message -ForegroundColor Red }
        throw "PowerShell syntax validation failed."
    }
}

Write-Host "[5/5] Creating V5 shortcut..." -ForegroundColor Cyan
$desktop=[Environment]::GetFolderPath("Desktop")
$lnk=Join-Path $desktop "AI Cockpit START V5.lnk"
$ws=New-Object -ComObject WScript.Shell
$s=$ws.CreateShortcut($lnk)
$s.TargetPath="$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$s.Arguments='-NoLogo -NoProfile -ExecutionPolicy Bypass -NoExit -File "'+$launcher+'"'
$s.WorkingDirectory=$Root
$s.WindowStyle=1
$s.Description="AI Cockpit V5 startup"
$s.Save()

Write-Host ""
Write-Host "V5 INSTALL COMPLETE" -ForegroundColor Green
Write-Host ("Runtime: "+$RuntimeDir) -ForegroundColor Cyan
Write-Host ("Shortcut: "+$lnk) -ForegroundColor Cyan
Write-Host "Important: V5 preserves an already-working SBV2 server on port 5000." -ForegroundColor Yellow