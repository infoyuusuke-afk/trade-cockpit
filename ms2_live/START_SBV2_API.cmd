@echo off
setlocal

set "SBV2_DIR=C:\sbv2\Style-Bert-VITS2"
set "SBV2_PY=%SBV2_DIR%\venv\Scripts\python.exe"
set "SBV2_SERVER=%SBV2_DIR%\server_fastapi.py"

echo ===================================================
echo AI Cockpit - Style-Bert-VITS2 Voice API
echo ===================================================

if not exist "%SBV2_PY%" (
  echo ERROR: SBV2 Python not found: %SBV2_PY%
  pause
  exit /b 1
)
if not exist "%SBV2_SERVER%" (
  echo ERROR: server_fastapi.py not found: %SBV2_SERVER%
  pause
  exit /b 1
)

powershell.exe -NoLogo -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:5000/status' -TimeoutSec 2; if($r.StatusCode -eq 200){exit 0} } catch {}; exit 1"
if not errorlevel 1 (
  echo SBV2 API is already running at http://127.0.0.1:5000
  exit /b 0
)

cd /d "%SBV2_DIR%"
"%SBV2_PY%" server_fastapi.py
