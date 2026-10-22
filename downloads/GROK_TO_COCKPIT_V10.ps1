#requires -Version 5.1
<#
OWNER 2026-10-23: hands a Grok answer to the AI Cockpit by hand (no API, no cost).
Saves the clipboard text as RuntimeDir\grok_inbox\grok_<yyyyMMdd_HHmmss>.txt and checks it
with scripts\v10_grok_manual.py --check (the same reader the Brain uses). Nothing else is
touched: no Excel, no order path, no network. Keep this file ASCII (PowerShell 5.1 reads a
BOM-less script with the ANSI code page).
#>
[CmdletBinding()]
param([string]$RuntimeDir = "")
$ErrorActionPreference = "Stop"
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
if ([string]::IsNullOrWhiteSpace($RuntimeDir)) {
    $daytrade = -join @([char]0x30C7, [char]0x30A4, [char]0x30C8, [char]0x30EC)
    foreach ($c in @((Join-Path ([Environment]::GetFolderPath("Desktop")) ($daytrade + "\MarketSpeed II RSS\files")),
                     (Join-Path $env:USERPROFILE ("OneDrive\Desktop\" + $daytrade + "\MarketSpeed II RSS\files")))) {
        if (Test-Path -LiteralPath $c -PathType Container) { $RuntimeDir = $c; break }
    }
}
if (-not $RuntimeDir) { Write-Output "NG: RuntimeDir not found"; exit 2 }
$text = Get-Clipboard -Raw
if ([string]::IsNullOrWhiteSpace($text)) { Write-Output "NG: clipboard is empty (copy the Grok answer first)"; exit 2 }
if ($text.Length -gt 60000) { Write-Output "NG: clipboard text is too long"; exit 2 }
$inbox = Join-Path $RuntimeDir "grok_inbox"
New-Item -ItemType Directory -Force -Path $inbox | Out-Null
$path = Join-Path $inbox ("grok_" + (Get-Date -Format "yyyyMMdd_HHmmss_fff") + ".txt")
if (Test-Path -LiteralPath $path) { Write-Output "NG: try again"; exit 2 }
[IO.File]::WriteAllText($path, $text, [Text.UTF8Encoding]::new($false))
$python = $null
foreach ($cand in @((Join-Path $repo ".venv\Scripts\python.exe"), (Join-Path $repo "venv\Scripts\python.exe"))) {
    if (Test-Path -LiteralPath $cand) { $python = $cand; break }
}
if (-not $python) { $cmd = Get-Command python.exe -ErrorAction SilentlyContinue; if ($cmd) { $python = $cmd.Source } }
if (-not $python) { Write-Output ("SAVED " + $path + " (python not found: not checked)"); exit 1 }
$env:PYTHONIOENCODING = "utf-8"
& $python -I (Join-Path $repo "scripts\v10_grok_manual.py") --check $path
$code = $LASTEXITCODE
if ($code -ne 0) {
    # an unusable answer is not left in the inbox
    Remove-Item -LiteralPath $path -ErrorAction SilentlyContinue
}
exit $code
