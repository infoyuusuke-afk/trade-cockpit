param(
    [string]$RepoRoot = "",
    [switch]$SelfTest,
    [switch]$ReloadSupervisor
)

# Reload only the AI SHADOW supervisor after the ledger code is present.
# This script does not stop Excel, MarketSpeed II, the Collector, or the Gateway.
# It does not start the Controller. real_submit_allowed stays false.
$ErrorActionPreference = "Stop"

function Get-QuotedArg([string]$Value) {
    return '"' + $Value + '"'
}

function Get-RepoRoot {
    if (-not [string]::IsNullOrWhiteSpace($RepoRoot)) { return $RepoRoot }
    return (Split-Path -Parent $PSScriptRoot)
}

function Get-ProcessIds([scriptblock]$Match) {
    $found = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object $Match | ForEach-Object { [int]$_.ProcessId })
    return @($found | Sort-Object)
}

function Get-SupervisorIds {
    return Get-ProcessIds {
        $cmd = [string]$_.CommandLine
        ($cmd -like "*ai_shadow_supervisor.py*") -and ($cmd -notlike "*MS2_RSS_100_Collector.ps1*") -and ($cmd -notlike "*AI_COCKPIT_GATEWAY_V9.ps1*")
    }
}

function Get-CollectorIds {
    return Get-ProcessIds {
        $cmd = [string]$_.CommandLine
        $cmd -like "*MS2_RSS_100_Collector.ps1*"
    }
}

function Get-GatewayIds {
    return Get-ProcessIds {
        $cmd = [string]$_.CommandLine
        ($cmd -like "*AI_COCKPIT_GATEWAY_V9.ps1*") -and ($cmd -notlike "*MS2_RSS_100_Collector.ps1*")
    }
}

function Get-ImageIds([string]$Pattern) {
    $found = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match $Pattern } | ForEach-Object { [int]$_.Id })
    return @($found | Sort-Object)
}

function Convert-IdList([int[]]$Ids) {
    if ($null -eq $Ids -or $Ids.Count -eq 0) { return "" }
    return ($Ids -join ",")
}

function Resolve-RuntimeDir {
    $manifest = "C:\AI_Cockpit_OneClick_Starter\V9_RUNTIME.json"
    if (Test-Path -LiteralPath $manifest) {
        $text = [IO.File]::ReadAllText($manifest, [Text.Encoding]::UTF8) | ConvertFrom-Json
        $dir = [string]$text.runtime_dir
        if (-not [string]::IsNullOrWhiteSpace($dir) -and (Test-Path -LiteralPath ($dir + "\live_ms2.json"))) { return $dir }
    }
    $statePath = "C:\AI_Cockpit_OneClick_Starter\V9_CONTROLLER_STATE.json"
    $state = [IO.File]::ReadAllText($statePath, [Text.Encoding]::UTF8) | ConvertFrom-Json
    $dir = [string]$state.runtime_dir
    if ([string]::IsNullOrWhiteSpace($dir)) { $dir = [string]$state.repo_root }
    return $dir
}

