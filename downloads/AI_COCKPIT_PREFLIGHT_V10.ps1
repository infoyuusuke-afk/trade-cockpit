param(
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [string]$Root = "C:\AI_Cockpit_OneClick_Starter",
    [Parameter(Mandatory = $true)][string]$OutputPath,
    [switch]$SelfTest
)

$ErrorActionPreference = "Stop"

function Read-JsonUtf8([string]$Path) {
    return ([IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8) | ConvertFrom-Json)
}

function Get-SafeProperty($Object, [string]$Name, $Default = $null) {
    if ($null -eq $Object) { return $Default }
    if ($Object -is [Collections.IDictionary] -and $Object.Contains($Name)) {
        return $Object[$Name]
    }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $Default }
    return $property.Value
}

function Get-RepoIdentity([string]$Path) {
    $sha = ""
    $branch = ""
    try {
        $sha = (& git -C $Path rev-parse HEAD 2>$null).Trim()
        if ($LASTEXITCODE -ne 0) { $sha = "" }
        $branch = (& git -C $Path rev-parse --abbrev-ref HEAD 2>$null).Trim()
        if ($LASTEXITCODE -ne 0) { $branch = "" }
    } catch {
        $sha = ""
        $branch = ""
    }
    return [ordered]@{ sha=$sha; branch=$branch }
}

function Get-ManifestRepoHash($Manifest, [string]$RelativePath) {
    try {
        $identity = Get-SafeProperty $Manifest "identity_diagnostics"
        $artifacts = Get-SafeProperty $identity "repo_artifacts"
        $entry = Get-SafeProperty $artifacts $RelativePath
        return [string](Get-SafeProperty $entry "source_raw_sha256" "")
    } catch {
        return ""
    }
}

