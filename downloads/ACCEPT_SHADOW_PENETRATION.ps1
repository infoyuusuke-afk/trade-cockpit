param(
    [Parameter(Mandatory = $true)][string]$RepoRoot
)

# Read Collector and Gateway, then check Strategy Input and one AI SHADOW cycle.
# Does not stop Excel, MarketSpeed II, or the Collector. Does not start the Controller.
$ErrorActionPreference = "Stop"

function Read-JsonText([string]$Url) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $client.ReceiveTimeout = 5000
        $client.SendTimeout = 5000
        $client.Connect("127.0.0.1", ($(if ($Url -match ':28581') { 28581 } else { 28580 })))
        $stream = $client.GetStream()
        $path = "/live_ms2.json"
        $request = "GET " + $path + " HTTP/1.1`r`nHost: 127.0.0.1`r`nConnection: close`r`n`r`n"
        $bytes = [Text.Encoding]::ASCII.GetBytes($request)
        $stream.Write($bytes, 0, $bytes.Length)
        $buffer = New-Object System.IO.MemoryStream
        $chunk = New-Object byte[] 8192
        while (($read = $stream.Read($chunk, 0, $chunk.Length)) -gt 0) {
            $buffer.Write($chunk, 0, $read)
        }
        $raw = [Text.Encoding]::UTF8.GetString($buffer.ToArray())
        $split = $raw.IndexOf("`r`n`r`n")
        if ($split -lt 0) { throw "HTTP_BODY_MISSING" }
        $head = $raw.Substring(0, $split)
        if ($head -notmatch " 200 ") { throw ("HTTP_STATUS " + ($head -split "`r`n")[0]) }
        return $raw.Substring($split + 4)
    } finally {
        $client.Close()
    }
}

function Test-PortOpen([int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $client.Connect("127.0.0.1", $Port)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

$statePath = "C:\AI_Cockpit_OneClick_Starter\V9_CONTROLLER_STATE.json"
$state = [IO.File]::ReadAllText($statePath, [Text.Encoding]::UTF8) | ConvertFrom-Json
$runtimeDir = [string]$state.runtime_dir
if ([string]::IsNullOrWhiteSpace($runtimeDir)) {
    $runtimeDir = [string]$state.repo_root
}
if ([string]::IsNullOrWhiteSpace($runtimeDir) -or -not (Test-Path -LiteralPath (Join-Path $runtimeDir "live_ms2.json"))) {
    throw "RUNTIME_DIR_UNRESOLVED"
}

$collectorBody = Read-JsonText "http://127.0.0.1:28580/live_ms2.json"
if (-not (Test-PortOpen 28581)) {
    $gateway = Join-Path $RepoRoot "downloads\AI_COCKPIT_GATEWAY_V9.ps1"
    $arg = '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "' + $gateway + '" -RepoRoot "' + $RepoRoot + '" -RuntimeDir "' + $runtimeDir + '" -Port 28581'
    Start-Process -FilePath "powershell.exe" -ArgumentList $arg -WindowStyle Hidden | Out-Null
    $deadline = (Get-Date).AddSeconds(20)
    while ((Get-Date) -lt $deadline -and -not (Test-PortOpen 28581)) { Start-Sleep -Seconds 1 }
}
if (-not (Test-PortOpen 28581)) { throw "GATEWAY_PORT_CLOSED" }
$gatewayBody = Read-JsonText "http://127.0.0.1:28581/live_ms2.json"

$temp = Join-Path ([IO.Path]::GetTempPath()) ("shadow-penetration-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $temp -Force | Out-Null
$collectorPath = Join-Path $temp "collector.json"
$gatewayPath = Join-Path $temp "gateway.json"
[IO.File]::WriteAllText($collectorPath, $collectorBody, [Text.UTF8Encoding]::new($false))
[IO.File]::WriteAllText($gatewayPath, $gatewayBody, [Text.UTF8Encoding]::new($false))

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
