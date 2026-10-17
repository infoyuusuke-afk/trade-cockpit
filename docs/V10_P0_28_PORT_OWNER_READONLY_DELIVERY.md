# P0-28 OWNER port-owner diagnosis — pinned read-only delivery

Status: PREPARED for independent GPT review. OWNER execution is **not** authorized until the dedicated Windows synthetic CI and safety review pass.

## Fixed source of truth

| Field | Exact value |
|---|---|
| Immutable commit | `30e4838f47a29ce26dad328f5002d972732c2600` |
| Entry file | `downloads/DIAGNOSE_V10_LEGACY_PORT_OWNER_READONLY_V1.ps1` |
| Git blob SHA1 | `2e6db75270f93425760580a4dc6a1a8c6d5c1060` |
| SHA256 of exact ASCII/UTF-8 LF bytes | `8855AF82866A7ABCE972275D3DB8CF855251DB2D1F612B80E669D0548199C620` |

Never execute branch-tracking URLs or an unverified local copy. Only the fixed commit's exact byte content may run. Never run `STOP_V10_LEGACY_SESSION_V1.ps1 -Execute` in this diagnostic step.

## Procedure (only after separate OWNER authorization)

Open **Windows PowerShell 5.1** separately while leaving the existing AI Cockpit running. Copy as a single block. This code writes only to its own temporary directory and removes that directory.

```powershell
$c='30e4838f47a29ce26dad328f5002d972732c2600'
$h='8855AF82866A7ABCE972275D3DB8CF855251DB2D1F612B80E669D0548199C620'
$d=Join-Path $env:TEMP ('p028-owner-'+[guid]::NewGuid().ToString('N'))
try {
  [void](New-Item -ItemType Directory -LiteralPath $d -ErrorAction Stop)
  $f=Join-Path $d 'DIAGNOSE_V10_LEGACY_PORT_OWNER_READONLY_V1.ps1'
  [Net.ServicePointManager]::SecurityProtocol=[Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
  Invoke-WebRequest -UseBasicParsing -Uri "https://raw.githubusercontent.com/infoyuusuke-afk/trade-cockpit/$c/downloads/DIAGNOSE_V10_LEGACY_PORT_OWNER_READONLY_V1.ps1" -OutFile $f -ErrorAction Stop
  $got=(Get-FileHash -Algorithm SHA256 -LiteralPath $f -ErrorAction Stop).Hash
  if ($got -cne $h) { Write-Output 'P0_28_DELIVERY=BLOCKED_HASH_MISMATCH' }
  else { powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $f }
} finally {
  if(Test-Path -LiteralPath $d) { Remove-Item -LiteralPath $d -Recurse -Force }
}
```

## Interpreting the result

- `P0_28_RESULT=CLASSIFIED`: all listened-on V10 ports were categorized. `TRACKED_RECORDED` means a PID matches the state file, not that the process identity was cryptographically or independently proven. **This result is not P0-27 PASS or permission to stop.**
- `P0_28_RESULT=ATTRIBUTION_UNVERIFIED`: at least one listener requires investigation. Inspect the port number and `_REASON` enum.
- `P0_28_RESULT=INCONCLUSIVE`: state/process/listeners changed during the check; don't infer an incident, and don't retry automatically.
- `P0_28_RESULT=BLOCKED`: inspection is not possible or source state is unavailable.

Only count/status/reason code/port number are displayed. No PID, paths, command lines, workbook names, Excel COM or market data. The procedure never issues stops, restarts, orders, or cutovers.

`STATE_MODIFIED=false`, `PROCESSES_STOPPED=0`, `EXCEL_ACTION=NONE`, `STOP_ALLOWED=false`, `CUTOVER_ELIGIBLE=false`, `REAL_SUBMIT_ALLOWED=false` should always be present.

The current Windows machine displayed `WRONG_SOURCE_WORKBOOK` during startup; this tool **does not prove live market-source identity, fresh price, or data persistence**. Those are separate gates.

Do not use this as an excuse to weaken P0-27 admission or expand a stop list without independent evidence.