function New-SanitizedPreflight([string]$ResolvedRepoRoot, [string]$ResolvedRoot) {
    $manifest = $null
    $state = $null
    $reasons = New-Object System.Collections.Generic.List[string]
    try {
        $manifestPath = Join-Path $ResolvedRoot "V10_RUNTIME.json"
        if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
            $manifest = Read-JsonUtf8 $manifestPath
        } else {
            [void]$reasons.Add("MANIFEST_MISSING")
        }
    } catch {
        [void]$reasons.Add("MANIFEST_INVALID")
    }
    try {
        $statePath = Join-Path $ResolvedRoot "V10_CONTROLLER_STATE.json"
        if (Test-Path -LiteralPath $statePath -PathType Leaf) {
            $state = Read-JsonUtf8 $statePath
        } else {
            [void]$reasons.Add("STATE_MISSING")
        }
    } catch {
        [void]$reasons.Add("STATE_INVALID")
    }

    $repo = Get-RepoIdentity $ResolvedRepoRoot
    if ([string]::IsNullOrWhiteSpace([string]$repo.sha)) { [void]$reasons.Add("REPO_SHA_UNKNOWN") }
    $manifestSha = [string](Get-SafeProperty $manifest "repo_sha" "")
    $manifestBranch = [string](Get-SafeProperty $manifest "repo_branch" "")
    $shaMatch = (
        -not [string]::IsNullOrWhiteSpace($manifestSha) -and
        -not [string]::IsNullOrWhiteSpace([string]$repo.sha) -and
        $manifestSha -eq [string]$repo.sha
    )
    if (-not $shaMatch) { [void]$reasons.Add("DEPLOYED_SHA_UNVERIFIED") }

    $artifacts = [ordered]@{}
    foreach ($relativePath in @(
        "downloads/RUN_AI_COCKPIT_V10.ps1",
        "downloads/AI_COCKPIT_CONTROLLER_V10.ps1",
        "downloads/AI_COCKPIT_GATEWAY_V10.ps1"
    )) {
        $fullPath = Join-Path $ResolvedRepoRoot $relativePath.Replace("/", "\")
        $actual = ""
        try {
            if (Test-Path -LiteralPath $fullPath -PathType Leaf) {
                $actual = (Get-FileHash -LiteralPath $fullPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
            }
        } catch {}
        $expected = Get-ManifestRepoHash $manifest $relativePath
        $status = if ([string]::IsNullOrWhiteSpace($actual) -or [string]::IsNullOrWhiteSpace($expected)) {
            "UNKNOWN"
        } elseif ($actual -eq $expected) {
            "VERIFIED"
        } else {
            "FAIL"
        }
        if ($status -ne "VERIFIED") { [void]$reasons.Add("ARTIFACT_IDENTITY_" + $status) }
        $artifacts[$relativePath] = [ordered]@{
            actual_raw_sha256 = if ([string]::IsNullOrWhiteSpace($actual)) { $null } else { $actual }
            manifest_raw_sha256 = if ([string]::IsNullOrWhiteSpace($expected)) { $null } else { $expected }
            status = $status
        }
    }

    $identity = Get-SafeProperty $state "identity_diagnostics"
    $controllerOverall = [string](Get-SafeProperty $identity "overall" "UNKNOWN")
    if ($controllerOverall -eq "FAIL") {
        [void]$reasons.Add("CONTROLLER_IDENTITY_FAIL")
    } elseif ($controllerOverall -ne "VERIFIED") {
        [void]$reasons.Add("CONTROLLER_IDENTITY_UNKNOWN")
    }
    $ports = [ordered]@{}
    $statePorts = Get-SafeProperty $identity "ports"
    $hasPortFail = $false
    foreach ($port in 28580..28584) {
        $entry = Get-SafeProperty $statePorts ([string]$port)
        $ownerPids = @(Get-SafeProperty $entry "owner_pids" @())
        $portStatus = [string](Get-SafeProperty $entry "status" "UNKNOWN")
        if ($portStatus -eq "FAIL") {
            $hasPortFail = $true
            [void]$reasons.Add("PORT_IDENTITY_FAIL")
        } elseif ($portStatus -notin @("VERIFIED", "VERIFIED_BRIDGE_CHILD")) {
            [void]$reasons.Add("PORT_IDENTITY_UNKNOWN")
        }
        $ports[[string]$port] = [ordered]@{
            status = $portStatus
            owner_count = $ownerPids.Count
            loopback_only = Get-SafeProperty $entry "loopback_only"
        }
    }
    $ui = Get-SafeProperty $identity "ui"
    $baselineId = Get-SafeProperty $ui "baseline_id"
    $baselineStatus = [string](Get-SafeProperty $ui "baseline_status" "UNKNOWN")
    if ([string]::IsNullOrWhiteSpace([string]$baselineId) -or $baselineStatus -ne "VERIFIED") {
        [void]$reasons.Add("UI_BASELINE_UNVERIFIED")
    }

    $hasFail = (
        @($artifacts.Values | Where-Object { $_.status -eq "FAIL" }).Count -gt 0 -or
        $controllerOverall -eq "FAIL" -or
        $hasPortFail -or
        $baselineStatus -eq "FAIL"
    )
    $overall = if ($hasFail) { "FAIL" } elseif ($reasons.Count -gt 0) { "UNKNOWN" } else { "VERIFIED" }
    return [ordered]@{
        schema_version = "v10-sanitized-preflight-1"
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        overall = $overall
        reason_codes = @($reasons | Select-Object -Unique)
        deployment = [ordered]@{
            manifest_repo_sha = if ([string]::IsNullOrWhiteSpace($manifestSha)) { $null } else { $manifestSha }
            manifest_repo_branch = if ([string]::IsNullOrWhiteSpace($manifestBranch)) { $null } else { $manifestBranch }
            checkout_repo_sha = if ([string]::IsNullOrWhiteSpace([string]$repo.sha)) { $null } else { [string]$repo.sha }
            checkout_repo_branch = if ([string]::IsNullOrWhiteSpace([string]$repo.branch)) { $null } else { [string]$repo.branch }
            sha_match = $shaMatch
        }
        artifacts = $artifacts
        controller_identity = [ordered]@{
            schema_version = [string](Get-SafeProperty $identity "schema_version" "")
            overall = $controllerOverall
            checked_at = Get-SafeProperty $identity "checked_at"
        }
        ports = $ports
        ui = [ordered]@{
            baseline_id = $baselineId
            baseline_status = $baselineStatus
        }
        privacy = [ordered]@{
            absolute_paths_omitted = $true
            usernames_omitted = $true
            command_lines_omitted = $true
            workbook_data_omitted = $true
            account_order_data_omitted = $true
        }
    }
}

function Write-PreflightOutput($Evidence, [string]$Path) {
    $parent = Split-Path -Parent $Path
    if (-not [string]::IsNullOrWhiteSpace($parent) -and
        -not (Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $tmp = $Path + "." + $PID + ".tmp"
    [IO.File]::WriteAllText($tmp, ($Evidence | ConvertTo-Json -Depth 10), [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}

if ($SelfTest) {
    $fixtureRoot = Join-Path ([IO.Path]::GetTempPath()) ("u0g-preflight-" + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $fixtureRoot -Force | Out-Null
    try {
        $repo = Get-RepoIdentity $RepoRoot
        $repoArtifacts = [ordered]@{}
        foreach ($relativePath in @(
            "downloads/RUN_AI_COCKPIT_V10.ps1",
            "downloads/AI_COCKPIT_CONTROLLER_V10.ps1",
            "downloads/AI_COCKPIT_GATEWAY_V10.ps1"
        )) {
            $repoArtifacts[$relativePath] = [ordered]@{
                source_raw_sha256 = (Get-FileHash -LiteralPath (Join-Path $RepoRoot $relativePath.Replace("/", "\")) -Algorithm SHA256).Hash.ToLowerInvariant()
            }
        }
        $manifest = [ordered]@{
            repo_sha = $repo.sha
            repo_branch = $repo.branch
            runtime_dir = "PRIVATE_PATH_MUST_NOT_LEAK"
            identity_diagnostics = [ordered]@{ repo_artifacts=$repoArtifacts }
        }
        $state = [ordered]@{
            workbook_path = "PRIVATE_WORKBOOK_MUST_NOT_LEAK"
            username = "PRIVATE_USER_MUST_NOT_LEAK"
            identity_diagnostics = [ordered]@{
                schema_version = "v10-runtime-identity-1"
                overall = "VERIFIED"
                checked_at = (Get-Date).ToString("o")
                ports = [ordered]@{}
                ui = [ordered]@{
                    baseline_id = "approved-fixture"
                    baseline_status = "VERIFIED"
                }
            }
        }
        foreach ($port in 28580..28584) {
            $state.identity_diagnostics.ports[[string]$port] = [ordered]@{
                status="VERIFIED"; owner_pids=@(42); loopback_only=$true
            }
        }
        [IO.File]::WriteAllText((Join-Path $fixtureRoot "V10_RUNTIME.json"), ($manifest | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
        [IO.File]::WriteAllText((Join-Path $fixtureRoot "V10_CONTROLLER_STATE.json"), ($state | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
        $evidence = New-SanitizedPreflight $RepoRoot $fixtureRoot
        Write-PreflightOutput $evidence $OutputPath
        $text = [IO.File]::ReadAllText($OutputPath, [Text.Encoding]::UTF8)
        foreach ($forbidden in @(
            $fixtureRoot,
            "PRIVATE_PATH_MUST_NOT_LEAK",
            "PRIVATE_WORKBOOK_MUST_NOT_LEAK",
            "PRIVATE_USER_MUST_NOT_LEAK",
            "CommandLine",
            "repo_root",
            "runtime_dir"
        )) {
            if ($text.IndexOf($forbidden, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
                throw "Sanitized preflight leaked forbidden data."
            }
        }
        if ([string]$evidence.overall -ne "VERIFIED") { throw "Sanitized preflight fixture did not verify." }
        Write-Output "U0_G_SANITIZED_PREFLIGHT_SELFTEST_PASS"
    } finally {
        Remove-Item -LiteralPath $fixtureRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    exit 0
}

$result = New-SanitizedPreflight $RepoRoot $Root
Write-PreflightOutput $result $OutputPath
Write-Output "U0_G_SANITIZED_PREFLIGHT_COMPLETE"
