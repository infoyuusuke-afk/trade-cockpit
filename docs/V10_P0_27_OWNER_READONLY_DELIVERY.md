# P0-27 OWNER read-only acceptance: pinned delivery

Status: prepared for safety review only. Run it only after the OWNER has
approved it separately. This page is not a stop, cutover or trading
authorisation.

## Pinned values

| Item | Value |
|---|---|
| Entry commit (full SHA, never a branch URL) | `d20f9655904468f8b201771a5753b8f106b38ec2` |
| Entry file | `downloads/VERIFY_V10_LEGACY_OWNER_READONLY_V1.ps1` |
| Entry Git blob | `fd40b678976aca40b1f8e01d36533d1d87ac3a0e` |
| Entry SHA256 (exact bytes served for that commit) | `71E3DF68DE60ACCADCF65FC4854D3CEF0C2B5B3EDF5D75B81481788718F858F9` |
| Reviewed components commit (`-PinnedCommit`) | `f2261e257bc22bc70fe5105e94f6494c291dae08` |

The entry checks the two components it fetches by Git blob, but it cannot
check itself. The procedure below therefore fetches the entry by full
commit SHA into a new TEMP folder and runs it only if its SHA256 matches the
table. Never run a local, edited or branch-tracking copy.

## Procedure (Windows PowerShell 5.1, strict mode only)

The first OWNER acceptance uses strict mode only. Do not add
`-IncludeStopDryRun` or `-Execute`. The procedure never passes either.

```powershell
$c='d20f9655904468f8b201771a5753b8f106b38ec2'; $h='71E3DF68DE60ACCADCF65FC4854D3CEF0C2B5B3EDF5D75B81481788718F858F9'
$d=Join-Path $env:TEMP ('v10-owner-entry-'+[guid]::NewGuid().ToString('N')); [void](New-Item -ItemType Directory -Path $d)
$f=Join-Path $d 'VERIFY_V10_LEGACY_OWNER_READONLY_V1.ps1'
[Net.ServicePointManager]::SecurityProtocol=[Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest -UseBasicParsing -Uri "https://raw.githubusercontent.com/infoyuusuke-afk/trade-cockpit/$c/downloads/VERIFY_V10_LEGACY_OWNER_READONLY_V1.ps1" -OutFile $f
$s=[Security.Cryptography.SHA256]::Create(); $got=([BitConverter]::ToString($s.ComputeHash([IO.File]::ReadAllBytes($f)))).Replace('-',''); $s.Dispose()
if ($got -cne $h) { 'ENTRY_RESULT=BLOCKED_ENTRY_HASH_MISMATCH' } else { powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $f -PinnedCommit f2261e257bc22bc70fe5105e94f6494c291dae08 }
Remove-Item -LiteralPath $d -Recurse -Force
```

`-Root` is left at its default `C:\AI_Cockpit_OneClick_Starter`.

When the P0-27 admission gate blocks, the new optional P0_27_BLOCK_PORT and P0_27_BLOCK_DETAIL are masked fixed reason codes only. They never prove ownership or authorize a stop. No PID, path, command-line arguments, source text or workbook name is emitted.

## What a pass means and does not mean

- `P0_27_RESULT=READONLY_VERIFIED` means only this: the legacy session's
  processes, Start-Job bridges, venv children, BRAIN status and V10 listeners
  were attributed, and the state file, Excel process set, listeners, admitted
  processes and listed launch files were identical before and after.
- `STOP_ALLOWED=false`, `CUTOVER_ELIGIBLE=false` and
  `REAL_SUBMIT_ALLOWED=false` stay false on every result.
- `EXCEL_WORKBOOK_COEXISTENCE=NOT_EVALUATED`: a pass says nothing about
  whether a new V10 can start while business Excel is open.
- Launch files: only the folders the entry could list are compared
  (`LAUNCH_SCOPE=LISTED_FOLDERS_ONLY`, `LAUNCH_DIRS_CHECKED`,
  `LAUNCH_DIRS_ABSENT`):
  - the root folder: CMD, BAT, LNK, PS1 and VBS files;
  - the user, OneDrive and common Desktop folders, and the user and common
    Startup folders: LNK, CMD and BAT files.
  Other desktops, profiles or shortcuts elsewhere are not inspected. This is
  not a check of every shortcut on the PC.
- The only writes are the TEMP folders above. They are removed, and
  `TEMP_REMOVED=true` reports the entry's own folder.
- Output is codes and counts only. Share the printed lines; they contain no
  paths, PIDs, command lines or workbook names.
