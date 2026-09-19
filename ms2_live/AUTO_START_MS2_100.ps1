param([int]$WaitMinutes = 15)

$ErrorActionPreference = "Stop"
$speaker = New-Object -ComObject SAPI.SpVoice
$speaker.Volume = 100
$speaker.Rate = -2   # ユーザー指摘（聞き取りづらい）への対応。標準(0)よりやや遅くする
$workbook = Join-Path $PSScriptRoot "Kioxia_MS2_RSS_Live_Signals.xlsx"
$collector = Join-Path $PSScriptRoot "MS2_RSS_100_Collector.ps1"
$strategySpeaker = Join-Path $PSScriptRoot "SPEAK_TODAY_STRATEGY.ps1"
$methodAudit = Join-Path $PSScriptRoot "METHOD_PROFIT_AUDIT.ps1"
$log = Join-Path $PSScriptRoot "auto_start.log"

function Write-Log([string]$message) {
    Add-Content -Path $log -Encoding UTF8 -Value ((Get-Date).ToString("yyyy-MM-dd HH:mm:ss")+" "+$message)
}

# ユーザー指摘（2026-09-15）: 「全体的に音声が聞き取りづらい」への対応。Watcher・Heartbeat等と
# 共有の名前付きMutexで音声を直列化し、複数プロセスの発話が重ならないようにする。
function Invoke-SerializedSpeak($speaker, [string]$text, [int]$timeoutMs = 20000) {
    if ($null -eq $speaker -or [string]::IsNullOrEmpty($text)) { return }
    $mutex = $null
    $acquired = $false
    try {
        $mutex = New-Object System.Threading.Mutex($false, "Global\KioxiaVoiceMutex")
        $acquired = $mutex.WaitOne($timeoutMs)
        $speaker.Speak($text, 0) | Out-Null
    } catch {
    } finally {
        if ($acquired -and $null -ne $mutex) { try { $mutex.ReleaseMutex() } catch {} }
        if ($null -ne $mutex) { $mutex.Dispose() }
    }
}

$existing = @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*MS2_RSS_100_Collector.ps1*" })
if ($existing.Count -gt 0) { Write-Log "collector already running"; exit 0 }

# Excelがバックグラウンドに残った状態で別インスタンスを開くと、RSSタブが消えることがある。
# 未保存ブックを守るため強制終了はせず、利用者へ終了を依頼して安全停止する。
$excelProcesses = @(Get-Process EXCEL -ErrorAction SilentlyContinue)
if ($excelProcesses.Count -gt 0) {
    Write-Log "Excel process already exists; automatic start stopped to protect unsaved work"
    Invoke-SerializedSpeak $speaker "エクセルがすでに起動しています。タスクマネージャーを確認し、すべてのエクセルを終了してから、今すぐ自動起動テストを実行してください。"
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show("Excelがバックグラウンドに残っています。`n未保存データ保護のため自動起動を止めました。`nExcelをすべて終了してから再実行してください。","AIコクピット自動起動") | Out-Null
    exit 3
}

# SBV2音声ブリッジ（PR #19・共有シートC-032/C-033、ユーザー依頼2026-09-19）: インストール
# されていれば自動起動する。モデル読み込みに数十秒かかるため、この後のMS2ログイン待ち
# （ユーザーの手動操作＋Read-Host）と並行して進むよう、ここで早めに起動要求だけ出す。
# 未インストール・起動失敗時は何もしない。SPEAK_LIVE_EMOTION.ps1側に既存のSAPIフォール
# バックがあるため、音声自体が出なくなることはない（Test-SbV2Ready→ダメならSAPI）。
$sbv2Root = "C:\sbv2\Style-Bert-VITS2"
$sbv2Server = Join-Path $sbv2Root "Server.bat"
$sbv2Running = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*server_fastapi.py*" })
if ($sbv2Running.Count -gt 0) {
    Write-Log "sbv2 api already running"
} elseif (Test-Path $sbv2Server) {
    try {
        Start-Process -FilePath $sbv2Server -WorkingDirectory $sbv2Root -WindowStyle Minimized
        Write-Log "sbv2 api launch requested"
    } catch {
        Write-Log ("sbv2 api launch failed: " + $_.Exception.Message)
    }
} else {
    Write-Log "sbv2 not installed at $sbv2Root; voice will use SAPI fallback"
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
    Write-Log "MarketSpeed II launch requested"
}
else { Write-Log "MarketSpeed II shortcut not found; waiting for manual launch" }

