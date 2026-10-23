#requires -Version 5.1
<#
OWNER 2026-10-23: the start window closes by itself after V10 stops; the reason it stopped
is kept in a log file in the AI cockpit folder; an abnormal stop is announced on screen and
by voice with the log location.

The desktop button (AI cockpit folder, 1_<start>.cmd) calls this script. It runs START_AI_COCKPIT_V10.ps1 with
this checkout's approval file exactly as START_AI_COCKPIT_V10.cmd does (no other change),
copies everything it prints into Desktop\<AI cockpit>\<start log>\yyyyMMdd_HHmmss.log and,
when it returns, writes one RESULT line:
- NORMAL_STOP: START returned 0, or the runner ended after a Safe Stop (Safe Stop removes
  V10_CONTROLLER_STATE.json only after every component has stopped);
- ABNORMAL_STOP: anything else (start blocked, runner failure with the state file left).
On ABNORMAL_STOP it shows a message box with the reason and the log path and reads one
sentence aloud with the Windows speech engine (the cockpit's own voice may be down too).
The window then closes by itself. Nothing here starts, stops or changes any V10 component.
Keep this file ASCII (Japanese text as \u escapes): PowerShell 5.1 reads a BOM-less file
with the ANSI code page.
#>
[CmdletBinding()]
param([string]$LogDir = "", [string]$StateFile = "C:\AI_Cockpit_OneClick_Starter\V10_CONTROLLER_STATE.json",
      [switch]$NoAlert)   # NoAlert: tests only (no voice, no message box)
$ErrorActionPreference = "Continue"
function J([string]$s) { return [regex]::Unescape($s) }
$start = Join-Path $PSScriptRoot "START_AI_COCKPIT_V10.ps1"
$approval = Join-Path $PSScriptRoot "V10_APPROVED_SOURCE.json"
if ([string]::IsNullOrWhiteSpace($LogDir)) {
    $LogDir = Join-Path ([Environment]::GetFolderPath("Desktop")) ((J "AI\u30b3\u30af\u30d4\u30c3\u30c8") + "\" + (J "\u8d77\u52d5\u8a18\u9332"))
}
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$log = Join-Path $LogDir ((Get-Date -Format "yyyyMMdd_HHmmss") + ".log")
$utf8 = [Text.UTF8Encoding]::new($true)
[IO.File]::WriteAllText($log, ("START " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss") + " " + $start + "`r`n"), $utf8)
& powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $start -ApprovalFile $approval 2>&1 | ForEach-Object {
    $line = [string]$_
    Write-Host $line
    [IO.File]::AppendAllText($log, $line + "`r`n", $utf8)
}
$rc = $LASTEXITCODE
$text = [IO.File]::ReadAllText($log, $utf8)
$stateLeft = Test-Path -LiteralPath $StateFile
if ($rc -eq 0 -or ($text.Contains("V10_RUNNER_EXIT_FAILURE") -and -not $stateLeft)) {
    $result = "RESULT=NORMAL_STOP rc=" + $rc
    [IO.File]::AppendAllText($log, ("END " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss") + " " + $result + "`r`n"), $utf8)
    exit 0
}
$codes = @([regex]::Matches($text, "V10_[A-Z0-9_]+(=BLOCKED)?") | ForEach-Object { $_.Value } | Select-Object -Unique)
$reason = if ($codes.Count -gt 0) { ($codes | Select-Object -Last 3) -join " " } else { "UNKNOWN" }
if ($stateLeft) { $reason = $reason + " CONTROLLER_STATE_LEFT" }
$result = "RESULT=ABNORMAL_STOP rc=" + $rc + " reason=" + $reason
[IO.File]::AppendAllText($log, ("END " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss") + " " + $result + "`r`n"), $utf8)
if ($NoAlert) { exit 1 }
try {
    Add-Type -AssemblyName System.Speech
    $voice = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $ja = $voice.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -eq "ja-JP" } | Select-Object -First 1
    if ($ja) { $voice.SelectVoice($ja.VoiceInfo.Name) }
    $voice.Speak((J "AI\u30b3\u30af\u30d4\u30c3\u30c8\u304c\u7570\u5e38\u3067\u6b62\u307e\u308a\u307e\u3057\u305f\u3002\u8a18\u9332\u306f\u30c7\u30b9\u30af\u30c8\u30c3\u30d7\u306eAI\u30b3\u30af\u30d4\u30c3\u30c8\u30d5\u30a9\u30eb\u30c0\u306e\u8d77\u52d5\u8a18\u9332\u306b\u3042\u308a\u307e\u3059\u3002"))
} catch {
    [IO.File]::AppendAllText($log, ("VOICE_FAILED " + $_.Exception.Message + "`r`n"), $utf8)
}
try {
    $shell = New-Object -ComObject WScript.Shell
    [void]$shell.Popup(((J "\u7406\u7531: ") + $reason + "`r`n" + (J "\u8a18\u9332\u30d5\u30a1\u30a4\u30eb: ") + $log), 0,
                       (J "AI\u30b3\u30af\u30d4\u30c3\u30c8\u304c\u7570\u5e38\u3067\u6b62\u307e\u308a\u307e\u3057\u305f"), 48)
} catch {
    [IO.File]::AppendAllText($log, ("POPUP_FAILED " + $_.Exception.Message + "`r`n"), $utf8)
}
exit 1