function Read-JsonFile([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    $text = [IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8)
    return $text | ConvertFrom-Json
}

function Get-IdentitySignal([string]$LivePath) {
    $payload = Read-JsonFile $LivePath
    if ($null -eq $payload) { return "LIVE_FILE_MISSING" }
    foreach ($row in @($payload.all_targets)) {
        $ticker = [string]$row.ticker
        if ($ticker -eq "285A.T" -or $ticker -eq "285A") { return [string]$row.signal }
    }
    return "SIGNAL_ROW_MISSING"
}

function Test-RealSubmitFalse($Status) {
    return ($null -ne $Status -and $Status.real_submit_allowed -eq $false)
}

function Get-IdentityText($Status) {
    if ($null -eq $Status) { return "STATUS_MISSING" }
    $reasons = @($Status.identity_proof_reasons)
    if ($reasons.Count -eq 0) { return "EMPTY" }
    return ($reasons -join ",")
}

function Stop-ShadowSupervisorOnly {
    $ids = Get-SupervisorIds
    foreach ($procId in $ids) {
        Stop-Process -Id $procId -Force
    }
    return $ids.Count
}

function Start-ShadowSupervisor([string]$Root) {
    $runtimeDir = Resolve-RuntimeDir
    $live = $runtimeDir + "\live_ms2.json"
    if (-not (Test-Path -LiteralPath $live)) { throw "RUNTIME_DIR_UNRESOLVED" }
    $dataDir = "C:\AI_Cockpit_OneClick_Starter\Logs\V9\ai_shadow"
    if (-not (Test-Path -LiteralPath $dataDir)) { New-Item -ItemType Directory -Path $dataDir -Force | Out-Null }
    $status = $runtimeDir + "\ai_shadow_status.json"
    $manifest = "C:\AI_Cockpit_OneClick_Starter\V9_RUNTIME.json"
    $python = $null
    foreach ($cand in @(
        ($Root.TrimEnd('\') + "\.venv\Scripts\python.exe"),
        ($Root.TrimEnd('\') + "\venv\Scripts\python.exe")
    )) {
        if (Test-Path -LiteralPath $cand) { $python = $cand; break }
    }
    $prefix = @()
    if (-not $python) {
        $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($null -ne $cmd) { $python = $cmd.Source }
    }
    if (-not $python) {
        $py = Get-Command py.exe -ErrorAction SilentlyContinue
        if ($null -ne $py) { $python = $py.Source; $prefix = @("-3") }
    }
    if (-not $python) { throw "PYTHON_NOT_FOUND" }
    $script = $Root.TrimEnd('\') + "\scripts\ai_shadow_supervisor.py"
    $argList = $prefix + @(
        "-u", (Get-QuotedArg $script),
        "--live", (Get-QuotedArg $live),
        "--data-dir", (Get-QuotedArg $dataDir),
        "--status", (Get-QuotedArg $status),
        "--runtime-manifest", (Get-QuotedArg $manifest),
        "--interval", "5"
    )
    Start-Process -FilePath $python -ArgumentList $argList -WindowStyle Hidden | Out-Null
}

function Wait-SupervisorCount([int]$Expected, [int]$Seconds) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    do {
        $ids = @(Get-SupervisorIds)
        if ($ids.Count -eq $Expected) { return $true }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)
    return $false
}

if ($SelfTest) {
    $root = Get-RepoRoot
    $ledger = Join-Path $root "scripts/shadow_trade_ledger.py"
    $supervisor = Join-Path $root "scripts/ai_shadow_supervisor.py"
    if (-not (Test-Path -LiteralPath $ledger)) { throw "ledger code must exist before a reload" }
    $supervisorText = [IO.File]::ReadAllText($supervisor, [Text.Encoding]::UTF8)
    if ($supervisorText.IndexOf("import shadow_trade_ledger") -lt 0) { throw "supervisor must import the ledger" }
    if ($supervisorText.IndexOf("LONG_ENTRY_SIGNALS") -lt 0) { throw "entry signals missing" }
    $text = [IO.File]::ReadAllText($PSCommandPath, [Text.Encoding]::UTF8)
    $stopAt = $text.IndexOf("function Stop-ShadowSupervisorOnly")
    $startAt = $text.IndexOf("function Start-ShadowSupervisor")
    $gateAt = $text.IndexOf('Write-Output "LEDGER_CODE_MISSING"')
    $callAt = $text.LastIndexOf("Stop-ShadowSupervisorOnly")
    if ($gateAt -lt 0 -or $callAt -lt 0 -or $gateAt -gt $callAt) { throw "missing ledger code must abort before stop" }
    if ($text.IndexOf("MS2_RSS_100_Collector.ps1") -lt 0) { throw "collector process must be identified" }
    if ($text.IndexOf("AI_COCKPIT_GATEWAY_V9.ps1") -lt 0) { throw "gateway process must be identified" }
    $stopBody = $text.Substring($stopAt, $startAt - $stopAt)
    if ($stopBody.IndexOf("Stop-Process -Id ") -lt 0) { throw "stop must target the supervisor process id" }
    if ($stopBody.IndexOf("MS2_RSS_100_Collector.ps1") -ge 0) { throw "stop must not name the collector" }
    if ($stopBody.IndexOf("AI_COCKPIT_GATEWAY_V9.ps1") -ge 0) { throw "stop must not name the gateway" }
    $excelQuit = "Excel" + ".Quit"
    $controller = "AI_COCKPIT_CONTROLLER" + "_V9.ps1"
    if ($text.IndexOf($excelQuit) -ge 0) { throw "excel must stay up" }
    if ($text.IndexOf($controller) -ge 0) { throw "controller must not start" }
    if ($text.IndexOf("real_submit_allowed") -lt 0) { throw "real submit must be checked" }
    $tokens = $null
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($PSCommandPath, [ref]$tokens, [ref]$errors) | Out-Null
    if ($errors.Count -gt 0) { throw ("parse failed: " + $errors[0].ToString()) }
    Write-Output "SHADOW_LEDGER_RELOAD_SELFTEST PASS"
    exit 0
}

if (-not $ReloadSupervisor) { throw "specify -ReloadSupervisor or -SelfTest" }

$root = Get-RepoRoot
$ledgerPath = $root.TrimEnd('\') + "\scripts\shadow_trade_ledger.py"
$supervisorPath = $root.TrimEnd('\') + "\scripts\ai_shadow_supervisor.py"
if (-not (Test-Path -LiteralPath $ledgerPath) -or -not (Test-Path -LiteralPath $supervisorPath)) {
    Write-Output "LEDGER_CODE_MISSING"
    Write-Output "SUPERVISOR_RELOAD_ACCEPTANCE=FAIL"
    exit 1
}
$supervisorSource = [IO.File]::ReadAllText($supervisorPath, [Text.Encoding]::UTF8)
if ($supervisorSource.IndexOf("import shadow_trade_ledger") -lt 0) {
    Write-Output "LEDGER_CODE_MISSING"
    Write-Output "SUPERVISOR_RELOAD_ACCEPTANCE=FAIL"
    exit 1
}
$ruleChange = 0
if ($supervisorSource.IndexOf("LONG_ENTRY_SIGNALS = frozenset") -lt 0 -or $supervisorSource.IndexOf("SHORT_ENTRY_SIGNALS = frozenset") -lt 0) {
    $ruleChange = 1
}

$runtimeDir = Resolve-RuntimeDir
$livePath = $runtimeDir + "\live_ms2.json"
$statusPath = $runtimeDir + "\ai_shadow_status.json"
$beforeIds = @(Get-SupervisorIds)
$collectorBefore = Convert-IdList (Get-CollectorIds)
$gatewayBefore = Convert-IdList (Get-GatewayIds)
$excelBefore = Convert-IdList (Get-ImageIds "^EXCEL$")
$ms2Before = Convert-IdList (Get-ImageIds "MarketSpeed|MARKETSPEED")
Write-Output ("SUPERVISOR_PROCESS_COUNT_BEFORE=" + $beforeIds.Count)
if ($beforeIds.Count -ne 1) {
    Write-Output "SUPERVISOR_RELOAD_ACCEPTANCE=FAIL"
    Write-Output "REAL_SUBMIT_ALLOWED=0"
    exit 1
}
$statusBefore = Read-JsonFile $statusPath
if (-not (Test-RealSubmitFalse $statusBefore)) {
    Write-Output "REAL_SUBMIT_ALLOWED_BEFORE=NOT_FALSE"
    Write-Output "SUPERVISOR_RELOAD_ACCEPTANCE=FAIL"
    exit 1
}
$signalBefore = Get-IdentitySignal $livePath
$identityBefore = Get-IdentityText $statusBefore
$stateBefore = [string]$statusBefore.state
Write-Output "REAL_SUBMIT_ALLOWED_BEFORE=0"
Write-Output ("SHADOW_STATE_BEFORE=" + $stateBefore)
Write-Output ("IDENTITY_BEFORE=" + $identityBefore)
Write-Output ("SIGNAL_BEFORE=" + $signalBefore)
Write-Output ("LIVE_SIGNAL_RULE_CHANGE=" + $ruleChange)

$stopped = Stop-ShadowSupervisorOnly
Write-Output ("SUPERVISOR_STOPPED=" + $stopped)
if (-not (Wait-SupervisorCount 0 15)) {
    Write-Output "SUPERVISOR_RELOAD_ACCEPTANCE=FAIL"
    exit 1
}
Start-ShadowSupervisor $root
$fresh = $false
$deadline = (Get-Date).AddSeconds(40)
$statusAfter = $null
do {
    Start-Sleep -Seconds 2
    $nowIds = @(Get-SupervisorIds)
    $statusAfter = Read-JsonFile $statusPath
    if ($nowIds.Count -eq 1 -and (Test-RealSubmitFalse $statusAfter) -and [string]$statusAfter.state -eq "RUNNING") {
        $fresh = $true
        break
    }
} while ((Get-Date) -lt $deadline)

$afterIds = @(Get-SupervisorIds)
$collectorAfter = Convert-IdList (Get-CollectorIds)
$gatewayAfter = Convert-IdList (Get-GatewayIds)
$excelAfter = Convert-IdList (Get-ImageIds "^EXCEL$")
$ms2After = Convert-IdList (Get-ImageIds "MarketSpeed|MARKETSPEED")
$signalAfter = Get-IdentitySignal $livePath
$identityAfter = Get-IdentityText $statusAfter
$submitAfter = 0
if (-not (Test-RealSubmitFalse $statusAfter)) { $submitAfter = 1 }
Write-Output ("SUPERVISOR_PROCESS_COUNT_AFTER=" + $afterIds.Count)
Write-Output ("REAL_SUBMIT_ALLOWED_AFTER=" + $(if ($submitAfter -eq 0) { "0" } else { "NOT_FALSE" }))
Write-Output ("SHADOW_STATE_AFTER=" + [string]$statusAfter.state)
Write-Output ("IDENTITY_AFTER=" + $identityAfter)
Write-Output ("SIGNAL_AFTER=" + $signalAfter)
Write-Output ("HEARTBEAT_FRESH=" + $(if ($fresh) { "1" } else { "0" }))
Write-Output ("COLLECTOR_UNTOUCHED=" + $(if ($collectorBefore -eq $collectorAfter) { "1" } else { "0" }))
Write-Output ("GATEWAY_UNTOUCHED=" + $(if ($gatewayBefore -eq $gatewayAfter) { "1" } else { "0" }))
Write-Output ("EXCEL_UNTOUCHED=" + $(if ($excelBefore -eq $excelAfter) { "1" } else { "0" }))
Write-Output ("MS2_UNTOUCHED=" + $(if ($ms2Before -eq $ms2After) { "1" } else { "0" }))
Write-Output "LEDGER_CODE=1"
$pass = $fresh -and $afterIds.Count -eq 1 -and $submitAfter -eq 0 -and $ruleChange -eq 0 -and $collectorBefore -eq $collectorAfter -and $gatewayBefore -eq $gatewayAfter -and $excelBefore -eq $excelAfter -and $ms2Before -eq $ms2After
if ($identityBefore -eq "RUNTIME_IDENTITY_VERIFIED" -and $identityAfter -ne "RUNTIME_IDENTITY_VERIFIED") { $pass = $false }
if ($pass) {
    Write-Output "SUPERVISOR_RELOAD_ACCEPTANCE=PASS"
    exit 0
}
Write-Output "SUPERVISOR_RELOAD_ACCEPTANCE=FAIL"
exit 1
