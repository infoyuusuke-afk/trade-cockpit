#requires -Version 5.1
<#
V10 isolated checkout identity preflight. NO startup, deployment, process or
MS2/Excel/broker interaction. A passing check is NOT Owner authorization.
This file deliberately has no Execute/Start/Stop mode.
#>
[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [string]$ApprovalFile = ""
)

$ErrorActionPreference = "Stop"

function Read-GitText([string]$Checkout, [string[]]$GitArgs) {
    # --no-optional-locks keeps status from refreshing/writing an index lock.
    $output = & git --no-optional-locks -C $Checkout @GitArgs 2>&1
    if ($LASTEXITCODE -ne 0) { throw "V10_GIT_CHECK_FAILED" }
    return ([string]::Join([Environment]::NewLine, [string[]]@($output))).Trim()
}

try {
    if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
        $RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
    }
    if (-not (Test-Path -LiteralPath $RepoRoot -PathType Container)) {
        throw "V10_CHECKOUT_NOT_FOUND"
    }
    $repo = [IO.Path]::GetFullPath($RepoRoot)

    if ([string]::IsNullOrWhiteSpace($ApprovalFile)) {
        $ApprovalFile = Join-Path $repo "downloads\V10_APPROVED_SOURCE.json"
    }
    if (-not (Test-Path -LiteralPath $ApprovalFile -PathType Leaf)) {
        throw "V10_APPROVED_SOURCE_FILE_MISSING"
    }
    $file = Get-Item -LiteralPath $ApprovalFile -ErrorAction Stop
    if (($file.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "V10_APPROVED_SOURCE_LINK_REFUSED"
    }
    if ($file.Length -gt 4096 -or $file.Length -eq 0) {
        throw "V10_APPROVED_SOURCE_SIZE_INVALID"
    }

    $cfg = [IO.File]::ReadAllText($file.FullName, [Text.Encoding]::UTF8) |
        ConvertFrom-Json -ErrorAction Stop
    if ($null -eq $cfg -or $cfg -isnot [pscustomobject]) {
        throw "V10_APPROVED_SOURCE_SCHEMA_INVALID"
    }
    $fields = @($cfg.PSObject.Properties.Name)
    if ($fields.Count -ne 4) { throw "V10_APPROVED_SOURCE_SCHEMA_INVALID" }
    foreach ($required in @("schema","branch","commit_sha","real_submit_allowed")) {
        if ($fields -cnotcontains $required) {
            throw "V10_APPROVED_SOURCE_SCHEMA_INVALID"
        }
    }
    if ($cfg.schema -isnot [string] -or
        $cfg.schema -cne "v10_approved_source_v1") {
        throw "V10_APPROVED_SOURCE_SCHEMA_INVALID"
    }
    if ($cfg.real_submit_allowed -isnot [bool] -or $cfg.real_submit_allowed) {
        throw "V10_APPROVED_SOURCE_REAL_SUBMIT_MUST_BE_FALSE"
    }
    if ($cfg.branch -isnot [string] -or
        $cfg.branch -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$' -or
        $cfg.branch.Contains("..") -or
        $cfg.branch.EndsWith("/") -or $cfg.branch.EndsWith(".")) {
        throw "V10_REVIEWED_BRANCH_INVALID"
    }
    if ($cfg.commit_sha -isnot [string] -or
        $cfg.commit_sha -cnotmatch '^[0-9a-fA-F]{40}$') {
        throw "V10_FULL_SHA_REQUIRED"
    }

    # Git for Windows emits --show-toplevel in its own output encoding.
    # Windows PowerShell 5.1 may decode non-ASCII directory names incorrectly.
    # Instead prove that -C points at the TOP of a non-bare worktree using
    # encoding-independent ASCII Git predicates. Never accept a subdirectory.
    $inside = Read-GitText $repo @("rev-parse","--is-inside-work-tree")
    $bare = Read-GitText $repo @("rev-parse","--is-bare-repository")
    $prefix = Read-GitText $repo @("rev-parse","--show-prefix")
    if ($inside -cne "true" -or $bare -cne "false" -or
        -not [string]::IsNullOrEmpty($prefix)) {
        throw "V10_CHECKOUT_ROOT_MISMATCH"
    }
    $actualBranch = Read-GitText $repo @("symbolic-ref","--quiet","--short","HEAD")
    $actualSha = Read-GitText $repo @("rev-parse","--verify","HEAD")
    if (-not [string]::Equals($actualBranch,$cfg.branch,
                             [StringComparison]::Ordinal)) {
        throw "V10_BRANCH_IDENTITY_MISMATCH"
    }
    if (-not [string]::Equals($actualSha,$cfg.commit_sha,
                             [StringComparison]::OrdinalIgnoreCase)) {
        throw "V10_SHA_IDENTITY_MISMATCH"
    }
    $status = Read-GitText $repo @("status","--porcelain=v1","--untracked-files=all")
    if (-not [string]::IsNullOrWhiteSpace($status)) {
        throw "V10_WORKTREE_NOT_CLEAN"
    }
    Write-Output "V10_READONLY_SOURCE=PASS"
    Write-Output "GIT_BRANCH_AND_FULL_SHA_MATCH=1"
    Write-Output "GIT_WORKTREE_CLEAN=1"
    Write-Output "RUNTIME_FILES_TOUCHED=0"
    Write-Output "CONTROLLER_STARTED=0"
    Write-Output "MS2_TOUCHED=0"
    Write-Output "EXCEL_TOUCHED=0"
    Write-Output "REAL_SUBMIT_ALLOWED=0"
    Write-Output "OWNER_AUTHENTICATED=0"
    exit 0
} catch {
    $code = [string]$_.Exception.Message
    if (-not $code.StartsWith("V10_", [StringComparison]::Ordinal)) {
        $code = "V10_READONLY_CHECK_ERROR"
    }
    Write-Output "V10_READONLY_SOURCE=BLOCKED"
    Write-Output $code
    Write-Output "RUNTIME_FILES_TOUCHED=0"
    Write-Output "CONTROLLER_STARTED=0"
    Write-Output "REAL_SUBMIT_ALLOWED=0"
    exit 2
}
