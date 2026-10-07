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
$pin='7c67b3da874610a3121c1f0d1b48ad5fae445fbb'
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
$ErrorActionPreference='Stop';Add-Type -AssemblyName System.IO.Compression;$b='H4sIAO8Zw2oC/7VXa3OiyBr+7q/oSlEHqKSJJtmdi8WpdRmTccfRlJLJOWUcC6HRXqGbaRqTVNb/ft4GFHKbsWb3fFLo99bP+7wXtK4QXHR8STm7FCQkgjCf2PpY8kRvhBnLT9DAmKRSULaYamvzgYa7x/fve+kgi6KhuF5SScaJ5xMDZMwHQWQmGNL1TVuTtra2XEFjwyx+9AO9/HegH5jWiCSRUtSP9SP9Rjfbt0sagR1p9QlbyCXCC4lOEfZYgOBllwXpNZVLQ8maD8q8tMbZvIjJaB7tFHHL3LQhXDCFMCMQjamMGC5JJb70lOU+hC28KH/QJJiT4l6ZnPSGlnoJV7wg8hzuqJ7AkLnxPekvHzb/aJSbdgmYJjcV7lcV7tkeuGcV7lroRSkB7H1by+rYQ1gKZ3jgfX5LRI+tPUE9Jg1TIaX5tcCtBZV57GDEfxy7v439zKxCr+tSFvL7LEuzFcFeuDqWwgsI9rm/SpTR2iX71SWT/JKYcflaiow/OGX46V8tQXrAb1nEvSDVTaSPrgazTm/mDJ1Plz139uWdlaQtuMozfH7aXZyezCK6Jsrb5/HJbDQez1rN5szhUUR8ycXf96jclCl4ZmXHFpGRGpZDRrZoTqZTTZlJIX8pIcwekFs8nP8JwSF9fJ9KEltlsKCZWheEEUEhrzSV24TobW1F7lP7N2B7yAXxfKgACDZGlKHfjNI+OADrqEqjkijYxBAm31TZPficScoyRcmVrTGg31WSPKOfQgblPiE2Jj3K0k/k3tBWyol6PdFWUzu/dXuy5jSY5nezOkEAzlQZKa/5K4dnrKj6FhT1UvBbZOij7uVw9rnjOh+BG1cD19YPa9I1KquXk+a0Bu254LETB9UtHR7HUOt9ysgetVmXftwd/TixJ+NcF4QSgCPlDKwMRUCZF/UWDJB3vJRUKYg9sSKiSIJ+s2P+TY3yznDgjob9fne0Zf9RXfLlAjl6xdhFx+1ed/5biR3vxI5/4LMm+ZrPl4098akIQIM7uw6k1WMBuRuGW0COFJYF8UAU4Uiq3NeYl0pPQB+GQ9zatu/8HfRugpqq0y0feZgUx9NiiPjLgs4wvTAXu2c1w9TzjhlbOaSinkPOVpXv/Ae3KqbV71O12ELusHWUB7vVqggKzHlMzY5Y/PPU/GZPBFmQO1D8rIbeI9kjHcPg5iPO5U16eGBMvh5MD03AJk/AN7iM75M0rVrXN+tC8CxJJ62p9cWL8owk+3swbsaHZmk9eW49eWq9WjVeRs0BLzTwJEkftBDKP/jJDpkmtu68z8ulmG4z6MJORP3VbKzSRsTNl3f12hi7QG3rT6hyXV3mtWUkTcplhOfLyDmwFVAaES/oRJFL7iSQJDmaqH8wd30eFBm+cs/fmn9B91wTIRUz8B/gqa2Fqb3jB7cE4DoTAOyu636fI6Fq82XHzcEqWi683pT7UNFi9af3nF0NRt3Oh87v/a6+qU+R2IOSKzpYohaRdEmiyCJ3BDpCcpsu87/gdKeRCO4XCrCQYYfGPQZlAesquqbs9GR2CefACIQBKYARGQcDLybIhno9LNwdqkpFuLbzIrXo5htOHFTwKE9WjYdtzbPL9o+UZE5Bb7tRvgCLB5TT5nZZl5XO/Ds6c0ByR1SYrcWRyztCePeGCRuTskDY+v3wegDodhyne+nOxt3+udsdu4Vl6JMPDW3tRfTn2NzYoe1vq6OAvCqWfNxzET+a+DvpcuzD+QuTf0s1o49yEfNRc+aCLihTdLaNfyHYexB2CjkkSMwhkgXkPRMRKiTRyb81BkT9a5hJXMzP8qOiCKLfGbvd//RcZ/ihm6PTfDGWK1Tz/CiiMkc5muWGoYLeNDRVPTZUucpTcVzlqXEtoGwwBJVkslw51JqhdMyGllBm62/8X9/MTwPv7ZuzX1tN77R10vJbYTNozc/eesEvoUfOzn4J53O9UQGh9FFIoNS29/czkXJxnDQx1EFEcALpJDj0aORHPCUBDs7enjZeg6Ks1wsYteddtRCdd3r97gfokFru5SM0mnoicv+CrDFsKClBGEN/oeE9KpQ/Qo1/JyGNfH6+EEY+R3f+kEpJrNoJ0r9Omvidh8MOPp8+nDU3mmoGz4JWfme9wZdOv6dCfxIudCYcQt8ELiJDQX+of4UExzGVG1jcy3hfheh74Ctr7T2wvewNnuDb/j/g294bX5JHbv4gxqLZvKD3FJOYiAXBcy+PmKZY9eMUvn5yaVRZ2BeqwdCdbaNRYTxN6JL4Kw51hUPwFxAJvSp31djTvvOx63waXrk1ti/3TMTfoXjxXaM8WflOUHwkF5nYJ0aRMejWdu3bMI9S/9FCD/iVumi3SpW6eLyiyQWVV0ne5fHvAnK33K+pwAy9S2CQkGC89IpU4w7sY4kcwWcUjcnuK/gHeTH0coypY9Ul66LQaTf/A48tDsahEgAA';$bytes=[Convert]::FromBase64String($b);$m=New-Object IO.MemoryStream;[void]$m.Write($bytes,0,$bytes.Length);$m.Position=0;$z=New-Object IO.Compression.GzipStream($m,([IO.Compression.CompressionMode]::Decompress));$r=New-Object IO.StreamReader($z);$s=$r.ReadToEnd();$r.Close();if($env:OWNER_ACCEPT_SELFTEST -eq '1'){$script:OwnerExpanded=$s}else{Invoke-Expression $s}
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
    if (-not $plain.Contains('7c67b3da874610a3121c1f0d1b48ad5fae445fbb')) { throw 'pin missing' }
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
