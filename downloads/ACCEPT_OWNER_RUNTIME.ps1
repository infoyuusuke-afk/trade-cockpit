# Owner paste payload. The pasted line is powershell.exe -EncodedCommand
# with this file as UTF-16LE base64, so an outer PowerShell cannot expand
# $variables before the script starts. -OwnerCommandSelfTest only parses.
param(
    [switch]$OwnerCommandSelfTest
)

$ErrorActionPreference = 'Stop'

if ($OwnerCommandSelfTest) {
    $text = [IO.File]::ReadAllText($PSCommandPath)
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($text))
    $decoded = [Text.Encoding]::Unicode.GetString([Convert]::FromBase64String($encoded))
    if ($decoded -ne $text) { throw 'encoded roundtrip mismatch' }
    $tokens = $null
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseInput($decoded, [ref]$tokens, [ref]$errors) | Out-Null
    if ($errors.Count -gt 0) { throw 'decoded owner command parse failed' }
    $line = 'powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -EncodedCommand ' + $encoded
    $dollar = [string][char]36
    if ($line.Contains($dollar)) { throw 'owner command contains a dollar sign' }
    $runtime = $text.Substring($text.LastIndexOf('exit 0') + 6)
    if ($runtime.Contains('Stop-Process')) { throw 'launcher must not stop a process' }
    if (-not $text.Contains('-AcceptRuntimeCollector')) { throw 'launcher must call accept' }
    if (-not $text.Contains('82c49a6d614a6a09f9f239cc7de6b3f25d39310a')) { throw 'pin missing' }
    $sha = [System.BitConverter]::ToString([System.Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($encoded))).Replace('-', '')
    Write-Output 'OWNER_ENCODED_COMMAND_PARSE PASS'
    Write-Output ('OWNER_COMMAND_SHA256=' + $sha)
    exit 0
}

$desk = [Environment]::GetFolderPath('Desktop')
$needle = Join-Path 'downloads' 'RUN_AI_COCKPIT_V9.ps1'
$hits = @(Get-ChildItem -LiteralPath $desk -Recurse -File -Filter 'card_system.js' -Depth 4 -ErrorAction SilentlyContinue | Where-Object { Test-Path -LiteralPath (Join-Path $_.Directory.FullName $needle) })
if ($hits.Count -ne 1) { throw ('REPO_MATCH_COUNT=' + $hits.Count) }
$repo = $hits[0].Directory.FullName
& git -C $repo fetch origin cursor/p0-stale-price-failclosed-d483
if ($LASTEXITCODE -ne 0) { throw 'GIT_FETCH_FAILED' }
& git -C $repo checkout -B cursor/p0-stale-price-failclosed-d483 origin/cursor/p0-stale-price-failclosed-d483
if ($LASTEXITCODE -ne 0) { throw 'GIT_CHECKOUT_FAILED' }
& git -C $repo reset --hard 82c49a6d614a6a09f9f239cc7de6b3f25d39310a
if ($LASTEXITCODE -ne 0) { throw 'GIT_RESET_FAILED' }
$runner = Join-Path $repo 'downloads\RUN_AI_COCKPIT_V9.ps1'
& $runner -RepoRoot $repo -SkipGitUpdate -Branch cursor/p0-stale-price-failclosed-d483 -ExpectedSha 82c49a6d614a6a09f9f239cc7de6b3f25d39310a -AcceptRuntimeCollector
if ($LASTEXITCODE -ne 0) { throw ('ACCEPT_EXIT=' + $LASTEXITCODE) }
