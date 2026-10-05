# Owner paste payload. The pasted line is powershell.exe -EncodedCommand
# so an outer PowerShell cannot expand variables before this script starts.
param(
    [switch]$OwnerCommandSelfTest
)

$ErrorActionPreference = 'Stop'

function Get-NormalizedRepoPath([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return '' }
    $text = $Value.Trim().Trim('"').Trim("'").Replace('/', '\')
    while ($text.Length -gt 3 -and $text.EndsWith('\')) { $text = $text.Substring(0, $text.Length - 1) }
    if (($text -ne '') -and (Test-Path -LiteralPath $text)) {
        try { $text = [IO.Path]::GetFullPath($text) } catch {}
        while ($text.Length -gt 3 -and $text.EndsWith('\')) { $text = $text.Substring(0, $text.Length - 1) }
    }
    return $text
}

function Test-TradeCockpitOriginUrl([string]$Url) {
    if ([string]::IsNullOrWhiteSpace($Url)) { return $false }
    $compact = $Url.Trim().TrimEnd('/').ToLowerInvariant()
    if ($compact.EndsWith('.git')) { $compact = $compact.Substring(0, $compact.Length - 4) }
    return $compact.EndsWith('infoyuusuke-afk/trade-cockpit')
}

function Test-OwnerRepoLayout([string]$Path) {
    $runner = Join-Path (Join-Path $Path 'downloads') 'RUN_AI_COCKPIT_V9.ps1'
    $collector = Join-Path (Join-Path $Path 'ms2_live') 'MS2_RSS_100_Collector.ps1'
    $gitDir = Join-Path $Path '.git'
    if (-not (Test-Path -LiteralPath $runner)) { return $false }
    if (-not (Test-Path -LiteralPath $collector)) { return $false }
    if (-not (Test-Path -LiteralPath $gitDir)) { return $false }
    return $true
}

function Select-SingleRepoPath([string[]]$Paths) {
    $seen = New-Object 'System.Collections.Generic.List[string]'
    $keys = @{}
    foreach ($item in @($Paths)) {
        $norm = Get-NormalizedRepoPath ([string]$item)
        if ($norm -eq '') { continue }
        $key = $norm.ToUpperInvariant()
        if (-not $keys.ContainsKey($key)) {
            $keys[$key] = $true
            [void]$seen.Add($norm)
        }
    }
    if ($seen.Count -ne 1) { throw ('REPO_MATCH_COUNT=' + $seen.Count) }
    return $seen[0]
}

function Get-RepoFromScriptCommand([string]$CommandLine) {
    if ([string]::IsNullOrWhiteSpace($CommandLine)) { return '' }
    $cmp = [StringComparison]::OrdinalIgnoreCase
    $markers = @(
        '\downloads\AI_COCKPIT_CONTROLLER_V9.ps1',
        '\downloads\RUN_AI_COCKPIT_V9.ps1',
        '\downloads\AI_COCKPIT_GATEWAY_V9.ps1',
        '/downloads/AI_COCKPIT_CONTROLLER_V9.ps1',
        '/downloads/RUN_AI_COCKPIT_V9.ps1',
        '/downloads/AI_COCKPIT_GATEWAY_V9.ps1'
    )
    foreach ($marker in $markers) {
        $idx = $CommandLine.IndexOf($marker, $cmp)
        if ($idx -lt 1) { continue }
        $start = $idx - 1
        while ($start -ge 0) {
            $ch = $CommandLine[$start]
            if ($ch -eq '"' -or $ch -eq "'" -or [string]$ch -eq ' ') { break }
            $start = $start - 1
        }
        return $CommandLine.Substring($start + 1, $idx - $start - 1)
    }
    return ''
}

function Get-RepoFromRepoRootArgument([string]$CommandLine) {
    if ([string]::IsNullOrWhiteSpace($CommandLine)) { return '' }
    $quoted = [regex]::Match($CommandLine, '-RepoRoot\s+"([^"]+)"')
    if ($quoted.Success) { return $quoted.Groups[1].Value }
    $plain = [regex]::Match($CommandLine, '-RepoRoot\s+(\S+)')
    if ($plain.Success) { return $plain.Groups[1].Value.Trim('"') }
    return ''
}

function Get-RecordedRepoCandidates {
    $found = New-Object 'System.Collections.Generic.List[string]'
    $statePath = 'C:\AI_Cockpit_OneClick_Starter\V9_CONTROLLER_STATE.json'
    if (Test-Path -LiteralPath $statePath) {
        try {
            $obj = [IO.File]::ReadAllText($statePath, [Text.Encoding]::UTF8) | ConvertFrom-Json
            $fromState = [string]$obj.repo_root
            if (-not [string]::IsNullOrWhiteSpace($fromState)) { [void]$found.Add($fromState) }
        } catch {
            throw 'CONTROLLER_STATE_UNREADABLE'
        }
    }
    foreach ($image in @('powershell.exe', 'pwsh.exe')) {
        $procs = @(Get-CimInstance Win32_Process -Filter ("Name = '" + $image + "'") -ErrorAction Stop)
        foreach ($proc in $procs) {
            $cmd = [string]$proc.CommandLine
            $fromScript = Get-RepoFromScriptCommand $cmd
            if ($fromScript -ne '') { [void]$found.Add($fromScript) }
            $fromArg = Get-RepoFromRepoRootArgument $cmd
            if ($fromArg -ne '') { [void]$found.Add($fromArg) }
        }
    }
    return @($found.ToArray())
}

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
    if ($runtime.Contains('card_system.js')) { throw 'card search must be gone' }
    if ($runtime.Contains('-Depth')) { throw 'desktop depth search must be gone' }
    if ($runtime.Contains('origin/cursor/')) { throw 'remote-tracking checkout must be gone' }
    if ($runtime.Contains('checkout -B')) { throw 'branch checkout must be gone' }
    if (-not $runtime.Contains('rev-parse --verify FETCH_HEAD')) { throw 'FETCH_HEAD must be verified' }
    if (-not $runtime.Contains('merge-base --is-ancestor')) { throw 'pin ancestry must be verified' }
    if (-not $runtime.Contains('checkout -f --detach')) { throw 'pin detach missing' }
    if (-not $text.Contains('-AcceptRuntimeCollector')) { throw 'launcher must call accept' }
    if (-not $text.Contains('82c49a6d614a6a09f9f239cc7de6b3f25d39310a')) { throw 'pin missing' }
    if ((Select-SingleRepoPath @('C:\repo', 'c:\repo\')) -ne 'C:\repo') { throw 'same repo must collapse' }
    $two = $false
    try { Select-SingleRepoPath @('C:\a', 'C:\b') | Out-Null } catch { if ($_.Exception.Message -like 'REPO_MATCH_COUNT=2*') { $two = $true } }
    if (-not $two) { throw 'two repos must fail closed' }
    $zero = $false
    try { Select-SingleRepoPath @() | Out-Null } catch { if ($_.Exception.Message -like 'REPO_MATCH_COUNT=0*') { $zero = $true } }
    if (-not $zero) { throw 'zero repos must fail closed' }
    if (-not (Test-TradeCockpitOriginUrl 'https://github.com/infoyuusuke-afk/trade-cockpit.git')) { throw 'https origin' }
    if (-not (Test-TradeCockpitOriginUrl 'git@github.com:infoyuusuke-afk/trade-cockpit')) { throw 'ssh origin' }
    if (Test-TradeCockpitOriginUrl 'https://github.com/other/trade-cockpit.git') { throw 'other origin must fail' }
    $sample = 'powershell.exe -File "C:\work\trade-cockpit\downloads\AI_COCKPIT_CONTROLLER_V9.ps1" -RepoRoot "C:\work\trade-cockpit"'
    if ((Get-RepoFromScriptCommand $sample) -ne 'C:\work\trade-cockpit') { throw 'script path parse' }
    if ((Get-RepoFromRepoRootArgument $sample) -ne 'C:\work\trade-cockpit') { throw 'reporoot arg parse' }
    $layout = Join-Path ([IO.Path]::GetTempPath()) ('owner-repo-' + [Guid]::NewGuid().ToString('N'))
    $downloadsDir = Join-Path $layout 'downloads'
    $ms2Dir = Join-Path $layout 'ms2_live'
    New-Item -ItemType Directory -Path $downloadsDir -Force | Out-Null
    New-Item -ItemType Directory -Path $ms2Dir -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $layout '.git') -Force | Out-Null
    New-Item -ItemType File -Path (Join-Path $downloadsDir 'RUN_AI_COCKPIT_V9.ps1') -Force | Out-Null
    New-Item -ItemType File -Path (Join-Path $ms2Dir 'MS2_RSS_100_Collector.ps1') -Force | Out-Null
    try {
        if (-not (Test-OwnerRepoLayout $layout)) { throw 'layout must match' }
    } finally {
        Remove-Item -LiteralPath $layout -Recurse -Force -ErrorAction SilentlyContinue
    }
    $sha = [System.BitConverter]::ToString([System.Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($encoded))).Replace('-', '')
    Write-Output 'OWNER_ENCODED_COMMAND_PARSE PASS'
    Write-Output ('OWNER_COMMAND_SHA256=' + $sha)
    exit 0
}

$valid = New-Object 'System.Collections.Generic.List[string]'
foreach ($candidate in @(Get-RecordedRepoCandidates)) {
    $norm = Get-NormalizedRepoPath ([string]$candidate)
    if ($norm -eq '') { continue }
    if (-not (Test-OwnerRepoLayout $norm)) { continue }
    $originText = (& git -C $norm remote get-url origin 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { continue }
    if (-not (Test-TradeCockpitOriginUrl $originText)) { continue }
    [void]$valid.Add($norm)
}
$repo = Select-SingleRepoPath @($valid.ToArray())
Write-Output ('REPO=' + $repo)
$pin = '82c49a6d614a6a09f9f239cc7de6b3f25d39310a'
& git -C $repo fetch origin cursor/p0-stale-price-failclosed-d483
if ($LASTEXITCODE -ne 0) { throw 'GIT_FETCH_FAILED' }
$fetchHead = (& git -C $repo rev-parse --verify FETCH_HEAD 2>$null | Out-String).Trim()
if (($LASTEXITCODE -ne 0) -or ($fetchHead -notmatch '^[0-9a-fA-F]{40}$')) { throw 'GIT_FETCH_HEAD_INVALID' }
& git -C $repo cat-file -e ($pin + '^{commit}') 2>$null
if ($LASTEXITCODE -ne 0) {
    & git -C $repo fetch origin $pin
    if ($LASTEXITCODE -ne 0) { throw 'GIT_PIN_FETCH_FAILED' }
    $fetchHead = (& git -C $repo rev-parse --verify FETCH_HEAD 2>$null | Out-String).Trim()
    if (($LASTEXITCODE -ne 0) -or ($fetchHead -ne $pin)) { throw 'GIT_PIN_FETCH_FAILED' }
}
if ($fetchHead -ne $pin) {
    & git -C $repo merge-base --is-ancestor $pin $fetchHead
    if ($LASTEXITCODE -ne 0) { throw 'GIT_PIN_NOT_IN_FETCH' }
}
& git -C $repo checkout -f --detach $pin
if ($LASTEXITCODE -ne 0) { throw 'GIT_PIN_CHECKOUT_FAILED' }
$head = (& git -C $repo rev-parse --verify HEAD 2>$null | Out-String).Trim()
if (($LASTEXITCODE -ne 0) -or (-not $head.StartsWith($pin))) { throw 'GIT_PIN_CHECKOUT_FAILED' }
$runner = Join-Path $repo 'downloads\RUN_AI_COCKPIT_V9.ps1'
& $runner -RepoRoot $repo -SkipGitUpdate -Branch cursor/p0-stale-price-failclosed-d483 -ExpectedSha $pin -AcceptRuntimeCollector
if ($LASTEXITCODE -ne 0) { throw ('ACCEPT_EXIT=' + $LASTEXITCODE) }
