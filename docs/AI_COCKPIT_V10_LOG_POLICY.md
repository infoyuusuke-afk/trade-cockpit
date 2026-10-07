# AI Cockpit V10 Log Policy

Canonical runtime generation is V10 only.

## Keep
- V10 incident/fix history
- START/STOP lifecycle logs
- Controller/Gateway/Watcher/Collector/Shadow/Voice runtime logs
- error/fail-closed evidence
- daily trading/replay/acceptance logs needed for verification

## Do not keep as active runtime assets
- V4/V5/V6/V8/V9 launchers/controllers/gateways/watchers
- superseded recovery/diagnostic scripts
- one-off installers after migration completes

## Runtime log location policy
Runtime logs remain outside the tracked source tree unless they are needed as durable evidence.
When evidence must be shared across Cursor / Cloud / Work / other GPT chats, summarize it in docs and commit it to GitHub.

## Acceptance rule
Do not mark lifecycle PASS from START alone.
Required sequence:
START -> RUNNING -> STOP -> CLEAN -> RESTART

## Safety
- real_submit_allowed=false
- no global Excel kill
- no global PowerShell kill
- no MarketSpeed II force kill
- PID-specific cleanup only after identity verification
