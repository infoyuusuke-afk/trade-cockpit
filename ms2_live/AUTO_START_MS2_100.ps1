param([int]$WaitMinutes = 15)

$ErrorActionPreference = "Stop"
$speaker = New-Object -ComObject SAPI.SpVoice
$workbook = Join-Path $PSScriptRoot "Kioxia_MS2_RSS_Live_Signals.xlsx"
$collector = Join-Path $PSScriptRoot "MS2_RSS_100_Collector.ps1"
$strategySpeaker = Join-Path $PSScriptRoot "SPEAK_TODAY_STRATEGY.ps1"
$log = Join-Path $PSScriptRoot "auto_start.log"

function Write-Log([string]$message) {
    Add-Content -Path $log -Encoding UTF8 -Value ((Get-Date).ToString("yyyy-MM-dd HH:mm:ss")+" "+$message)
}

$existing = @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*MS2_RSS_100_Collector.ps1*" })
if ($existing.Count -gt 0) { Write-Log "collector already running"; exit 0 }

# Excelがバックグラウンドに残った状態で別インスタンスを開くと、RSSタブが消えることがある。
# 未保存ブックを守るため強制終了はせず、利用者へ終了を依頼して安全停止する。
$excelProcesses = @(Get-Process EXCEL -ErrorAction SilentlyContinue)
if ($excelProcesses.Count -gt 0) {
    Write-Log "Excel process already exists; automatic start stopped to protect unsaved work"
    $speaker.Speak("エクセルがすでに起動しています。タスクマネージャーを確認し、すべてのエクセルを終了してから、今すぐ自動起動テストを実行してください。",1) | Out-Null
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show("Excelがバックグラウンドに残っています。`n未保存データ保護のため自動起動を止めました。`nExcelをすべて終了してから再実行してください。","AIコクピット自動起動") | Out-Null
    exit 3
}

$marketSpeed = $null
$candidates = @(
    "$env:ProgramFiles\MARKETSPEED2\MARKETSPEED2.exe",
    "${env:ProgramFiles(x86)}\MARKETSPEED2\MARKETSPEED2.exe",
    "$env:LOCALAPPDATA\Rakuten Securities\MARKETSPEED2\MARKETSPEED2.exe"
)
foreach ($candidate in $candidates) { if ($candidate -and (Test-Path $candidate)) { $marketSpeed=$candidate; break } }
if (-not $marketSpeed) {
    $menus = @("$env:ProgramData\Microsoft\Windows\Start Menu\Programs","$env:APPDATA\Microsoft\Windows\Start Menu\Programs")
    foreach ($menu in $menus) {
        $shortcut = Get-ChildItem -Path $menu -Filter "*.lnk" -Recurse -ErrorAction SilentlyContinue | Where-Object { $_.Name -match "MARKETSPEED|マーケットスピード" } | Select-Object -First 1
        if ($shortcut) { $marketSpeed=$shortcut.FullName; break }
    }
}
if ($marketSpeed) {
    Start-Process $marketSpeed
    Write-Log "MarketSpeed II launch requested; waiting before Excel launch"
    Start-Sleep -Seconds 15
}
else { Write-Log "MarketSpeed II shortcut not found; waiting for manual launch" }

if (Test-Path $workbook) { Start-Process $workbook; Write-Log "workbook launch requested" }
else { throw "Excelファイルがありません: $workbook" }

$speaker.Speak("マーケットスピードツーへログインし、エクセルのRSS接続を確認してください。接続後、自動で監視を開始します。",1) | Out-Null
$deadline = (Get-Date).AddMinutes($WaitMinutes)
$ready = $false
while ((Get-Date) -lt $deadline) {
    try {
        $excel = [Runtime.InteropServices.Marshal]::GetActiveObject("Excel.Application")
        foreach ($book in $excel.Workbooks) {
            if ($book.Name -like "Kioxia_MS2_RSS_Live_Signals*.xlsx") { $ready=$true; break }
        }
    } catch {}
    if ($ready) { break }
    Start-Sleep -Seconds 5
}
if (-not $ready) {
    Write-Log "Excel workbook was not ready within timeout"
    $speaker.Speak("エクセルを確認できないため、自動監視を開始できませんでした。",1) | Out-Null
    exit 2
}

if (Test-Path $strategySpeaker) {
    Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @('-NoLogo','-NoProfile','-ExecutionPolicy','Bypass','-File',$strategySpeaker)
    Write-Log "today strategy speaker started"
}

Write-Log "collector starting"
& powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $collector -StopAfterClose
