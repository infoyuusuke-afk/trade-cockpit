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

if(-not(Test-Path -LiteralPath $Root)){ New-Item -ItemType Directory -Path $Root -Force | Out-Null }

Write-Host "[1/3] Downloading V6 launcher..." -ForegroundColor Cyan
Invoke-WebRequest ($base+"/downloads/START_AI_COCKPIT_V6.ps1"+$cache) -OutFile $launcher -UseBasicParsing

Write-Host "[2/3] Validating V6 syntax..." -ForegroundColor Cyan
$tokens=$null
$errors=$null
[System.Management.Automation.Language.Parser]::ParseFile($launcher,[ref]$tokens,[ref]$errors) | Out-Null
if($errors.Count -gt 0){
    $errors | ForEach-Object { Write-Host $_.Message -ForegroundColor Red }
    throw "V6 launcher syntax validation failed."
}

$marker=Join-Path $Root "V6_INSTALL_CHANNEL.txt"
@(
    "channel="+$Channel
    "ref="+$ref
    "installed_at="+(Get-Date -Format "yyyy-MM-ddTHH:mm:sszzz")
    "launcher="+$launcher
) | Set-Content -LiteralPath $marker -Encoding UTF8

Write-Host "[3/3] Replacing startup shortcut..." -ForegroundColor Cyan
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

Write-Host ""
Write-Host ("V6 INSTALL COMPLETE / "+$Channel) -ForegroundColor Green
Write-Host "Use only: AI Cockpit START V6" -ForegroundColor Yellow