# ゆうすけの指摘（2026-09-14）: MS2はパスキー認証等でログイン完了までの時間が読めず、
# ログイン完了前にExcelを開くとRSSタブ自体が出ずRSS接続できない。固定待機時間では
# 短すぎる日もあるため、ログイン完了をユーザー自身に確定させ、Enterキーで進める。
Invoke-SerializedSpeak $speaker "マーケットスピードツーへログインしてください。ログインが完了したら、エンターキーを押してください。"
Write-Host "MarketSpeed IIへのログインが完了したら、Enterキーを押してください。" -ForegroundColor Cyan
Read-Host | Out-Null
Write-Log "user confirmed MS2 login complete"

if (Test-Path $workbook) { Start-Process $workbook; Write-Log "workbook launch requested" }
else { throw "Excelファイルがありません: $workbook" }

Invoke-SerializedSpeak $speaker "マーケットスピードツーへログインし、エクセルのRSS接続を確認してください。接続後、自動で監視を開始します。"
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
    Invoke-SerializedSpeak $speaker "エクセルを確認できないため、自動監視を開始できませんでした。"
    exit 2
}

# 2026-09-14夜の実機テストで判明したバグ修正: -ArgumentListに配列でパスを渡すと、
# パスにスペースが含まれる場合（このフォルダー自体がそう）引用符が付かず、
# 子プロセスが-Fileの引数を正しく受け取れず起動直後に終了していた（プロセスが一切残らない）。
# 単一の文字列でパスを明示的にダブルクォートすることで回避する。
if (Test-Path $strategySpeaker) {
    Start-Process powershell.exe -WindowStyle Hidden -ArgumentList ('-NoLogo -NoProfile -ExecutionPolicy Bypass -File "' + $strategySpeaker + '"')
    Write-Log "today strategy speaker started"
}
if (Test-Path $methodAudit) {
    Start-Process powershell.exe -WindowStyle Hidden -ArgumentList ('-NoLogo -NoProfile -ExecutionPolicy Bypass -File "' + $methodAudit + '"')
    Write-Log "method profit audit started"
}

# ゆうすけの意向（2026-09-14）: MS2ログインだけ手動で、あとは自動化したい。
# Kioxia_RSS_Live_Watcher.ps1は既存の自動起動チェーンに含まれていなかったため追加する。
# 手動起動時と同じくウィンドウは表示したままにする（停止したいときにCtrl+Cで安全に止められるように）。
$kioxiaWatcher = Join-Path $PSScriptRoot "Kioxia_RSS_Live_Watcher.ps1"
$alreadyRunning = @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*Kioxia_RSS_Live_Watcher.ps1*" })
if ($alreadyRunning.Count -gt 0) {
    Write-Log "kioxia watcher already running"
} elseif (Test-Path $kioxiaWatcher) {
    Start-Process powershell.exe -ArgumentList ('-NoLogo -NoProfile -ExecutionPolicy Bypass -NoExit -File "' + $kioxiaWatcher + '"')
    Write-Log "kioxia watcher started"
} else {
    Write-Log "kioxia watcher script not found: $kioxiaWatcher"
}

# 2026-09-15未明・ChatGPT C-011指摘への対応: DASHBOARD!A5等のNOW()ベース安全ゲートは、
# Watcherが完全に落ちると再計算が止まり凍結してしまう（実機の独立テストで確認済み）。
# Watcher本体とは別の最小限プロセスが再計算だけを担うことで、Watcherがどんな理由で
# 落ちても安全ゲートが正しく機能し続けるようにする。
$heartbeat = Join-Path $PSScriptRoot "Kioxia_Safety_Heartbeat.ps1"
$heartbeatRunning = @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*Kioxia_Safety_Heartbeat.ps1*" })
if ($heartbeatRunning.Count -gt 0) {
    Write-Log "safety heartbeat already running"
} elseif (Test-Path $heartbeat) {
    Start-Process powershell.exe -WindowStyle Hidden -ArgumentList ('-NoLogo -NoProfile -ExecutionPolicy Bypass -File "' + $heartbeat + '"')
    Write-Log "safety heartbeat started"
} else {
    Write-Log "safety heartbeat script not found: $heartbeat"
}

Write-Log "collector starting"
& powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $collector -StopAfterClose
