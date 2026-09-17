@echo off
setlocal
cd /d "%~dp0"
title MS2 RSS 100 STOCK LIVE

echo ===================================================
echo MS2 RSS - 100 STOCK LIVE TOP5
echo ===================================================
echo 1. MarketSpeed II: login
echo 2. Excel: open Kioxia_MS2_RSS_Live_Signals.xlsx
echo 3. Excel RSS tab: confirm CONNECTED
echo 4. Keep Excel open
echo.
pause

rem Stop before launching background voices if the collector cannot attach to its workbook.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0TEST_MS2_WORKBOOK_READY.ps1"
if errorlevel 1 (
  echo Open the MS2 RSS workbook in Excel, confirm RSS connection, then start again.
  exit /b 1
)

rem ---------------------------------------------------
rem Voice API: start Style-Bert-VITS2 only when needed.
rem If SBV2 is unavailable, voice scripts fall back to
rem Windows SAPI and MS2 collection continues.
rem ---------------------------------------------------
powershell.exe -NoLogo -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:5000/status' -TimeoutSec 2; if($r.StatusCode -eq 200){exit 0} } catch {}; exit 1"
if errorlevel 1 (
  if exist "C:\sbv2\Style-Bert-VITS2\venv\Scripts\python.exe" (
    echo Starting SBV2 voice API...
    start "SBV2 Voice API" /min cmd.exe /c "cd /d C:\sbv2\Style-Bert-VITS2 && venv\Scripts\python server_fastapi.py"
    powershell.exe -NoLogo -NoProfile -Command "$ok=$false; foreach($i in 1..20){ try { $r=Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:5000/status' -TimeoutSec 2; if($r.StatusCode -eq 200){$ok=$true; break} } catch {}; Start-Sleep -Seconds 1 }; if($ok){exit 0}else{exit 1}"
    if errorlevel 1 (
      echo WARNING: SBV2 API did not become ready. Windows SAPI fallback will be used.
    ) else (
      echo SBV2 voice API ready.
    )
  ) else (
    echo WARNING: SBV2 is not installed at C:\sbv2\Style-Bert-VITS2.
    echo Windows SAPI fallback will be used.
  )
) else (
  echo SBV2 voice API already running.
)

start "AI Cockpit Strategy Voice" /min powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0SPEAK_TODAY_STRATEGY.ps1"
start "AI Cockpit Live Emotion" /min powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0SPEAK_LIVE_EMOTION.ps1"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -NoExit -File "%~dp0MS2_RSS_100_Collector.ps1"

echo.
pause
