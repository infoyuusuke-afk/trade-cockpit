param(
    [string]$RepoRoot = "",
    [string]$Branch = "fix/v9-ui-voice-convergence",
    [string]$ExpectedSha = "",
    [switch]$SkipGitUpdate,
    [string]$RuntimeDirOverride = "",
    [string]$Root = "C:\AI_Cockpit_OneClick_Starter",
    [switch]$DeployRuntimeOnly,
    [switch]$AcceptRuntimeCollector,
    [switch]$RuntimeAcceptSelfTest
)

# One-shot entry point: update (git fetch/checkout a PINNED branch, or an
# exact SHA if given) + backup (previous V8 logs/state, timestamped) +
# start (Controller V8), so the person running this never has to type
# several separate diagnostic commands by hand.
#
# 2026-09-25 P0 fix: $Branch used to default to "" and silently fall back
# to "whatever branch this checkout happens to be on right now" - an
# implicit, unverified target. It now defaults to the one reviewed
# integration branch, and every git step that can fail (fetch/checkout/
# reset) is fatal: on failure this script stops before ever starting the
# Controller ("fail-closed"), it does not fall back to running whatever
# happened to already be on disk. After updating, the actual branch/SHA is
# re-read from git and compared against what was requested; a mismatch is
# also fatal. Pass -SkipGitUpdate only when you deliberately want to run
# the exact commit already checked out (e.g. re-running after a crash) -
# even then, the branch/SHA actually on disk is printed so it's never
# ambiguous what is about to start.

$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
    if (-not [string]::IsNullOrWhiteSpace($RepoRoot)) { return $RepoRoot }
    $candidate = Split-Path -Parent $PSScriptRoot
    if (Test-Path -LiteralPath (Join-Path $candidate "card_system.js")) { return $candidate }
    throw "Could not resolve the trade-cockpit repo root from this script's location. Pass -RepoRoot explicitly."
}

function Invoke-GitFatal([string]$RepoPath, [string[]]$GitArgs, [string]$FailMessage) {
    $output = & git -C $RepoPath @GitArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw ($FailMessage + " (git " + ($GitArgs -join ' ') + "): " + ($output -join " | "))
    }
    return $output
}

