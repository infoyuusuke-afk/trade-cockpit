param(
    [string]$RepoRoot = "C:\AI_Cockpit_Current\trade-cockpit",
    [string]$BrainRoot = "C:\AI_Cockpit_Brain",
    [string]$ReleaseBranch = "release/ai-cockpit-20261008",
    [string]$StateRoot = "C:\AI_Cockpit_OneClick_Starter"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$startupLogDir = Join-Path $StateRoot "Logs\Startup"
if (-not (Test-Path -LiteralPath $startupLogDir)) {
    New-Item -ItemType Directory -Path $startupLogDir -Force | Out-Null
}
$startupLog = Join-Path $startupLogDir ("startup_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".log")
Start-Transcript -LiteralPath $startupLog -Force | Out-Null

function Write-Step([string]$Text, [ConsoleColor]$Color = [ConsoleColor]::Cyan) {
    Write-Host ("[" + (Get-Date -Format "HH:mm:ss") + "] " + $Text) -ForegroundColor $Color
}

function Invoke-Git([string[]]$Args, [string]$Where = $RepoRoot) {
    $output = @(& git -C $Where @Args 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw ("git " + ($Args -join " ") + " failed: " + ($output -join " | "))
    }
    return $output
}

function Test-Port([int]$Port, [int]$TimeoutMs = 400) {
    $client = New-Object Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) { return $false }
        $client.EndConnect($async)
        return $true
    } catch {
        return $false
    } finally {
        try { $client.Close() } catch {}
    }
}

function Wait-Port([int]$Port, [int]$Seconds) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Port $Port 400) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Stop-BrainLaneOnly {
    $targets = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $cmd = [string]$_.CommandLine
        -not [string]::IsNullOrWhiteSpace($cmd) -and
        (
            $cmd -like "*C:\AI_Cockpit_Brain\downloads\AI_COCKPIT_GATEWAY_V9.ps1*" -or
            $cmd -like "*C:\AI_Cockpit_Brain\scripts\production_candidate_bridge.py*" -or
            $cmd -like "*C:\AI_Cockpit_Brain\scripts\ai_shadow_supervisor.py*"
        )
    })
    foreach ($proc in $targets) {
        try {
            Stop-Process -Id ([int]$proc.ProcessId) -Force -ErrorAction Stop
            Write-Step ("Stopped stale Brain lane PID " + $proc.ProcessId) DarkGray
        } catch {}
    }
    Start-Sleep -Milliseconds 500
}

function Stop-StaleCanonicalExcelIfSafe([string]$RuntimeDir) {
    $book = Join-Path $RuntimeDir "Kioxia_MS2_RSS_Live_Signals.xlsx"
    $excel = @(Get-CimInstance Win32_Process -Filter "Name = 'EXCEL.EXE'" -ErrorAction SilentlyContinue)
    if ($excel.Count -eq 0) { return }
    if ($excel.Count -gt 1) {
        throw "EXCEL_PRECHECK_BLOCKED: multiple Excel processes are open. Close non-cockpit Excel before startup."
    }
    $cmd = [string]$excel[0].CommandLine
    if ($cmd -like ("*" + $book + "*") -and $cmd -match '(?i)(^|\s)/x(\s|$)') {
        Write-Step ("Closing stale isolated cockpit Excel PID " + $excel[0].ProcessId) Yellow
        Stop-Process -Id ([int]$excel[0].ProcessId) -Force -ErrorAction Stop
        Start-Sleep -Seconds 3
        return
    }
    throw "EXCEL_PRECHECK_BLOCKED: an Excel process is already open and is not the isolated cockpit workbook."
}

