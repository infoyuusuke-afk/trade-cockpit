$ErrorActionPreference = "Stop"
$taskName = "AI Cockpit MS2 Live"
$launcher = Join-Path $PSScriptRoot "AUTO_START_MS2_100.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ('-NoLogo -NoProfile -WindowStyle Normal -ExecutionPolicy Bypass -File "'+$launcher+'"')
$triggers = @(
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 8:00am
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Tuesday -At 8:00am
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Wednesday -At 8:00am
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Thursday -At 8:00am
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday -At 8:00am
)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 9) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "平日8:00の自動起動を設定しました。" -ForegroundColor Green
Write-Host "PCへログイン済みであることと、MarketSpeed IIのログイン確認は必要です。" -ForegroundColor Yellow
Read-Host "Enterキーで閉じる"
