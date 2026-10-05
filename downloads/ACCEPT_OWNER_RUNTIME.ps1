# Owner paste payload. The pasted line is powershell.exe -EncodedCommand
# of $stub only. A 28770-character EncodedCommand was rejected by the
# interactive console as invalid Base64, so this stub stays under 8000
# characters and inflates the accept script. Do not encode this file.
param(
    [switch]$OwnerCommandSelfTest
)

$ErrorActionPreference = 'Stop'

$inner = @'
$ErrorActionPreference='Stop'
function N([string]$v){if([string]::IsNullOrWhiteSpace($v)){return ''};$t=$v.Trim().Trim('"').Trim("'").Replace('/','\');while($t.Length -gt 3 -and $t.EndsWith('\')){$t=$t.Substring(0,$t.Length-1)};if(($t -ne '')-and(Test-Path -LiteralPath $t)){try{$t=[IO.Path]::GetFullPath($t)}catch{};while($t.Length -gt 3 -and $t.EndsWith('\')){$t=$t.Substring(0,$t.Length-1)}};return $t}
function U([string]$u){if([string]::IsNullOrWhiteSpace($u)){return $false};$c=$u.Trim().TrimEnd('/').ToLowerInvariant();if($c.EndsWith('.git')){$c=$c.Substring(0,$c.Length-4)};return $c.EndsWith('infoyuusuke-afk/trade-cockpit')}
function L([string]$p){if(-not(Test-Path -LiteralPath (Join-Path (Join-Path $p 'downloads') 'RUN_AI_COCKPIT_V9.ps1'))){return $false};if(-not(Test-Path -LiteralPath (Join-Path (Join-Path $p 'ms2_live') 'MS2_RSS_100_Collector.ps1'))){return $false};if(-not(Test-Path -LiteralPath (Join-Path $p '.git'))){return $false};return $true}
function One([string[]]$Paths){$seen=New-Object 'System.Collections.Generic.List[string]';$keys=@{};foreach($item in @($Paths)){$n=N ([string]$item);if($n -eq ''){continue};$k=$n.ToUpperInvariant();if(-not $keys.ContainsKey($k)){$keys[$k]=$true;[void]$seen.Add($n)}};if($seen.Count -ne 1){throw ('REPO_MATCH_COUNT='+$seen.Count)};return $seen[0]}
function FromCmd([string]$CommandLine){if([string]::IsNullOrWhiteSpace($CommandLine)){return ''};$cmp=[StringComparison]::OrdinalIgnoreCase;foreach($marker in @('\downloads\AI_COCKPIT_CONTROLLER_V9.ps1','\downloads\RUN_AI_COCKPIT_V9.ps1','\downloads\AI_COCKPIT_GATEWAY_V9.ps1','/downloads/AI_COCKPIT_CONTROLLER_V9.ps1','/downloads/RUN_AI_COCKPIT_V9.ps1','/downloads/AI_COCKPIT_GATEWAY_V9.ps1')){$idx=$CommandLine.IndexOf($marker,$cmp);if($idx -lt 1){continue};$start=$idx-1;while($start -ge 0){$ch=$CommandLine[$start];if(($ch -eq '"')-or($ch -eq "'")-or([string]$ch -eq ' ')){break};$start=$start-1};return $CommandLine.Substring($start+1,$idx-$start-1)};return ''}
function FromArg([string]$CommandLine){if([string]::IsNullOrWhiteSpace($CommandLine)){return ''};$q=[regex]::Match($CommandLine,'-RepoRoot\s+"([^"]+)"');if($q.Success){return $q.Groups[1].Value};$p=[regex]::Match($CommandLine,'-RepoRoot\s+(\S+)');if($p.Success){return $p.Groups[1].Value.Trim('"')};return ''}
function Candidates{$found=New-Object 'System.Collections.Generic.List[string]';$sp='C:\AI_Cockpit_OneClick_Starter\V9_CONTROLLER_STATE.json';if(Test-Path -LiteralPath $sp){try{$o=[IO.File]::ReadAllText($sp,[Text.Encoding]::UTF8)|ConvertFrom-Json;$fs=[string]$o.repo_root;if(-not [string]::IsNullOrWhiteSpace($fs)){[void]$found.Add($fs)}}catch{throw 'CONTROLLER_STATE_UNREADABLE'}};foreach($image in @('powershell.exe','pwsh.exe')){foreach($proc in @(Get-CimInstance Win32_Process -Filter ("Name = '"+$image+"'") -ErrorAction Stop)){$cmd=[string]$proc.CommandLine;$a=FromCmd $cmd;if($a -ne ''){[void]$found.Add($a)};$b=FromArg $cmd;if($b -ne ''){[void]$found.Add($b)}}};return @($found.ToArray())}
if($env:OWNER_ACCEPT_SELFTEST -ne '1'){
$valid=New-Object 'System.Collections.Generic.List[string]'
foreach($candidate in @(Candidates)){$norm=N ([string]$candidate);if($norm -eq ''){continue};if(-not (L $norm)){continue};$originText=(& git -C $norm remote get-url origin 2>$null|Out-String).Trim();if($LASTEXITCODE -ne 0){continue};if(-not (U $originText)){continue};[void]$valid.Add($norm)}
$repo=One @($valid.ToArray())
Write-Output ('REPO='+$repo)
$pin='811f97aba5a5c3057636c152eddada53e97b3685'
& git -C $repo fetch origin cursor/p0-stale-price-failclosed-d483
if($LASTEXITCODE -ne 0){throw 'GIT_FETCH_FAILED'}
$fetchHead=(& git -C $repo rev-parse --verify FETCH_HEAD 2>$null|Out-String).Trim()
if(($LASTEXITCODE -ne 0)-or($fetchHead -notmatch '^[0-9a-fA-F]{40}$')){throw 'GIT_FETCH_HEAD_INVALID'}
& git -C $repo cat-file -e ($pin+'^{commit}') 2>$null
if($LASTEXITCODE -ne 0){& git -C $repo fetch origin $pin;if($LASTEXITCODE -ne 0){throw 'GIT_PIN_FETCH_FAILED'};$fetchHead=(& git -C $repo rev-parse --verify FETCH_HEAD 2>$null|Out-String).Trim();if(($LASTEXITCODE -ne 0)-or($fetchHead -ne $pin)){throw 'GIT_PIN_FETCH_FAILED'}}
if($fetchHead -ne $pin){& git -C $repo merge-base --is-ancestor $pin $fetchHead;if($LASTEXITCODE -ne 0){throw 'GIT_PIN_NOT_IN_FETCH'}}
& git -C $repo checkout -f --detach $pin
if($LASTEXITCODE -ne 0){throw 'GIT_PIN_CHECKOUT_FAILED'}
$head=(& git -C $repo rev-parse --verify HEAD 2>$null|Out-String).Trim()
if(($LASTEXITCODE -ne 0)-or(-not $head.StartsWith($pin))){throw 'GIT_PIN_CHECKOUT_FAILED'}
$runner=Join-Path $repo 'downloads\RUN_AI_COCKPIT_V9.ps1'
& $runner -RepoRoot $repo -SkipGitUpdate -Branch cursor/p0-stale-price-failclosed-d483 -ExpectedSha $pin -AcceptRuntimeCollector
if($LASTEXITCODE -ne 0){throw ('ACCEPT_EXIT='+$LASTEXITCODE)}
}
'@

$stub = @'
$ErrorActionPreference='Stop';Add-Type -AssemblyName System.IO.Compression;$b='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';$bytes=[Convert]::FromBase64String($b);$m=New-Object IO.MemoryStream;[void]$m.Write($bytes,0,$bytes.Length);$m.Position=0;$z=New-Object IO.Compression.GzipStream($m,([IO.Compression.CompressionMode]::Decompress));$r=New-Object IO.StreamReader($z);$s=$r.ReadToEnd();$r.Close();if($env:OWNER_ACCEPT_SELFTEST -eq '1'){$script:OwnerExpanded=$s}else{Invoke-Expression $s}
'@

if ($OwnerCommandSelfTest) {
    $plain = $inner.Trim() -replace "`r`n", "`n" -replace "`r", "`n"
    $lineStub = $stub.Trim() -replace "`r`n", "`n" -replace "`r", "`n"
    if ($lineStub.Contains("`n")) { throw 'stub must be one line' }
    Remove-Variable -Name OwnerExpanded -Scope Script -ErrorAction SilentlyContinue
    $env:OWNER_ACCEPT_SELFTEST = '1'
    try {
        Invoke-Expression $lineStub
        if (-not (Test-Path variable:script:OwnerExpanded)) { throw 'stub selftest did not return the script' }
        $expanded = [string]$script:OwnerExpanded
    } finally {
        Remove-Item Env:OWNER_ACCEPT_SELFTEST -ErrorAction SilentlyContinue
    }
    $got = $expanded.Trim() -replace "`r`n", "`n" -replace "`r", "`n"
    if ($got -ne $plain) { throw 'stub payload drift' }
    $tokens = $null
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseInput($lineStub, [ref]$tokens, [ref]$errors) | Out-Null
    if ($errors.Count -gt 0) { throw 'stub parse failed' }
    $tokens = $null
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseInput($plain, [ref]$tokens, [ref]$errors) | Out-Null
    if ($errors.Count -gt 0) { throw 'accept script parse failed' }
    if ($plain.Contains('Stop-Process')) { throw 'launcher must not stop a process' }
    if ($plain.Contains('card_system.js')) { throw 'card search must be gone' }
    if ($plain.Contains('-Depth')) { throw 'desktop depth search must be gone' }
    if ($plain.Contains('origin/cursor/')) { throw 'remote-tracking checkout must be gone' }
    if ($plain.Contains('checkout -B')) { throw 'branch checkout must be gone' }
    if (-not $plain.Contains('rev-parse --verify FETCH_HEAD')) { throw 'FETCH_HEAD must be verified' }
    if (-not $plain.Contains('merge-base --is-ancestor')) { throw 'pin ancestry must be verified' }
    if (-not $plain.Contains('checkout -f --detach')) { throw 'pin detach missing' }
    if (-not $plain.Contains('-AcceptRuntimeCollector')) { throw 'launcher must call accept' }
    if (-not $plain.Contains('811f97aba5a5c3057636c152eddada53e97b3685')) { throw 'pin missing' }
    if (-not $plain.Contains('V9_CONTROLLER_STATE.json')) { throw 'state file missing' }
    if (-not $plain.Contains('Win32_Process')) { throw 'process scan missing' }
    $env:OWNER_ACCEPT_SELFTEST = '1'
    try {
        . ([scriptblock]::Create($plain))
        if ((One @('C:\repo', 'c:\repo\')) -ne 'C:\repo') { throw 'same repo must collapse' }
        $two = $false
        try { One @('C:\a', 'C:\b') | Out-Null } catch { if ($_.Exception.Message -like 'REPO_MATCH_COUNT=2*') { $two = $true } }
        if (-not $two) { throw 'two repos must fail closed' }
        $zero = $false
        try { One @() | Out-Null } catch { if ($_.Exception.Message -like 'REPO_MATCH_COUNT=0*') { $zero = $true } }
        if (-not $zero) { throw 'zero repos must fail closed' }
        if (-not (U 'https://github.com/infoyuusuke-afk/trade-cockpit.git')) { throw 'https origin' }
        if (-not (U 'git@github.com:infoyuusuke-afk/trade-cockpit')) { throw 'ssh origin' }
        if (U 'https://github.com/other/trade-cockpit.git') { throw 'other origin must fail' }
        $sample = 'powershell.exe -File "C:\work\trade-cockpit\downloads\AI_COCKPIT_CONTROLLER_V9.ps1" -RepoRoot "C:\work\trade-cockpit"'
        if ((FromCmd $sample) -ne 'C:\work\trade-cockpit') { throw 'script path parse' }
        if ((FromArg $sample) -ne 'C:\work\trade-cockpit') { throw 'reporoot arg parse' }
        $layout = Join-Path ([IO.Path]::GetTempPath()) ('owner-repo-' + [Guid]::NewGuid().ToString('N'))
        $downloadsDir = Join-Path $layout 'downloads'
        $ms2Dir = Join-Path $layout 'ms2_live'
        New-Item -ItemType Directory -Path $downloadsDir -Force | Out-Null
        New-Item -ItemType Directory -Path $ms2Dir -Force | Out-Null
        New-Item -ItemType Directory -Path (Join-Path $layout '.git') -Force | Out-Null
        New-Item -ItemType File -Path (Join-Path $downloadsDir 'RUN_AI_COCKPIT_V9.ps1') -Force | Out-Null
        New-Item -ItemType File -Path (Join-Path $ms2Dir 'MS2_RSS_100_Collector.ps1') -Force | Out-Null
        try {
            if (-not (L $layout)) { throw 'layout must match' }
        } finally {
            Remove-Item -LiteralPath $layout -Recurse -Force -ErrorAction SilentlyContinue
        }
    } finally {
        Remove-Item Env:OWNER_ACCEPT_SELFTEST -ErrorAction SilentlyContinue
    }
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($lineStub))
    $decoded = [Text.Encoding]::Unicode.GetString([Convert]::FromBase64String($encoded))
    if ($decoded -ne $lineStub) { throw 'encoded roundtrip mismatch' }
    $line = 'powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -EncodedCommand ' + $encoded
    $dollar = [string][char]36
    if ($line.Contains($dollar)) { throw 'owner command contains a dollar sign' }
    if ($line.Contains("`n") -or $line.Contains("`r")) { throw 'owner command must be one line' }
    if ($line.Length -ge 8000) { throw 'owner command exceeds console paste limit' }
    $payload = $encoded.Substring($encoded.LastIndexOf(' ') + 1)
    if ($payload -notmatch '^[A-Za-z0-9+/=]+$') { throw 'encoded payload is not base64' }
    $sha = [System.BitConverter]::ToString([System.Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($encoded))).Replace('-', '')
    Write-Output 'OWNER_ENCODED_COMMAND_PARSE PASS'
    Write-Output ('OWNER_COMMAND_SHA256=' + $sha)
    Write-Output ('OWNER_COMMAND_LENGTH=' + $line.Length)
    exit 0
}

Invoke-Expression ($stub.Trim())