function Get-RuntimeDir {
    $manifestPath = Join-Path $StateRoot "V9_RUNTIME.json"
    if (Test-Path -LiteralPath $manifestPath) {
        try {
            $manifest = [IO.File]::ReadAllText($manifestPath, [Text.Encoding]::UTF8) | ConvertFrom-Json
            $dir = [string]$manifest.runtime_dir
            if (-not [string]::IsNullOrWhiteSpace($dir) -and (Test-Path -LiteralPath $dir)) {
                return $dir
            }
        } catch {}
    }

    $roots = @(
        [Environment]::GetFolderPath("Desktop"),
        (Join-Path $env:USERPROFILE "Desktop"),
        (Join-Path $env:USERPROFILE "OneDrive\Desktop")
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique

    $hits = foreach ($root in $roots) {
        Get-ChildItem -LiteralPath $root -Recurse -File -Filter "Kioxia_MS2_RSS_Live_Signals.xlsx" -ErrorAction SilentlyContinue
    }
    $canonical = @($hits | Where-Object {
        $_.Directory.Name -eq "files" -and
        $null -ne $_.Directory.Parent -and
        $_.Directory.Parent.Name -eq "MarketSpeed II RSS"
    } | Sort-Object FullName -Unique)

    if ($canonical.Count -eq 1) { return $canonical[0].Directory.FullName }
    throw "RUNTIME_DIR_UNRESOLVED"
}

function Test-CollectorHealthy {
    try {
        $response = Invoke-WebRequest "http://127.0.0.1:28580/" -UseBasicParsing -TimeoutSec 4
        if ($response.StatusCode -ne 200) { return $false }
        $payload = $response.Content | ConvertFrom-Json
        if ($payload.source -ne "MarketSpeed II RSS / local PC") { return $false }
        if ($payload.data_conflict -eq $true) { return $false }
        if ($payload.real_submit_allowed -ne $false) { return $false }
        return $true
    } catch {
        return $false
    }
}

function Wait-CollectorHealthy([int]$Seconds) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-CollectorHealthy) { return $true }
        Start-Sleep -Seconds 2
    }
    return $false
}

