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
$pin='467a801f7389337ee77de283aee75d84f66bea28'
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
    if (-not $plain.Contains('467a801f7389337ee77de283aee75d84f66bea28')) { throw 'pin missing' }
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
