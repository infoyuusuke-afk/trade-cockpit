$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
function Import-Function([string]$RelativePath, [string]$Name) {
    $errors = $null; $tokens = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $repo $RelativePath), [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw ($errors | Out-String) }
    $function = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $Name }, $true)
    if ($null -eq $function) { throw "Function missing: $Name" }
    return $function.Extent.Text
}
. ([scriptblock]::Create((Import-Function 'downloads/AI_COCKPIT_CONTROLLER_V9.ps1' 'Stop-ManagedWorkersOnWorkbookClose')))
$script:stopped = @()
function Get-Process { param($Id, $ErrorAction) if ($Id -ne 99) { return @{ Id=$Id } } }
function Stop-Process { param($Id, [switch]$Force, $ErrorAction) $script:stopped += $Id }
function Test-OwnedPidIdentity { param($Field, $ProcessId) return $ProcessId -ne 12 }
$session = @{excel_pid=20; watcher_pid=10; heartbeat_pid=12; collector_pid=99; gateway_pid=20; voice_bridge_pid=14; sbv2_pid=0}
Stop-ManagedWorkersOnWorkbookClose $session
if (($script:stopped -join ',') -ne '10,14') { throw "Unsafe worker cleanup: $script:stopped" }
Write-Output 'PASS: only verified live workers stopped; Excel, recycled, missing and zero PIDs preserved'
. ([scriptblock]::Create((Import-Function 'downloads/AI_COCKPIT_GATEWAY_V9.ps1' 'Test-HealthProcess')))
$script:fakeProcess = $null
function Get-CimInstance { param($ClassName, $Filter, $ErrorAction) if ($script:fakeProcess -eq 'error') { throw 'denied' }; return $script:fakeProcess }
$stamp = Get-Date
if (Test-HealthProcess 10 'watcher.ps1' $stamp) { throw 'Missing process accepted' }
$script:fakeProcess = @{CommandLine='powershell watcher.ps1'; CreationDate=$stamp.AddSeconds(-1)}
if (-not (Test-HealthProcess 10 'watcher.ps1' $stamp)) { throw 'Valid process rejected' }
$script:fakeProcess.CreationDate=$stamp.AddSeconds(1)
if (Test-HealthProcess 10 'watcher.ps1' $stamp) { throw 'Recycled PID accepted' }
$script:fakeProcess = @{CommandLine='powershell other.ps1'; CreationDate=$stamp.AddSeconds(-1)}
if (Test-HealthProcess 10 'watcher.ps1' $stamp) { throw 'Wrong command accepted' }
$script:fakeProcess='error'
if (Test-HealthProcess 10 'watcher.ps1' $stamp) { throw 'Access denied accepted' }
Write-Output 'PASS: health rejects missing, recycled, wrong-command and inaccessible processes'