try {
    Write-Step "AI Cockpit validated startup beginning." Green

    if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot ".git"))) {
        throw "REPO_NOT_FOUND: $RepoRoot"
    }

    Write-Step ("Fetching frozen release branch " + $ReleaseBranch + "...")
    Invoke-Git @("fetch", "origin", $ReleaseBranch, "--quiet") | Out-Null

    $releaseSha = (Invoke-Git @("rev-parse", ("origin/" + $ReleaseBranch))).Trim()
    Write-Step ("Release SHA " + $releaseSha.Substring(0, 12)) Green

    $runtimeDir = Get-RuntimeDir
    Write-Step ("RuntimeDir " + $runtimeDir)

    Stop-BrainLaneOnly
    Stop-StaleCanonicalExcelIfSafe $runtimeDir

    $runScript = Join-Path $RepoRoot "downloads\RUN_AI_COCKPIT_V9.ps1"
    if (-not (Test-Path -LiteralPath $runScript)) {
        throw "RUNNER_NOT_FOUND: $runScript"
    }

    $psExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    $runArgs = (
        '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "' + $runScript + '" ' +
        '-RepoRoot "' + $RepoRoot + '" ' +
        '-Branch "' + $ReleaseBranch + '" ' +
        '-ExpectedSha "' + $releaseSha + '" ' +
        '-RuntimeDirOverride "' + $runtimeDir + '" ' +
        '-Root "' + $StateRoot + '"'
    )

    Write-Step "Starting canonical Controller lane..."
    $controllerWindow = Start-Process -FilePath $psExe -ArgumentList $runArgs -PassThru

    foreach ($port in 28580,28581,28582,28583) {
        if (-not (Wait-Port $port 75)) {
            throw ("CANONICAL_PORT_TIMEOUT_" + $port)
        }
        Write-Step ("Port " + $port + " READY") Green
    }

    if (-not (Wait-CollectorHealthy 45)) {
        throw "COLLECTOR_HEALTH_ACCEPTANCE_FAILED"
    }
    Write-Step "Collector HTTP acceptance PASS." Green

    Invoke-Git @("fetch", "origin", $ReleaseBranch, "--quiet") | Out-Null

    if (-not (Test-Path -LiteralPath $BrainRoot)) {
        Write-Step "Creating Brain worktree..."
        Invoke-Git @("worktree", "add", "--detach", $BrainRoot, ("origin/" + $ReleaseBranch)) | Out-Null
    } else {
        Write-Step "Resetting Brain worktree to frozen release..."
        Invoke-Git @("reset", "--hard", ("origin/" + $ReleaseBranch), "--quiet") $BrainRoot | Out-Null
    }

    Stop-BrainLaneOnly

    $gatewayScript = Join-Path $BrainRoot "downloads\AI_COCKPIT_GATEWAY_V9.ps1"
    $gatewayArgs = (
        '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "' + $gatewayScript + '" ' +
        '-RepoRoot "' + $BrainRoot + '" ' +
        '-RuntimeDir "' + $runtimeDir + '" ' +
        '-Build "VALIDATED-20261008" -Port 28584'
    )
    Write-Step "Starting Brain UI gateway 28584..."
    $brainGateway = Start-Process -FilePath $psExe -ArgumentList $gatewayArgs -PassThru

    if (-not (Wait-Port 28584 20)) {
        throw "BRAIN_GATEWAY_28584_TIMEOUT"
    }

    $activate = Join-Path $BrainRoot "downloads\ACTIVATE_BRAIN_SHADOW_LINEAGE.ps1"
    Write-Step "Activating Brain -> candidate_id -> Shadow lineage..."
    & $psExe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $activate -RepoRoot $RepoRoot -BrainRoot $BrainRoot -Branch $ReleaseBranch
    if ($LASTEXITCODE -ne 0) {
        throw "BRAIN_SHADOW_LINEAGE_ACTIVATION_FAILED"
    }

    if (-not (Wait-Port 28584 20)) {
        throw "BRAIN_GATEWAY_LOST_AFTER_ACTIVATION"
    }

    $brainOk = $false
    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline) {
        try {
            $brain = Invoke-RestMethod ("http://127.0.0.1:28584/brain_shadow_live.json?t=" + [DateTimeOffset]::Now.ToUnixTimeMilliseconds()) -TimeoutSec 4
            if (
                $null -ne $brain -and
                $brain.real_submit_allowed -eq $false -and
                [string]$brain.brain.title -eq "AI BRAIN LIVE"
            ) {
                $brainOk = $true
                break
            }
        } catch {}
        Start-Sleep -Seconds 2
    }
    if (-not $brainOk) {
        throw "BRAIN_LIVE_ACCEPTANCE_FAILED"
    }

    $ports = [ordered]@{}
    foreach ($port in 28580,28581,28582,28583,28584) {
        $ports[[string]$port] = Test-Port $port 500
    }

    $collector = Invoke-RestMethod "http://127.0.0.1:28580/" -TimeoutSec 4
    $brainNow = Invoke-RestMethod ("http://127.0.0.1:28584/brain_shadow_live.json?t=" + [DateTimeOffset]::Now.ToUnixTimeMilliseconds()) -TimeoutSec 4

    Write-Host ""
    Write-Host "==================================================" -ForegroundColor DarkGreen
    Write-Host " TOMORROW STARTUP ACCEPTANCE = PASS" -ForegroundColor Green
    Write-Host "==================================================" -ForegroundColor DarkGreen
    foreach ($port in 28580,28581,28582,28583,28584) {
        Write-Host ($port.ToString() + "=" + $ports[[string]$port]) -ForegroundColor Green
    }
    Write-Host ("UPDATED_AT=" + [string]$collector.updated_at) -ForegroundColor Green
    Write-Host ("DATA_CONFLICT=" + [string]$collector.data_conflict) -ForegroundColor Green
    Write-Host ("BRAIN_SYMBOL=" + [string]$brainNow.brain.symbol) -ForegroundColor Green
    Write-Host ("BRAIN_SIDE=" + [string]$brainNow.brain.side) -ForegroundColor Green
    Write-Host ("BRAIN_CANDIDATE_ID=" + [string]$brainNow.brain.candidate_id) -ForegroundColor Green
    Write-Host ("LINKED=" + [string]$brainNow.link.linked) -ForegroundColor Green
    Write-Host "REAL_SUBMIT_ALLOWED=0" -ForegroundColor Green
    Write-Host "TOMORROW_STARTUP_ACCEPTANCE=PASS" -ForegroundColor Green
    Write-Host ("STARTUP_LOG=" + $startupLog) -ForegroundColor DarkGray

    Start-Process "http://127.0.0.1:28584/?brain=1"
}
catch {
    Write-Host ""
    Write-Host "==================================================" -ForegroundColor Red
    Write-Host " TOMORROW STARTUP ACCEPTANCE = FAIL" -ForegroundColor Red
    Write-Host "==================================================" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Yellow
    Write-Host "real_submit_allowed remains false." -ForegroundColor Yellow
    Write-Host ("STARTUP_LOG=" + $startupLog) -ForegroundColor DarkGray
    [Environment]::ExitCode = 1
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
}
