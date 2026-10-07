# AI Cockpit V10 Cleanup Log

Date: 2026-10-08 JST

Purpose: remove obsolete pre-V10 runtime artifacts while retaining durable incident/log evidence.

## Removed from active source tree
The following classes were removed:
- V8/V9 Controller/Gateway/Voice/Excel identity probe
- V8/V9 RUN and STOP scripts
- V8->V9 switch script
- V4/V5/V6 START/install scripts
- V5 autoclose patch
- V9 canonical workbook recovery helpers
- V9 canonical Excel diagnostic scripts

Git history remains the recovery/audit trail.

## Commits
- Individual cleanup sequence ended at: fc2821b993d4b68cc48de9c4fa962be5a68f9e7a
- Bulk legacy cleanup: a9633f586f10e3d628e7ae758b403728ab38c94b

## Retained active V10 core
- downloads/RUN_AI_COCKPIT_V10.ps1
- downloads/AI_COCKPIT_CONTROLLER_V10.ps1
- downloads/STOP_AI_COCKPIT_V10.ps1
- downloads/AI_COCKPIT_GATEWAY_V10.ps1
- downloads/AI_COCKPIT_VOICE_BRIDGE_V10.ps1
- downloads/EXCEL_IDENTITY_PROBE_V10.ps1
- downloads/START_AI_COCKPIT_V10.cmd
- downloads/STOP_AI_COCKPIT_V10.cmd
- index.html
- V10 Watcher/Collector/Heartbeat/Shadow components

## Durable incident record
See:
- docs/AI_COCKPIT_V10_INCIDENT_AND_FIX_LOG.md
- docs/AI_COCKPIT_V10_LOG_POLICY.md


## Local V10 runtime folder cleanup completed — 2026-10-08

Target:
`C:\Users\yusuk\Desktop\デイトレ\MarketSpeed II RSS\files`

Completed:
- Deleted 60 unreferenced legacy backup files (~5.54 MB).
- Removed the now-empty V8 evacuation folder.
- Moved 18 log files covering the prior 9 days into `history\<date>` folders.
- Total files reduced from 274 to 214.
- Files visible at the folder root reduced from 46 to 28.

Verification:
- 8 required V10 files matched the recorded SHA256 values.
- Kept the active Excel workbook, current state/status JSON, same-day logs, and history under `records`.
- Verified content integrity for all 18 moved logs.
- Confirmed zero unexpected missing files.
- No Excel / PowerShell / MarketSpeed II stop or restart was performed.
- No active runtime code was changed.
- Full runtime acceptance was outside the scope of this cleanup.

Evidence retained in the local working folder's `outputs` directory:
- `deletion_manifest.csv`
- `history_move_manifest.csv`
- `remaining_files.csv`
- `verification.json`
- `history_verification.json`

Status:
`LOCAL_RUNTIME_FOLDER_CLEANUP=PASS`

No additional deletion rules or automatic cleanup scheduling were configured.
