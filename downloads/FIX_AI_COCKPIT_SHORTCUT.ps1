param(
    [string]$Root = "C:\AI_Cockpit_OneClick_Starter"
)

$ErrorActionPreference = "Stop"

$Launcher = Join-Path $Root "START_AI_COCKPIT.ps1"
if(-not(Test-Path -LiteralPath $Launcher)){ throw "Launcher not found: $Launcher" }

$desktop=[Environment]::GetFolderPath("Desktop")
$name=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("QUnjgrPjgq/jg5Tjg4Pjg4jotbfli5U="))
$lnk=Join-Path $desktop ($name+".lnk")

$ws=New-Object -ComObject WScript.Shell
$s=$ws.CreateShortcut($lnk)
$s.TargetPath="$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$s.Arguments='-NoLogo -NoProfile -ExecutionPolicy Bypass -File "'+$Launcher+'"'
$s.WorkingDirectory=$Root
$s.WindowStyle=1
$s.Description="AI Cockpit clean startup"
$s.Save()

Write-Host "AI Cockpit shortcut repaired." -ForegroundColor Green
Write-Host $lnk -ForegroundColor Cyan
