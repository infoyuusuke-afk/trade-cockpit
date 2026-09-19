param([string]$Root = "C:\AI_Cockpit_OneClick_Starter")

$ErrorActionPreference = "Stop"
$launcher = Join-Path $Root "START_AI_COCKPIT.ps1"
if(-not(Test-Path -LiteralPath $launcher)){ throw "Launcher not found: $launcher" }

$cmdPath = Join-Path $Root "AI_COCKPIT_START_DEBUG.cmd"
$cmdText = @'
@echo off
title AI Cockpit Startup
cd /d "%~dp0"
echo ==============================================
echo  AI COCKPIT START WRAPPER
echo ==============================================
echo Launcher: %~dp0START_AI_COCKPIT.ps1
echo.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -NoExit -File "%~dp0START_AI_COCKPIT.ps1"
echo.
echo PowerShell returned to wrapper.
pause
'@

$ascii = New-Object System.Text.ASCIIEncoding
[IO.File]::WriteAllText($cmdPath,$cmdText,$ascii)

$desktopCandidates = @(
    [Environment]::GetFolderPath("Desktop"),
    (Join-Path $env:USERPROFILE "Desktop"),
    (Join-Path $env:USERPROFILE "OneDrive\Desktop")
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique

$ws = New-Object -ComObject WScript.Shell
foreach($desktop in $desktopCandidates){
    $lnk = Join-Path $desktop "AI Cockpit START.lnk"
    $s = $ws.CreateShortcut($lnk)
    $s.TargetPath = "$env:SystemRoot\System32\cmd.exe"
    $s.Arguments = '/k ""' + $cmdPath + '""'
    $s.WorkingDirectory = $Root
    $s.WindowStyle = 1
    $s.Description = "AI Cockpit startup - diagnostic wrapper"
    $s.Save()
    Write-Host ("Created: " + $lnk) -ForegroundColor Green
}

Write-Host ""
Write-Host "Use the new desktop shortcut: AI Cockpit START" -ForegroundColor Cyan
Write-Host "This wrapper cannot disappear instantly; CMD remains open even if PowerShell fails." -ForegroundColor Yellow