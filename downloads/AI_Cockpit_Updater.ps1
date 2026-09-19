param(
    [string]$Root = "C:\\AI_Cockpit_OneClick_Starter",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ManifestUrl = "https://infoyuusuke-afk.github.io/trade-cockpit/downloads/version.json"
$UpdatesDir = Join-Path $Root "Updates"
$StatePath = Join-Path $Root "update_state.json"
$LogDir = Join-Path $Root "Logs"

New-Item -ItemType Directory -Force -Path $UpdatesDir,$LogDir | Out-Null
$log = Join-Path $LogDir ("updater_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

function Log([string]$m,[string]$level="INFO") {
    $line = "[{0}] [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"),$level,$m
    Write-Host $line
    Add-Content -LiteralPath $log -Value $line -Encoding UTF8
}

try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Log "Checking stable update manifest."
    $manifest = Invoke-RestMethod -Uri $ManifestUrl -UseBasicParsing -TimeoutSec 15
} catch {
    Log ("Update check skipped: " + $_.Exception.Message) "WARN"
    exit 0
}

if (-not $manifest.version -or -not $manifest.download_url -or -not $manifest.kit_name) {
    Log "Manifest is incomplete. No download performed." "WARN"
    exit 0
}

$state = [pscustomobject]@{
    installed_version = "0.0.0.0"
    downloaded_version = ""
    downloaded_path = ""
    checked_at = ""
}
if (Test-Path -LiteralPath $StatePath) {
    try {
        $old = Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($old.installed_version) { $state.installed_version = [string]$old.installed_version }
        if ($old.downloaded_version) { $state.downloaded_version = [string]$old.downloaded_version }
        if ($old.downloaded_path) { $state.downloaded_path = [string]$old.downloaded_path }
    } catch {
        Log "Existing update_state.json could not be read; continuing safely." "WARN"
    }
}

try {
    $remoteVer = [version]([string]$manifest.version)
    $installedVer = [version]([string]$state.installed_version)
} catch {
    Log "Version format is invalid. No download performed." "WARN"
    exit 0
}

$state.checked_at = (Get-Date).ToString("o")

if (-not $Force -and $remoteVer -le $installedVer) {
    Log ("Already installed or newer: local {0}, remote {1}" -f $installedVer,$remoteVer) "OK"
    $state | ConvertTo-Json | Set-Content -LiteralPath $StatePath -Encoding UTF8
    exit 0
}

$target = Join-Path $UpdatesDir ("{0}_{1}" -f $manifest.version,$manifest.kit_name)

if (-not $Force -and $state.downloaded_version -eq [string]$manifest.version -and (Test-Path -LiteralPath $state.downloaded_path)) {
    Log ("Latest kit is already downloaded and pending validation: " + $state.downloaded_path) "OK"
    $state | ConvertTo-Json | Set-Content -LiteralPath $StatePath -Encoding UTF8
    exit 0
}

$tmp = $target + ".download"
Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue

try {
    Log ("Downloading stable kit {0}..." -f $manifest.version)
    Invoke-WebRequest -Uri ([string]$manifest.download_url) -OutFile $tmp -UseBasicParsing -TimeoutSec 60

    $item = Get-Item -LiteralPath $tmp
    if ($manifest.size_bytes -and [int64]$item.Length -ne [int64]$manifest.size_bytes) {
        throw "Downloaded size mismatch. Expected $($manifest.size_bytes), got $($item.Length)."
    }
    if ($manifest.sha256) {
        $actual = (Get-FileHash -LiteralPath $tmp -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne ([string]$manifest.sha256).ToLowerInvariant()) {
            throw "SHA256 mismatch. Download rejected."
        }
    }

    Move-Item -LiteralPath $tmp -Destination $target -Force
    $state.downloaded_version = [string]$manifest.version
    $state.downloaded_path = $target
    $state.checked_at = (Get-Date).ToString("o")
    $state | ConvertTo-Json | Set-Content -LiteralPath $StatePath -Encoding UTF8

    $pending = [pscustomobject]@{
        version = [string]$manifest.version
        downloaded_at = (Get-Date).ToString("o")
        zip_path = $target
        status = "downloaded_pending_validation"
        note = "Downloaded automatically. Runtime files are not overwritten until the kit is validated and an apply step is explicitly enabled."
    }
    $pending | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $UpdatesDir "pending_update.json") -Encoding UTF8
    Log ("Latest stable kit downloaded: " + $target) "OK"
} catch {
    Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    Log ("Download failed safely: " + $_.Exception.Message) "ERROR"
    exit 0
}
