param([string]$Root = "C:\AI_Cockpit_OneClick_Starter")

$ErrorActionPreference="Stop"
$launcher=Join-Path $Root "START_AI_COCKPIT_V5.ps1"
if(-not(Test-Path -LiteralPath $launcher)){ throw "V5 launcher not found: $launcher" }

$desktop=[Environment]::GetFolderPath("Desktop")
$lnk=Join-Path $desktop "AI Cockpit START V5.lnk"
$ws=New-Object -ComObject WScript.Shell
$s=$ws.CreateShortcut($lnk)
$s.TargetPath="$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$s.Arguments='-NoLogo -NoProfile -ExecutionPolicy Bypass -File "'+$launcher+'"'
$s.WorkingDirectory=$Root
$s.WindowStyle=1
$s.Description="AI Cockpit V5 startup - auto close on success"
$s.Save()

Write-Host "V5 shortcut updated: startup window will auto-close on success." -ForegroundColor Green
Write-Host $lnk -ForegroundColor Cyan