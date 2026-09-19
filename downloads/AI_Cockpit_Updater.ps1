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


# AI_COCKPIT_RUNTIME_DEPENDENCY_REPAIR_V1
# Repair only missing non-secret runtime support files. Existing files are never overwritten here.
try {
    $runtimeDir = Join-Path ([Environment]::GetFolderPath("Desktop")) "デイトレ\MarketSpeed II RSS\files"
    if (Test-Path -LiteralPath $runtimeDir) {
        $required = @(
            @{
                Name = "watchlist_100.json"
                Url  = "https://raw.githubusercontent.com/infoyuusuke-afk/trade-cockpit/main/ms2_live/watchlist_100.json"
            },
            @{
                Name = "MS2_Common_Engine.ps1"
                Url  = "https://raw.githubusercontent.com/infoyuusuke-afk/trade-cockpit/main/ms2_live/MS2_Common_Engine.ps1"
            }
        )
        foreach ($dep in $required) {
            $dest = Join-Path $runtimeDir $dep.Name
            if (-not (Test-Path -LiteralPath $dest)) {
                Log ("Missing runtime dependency detected: " + $dep.Name) "WARN"
                Invoke-WebRequest -Uri $dep.Url -OutFile $dest -UseBasicParsing -TimeoutSec 30
                if (-not (Test-Path -LiteralPath $dest) -or (Get-Item -LiteralPath $dest).Length -le 0) {
                    throw ("Runtime dependency repair failed: " + $dep.Name)
                }
                Log ("Runtime dependency repaired: " + $dest) "OK"
            }
        }
    }
} catch {
    Log ("Runtime dependency repair failed safely: " + $_.Exception.Message) "WARN"
}
