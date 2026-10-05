param(
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [switch]$SelfTest
)

# Read Collector 28580, then Gateway 28581, then Strategy Input and one AI SHADOW cycle.
# A 503 is a running listener refusing the snapshot. This script prints the port and the reason.
# It does not stop Excel, MarketSpeed II, or the Collector. It does not start the Controller.
$ErrorActionPreference = "Stop"

function Get-QuotedArg([string]$Value) {
    return '"' + $Value + '"'
}

function Get-GatewayStartArgs([string]$Root, [string]$RuntimeDir) {
    $gateway = $Root.TrimEnd('\') + "\downloads\AI_COCKPIT_GATEWAY_V9.ps1"
    return @(
        "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", (Get-QuotedArg $gateway),
        "-RepoRoot", (Get-QuotedArg $Root),
        "-RuntimeDir", (Get-QuotedArg $RuntimeDir),
        "-Port", "28581"
    )
}

function Read-Http([int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $client.ReceiveTimeout = 5000
        $client.SendTimeout = 5000
        $client.Connect("127.0.0.1", $Port)
        $stream = $client.GetStream()
        $request = "GET /live_ms2.json HTTP/1.1`r`nHost: 127.0.0.1`r`nConnection: close`r`n`r`n"
        $bytes = [Text.Encoding]::ASCII.GetBytes($request)
        $stream.Write($bytes, 0, $bytes.Length)
        $buffer = New-Object System.IO.MemoryStream
        $chunk = New-Object byte[] 8192
        while (($read = $stream.Read($chunk, 0, $chunk.Length)) -gt 0) {
            $buffer.Write($chunk, 0, $read)
        }
        $raw = [Text.Encoding]::UTF8.GetString($buffer.ToArray())
        $split = $raw.IndexOf("`r`n`r`n")
        if ($split -lt 0) { return @{ Port = $Port; Status = "HTTP_BODY_MISSING"; Body = ""; Reason = "HTTP_BODY_MISSING" } }
        $head = $raw.Substring(0, $split)
        $status = ($head -split "`r`n")[0]
        $body = $raw.Substring($split + 4)
        $reason = ""
        try {
            $obj = $body | ConvertFrom-Json
            if ($null -ne $obj.reason) { $reason = [string]$obj.reason }
            elseif ($null -ne $obj.stale_reason) { $reason = [string]$obj.stale_reason }
        } catch {
            $reason = ""
        }
        return @{ Port = $Port; Status = $status; Body = $body; Reason = $reason }
    } catch {
        return @{ Port = $Port; Status = "PORT_CLOSED"; Body = ""; Reason = ($_.Exception.Message) }
    } finally {
        $client.Close()
    }
}

function Test-StaleOnly([string]$Reason) {
    if ([string]::IsNullOrWhiteSpace($Reason)) { return $false }
    $allowed = @("STALE_OR_MISSING_TIMESTAMP", "LIVE_VALUES_UNAVAILABLE", "INSUFFICIENT_COVERAGE", "live_ms2.json freshness threshold exceeded")
    foreach ($part in ($Reason -split ",")) {
        $item = $part.Trim()
        if ($allowed -notcontains $item) { return $false }
    }
    return $true
}

function Write-Probe($Result) {
    Write-Host ("PROBE PORT=" + $Result.Port + " STATUS=" + $Result.Status + " REASON=" + $Result.Reason)
}

function Write-MappingRows([string]$RuntimeDir) {
    $path = Join-Path $RuntimeDir "live_ms2.json"
    if (-not (Test-Path -LiteralPath $path)) { return }
    try {
        $obj = [IO.File]::ReadAllText($path, [Text.Encoding]::UTF8) | ConvertFrom-Json
        $diag = $obj.live_price_diagnostics
        if ($null -eq $diag) { return }
        foreach ($row in @($diag.mismatches)) {
            if ($null -eq $row) { continue }
            Write-Host ("MAPPING ROW=" + $row.row + " EXPECTED=" + $row.symbol + " SHEET=" + $row.sheet_code + " REASON=" + $row.reason)
        }
    } catch {}
}

function Wait-Port([int]$Port, [int]$Seconds, [bool]$StaleRetries) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    $last = $null
    do {
        $last = Read-Http $Port
        Write-Probe $last
        if ($last.Status -match " 200 ") { return $last }
        if ($last.Status -eq "PORT_CLOSED") { return $last }
        if (-not $StaleRetries -or -not (Test-StaleOnly ([string]$last.Reason))) { return $last }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    return $last
}

function Start-GatewayOnly([string]$Root, [string]$RuntimeDir) {
    $argList = Get-GatewayStartArgs $Root $RuntimeDir
    Start-Process -FilePath "powershell.exe" -ArgumentList $argList -WindowStyle Hidden | Out-Null
}

function Stop-GatewayOnly {
    $procs = @(Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" -ErrorAction Stop | Where-Object {
        $cmd = [string]$_.CommandLine
        ($cmd -like "*AI_COCKPIT_GATEWAY_V9.ps1*") -and ($cmd -notlike "*MS2_RSS_100_Collector.ps1*")
    })
    foreach ($proc in $procs) {
        Stop-Process -Id ([int]$proc.ProcessId) -Force
    }
    return $procs.Count
}

