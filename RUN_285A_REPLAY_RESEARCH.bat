@echo off
setlocal
cd /d "%~dp0"
python scripts\run_latest_tradingview_replay.py --symbol TSE:285A
if errorlevel 1 (
  echo.
  echo Research run failed. No live order was sent.
  pause
  exit /b 1
)
echo.
echo Research run completed. Results are under data\replay_research_run
pause
