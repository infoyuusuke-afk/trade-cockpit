#requires -Version 5.1
<#
Canonical V10-only admission and launch entry.
Always invokes the separate immutable-source verifier FIRST. Then verifies
the release bundle before allowing the reviewed V10 RUN entry to execute.
Does not auto-create an approval pin or repair/download/checkout any source.
This Draft is NOT approval to deploy or start the Owner's Windows runtime.
#>
[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [string]$ApprovalFile = "",
    [switch]$VerifyOnly
)
$ErrorActionPreference = "Stop"
$runtimeInvoked = $false

try {
    if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
        $RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
    }
    if (-not (Test-Path -LiteralPath $RepoRoot -PathType Container)) {
        throw "V10_RELEASE_REPO_MISSING"
    }
    $repo = [IO.Path]::GetFullPath($RepoRoot)
    $repoItem = Get-Item -LiteralPath $repo -ErrorAction Stop
    if (($repoItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "V10_RELEASE_ROOT_LINK_REFUSED"
    }
    if ([string]::IsNullOrWhiteSpace($ApprovalFile)) {
        $ApprovalFile = Join-Path $repo "downloads\V10_APPROVED_SOURCE.json"
    }
    $verifier = Join-Path $repo "downloads\VERIFY_V10_SOURCE_PIN_READONLY.ps1"
    if (-not (Test-Path -LiteralPath $verifier -PathType Leaf)) {
        throw "V10_SOURCE_VERIFIER_MISSING"
    }
    $verifierItem = Get-Item -LiteralPath $verifier -ErrorAction Stop
    if (($verifierItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "V10_SOURCE_VERIFIER_LINK_REFUSED"
    }

    # Independent read-only gate; no component discovery, staging or process
    # startup may occur before this child process confirms source identity.
    $verificationOutput = @(& powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $verifier -RepoRoot $repo -ApprovalFile $ApprovalFile 2>&1)
    $verificationCode = $LASTEXITCODE
    foreach ($line in $verificationOutput) { Write-Output ([string]$line) }
    $passes = @($verificationOutput | Where-Object {
        [string]$_ -ceq "V10_READONLY_SOURCE=PASS"
    })
    if ($verificationCode -ne 0 -or $passes.Count -ne 1) {
        throw "V10_SOURCE_ADMISSION_FAILED"
    }

    # Hard required components, not silently fetched from other folders.
    # Presence alone does NOT certify a deployable runtime; all components
    # must belong to this same SHA-verified clean Git checkout.
    $required = @(
        "downloads/RUN_AI_COCKPIT_V10.ps1",
        "downloads/AI_COCKPIT_CONTROLLER_V10.ps1",
        "downloads/AI_COCKPIT_GATEWAY_V10.ps1",
        "downloads/AI_COCKPIT_VOICE_BRIDGE_V10.ps1",
        "downloads/STOP_AI_COCKPIT_V10.ps1",
        "downloads/AI_COCKPIT_V10_BRAIN_PREFLIGHT.ps1",
        "scripts/ai_shadow_supervisor.py",
        "scripts/ai_brain_observer.py",
        "ms2_live/Kioxia_RSS_Live_Watcher.ps1",
        "ms2_live/Kioxia_Safety_Heartbeat.ps1",
        "ms2_live/MS2_RSS_100_Collector.ps1",
        "ms2_live/MS2_Common_Engine.ps1",
        "ms2_live/BUILD_KIOXIA_TIME_STATS.ps1",
        "ms2_live/SPEAK_TODAY_STRATEGY.ps1",
        "ms2_live/SPEAK_LIVE_EMOTION.ps1",
        "index.html",
        "card_system.js",
        "card_system.css",
        "card_table_adapter.css",
        "voice_client.js",
        "opportunity_radar.js",
        "card_table_adapter.js",
        "trade_control.js",
        "v10_publication_status.js",
        "theme.css",
        "focus.css",
        "next-theme-radar.css",
        "next-theme-radar.js",
        "earnings-calendar.js"
    )
    foreach ($relative in $required) {
        $full = [IO.Path]::GetFullPath((Join-Path $repo $relative))
        if (-not (Test-Path -LiteralPath $full -PathType Leaf)) {
            throw ("V10_RELEASE_COMPONENT_MISSING: " + $relative)
        }
        $item = Get-Item -LiteralPath $full -ErrorAction Stop
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw ("V10_RELEASE_COMPONENT_LINK_REFUSED: " + $relative)
        }
        if ($item.Length -le 0) {
            throw ("V10_RELEASE_COMPONENT_EMPTY: " + $relative)
        }
    }
    # A clean checkout is necessary but does not prove that every runtime
    # component came from the same V10 release candidate. Check Git blob
    # identities against an explicit tracked manifest, fail closed on mix.
    # The manifest records candidate evidence; NOT an Owner approval.
    $manifestPath = Join-Path $repo "downloads\V10_RELEASE_BUNDLE_MANIFEST.json"
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "V10_RELEASE_MANIFEST_MISSING"
    }
    $manifestItem = Get-Item -LiteralPath $manifestPath -ErrorAction Stop
    if (($manifestItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
        $manifestItem.Length -le 2 -or $manifestItem.Length -gt 8192) {
        throw "V10_RELEASE_MANIFEST_UNTRUSTED"
    }
    $manifest = [IO.File]::ReadAllText($manifestPath, [Text.Encoding]::UTF8) |
        ConvertFrom-Json -ErrorAction Stop
    if ($null -eq $manifest -or $manifest -isnot [pscustomobject] -or
        $manifest.PSObject.Properties.Name.Count -ne 4 -or
        [string]$manifest.schema -cne "v10_release_candidate_blobs_v1" -or
        [string]$manifest.candidate_source_commit -cnotmatch '^[0-9a-fA-F]{40}$' -or
        $manifest.files -isnot [array]) {
        throw "V10_RELEASE_MANIFEST_SCHEMA_INVALID"
    }
    if ($manifest.PSObject.Properties.Name -notcontains "real_submit_allowed" -or
        $manifest.real_submit_allowed -isnot [bool] -or
        $manifest.real_submit_allowed) {
        throw "V10_RELEASE_MANIFEST_REAL_SUBMIT_MUST_BE_FALSE"
    }
    $records = @($manifest.files)
    if ($records.Count -ne $required.Count) {
        throw "V10_RELEASE_MANIFEST_FILE_COUNT_MISMATCH"
    }
    $pinned = @{}
    foreach ($record in $records) {
        if ($null -eq $record -or $record -isnot [pscustomobject] -or
            $record.PSObject.Properties.Name.Count -ne 2 -or
            $record.PSObject.Properties.Name -notcontains "path" -or
            $record.PSObject.Properties.Name -notcontains "git_blob_sha") {
            throw "V10_RELEASE_MANIFEST_FILE_SCHEMA_INVALID"
        }
        $name = [string]$record.path
        $blob = [string]$record.git_blob_sha
        if ($required -cnotcontains $name -or $pinned.ContainsKey($name) -or
            $blob -cnotmatch '^[0-9a-fA-F]{40}$') {
            throw "V10_RELEASE_MANIFEST_FILE_INVALID"
        }
        $pinned[$name] = $blob
    }
    foreach ($relative in $required) {
        $actualBlob = & git --no-optional-locks -C $repo rev-parse ("HEAD:" + $relative) 2>&1
        if ($LASTEXITCODE -ne 0 -or
            -not [string]::Equals(([string]$actualBlob).Trim(),
                [string]$pinned[$relative], [StringComparison]::OrdinalIgnoreCase)) {
            throw ("V10_RELEASE_SOURCE_BLOB_MISMATCH: " + $relative)
        }
    }
    Write-Output "V10_RELEASE_SOURCE_BLOBS_MATCH=29"
    $runner = Join-Path $repo "downloads\RUN_AI_COCKPIT_V10.ps1"
    # Fail closed on a stale V10 RUN that lacks the reviewed admission gate.
    $runnerSource = [IO.File]::ReadAllText($runner, [Text.Encoding]::UTF8)
    foreach ($contract in @(
        'V10_MUTATING_START_REQUIRES_APPROVAL_FILE',
        'PINNED_SHA_MUST_BE_FULL_40_HEX',
        'V10_WORKTREE_NOT_CLEAN',
        'REAL_SUBMIT_ALLOWED=0'
    )) {
        if (-not $runnerSource.Contains($contract)) {
            throw "V10_RUNNER_APPROVAL_CONTRACT_MISSING"
        }
    }
    Write-Output "V10_RELEASE_COMPONENTS_PRESENT=1"
    Write-Output "REAL_SUBMIT_ALLOWED=0"
    if ($VerifyOnly) {
        Write-Output "V10_START_PREFLIGHT=PASS_NO_RUNTIME"
        Write-Output "CONTROLLER_STARTED=0"
        Write-Output "RUNTIME_FILES_TOUCHED=0"
        exit 0
    }

    # This call only becomes reachable when a future explicitly approved
    # release includes the complete immutable V10 runtime in the same repo.
    # RUN retains its OWN approval/SHA/git-clean fail-closed checks.
    Write-Output "V10_REVIEWED_RUNNER_HANDOFF=1"
    $runtimeInvoked = $true
    & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $runner -RepoRoot $repo -ApprovalFile $ApprovalFile
    $runnerExit = $LASTEXITCODE
    if ($runnerExit -ne 0) {
        throw "V10_RUNNER_EXIT_FAILURE"
    }
    exit 0
} catch {
    $reason = [string]$_.Exception.Message
    if (-not $reason.StartsWith("V10_", [StringComparison]::Ordinal)) {
        $reason = "V10_START_UNVERIFIED_FAILURE"
    }
    Write-Output "V10_START=BLOCKED"
    Write-Output $reason
    if (-not $runtimeInvoked) {
        Write-Output "CONTROLLER_STARTED=0"
        Write-Output "RUNTIME_FILES_TOUCHED=0"
    } else {
        Write-Output "RUNTIME_STATE=UNKNOWN_AFTER_RUNNER"
    }
    Write-Output "REAL_SUBMIT_ALLOWED=0"
    exit 2
}