function Resolve-RuntimeDir {
    $manifest = "C:\AI_Cockpit_OneClick_Starter\V9_RUNTIME.json"
    if (Test-Path -LiteralPath $manifest) {
        $text = [IO.File]::ReadAllText($manifest, [Text.Encoding]::UTF8) | ConvertFrom-Json
        $dir = [string]$text.runtime_dir
        if (-not [string]::IsNullOrWhiteSpace($dir) -and (Test-Path -LiteralPath (Join-Path $dir "live_ms2.json"))) { return $dir }
    }
    $statePath = "C:\AI_Cockpit_OneClick_Starter\V9_CONTROLLER_STATE.json"
    $state = [IO.File]::ReadAllText($statePath, [Text.Encoding]::UTF8) | ConvertFrom-Json
    $dir = [string]$state.runtime_dir
    if ([string]::IsNullOrWhiteSpace($dir)) { $dir = [string]$state.repo_root }
    return $dir
}

if ($SelfTest) {
    $spaced = "C:\MarketSpeed II RSS\files"
    $args = Get-GatewayStartArgs "C:\repo" $spaced
    $joined = $args -join " "
    if ($joined -notlike '*-RuntimeDir "C:\MarketSpeed II RSS\files"*') { throw "runtime path must stay one quoted argument" }
    if ($joined -notlike '*-File "C:\repo\downloads\AI_COCKPIT_GATEWAY_V9.ps1"*') { throw "gateway file must stay one quoted argument" }
    $text = [IO.File]::ReadAllText($PSCommandPath, [Text.Encoding]::UTF8)
    $collectorRead = $text.IndexOf("PROBE_" + "COLLECTOR")
    $gatewayRead = $text.IndexOf("PROBE_" + "GATEWAY")
    if ($collectorRead -lt 0 -or $gatewayRead -lt 0 -or $collectorRead -gt $gatewayRead) { throw "collector probe must run before the gateway probe" }
    if ($text.IndexOf('AI_COCKPIT_GATEWAY_V9.ps1') -lt 0) { throw "gateway command missing" }
    if ($text.IndexOf('Stop-Process -Id ([int]$proc.ProcessId)') -lt 0) { throw "gateway stop must target the gateway process id" }
    $tokens = $null
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($PSCommandPath, [ref]$tokens, [ref]$errors) | Out-Null
    if ($errors.Count -gt 0) { throw ("parse failed: " + $errors[0].ToString()) }
    if (-not (Test-StaleOnly "STALE_OR_MISSING_TIMESTAMP")) { throw "stale reason must retry" }
    if (Test-StaleOnly "WRONG_SYMBOL_MAPPING") { throw "wrong symbol must not retry" }
    if (Test-StaleOnly "STALE_OR_MISSING_TIMESTAMP,WRONG_SOURCE_WORKBOOK") { throw "mixed hard reason must not retry" }
    Write-Output "SHADOW_PENETRATION_SELFTEST PASS"
    exit 0
}

$runtimeDir = Resolve-RuntimeDir
if ([string]::IsNullOrWhiteSpace($runtimeDir) -or -not (Test-Path -LiteralPath (Join-Path $runtimeDir "live_ms2.json"))) {
    throw "RUNTIME_DIR_UNRESOLVED"
}

# PROBE_COLLECTOR
$collector = Wait-Port 28580 90 $true
if ($collector.Status -notmatch " 200 ") {
    Write-MappingRows $runtimeDir
    throw ("COLLECTOR_HTTP " + $collector.Status + " " + $collector.Reason)
}

# PROBE_GATEWAY
$gateway = Wait-Port 28581 3 $false
if ($gateway.Status -eq "PORT_CLOSED") {
    Start-GatewayOnly $RepoRoot $runtimeDir
    $gateway = Wait-Port 28581 20 $true
}
if ($gateway.Status -notmatch " 200 ") {
    $replaced = Stop-GatewayOnly
    Write-Host ("GATEWAY_REPLACED=" + $replaced)
    Start-Sleep -Seconds 1
    Start-GatewayOnly $RepoRoot $runtimeDir
    $gateway = Wait-Port 28581 20 $true
}
if ($gateway.Status -notmatch " 200 ") {
    Write-MappingRows $runtimeDir
    throw ("GATEWAY_HTTP " + $gateway.Status + " " + $gateway.Reason)
}

$temp = Join-Path ([IO.Path]::GetTempPath()) ("shadow-penetration-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $temp -Force | Out-Null
$collectorPath = Join-Path $temp "collector.json"
$gatewayPath = Join-Path $temp "gateway.json"
[IO.File]::WriteAllText($collectorPath, [string]$collector.Body, [Text.UTF8Encoding]::new($false))
[IO.File]::WriteAllText($gatewayPath, [string]$gateway.Body, [Text.UTF8Encoding]::new($false))

$python = $null
foreach ($cand in @(
    (Join-Path $RepoRoot ".venv\Scripts\python.exe"),
    (Join-Path $RepoRoot "venv\Scripts\python.exe")
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
$script = Join-Path $RepoRoot "scripts\p0_shadow_penetration.py"
& $python @prefix $script --collector $collectorPath --gateway $gatewayPath
exit $LASTEXITCODE