# 2026-09-25 P0 fix (blocker before real-machine use): this script used to
# only update the git checkout and assume that was enough. It is not -
# the Controller runs Watcher/Heartbeat/Collector from Desktop-side
# RuntimeDir (the MS2 kit install), a completely separate location from
# the repo checkout. Repo updated != runtime updated. Concretely: the
# Watcher bridge port was moved 28581->28582 in the repo, but without this
# deploy phase the OLD Watcher.ps1 (still hardcoding 28581) stays running
# from RuntimeDir forever, re-colliding with the new Gateway. This phase
# copies the 3 runtime scripts into RuntimeDir every run, validating each
# one (staged copy -> AST parse -> SHA256 confirm) before touching
# anything real, and refuses to deploy at all - not partially - if even
# one fails.
function Resolve-RuntimeDirForDeploy([string]$Explicit) {
    if (-not [string]::IsNullOrWhiteSpace($Explicit)) {
        $resolved = [IO.Path]::GetFullPath($Explicit)
        if (-not (Test-Path -LiteralPath $resolved -PathType Container)) {
            throw "RuntimeDirOverride does not exist: $resolved"
        }
        $book = Join-Path $resolved "Kioxia_MS2_RSS_Live_Signals.xlsx"
        if (-not (Test-Path -LiteralPath $book -PathType Leaf)) {
            throw "RuntimeDirOverride is missing Kioxia_MS2_RSS_Live_Signals.xlsx: $resolved"
        }
        return $resolved
    }

    $roots = @(
        [Environment]::GetFolderPath("Desktop"),
        (Join-Path $env:USERPROFILE "Desktop"),
        (Join-Path $env:USERPROFILE "OneDrive\Desktop")
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique
    $hits = foreach ($r in $roots) {
        Get-ChildItem -LiteralPath $r -Recurse -File -Filter "MS2_RSS_100_Collector.ps1" -ErrorAction SilentlyContinue
    }
    # Only the canonical ...\MarketSpeed II RSS\files directory is a
    # valid runtime. Nested backup/staging folders under "files" must
    # never be selected as RuntimeDir.
    $canonical = @($hits | Where-Object {
        $_.Directory.Name -eq "files" -and
        $null -ne $_.Directory.Parent -and
        $_.Directory.Parent.Name -eq "MarketSpeed II RSS"
    } | Sort-Object FullName -Unique)
    if ($canonical.Count -eq 1) { return $canonical[0].Directory.FullName }
    if ($canonical.Count -gt 1) {
        $paths = ($canonical | ForEach-Object { $_.Directory.FullName } | Select-Object -Unique) -join " | "
        throw "Multiple canonical MS2 runtime folders found. Refusing to guess: $paths"
    }
    throw "Canonical MS2 runtime folder not found under Desktop (expected ...\MarketSpeed II RSS\files)."
}

function Get-Sha256Hex([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
}

function Format-PathCodePoints([string]$Value) {
    if ([string]::IsNullOrEmpty($Value)) { return "" }
    $parts = New-Object System.Collections.Generic.List[string]
    foreach ($ch in $Value.ToCharArray()) {
        $code = [int]$ch
        if ($code -ge 32 -and $code -lt 127) {
            [void]$parts.Add([string]$ch)
        } else {
            [void]$parts.Add("u+" + $code.ToString("X4"))
        }
    }
    return ($parts -join "")
}

function Test-PowerShellSyntaxOk([string]$Path) {
    $parseErrors = $null
    $tokens = $null
    [System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$parseErrors) | Out-Null
    return $parseErrors.Count -eq 0
}

$RUNTIME_DEPLOY_FILES = @(
    "Kioxia_RSS_Live_Watcher.ps1",
    "Kioxia_Safety_Heartbeat.ps1",
    "MS2_RSS_100_Collector.ps1",
    "MS2_Common_Engine.ps1",
    "BUILD_KIOXIA_TIME_STATS.ps1",
    "watchlist_100.json",
    "SPEAK_TODAY_STRATEGY.ps1",
    "SPEAK_LIVE_EMOTION.ps1"
)

function Deploy-RuntimeFiles([string]$RepoRoot, [string]$RuntimeDir) {
    $staged = @{}
    $allStagedPaths = @()
    try {
        # Phase 1: stage + validate every file first. Nothing real is
        # touched yet - a failure here leaves RuntimeDir completely
        # untouched (fail-closed, not a partial deploy).
        foreach ($name in $RUNTIME_DEPLOY_FILES) {
            $source = Join-Path $RepoRoot ("ms2_live\" + $name)
            if (-not (Test-Path -LiteralPath $source)) {
                throw "Runtime deploy source missing: $source"
            }
            $dest = Join-Path $RuntimeDir $name
            $stagedPath = $dest + ".staged_" + [Guid]::NewGuid().ToString("N").Substring(0, 8) + ".tmp"
            Copy-Item -LiteralPath $source -Destination $stagedPath -Force
            # Track the staged path immediately, before validation, so the
            # catch block below can always clean it up - including when
            # THIS file is the one that fails validation.
            $allStagedPaths += $stagedPath
            if ($name -like "*.ps1" -and -not (Test-PowerShellSyntaxOk $stagedPath)) {
                throw "Runtime deploy: AST parse failed for staged copy of $name - not deploying anything."
            }
            $sourceHash = Get-Sha256Hex $source
            $stagedHash = Get-Sha256Hex $stagedPath
            if ($sourceHash -ne $stagedHash) {
                throw "Runtime deploy: SHA256 mismatch between source and staged copy of $name - not deploying anything."
            }
            $staged[$name] = @{ staged_path = $stagedPath; dest_path = $dest; sha256 = $sourceHash }
        }
    } catch {
        foreach ($stagedPath in $allStagedPaths) {
            Remove-Item -LiteralPath $stagedPath -Force -ErrorAction SilentlyContinue
        }
        throw
    }

    # Phase 2: every file validated. Back up ALL originals first, then
    # replace them. If any move or post-deploy verification fails, restore
    # every already-replaced file from the backup so RuntimeDir never stays
    # half-upgraded.
    $backupRoot = Join-Path (Split-Path -Parent $RuntimeDir) "_v9_runtime_backups"
    if (-not (Test-Path -LiteralPath $backupRoot)) { New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null }
    $backupDir = Join-Path $backupRoot ("runtime_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

    $hadOriginal = @{}
    foreach ($name in $RUNTIME_DEPLOY_FILES) {
        $entry = $staged[$name]
        $had = Test-Path -LiteralPath $entry.dest_path
        $hadOriginal[$name] = $had
        if ($had) {
            Copy-Item -LiteralPath $entry.dest_path -Destination (Join-Path $backupDir $name) -Force
        }
    }

    $deployedHashes = [ordered]@{}
    $replaced = New-Object System.Collections.Generic.List[string]
    try {
        foreach ($name in $RUNTIME_DEPLOY_FILES) {
            $entry = $staged[$name]
            Move-Item -LiteralPath $entry.staged_path -Destination $entry.dest_path -Force -ErrorAction Stop
            $replaced.Add($name)
            $deployedHashes[$name] = $entry.sha256
        }

        # Verify from the ACTUAL deployed files, not the source.
        $watcherText = [IO.File]::ReadAllText((Join-Path $RuntimeDir "Kioxia_RSS_Live_Watcher.ps1"), [Text.Encoding]::UTF8)
        if ($watcherText -notmatch [regex]::Escape('Start-LocalJsonBridge $watcherJsonPath 28582')) {
            throw "Runtime deploy verification failed: deployed Watcher does not reference port 28582."
        }
        $collectorText = [IO.File]::ReadAllText((Join-Path $RuntimeDir "MS2_RSS_100_Collector.ps1"), [Text.Encoding]::UTF8)
        if ($collectorText -notmatch "28580") {
            throw "Runtime deploy verification failed: deployed Collector does not reference port 28580."
        }
        foreach ($name in $RUNTIME_DEPLOY_FILES) {
            $actual = Get-Sha256Hex (Join-Path $RuntimeDir $name)
            if ($actual -ne $staged[$name].sha256) {
                throw "Runtime deploy verification failed: deployed SHA256 mismatch for $name."
            }
        }
    } catch {
        $deployError = $_
        for ($i = $replaced.Count - 1; $i -ge 0; $i--) {
            $name = $replaced[$i]
            $dest = $staged[$name].dest_path
            try {
                if ($hadOriginal[$name]) {
                    Copy-Item -LiteralPath (Join-Path $backupDir $name) -Destination $dest -Force -ErrorAction Stop
                } else {
                    Remove-Item -LiteralPath $dest -Force -ErrorAction SilentlyContinue
                }
            } catch {}
        }
        foreach ($name in $RUNTIME_DEPLOY_FILES) {
            $sp = $staged[$name].staged_path
            if ($sp) { Remove-Item -LiteralPath $sp -Force -ErrorAction SilentlyContinue }
        }
        throw $deployError
    }

    return @{ hashes = $deployedHashes; backup_dir = $backupDir }
}

function Test-CollectorIdentityContract([string]$Text) {
    if ([string]::IsNullOrWhiteSpace($Text)) { return $false }
    $ordinal = [StringComparison]::Ordinal
    if ($Text.IndexOf("function Get-IdentityQuote", $ordinal) -lt 0) { return $false }
    if ($Text.IndexOf("workbook_identity_verified", $ordinal) -lt 0) { return $false }
    if ($Text.IndexOf('$script:IdentityTicker = "285A.T"', $ordinal) -lt 0) { return $false }
    return $true
}

function Get-IdentityRollbackBlock([string]$SourceText, [string]$DestinationText) {
    if ((Test-CollectorIdentityContract $DestinationText) -and -not (Test-CollectorIdentityContract $SourceText)) {
        return "RUNTIME_ROLLBACK_BLOCKED"
    }
    return ""
}

function Get-ComparablePath([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return "" }
    $text = $Value.Trim().Replace("/", "\")
    while ($text.EndsWith("\")) { $text = $text.Substring(0, $text.Length - 1) }
    return $text.ToUpperInvariant()
}

function Test-CollectorCommandLine([string]$CommandLine) {
    if ([string]::IsNullOrWhiteSpace($CommandLine)) { return $false }
    $cmp = [StringComparison]::OrdinalIgnoreCase
    if ($CommandLine.IndexOf("MS2_RSS_100_Collector.ps1", $cmp) -lt 0) { return $false }
    foreach ($name in @(
        "AI_COCKPIT_CONTROLLER_V9.ps1",
        "RUN_AI_COCKPIT_V9.ps1",
        "Kioxia_RSS_Live_Watcher.ps1",
        "Kioxia_Safety_Heartbeat.ps1",
        "AI_COCKPIT_GATEWAY_V9.ps1",
        "EXCEL.EXE"
    )) {
        if ($CommandLine.IndexOf($name, $cmp) -ge 0) { return $false }
    }
    return $true
}

function Test-LocalPreopen {
    $clock = (Get-Date).TimeOfDay
    return ($clock -ge [TimeSpan]::Parse("08:00:00") -and $clock -lt [TimeSpan]::Parse("09:00:00"))
}

function Get-RuntimeAcceptanceFailure($Payload, [bool]$Preopen, [string]$ExpectedWorkbookPath) {
    $reasons = New-Object System.Collections.Generic.List[string]
    if ($null -eq $Payload) { return "NO_PAYLOAD" }
    $diag = $null
    try { $diag = $Payload.live_price_diagnostics } catch { $diag = $null }
    $symbol = [string]$Payload.symbol
    if ([string]::IsNullOrWhiteSpace($symbol) -and $null -ne $diag) { $symbol = [string]$diag.symbol }
    if ($symbol -ne "285A.T") { [void]$reasons.Add("SYMBOL") }
    $count = $Payload.collector_count
    if ($null -eq $count -and $null -ne $diag) { $count = $diag.collector_count }
    $countNumber = 0
    try { $countNumber = [int]$count } catch { $countNumber = 0 }
    if ($countNumber -ne 1) { [void]$reasons.Add("COLLECTOR_COUNT") }
    $verified = $false
    $fullName = ""
    if ($null -ne $diag) {
        $verified = ($diag.workbook_identity_verified -eq $true)
        $fullName = [string]$diag.workbook_full_name
    }
    try {
        if ($null -ne $Payload.PSObject.Properties["workbook_identity_verified"]) {
            $verified = ($Payload.workbook_identity_verified -eq $true)
        }
        if ($null -ne $Payload.PSObject.Properties["workbook_full_name"] -and -not [string]::IsNullOrWhiteSpace([string]$Payload.workbook_full_name)) {
            $fullName = [string]$Payload.workbook_full_name
        }
    } catch {}
    if (-not $verified) { [void]$reasons.Add("WORKBOOK_IDENTITY") }
    if ((Get-ComparablePath $fullName) -ne (Get-ComparablePath $ExpectedWorkbookPath)) { [void]$reasons.Add("WORKBOOK_PATH") }
    $realSubmit = $Payload.real_submit_allowed
    if ($null -eq $realSubmit -and $null -ne $diag) { $realSubmit = $diag.real_submit_allowed }
    if ($realSubmit -ne $false) { [void]$reasons.Add("REAL_SUBMIT") }
    $price = $Payload.current_price
    if ($null -eq $price -and $null -ne $diag) { $price = $diag.current_price }
    $stamp = [string]$Payload.source_timestamp
    if ([string]::IsNullOrWhiteSpace($stamp) -and $null -ne $diag) { $stamp = [string]$diag.source_timestamp }
    $priceZero = $false
    if ($null -eq $price -or [string]$price -eq "") {
        $priceZero = $true
    } else {
        try { $priceZero = ([double]$price -eq 0) } catch { $priceZero = $true }
    }
    if ($priceZero) {
        if (-not $Preopen) { [void]$reasons.Add("PRICE") }
        elseif ($stamp -notmatch '^\d{2}:\d{2}:\d{2}$') { [void]$reasons.Add("QUOTE_CLOCK") }
    }
    $status = [string]$Payload.status
    $reasonText = [string]$Payload.reason
    if ([string]::IsNullOrWhiteSpace($reasonText)) { $reasonText = [string]$Payload.stale_reason }
    foreach ($item in @(
        "WRONG_SOURCE_WORKBOOK",
        "WRONG_SYMBOL_MAPPING",
        "DUPLICATE_COLLECTOR",
        "DATA_CONFLICT",
        "CACHED_OR_SAMPLE_PAYLOAD",
        "MISSING_PRICE_DIAGNOSTICS",
        "STALE_OR_MISSING_TIMESTAMP"
    )) {
        if ($reasonText.IndexOf($item, [StringComparison]::Ordinal) -ge 0) { [void]$reasons.Add($item) }
    }
    if ($status -eq "PRICE_SOURCE_MISMATCH") { [void]$reasons.Add("PRICE_SOURCE_MISMATCH") }
    if ($Payload.data_conflict -eq $true) { [void]$reasons.Add("DATA_CONFLICT") }
    if (-not $Preopen -and $status -eq "stale") { [void]$reasons.Add("STALE") }
    return ($reasons -join ",")
}

function Get-CollectorProcessIds {
    $ids = New-Object System.Collections.Generic.List[int]
    $procs = @(Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" -ErrorAction Stop)
    foreach ($proc in $procs) {
        if (Test-CollectorCommandLine ([string]$proc.CommandLine)) {
            [void]$ids.Add([int]$proc.ProcessId)
        }
    }
    return @($ids)
}

function Get-ControllerProcessCount {
    $count = 0
    $procs = @(Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" -ErrorAction Stop)
    foreach ($proc in $procs) {
        $cmd = [string]$proc.CommandLine
        if ($cmd.IndexOf("AI_COCKPIT_CONTROLLER_V9.ps1", [StringComparison]::OrdinalIgnoreCase) -ge 0) { $count++ }
    }
    return $count
}

function Get-CollectorHandoffMode([int]$ControllerCount, [int]$CollectorCount) {
    if ($ControllerCount -gt 1 -or $ControllerCount -lt 0) { return "REFUSE_CONTROLLER" }
    if ($CollectorCount -lt 0 -or $CollectorCount -gt 1) { return "REFUSE_COLLECTOR" }
    if ($ControllerCount -eq 1 -and $CollectorCount -eq 0) { return "REFUSE_COLLECTOR" }
    if ($ControllerCount -eq 0 -and $CollectorCount -eq 0) { return "DIRECT_START" }
    if ($ControllerCount -eq 1) { return "CONTROLLER_RESTARTS" }
    return "DIRECT_RESTART"
}

function Test-AncestorProcess([int]$ProcessId, [int]$AncestorId) {
    $current = $ProcessId
    for ($depth = 0; $depth -lt 6; $depth++) {
        if ($current -le 0) { return $false }
        if ($current -eq $AncestorId) { return $true }
        $info = $null
        try { $info = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $current) -ErrorAction SilentlyContinue } catch { return $false }
        if ($null -eq $info) { return $false }
        $current = [int]$info.ParentProcessId
    }
    return $false
}

function Get-LoopbackListenerProcessId([int]$Port) {
    try {
        $conn = @(Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
        if ($conn.Count -ge 1) { return [int]$conn[0].OwningProcess }
    } catch {}
    return 0
}

function Stop-OneCollectorProcess([int]$ProcessId) {
    $info = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $ProcessId) -ErrorAction Stop
    if ($null -eq $info) { return }
    if (-not (Test-CollectorCommandLine ([string]$info.CommandLine))) {
        throw ("REFUSING_TO_STOP_NON_COLLECTOR pid=" + $ProcessId)
    }
    $releasedListener = $false
    $listenerPid = Get-LoopbackListenerProcessId 28580
    if ($listenerPid -gt 0 -and $listenerPid -ne $ProcessId) {
        $listener = $null
        try { $listener = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $listenerPid) -ErrorAction SilentlyContinue } catch { $listener = $null }
        $listenerName = ""
        if ($null -ne $listener) { $listenerName = [string]$listener.Name }
        $listenerIsShell = ($listenerName -eq "powershell.exe" -or $listenerName -eq "pwsh.exe")
        if ($listenerIsShell -and (Test-AncestorProcess $listenerPid $ProcessId)) {
            Stop-Process -Id $listenerPid -Force -ErrorAction SilentlyContinue
            $releasedListener = $true
        }
    }
    $children = @(Get-CimInstance Win32_Process -Filter ("ParentProcessId = " + $ProcessId) -ErrorAction SilentlyContinue)
    foreach ($child in $children) {
        $childName = [string]$child.Name
        if ($childName -eq "powershell.exe" -or $childName -eq "pwsh.exe") {
            Stop-Process -Id ([int]$child.ProcessId) -Force -ErrorAction SilentlyContinue
        }
    }
    if ($releasedListener) {
        $quietDeadline = (Get-Date).AddSeconds(5)
        while ((Get-Date) -lt $quietDeadline) {
            if ((Get-LoopbackListenerProcessId 28580) -le 0) { break }
            Start-Sleep -Milliseconds 200
        }
    }
    Stop-Process -Id $ProcessId -Force -ErrorAction Stop
}

function Start-OneRuntimeCollector([string]$RuntimeDir) {
    $script = Join-Path $RuntimeDir "MS2_RSS_100_Collector.ps1"
    $exe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    if (-not (Test-Path -LiteralPath $exe)) {
        throw "Windows PowerShell 5.1 executable was not found. Collector was not started."
    }
    $stdout = Join-Path $RuntimeDir "MS2_RSS_100_Collector.acceptance.stdout.log"
    $stderr = Join-Path $RuntimeDir "MS2_RSS_100_Collector.acceptance.stderr.log"
    Remove-Item -LiteralPath $stdout, $stderr -Force -ErrorAction SilentlyContinue
    if ($script.Contains('"')) { throw "Collector script path contains a quote. Collector was not started." }
    # Windows PowerShell 5.1 does not quote an ArgumentList array. The
    # runtime path contains spaces (MarketSpeed II RSS), so -File must be
    # one quoted string or the process exits before the script starts.
    $collectorArgs = '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "' + $script + '"'
    return Start-Process -FilePath $exe -ArgumentList $collectorArgs -WorkingDirectory $RuntimeDir -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
}

function Receive-CollectorBridge {
    $client = $null
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $client.ReceiveTimeout = 5000
        $client.SendTimeout = 5000
        $client.Connect("127.0.0.1", 28580)
        $stream = $client.GetStream()
        $writer = New-Object System.IO.StreamWriter($stream)
        $writer.NewLine = "`r`n"
        $writer.AutoFlush = $true
        $writer.WriteLine("GET / HTTP/1.1")
        $writer.WriteLine("Host: 127.0.0.1")
        $writer.WriteLine("Connection: close")
        $writer.WriteLine("")
        $buffer = New-Object System.IO.MemoryStream
        $tmp = New-Object byte[] 8192
        while ($true) {
            $read = $stream.Read($tmp, 0, $tmp.Length)
            if ($read -le 0) { break }
            $buffer.Write($tmp, 0, $read)
        }
        $raw = [Text.Encoding]::UTF8.GetString($buffer.ToArray())
        $headerEnd = $raw.IndexOf("`r`n`r`n")
        if ($headerEnd -lt 0) { return $null }
        $header = $raw.Substring(0, $headerEnd)
        $body = $raw.Substring($headerEnd + 4)
        $statusCode = 0
        $first = ($header -split "`r`n")[0]
        $parts = $first -split " "
        if ($parts.Length -ge 2) { $statusCode = [int]$parts[1] }
        $obj = $body | ConvertFrom-Json
        return [pscustomobject]@{ status_code = $statusCode; payload = $obj }
    } catch {
        return $null
    } finally {
        if ($null -ne $client) { $client.Close() }
    }
}

function Restore-RuntimeBackupFiles([string]$BackupDir, [string]$RuntimeDir) {
    foreach ($name in $RUNTIME_DEPLOY_FILES) {
        $from = Join-Path $BackupDir $name
        $to = Join-Path $RuntimeDir $name
        if (Test-Path -LiteralPath $from) {
            Copy-Item -LiteralPath $from -Destination $to -Force
        }
    }
}

function Invoke-AcceptRuntimeCollector([string]$RuntimeDir, [string]$BackupDir, [int]$OldProcessId, [string]$BeforeHash, [string]$HandoffMode) {
    $started = $null
    $stopped = $false
    $replacementId = 0
    try {
        if ($HandoffMode -eq "DIRECT_START") {
            $started = Start-OneRuntimeCollector $RuntimeDir
            $replacementId = [int]$started.Id
        } else {
            Stop-OneCollectorProcess $OldProcessId
            $stopped = $true
            if ($HandoffMode -eq "DIRECT_RESTART") {
                $started = Start-OneRuntimeCollector $RuntimeDir
                $replacementId = [int]$started.Id
            }
        }
        $deadline = (Get-Date).AddSeconds(90)
        $lastFail = "TIMEOUT"
        $lastPayload = $null
        $expectedBook = Join-Path $RuntimeDir "Kioxia_MS2_RSS_Live_Signals.xlsx"
        while ((Get-Date) -lt $deadline) {
            Start-Sleep -Seconds 2
            if ($HandoffMode -eq "CONTROLLER_RESTARTS") {
                $fresh = @(Get-CollectorProcessIds | Where-Object { [int]$_ -ne $OldProcessId })
                if ($fresh.Count -gt 1) { throw ("COLLECTOR_PROCESS_AFTER=" + ($fresh -join ",")) }
                if ($fresh.Count -eq 1) { $replacementId = [int]$fresh[0] }
                if ($replacementId -eq 0) { $lastFail = "WAITING_FOR_CONTROLLER_RESTART"; continue }
            }
            if (($HandoffMode -eq "DIRECT_RESTART" -or $HandoffMode -eq "DIRECT_START") -and $null -ne $started -and $started.HasExited) {
                $errPath = Join-Path $RuntimeDir "MS2_RSS_100_Collector.acceptance.stderr.log"
                $tail = ""
                if (Test-Path -LiteralPath $errPath) {
                    $tail = [IO.File]::ReadAllText($errPath, [Text.Encoding]::Unicode)
                    if ($tail.Length -gt 400) { $tail = $tail.Substring($tail.Length - 400) }
                }
                throw ("COLLECTOR_EXITED code=" + $started.ExitCode + " " + ($tail -replace "[\r\n]+", " "))
            }
            $live = Receive-CollectorBridge
            if ($null -eq $live) { $lastFail = "PORT_CLOSED"; continue }
            $lastPayload = $live.payload
            $lastFail = Get-RuntimeAcceptanceFailure $live.payload (Test-LocalPreopen) $expectedBook
            if ([string]::IsNullOrWhiteSpace($lastFail)) { break }
        }
        if (-not [string]::IsNullOrWhiteSpace($lastFail)) {
            throw ("RUNTIME_ACCEPTANCE_FAILED " + $lastFail)
        }
        $ids = @(Get-CollectorProcessIds)
        if ($ids.Count -ne 1 -or $replacementId -eq 0 -or [int]$ids[0] -ne $replacementId -or $replacementId -eq $OldProcessId) {
            throw ("COLLECTOR_PROCESS_AFTER=" + ($ids -join ","))
        }
        return $lastPayload
    } catch {
        $acceptError = $_.Exception.Message
        Restore-RuntimeBackupFiles $BackupDir $RuntimeDir
        $restored = ""
        $restoredPath = Join-Path $RuntimeDir "MS2_RSS_100_Collector.ps1"
        if (Test-Path -LiteralPath $restoredPath) { $restored = Get-Sha256Hex $restoredPath }
        if ($restored -ne $BeforeHash) {
            throw ("ROLLBACK_HASH_MISMATCH expected=" + $BeforeHash + " got=" + $restored + " after " + $acceptError)
        }
        if ($null -ne $started) {
            try { Stop-OneCollectorProcess ([int]$started.Id) } catch {}
        } elseif ($replacementId -gt 0 -and $replacementId -ne $OldProcessId) {
            try { Stop-OneCollectorProcess $replacementId } catch {}
        }
        if ($stopped -and $HandoffMode -eq "DIRECT_RESTART") {
            try { Start-OneRuntimeCollector $RuntimeDir | Out-Null } catch {
                throw ("ROLLBACK_RESTART_FAILED " + $_.Exception.Message + " after " + $acceptError)
            }
        } elseif ($stopped -and $HandoffMode -eq "CONTROLLER_RESTARTS") {
            $seenReplacement = $false
            $restartDeadline = (Get-Date).AddSeconds(35)
            while ((Get-Date) -lt $restartDeadline) {
                Start-Sleep -Seconds 2
                $backIds = @(Get-CollectorProcessIds)
                if ($backIds.Count -gt 1) {
                    throw ("ROLLBACK_DUPLICATE collector_count=" + $backIds.Count + " after " + $acceptError)
                }
                if ($backIds.Count -eq 1) { $seenReplacement = $true; break }
            }
            if (-not $seenReplacement) {
                try { Start-OneRuntimeCollector $RuntimeDir | Out-Null } catch {
                    throw ("ROLLBACK_RESTART_FAILED " + $_.Exception.Message + " after " + $acceptError)
                }
            }
        }
        throw ("ROLLBACK=1 backup=" + $BackupDir + " restored_sha256=" + $restored + " " + $acceptError)
    }
}

function Invoke-RuntimeAcceptSelfTest {
    $root = Join-Path ([IO.Path]::GetTempPath()) ("v9-runtime-accept-" + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $root -Force | Out-Null
    try {
        $source = Join-Path $root "source.ps1"
        $dest = Join-Path $root "dest.ps1"
        $good = "function Get-IdentityQuote { }`r`nworkbook_identity_verified`r`n`$script:IdentityTicker = `"285A.T`"`r`n"
        [IO.File]::WriteAllText($source, $good, [Text.UTF8Encoding]::new($false))
        Copy-Item -LiteralPath $source -Destination $dest -Force
        if ((Get-Sha256Hex $source) -ne (Get-Sha256Hex $dest)) { throw "copied hash must match" }
        if ((Get-IdentityRollbackBlock "old collector" $good) -ne "RUNTIME_ROLLBACK_BLOCKED") { throw "old source must not replace identity runtime" }
        if ((Get-IdentityRollbackBlock $good $good) -ne "") { throw "same identity contract must deploy" }
        if ((Get-IdentityRollbackBlock $good "") -ne "") { throw "empty destination must deploy" }
        if ((Get-CollectorHandoffMode 0 1) -ne "DIRECT_RESTART") { throw "no controller must restart the collector directly" }
        if ((Get-CollectorHandoffMode 1 1) -ne "CONTROLLER_RESTARTS") { throw "one controller must restart the collector itself" }
        if ((Get-CollectorHandoffMode 2 1) -ne "REFUSE_CONTROLLER") { throw "two controllers must refuse before copy" }
        if ((Get-CollectorHandoffMode 0 0) -ne "DIRECT_START") { throw "zero collectors with no controller must start one" }
        if ((Get-CollectorHandoffMode 1 0) -ne "REFUSE_COLLECTOR") { throw "a controller with no collector must refuse before copy" }
        $spaced = 'C:\MarketSpeed II RSS\files\MS2_RSS_100_Collector.ps1'
        $quoted = '-File "' + $spaced + '"'
        if ($quoted -ne '-File "C:\MarketSpeed II RSS\files\MS2_RSS_100_Collector.ps1"') { throw "spaced collector path must stay one argument" }
        $starter = [IO.File]::ReadAllText($PSCommandPath)
        $marker = @'
-File "' + $script + '"'
'@
        if ($starter.IndexOf($marker.Trim(), [StringComparison]::Ordinal) -lt 0) { throw "collector start must quote the script path" }
        if ((Get-CollectorHandoffMode 1 2) -ne "REFUSE_COLLECTOR") { throw "two collectors must refuse before copy" }
        if (-not (Test-CollectorCommandLine "powershell.exe -File C:\files\MS2_RSS_100_Collector.ps1")) { throw "collector command must match" }
        if (Test-CollectorCommandLine "powershell.exe -File C:\files\AI_COCKPIT_CONTROLLER_V9.ps1") { throw "controller must not match" }
        if (Test-CollectorCommandLine "C:\Windows\EXCEL.EXE") { throw "excel must not match" }
        if (Test-CollectorCommandLine "powershell.exe -File C:\files\Kioxia_RSS_Live_Watcher.ps1") { throw "watcher must not match" }
        if (Test-CollectorCommandLine "powershell.exe -File C:\files\RUN_AI_COCKPIT_V9.ps1") { throw "runner must not match" }
        $expected = "C:\MarketSpeed II RSS\files\Kioxia_MS2_RSS_Live_Signals.xlsx"
        $preopen = [pscustomobject]@{
            status = "stale"
            reason = "LIVE_VALUES_UNAVAILABLE"
            symbol = "285A.T"
            current_price = 0
            collector_count = 1
            workbook_identity_verified = $true
            workbook_full_name = $expected
            real_submit_allowed = $false
            data_conflict = $false
            source_timestamp = "08:05:53"
        }
        $preopenFail = Get-RuntimeAcceptanceFailure $preopen $true $expected
        if (-not [string]::IsNullOrWhiteSpace($preopenFail)) { throw ("preopen zero price must pass: " + $preopenFail) }
        if ((Get-RuntimeAcceptanceFailure $preopen $false $expected).IndexOf("PRICE") -lt 0) { throw "session zero price must fail" }
        $wrong = [pscustomobject]@{
            status = "PRICE_SOURCE_MISMATCH"
            reason = "WRONG_SOURCE_WORKBOOK"
            symbol = "8035.T"
            current_price = 12100
            collector_count = 1
            workbook_identity_verified = $false
            workbook_full_name = $expected
            real_submit_allowed = $false
            data_conflict = $true
            source_timestamp = "08:05:53"
        }
        $wrongFail = Get-RuntimeAcceptanceFailure $wrong $true $expected
        if ($wrongFail.IndexOf("SYMBOL") -lt 0 -or $wrongFail.IndexOf("WRONG_SOURCE_WORKBOOK") -lt 0) { throw "8035 must fail during preopen" }
        $stale = [pscustomobject]@{
            status = "stale"
            reason = "STALE_OR_MISSING_TIMESTAMP,LIVE_VALUES_UNAVAILABLE"
            symbol = "285A.T"
            current_price = 0
            collector_count = 1
            workbook_identity_verified = $true
            workbook_full_name = $expected
            real_submit_allowed = $false
            data_conflict = $false
            source_timestamp = "08:05:53"
        }
        if ((Get-RuntimeAcceptanceFailure $stale $true $expected).IndexOf("STALE_OR_MISSING_TIMESTAMP") -lt 0) { throw "stale file must fail during preopen" }
        $duplicate = [pscustomobject]@{
            symbol = "285A.T"
            current_price = 100
            collector_count = 2
            workbook_identity_verified = $true
            workbook_full_name = $expected
            real_submit_allowed = $false
            data_conflict = $false
            source_timestamp = "09:01:00"
        }
        if ((Get-RuntimeAcceptanceFailure $duplicate $false $expected).IndexOf("COLLECTOR_COUNT") -lt 0) { throw "two collectors must fail" }
        $submit = [pscustomobject]@{
            symbol = "285A.T"
            current_price = 100
            collector_count = 1
            workbook_identity_verified = $true
            workbook_full_name = $expected
            real_submit_allowed = $true
            data_conflict = $false
            source_timestamp = "09:01:00"
        }
        if ((Get-RuntimeAcceptanceFailure $submit $false $expected).IndexOf("REAL_SUBMIT") -lt 0) { throw "real submit must fail" }
        $nested = [pscustomobject]@{
            live_price_diagnostics = [pscustomobject]@{
                symbol = "285A.T"
                current_price = 100
                collector_count = 1
                workbook_identity_verified = $true
                workbook_full_name = $expected
                real_submit_allowed = $false
                source_timestamp = "09:01:00"
            }
            data_conflict = $false
            real_submit_allowed = $false
        }
        $nestedFail = Get-RuntimeAcceptanceFailure $nested $false $expected
        if (-not [string]::IsNullOrWhiteSpace($nestedFail)) { throw ("nested diagnostics must pass: " + $nestedFail) }
        Write-Output "RUNTIME_ACCEPT_SELFTEST PASS"
        Write-Output "PINNED_B81B887_COLLECTOR_SHA256=510ACF2E8F962A9B9D7AA2777955E60DC2247C34C232EFBE9F50CCFFAB7C424F"
    } finally {
        Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
    }
}

if ($RuntimeAcceptSelfTest) {
    Invoke-RuntimeAcceptSelfTest
    exit 0
}

$repo = Resolve-RepoRoot
Write-Host "==================================================" -ForegroundColor DarkCyan
Write-Host " AI COCKPIT V9 - update + backup + start" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor DarkCyan
Write-Host ("Repo:   " + $repo) -ForegroundColor Cyan
Write-Host ("Branch: " + $Branch) -ForegroundColor Cyan
Write-Host ("State:  " + $Root) -ForegroundColor Cyan
if (-not [string]::IsNullOrWhiteSpace($RuntimeDirOverride)) {
    Write-Host ("Runtime override: " + $RuntimeDirOverride) -ForegroundColor Cyan
}
if (-not [string]::IsNullOrWhiteSpace($ExpectedSha)) {
    Write-Host ("Pinned SHA: " + $ExpectedSha) -ForegroundColor Cyan
}

try {
    if ($DeployRuntimeOnly -and [string]::IsNullOrWhiteSpace($ExpectedSha)) {
        throw "DeployRuntimeOnly requires -ExpectedSha. Refusing to copy an unpinned checkout into RuntimeDir."
    }
    if ($AcceptRuntimeCollector -and [string]::IsNullOrWhiteSpace($ExpectedSha)) {
        throw "AcceptRuntimeCollector requires -ExpectedSha. Refusing to copy an unpinned checkout into RuntimeDir."
    }
    if (-not $SkipGitUpdate) {
        Write-Host ("Updating checkout: fetching origin/" + $Branch + "...") -ForegroundColor Yellow
        Invoke-GitFatal $repo @("fetch", "origin", $Branch, "--quiet") "git fetch failed - refusing to start with a possibly-stale or partial checkout" | Out-Null
        $targetRev = if (-not [string]::IsNullOrWhiteSpace($ExpectedSha)) { $ExpectedSha } else { "origin/" + $Branch }
        $targetCollector = Invoke-GitFatal $repo @("show", ($targetRev + ":ms2_live/MS2_RSS_100_Collector.ps1")) "could not read the target collector before checkout"
        $runtimeDirForGuard = Resolve-RuntimeDirForDeploy $RuntimeDirOverride
        $runtimeCollectorPath = Join-Path $runtimeDirForGuard "MS2_RSS_100_Collector.ps1"
        $runtimeText = ""
        if (Test-Path -LiteralPath $runtimeCollectorPath) {
            $runtimeText = [IO.File]::ReadAllText($runtimeCollectorPath, [Text.Encoding]::UTF8)
        }
        $earlyBlock = Get-IdentityRollbackBlock ($targetCollector -join "`n") $runtimeText
        if (-not [string]::IsNullOrWhiteSpace($earlyBlock)) {
            throw "RUNTIME_ROLLBACK_BLOCKED: origin/$Branch would replace the 285A workbook-identity Collector already in RuntimeDir. Checkout was not changed. Runtime files were not replaced. Excel, MS2, Collector, and Controller were not touched."
        }
        Invoke-GitFatal $repo @("checkout", "-B", $Branch, ("origin/" + $Branch), "--quiet") "git checkout failed" | Out-Null
        Invoke-GitFatal $repo @("reset", "--hard", ("origin/" + $Branch), "--quiet") "git reset --hard failed" | Out-Null
        if (-not [string]::IsNullOrWhiteSpace($ExpectedSha)) {
            Invoke-GitFatal $repo @("reset", "--hard", $ExpectedSha, "--quiet") "git reset to ExpectedSha failed" | Out-Null
        }
    } else {
        Write-Host "Skipping git update (-SkipGitUpdate) - using whatever is already checked out." -ForegroundColor DarkGray
    }

    $actualBranch = (Invoke-GitFatal $repo @("rev-parse", "--abbrev-ref", "HEAD") "could not read the current branch after update").Trim()
    $actualSha = (Invoke-GitFatal $repo @("rev-parse", "HEAD") "could not read the current commit after update").Trim()
    Write-Host ("Now on " + $actualBranch + " @ " + $actualSha.Substring(0, 8)) -ForegroundColor Green

    if (-not $SkipGitUpdate -and $actualBranch -ne $Branch) {
        throw "Branch mismatch after checkout: expected '$Branch', got '$actualBranch'. Refusing to start Controller against an unexpected branch."
    }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedSha) -and -not $actualSha.StartsWith($ExpectedSha)) {
        throw "SHA mismatch after checkout: expected '$ExpectedSha', got '$actualSha'. Refusing to start Controller against an unverified commit."
    }

    Write-Host ""
    Write-Host "Deploying runtime scripts (Watcher/Heartbeat/Collector) to RuntimeDir..." -ForegroundColor Yellow
    $runtimeDirForDeploy = Resolve-RuntimeDirForDeploy $RuntimeDirOverride
    Write-Host ("  RuntimeDir: " + $runtimeDirForDeploy) -ForegroundColor Cyan
    Write-Host ("  RUNTIME_DIR_CODEPOINTS=" + (Format-PathCodePoints $runtimeDirForDeploy)) -ForegroundColor Cyan
    $collectorBefore = Join-Path $runtimeDirForDeploy "MS2_RSS_100_Collector.ps1"
    $collectorBeforeHash = ""
    if (Test-Path -LiteralPath $collectorBefore) { $collectorBeforeHash = Get-Sha256Hex $collectorBefore }
    Write-Host ("  COLLECTOR_BEFORE_SHA256=" + $collectorBeforeHash) -ForegroundColor Cyan
    $collectorSource = Join-Path $repo "ms2_live\MS2_RSS_100_Collector.ps1"
    $collectorText = [IO.File]::ReadAllText($collectorSource, [Text.Encoding]::UTF8)
    $destinationText = ""
    if (Test-Path -LiteralPath $collectorBefore) {
        $destinationText = [IO.File]::ReadAllText($collectorBefore, [Text.Encoding]::UTF8)
    }
    $rollbackBlock = Get-IdentityRollbackBlock $collectorText $destinationText
    if (-not [string]::IsNullOrWhiteSpace($rollbackBlock)) {
        throw "RUNTIME_ROLLBACK_BLOCKED: the runtime Collector already publishes 285A workbook identity and this checkout does not. Runtime files were not replaced. Excel, MS2, Collector, and Controller were not touched."
    }
    if (($DeployRuntimeOnly -or $AcceptRuntimeCollector) -and -not (Test-CollectorIdentityContract $collectorText)) {
        throw "Refusing to deploy a collector that does not publish the 285A workbook identity quote."
    }
    $oldCollectorId = 0
    $handoff = "DIRECT_RESTART"
    if ($AcceptRuntimeCollector) {
        $collectorIds = @(Get-CollectorProcessIds)
        $controllerCount = Get-ControllerProcessCount
        Write-Host ("  COLLECTOR_PROCESS_BEFORE=" + $collectorIds.Count) -ForegroundColor Cyan
        Write-Host ("  CONTROLLER_PROCESS_BEFORE=" + $controllerCount) -ForegroundColor Cyan
        $handoff = Get-CollectorHandoffMode $controllerCount $collectorIds.Count
        Write-Host ("  HANDOFF=" + $handoff) -ForegroundColor Cyan
        if ($handoff -eq "REFUSE_CONTROLLER") {
            throw ("CONTROLLER_PROCESS_BEFORE=" + $controllerCount + ". Expected 0 or 1. No files were copied. Excel, MS2, and Collector were not touched.")
        }
        if ($handoff -eq "REFUSE_COLLECTOR") {
            throw ("COLLECTOR_PROCESS_BEFORE=" + $collectorIds.Count + ". Expected exactly one Collector. No files were copied. Excel, MS2, and Controller were not touched.")
        }
        $oldCollectorId = 0
        if ($handoff -ne "DIRECT_START") { $oldCollectorId = [int]$collectorIds[0] }
    }
    $deployResult = Deploy-RuntimeFiles -RepoRoot $repo -RuntimeDir $runtimeDirForDeploy
    Write-Host ("  Deployed " + $RUNTIME_DEPLOY_FILES.Count + " files, backup: " + $deployResult.backup_dir) -ForegroundColor Green

    $runtimeManifestRoot = $Root
    if (-not (Test-Path -LiteralPath $runtimeManifestRoot)) { New-Item -ItemType Directory -Path $runtimeManifestRoot -Force | Out-Null }
    $runtimeManifest = [ordered]@{
        repo_sha    = $actualSha
        repo_branch = $actualBranch
        runtime_dir = $runtimeDirForDeploy
        files       = $deployResult.hashes
        deployed_at = (Get-Date).ToString("o")
    }
    $runtimeManifestPath = Join-Path $runtimeManifestRoot "V9_RUNTIME.json"
    [IO.File]::WriteAllText($runtimeManifestPath, ($runtimeManifest | ConvertTo-Json -Depth 6), [Text.UTF8Encoding]::new($false))
    Write-Host ("  Runtime manifest written: " + $runtimeManifestPath) -ForegroundColor Green
    $collectorAfterHash = Get-Sha256Hex (Join-Path $runtimeDirForDeploy "MS2_RSS_100_Collector.ps1")
    $sourceHash = Get-Sha256Hex $collectorSource
    if ($collectorAfterHash -ne $sourceHash) {
        Restore-RuntimeBackupFiles ([string]$deployResult.backup_dir) $runtimeDirForDeploy
        throw ("RUNTIME_SHA256_MISMATCH repo=" + $sourceHash + " runtime=" + $collectorAfterHash)
    }
    Write-Host ("  COLLECTOR_AFTER_SHA256=" + $collectorAfterHash) -ForegroundColor Green
    Write-Host "  RUNTIME_SHA256_MATCH=1" -ForegroundColor Green
    Write-Host ("  REPO_SHA=" + $actualSha) -ForegroundColor Green
    if ($AcceptRuntimeCollector) {
        $accepted = Invoke-AcceptRuntimeCollector $runtimeDirForDeploy ([string]$deployResult.backup_dir) $oldCollectorId $collectorBeforeHash $handoff
        $diag = $null
        try { $diag = $accepted.live_price_diagnostics } catch { $diag = $null }
        $symbol = [string]$accepted.symbol
        if ([string]::IsNullOrWhiteSpace($symbol) -and $null -ne $diag) { $symbol = [string]$diag.symbol }
        $price = $accepted.current_price
        if ($null -eq $price -and $null -ne $diag) { $price = $diag.current_price }
        $count = $accepted.collector_count
        if ($null -eq $count -and $null -ne $diag) { $count = $diag.collector_count }
        Write-Host "RUNTIME_ACCEPTANCE=PASS" -ForegroundColor Green
        Write-Host ("SYMBOL=" + $symbol) -ForegroundColor Green
        Write-Host ("CURRENT_PRICE=" + $price) -ForegroundColor Green
        Write-Host ("COLLECTOR_COUNT=" + $count) -ForegroundColor Green
        Write-Host "WORKBOOK_IDENTITY_VERIFIED=1" -ForegroundColor Green
        Write-Host ("PREOPEN=" + [int](Test-LocalPreopen)) -ForegroundColor Green
        Write-Host "REAL_SUBMIT_ALLOWED=0" -ForegroundColor Green
        Write-Host "EXCEL_TOUCHED=0" -ForegroundColor Green
        Write-Host "MS2_TOUCHED=0" -ForegroundColor Green
        Write-Host "CONTROLLER_STOPPED=0" -ForegroundColor Green
        Write-Host "CONTROLLER_STARTED=0" -ForegroundColor Green
        Write-Host "ROLLBACK=0" -ForegroundColor Green
        Write-Host ("BACKUP=" + $deployResult.backup_dir) -ForegroundColor Green
        Write-Host ("COLLECTOR_RUNTIME_SHA256=" + $collectorAfterHash) -ForegroundColor Green
        Write-Host ("REPO_SHA=" + $actualSha) -ForegroundColor Green
        Write-Host ""
        Read-Host "Press Enter to close"
        exit 0
    }
} catch {
    Write-Host ""
    Write-Host "==================================================" -ForegroundColor Red
    Write-Host " UPDATE/DEPLOY FAILED - CONTROLLER NOT STARTED (fail-closed)" -ForegroundColor Red
    Write-Host "==================================================" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Press Enter to close"
    [Environment]::Exit(1)
}

if ($DeployRuntimeOnly) {
    Write-Host "DEPLOY_RUNTIME_ONLY=1" -ForegroundColor Green
    Write-Host "EXCEL_TOUCHED=0" -ForegroundColor Green
    Write-Host "COLLECTOR_PROCESS_STOPPED=0" -ForegroundColor Green
    Write-Host "CONTROLLER_STARTED=0" -ForegroundColor Green
    Write-Host "REAL_SUBMIT_ALLOWED=0" -ForegroundColor Green
    Write-Host "The running Collector process keeps the code it already loaded. This copy does not restart it." -ForegroundColor Yellow
    exit 0
}

$root = $Root
$logDir = Join-Path $root "Logs\V9"
if (Test-Path -LiteralPath $logDir) {
    $backupDir = Join-Path $root ("Logs\V9_backup_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
    Write-Host ("Backing up previous logs to: " + $backupDir) -ForegroundColor Yellow
    Move-Item -LiteralPath $logDir -Destination $backupDir -Force -ErrorAction SilentlyContinue
}
$stateFile = Join-Path $root "V9_CONTROLLER_STATE.json"
if (Test-Path -LiteralPath $stateFile) {
    $stateBackup = Join-Path $root ("V9_CONTROLLER_STATE_backup_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".json")
    Copy-Item -LiteralPath $stateFile -Destination $stateBackup -Force -ErrorAction SilentlyContinue
}

Write-Host "Starting Controller V9..." -ForegroundColor Cyan
Write-Host ""

# Start Controller in its own process so RUN can continue to the Brain lane.
# This preserves the persistent Controller while keeping startup orchestration
# in this canonical RUN entrypoint.
$psExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$controllerScript = Join-Path $repo "downloads\AI_COCKPIT_CONTROLLER_V9.ps1"
$controllerArgs = '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "' + $controllerScript +
    '" -RepoRoot "' + $repo +
    '" -ExpectedBranch "' + $Branch +
    '" -RuntimeDirOverride "' + $runtimeDirForDeploy +
    '" -Root "' + $Root + '"'
$controllerProcess = Start-Process -FilePath $psExe -ArgumentList $controllerArgs -PassThru
Write-Host ("  Controller PID=" + $controllerProcess.Id) -ForegroundColor Cyan

function Test-AiCockpitLoopbackPort([int]$Port,[int]$TimeoutMs=400) {
    $client = New-Object Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect("127.0.0.1",$Port,$null,$null)
        if (-not $async.AsyncWaitHandle.WaitOne($TimeoutMs,$false)) { return $false }
        $client.EndConnect($async)
        return $true
    } catch {
        return $false
    } finally {
        try { $client.Close() } catch {}
    }
}

function Wait-AiCockpitLoopbackPort([int]$Port,[int]$Seconds) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-AiCockpitLoopbackPort $Port 400) { return $true }
        if ($controllerProcess.HasExited) {
            throw ("CONTROLLER_EXITED_BEFORE_PORT_" + $Port + " code=" + $controllerProcess.ExitCode)
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

foreach ($port in 28580,28581,28582,28583) {
    if (-not (Wait-AiCockpitLoopbackPort $port 75)) {
        throw ("PORT_TIMEOUT_" + $port)
    }
    Write-Host ("  Port " + $port + " READY") -ForegroundColor Green
}

# Brain lane: same current checkout, same runtime, no second worktree and no git mutation.
if (-not (Test-AiCockpitLoopbackPort 28584 500)) {
    $brainGateway = Join-Path $repo "downloads\AI_COCKPIT_GATEWAY_V9.ps1"
    if (-not (Test-Path -LiteralPath $brainGateway -PathType Leaf)) {
        throw "BRAIN_GATEWAY_SCRIPT_NOT_FOUND"
    }
    $brainArgs = '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "' + $brainGateway +
        '" -RepoRoot "' + $repo +
        '" -RuntimeDir "' + $runtimeDirForDeploy +
        '" -Build "V9-BRAIN-CURRENT" -Port 28584'
    Start-Process -FilePath $psExe -ArgumentList $brainArgs | Out-Null
    if (-not (Wait-AiCockpitLoopbackPort 28584 20)) {
        throw "BRAIN_GATEWAY_28584_TIMEOUT"
    }
}
Write-Host "  Port 28584 READY (Brain Gateway)" -ForegroundColor Green
Start-Process "http://127.0.0.1:28584/?brain=1"
