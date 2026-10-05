param(
    [string]$RepoRoot = "",
    [string]$RemoteBranch = "",
    [string]$Destination = "",
    [switch]$DryRun,
    [switch]$SelfTest
)

# Fetch the 100oku master branch, fast-forward a clean worktree, then copy.
# Fetch failure, a dirty worktree, local-only commits, diverged history,
# a missing or empty master file, or a hash mismatch does not update D:.
# The same commit may be copied again when the remote has not moved.
# This script does not start or stop Excel, MarketSpeed II, the Collector, the Gateway, or AI SHADOW.
# It does not submit orders. real_submit_allowed is unchanged.
$ErrorActionPreference = "Stop"
$env:GIT_TERMINAL_PROMPT = "0"
$env:GCM_INTERACTIVE = "Never"

function Get-DefaultRepoRoot {
    if (-not [string]::IsNullOrWhiteSpace($RepoRoot)) { return $RepoRoot }
    return (Split-Path -Parent $PSScriptRoot)
}

function Join-ChildPath([string]$Base, [string]$Name) {
    return [IO.Path]::Combine($Base, $Name)
}

function Get-Sha256Hex([string]$Path) {
    $sha = [Security.Cryptography.SHA256]::Create()
    $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    try {
        $hash = $sha.ComputeHash($stream)
    } finally {
        $stream.Dispose()
        $sha.Dispose()
    }
    return ([BitConverter]::ToString($hash)).Replace("-", "").ToLowerInvariant()
}

function Read-Utf8Text([string]$Path) {
    return [IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8)
}

function Write-JsonFile([string]$Path, $Object) {
    $json = ($Object | ConvertTo-Json -Depth 6) + [Environment]::NewLine
    $utf8 = New-Object System.Text.UTF8Encoding $false
    [IO.File]::WriteAllText($Path, $json, $utf8)
}

function Get-Manifest([string]$Root) {
    $path = Join-ChildPath (Join-ChildPath (Join-ChildPath $Root "docs") "100oku") "SYNC_MANIFEST.json"
    if (-not (Test-Path -LiteralPath $path)) { return $null }
    return (Read-Utf8Text $path) | ConvertFrom-Json
}

function Test-BranchName([string]$Name) {
    if ([string]::IsNullOrWhiteSpace($Name)) { return $false }
    if ($Name.IndexOf(" ") -ge 0) { return $false }
    if ($Name.IndexOf([char]34) -ge 0) { return $false }
    if ($Name.IndexOf("..") -ge 0) { return $false }
    return $Name -match '^cursor/[A-Za-z0-9][A-Za-z0-9._/-]*$'
}

function Invoke-Git([string]$Root, [string[]]$GitArgs) {
    $output = & git -C $Root @GitArgs 2>&1
    $text = ""
    if ($null -ne $output) {
        $text = (($output | ForEach-Object { "$_" }) -join "`n").Trim()
    }
    return [pscustomobject]@{
        Code = $LASTEXITCODE
        Text = $text
    }
}

function Get-OwnerShell {
    if (-not [string]::IsNullOrWhiteSpace($env:SystemRoot)) {
        $win = Join-ChildPath (Join-ChildPath (Join-ChildPath $env:SystemRoot "System32") "WindowsPowerShell") "v1.0\powershell.exe"
        if (Test-Path -LiteralPath $win) { return $win }
    }
    $found = Get-Command pwsh -ErrorAction SilentlyContinue
    if ($null -ne $found) { return [string]$found.Source }
    return ""
}

function Write-Fail([string]$Reason) {
    Write-Host "MASTER_SPEC_UPDATE_SYNC=FAIL"
    Write-Host ("REASON=" + $Reason)
    Write-Host "CLOUD_AGENT_WROTE_D_DRIVE=0"
    Write-Host "DESTINATION_WRITTEN=0"
}

function Resolve-Branch([string]$Root, [string]$Requested) {
    if (-not [string]::IsNullOrWhiteSpace($Requested)) { return $Requested }
    $manifest = Get-Manifest $Root
    if ($null -ne $manifest -and -not [string]::IsNullOrWhiteSpace([string]$manifest.remote_branch)) {
        return [string]$manifest.remote_branch
    }
    return "cursor/master-spec-fetch-sync-d483"
}

function Test-WorktreePorcelain([string]$Root) {
    $status = Invoke-Git $Root @("status", "--porcelain", "--untracked-files=normal")
    if ($status.Code -ne 0) {
        return "UNREADABLE"
    }
    if (-not [string]::IsNullOrWhiteSpace($status.Text)) {
        return "DIRTY"
    }
    return "CLEAN"
}

function Test-RequiredSources([string]$Root) {
    $manifest = Get-Manifest $Root
    if ($null -eq $manifest) { return "MANIFEST_MISSING" }
    foreach ($relative in @($manifest.required)) {
        $path = $Root
        foreach ($part in ([string]$relative -split '[\\/]')) {
            if (-not [string]::IsNullOrWhiteSpace($part)) {
                $path = Join-ChildPath $path $part
            }
        }
        if (-not (Test-Path -LiteralPath $path)) { return "MISSING" }
        if (([IO.FileInfo]$path).Length -le 0) { return "EMPTY" }
    }
    return "OK"
}

function Invoke-CopyScript([string]$Root, [string]$DestinationPath) {
    $sync = Join-ChildPath (Join-ChildPath $Root "downloads") "SYNC_100OKU_MASTER_SPEC.ps1"
    if (-not (Test-Path -LiteralPath $sync)) {
        $sync = Join-ChildPath $PSScriptRoot "SYNC_100OKU_MASTER_SPEC.ps1"
    }
    if (-not (Test-Path -LiteralPath $sync)) {
        Write-Fail "SYNC_SCRIPT_MISSING"
        return 1
    }
    $shell = Get-OwnerShell
    if ([string]::IsNullOrWhiteSpace($shell)) {
        Write-Fail "SHELL_MISSING"
        return 1
    }
    $args = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $sync, "-RepoRoot", $Root)
    if (-not [string]::IsNullOrWhiteSpace($DestinationPath)) {
        $args += @("-Destination", $DestinationPath)
    }
    & $shell @args | Out-Host
    if ($null -eq $LASTEXITCODE) { return 1 }
    return $LASTEXITCODE
}

function Confirm-Destination([string]$Root, [string]$Dest, [string]$ExpectedCommit) {
    $lastPath = Join-ChildPath $Dest "LAST_SYNC.json"
    if (-not (Test-Path -LiteralPath $lastPath)) {
        Write-Fail "LAST_SYNC_MISSING"
        return 1
    }
    $record = (Read-Utf8Text $lastPath) | ConvertFrom-Json
    $source = [string]$record.source_commit
    if ([string]::IsNullOrWhiteSpace($source)) { $source = [string]$record.repo_commit }
    if ($record.result -ne "PASS" -or $source -ne $ExpectedCommit) {
        Write-Fail "DESTINATION_HASH_MISMATCH"
        return 1
    }
    foreach ($file in @($record.files)) {
        $destFile = Join-ChildPath $Dest ([string]$file.name)
        if (-not (Test-Path -LiteralPath $destFile)) {
            Write-Fail "DESTINATION_HASH_MISMATCH"
            return 1
        }
        $actual = Get-Sha256Hex $destFile
        if ([string]::IsNullOrWhiteSpace($actual) -or $actual -ne [string]$file.sha256 -or $actual -ne [string]$file.destination_sha256) {
            $fail = [ordered]@{
                source_commit = $ExpectedCommit
                repo_commit = $ExpectedCommit
                destination = $Dest
                result = "FAIL"
                reason = "DESTINATION_HASH_MISMATCH"
                cloud_agent_wrote_destination = $false
                written_by = "owner_pc_update_sync_wrapper"
            }
            Write-JsonFile $lastPath $fail
            Write-Fail "DESTINATION_HASH_MISMATCH"
            return 1
        }
    }
    Write-Host "MASTER_SPEC_UPDATE_SYNC=PASS"
    Write-Host ("SOURCE_COMMIT=" + $ExpectedCommit)
    Write-Host ("DESTINATION=" + $Dest)
    Write-Host "CLOUD_AGENT_WROTE_D_DRIVE=0"
    Write-Host "DESTINATION_WRITTEN=1"
    return 0
}

function Invoke-UpdateAndSync([string]$Root, [string]$Branch, [string]$DestinationPath, [bool]$IsDryRun) {
    if (-not (Test-BranchName $Branch)) {
        Write-Fail "REMOTE_BRANCH_MISSING"
        return 1
    }
    Write-Host ("REMOTE_BRANCH=" + $Branch)
    $inside = Invoke-Git $Root @("rev-parse", "--is-inside-work-tree")
    if ($inside.Code -ne 0 -or $inside.Text -ne "true") {
        Write-Fail "WORKTREE_UNREADABLE"
        return 1
    }
    $porcelain = Test-WorktreePorcelain $Root
    if ($porcelain -ne "CLEAN") {
        Write-Fail ("WORKTREE_" + $porcelain)
        return 1
    }
    $headBefore = Invoke-Git $Root @("rev-parse", "HEAD")
    if ($headBefore.Code -ne 0 -or [string]::IsNullOrWhiteSpace($headBefore.Text)) {
        Write-Fail "WORKTREE_UNREADABLE"
        return 1
    }
    $refspec = "refs/heads/" + $Branch + ":refs/remotes/origin/" + $Branch
    $fetch = Invoke-Git $Root @("fetch", "origin", $refspec)
    if ($fetch.Code -ne 0) {
        Write-Fail "FETCH_FAILED"
        return 1
    }
    $remoteRef = "refs/remotes/origin/" + $Branch
    $remote = Invoke-Git $Root @("rev-parse", $remoteRef)
    if ($remote.Code -ne 0 -or [string]::IsNullOrWhiteSpace($remote.Text)) {
        Write-Fail "REMOTE_COMMIT_MISSING"
        return 1
    }
    $remoteSha = $remote.Text
    $headSha = $headBefore.Text
    Write-Host ("REMOTE_COMMIT=" + $remoteSha)
    Write-Host ("HEAD_BEFORE=" + $headSha)
    $move = "UNCHANGED"
    if ($headSha -ne $remoteSha) {
        $headAncestor = Invoke-Git $Root @("merge-base", "--is-ancestor", $headSha, $remoteSha)
        $remoteAncestor = Invoke-Git $Root @("merge-base", "--is-ancestor", $remoteSha, $headSha)
        if ($headAncestor.Code -eq 0) {
            $move = "FAST_FORWARD"
        } elseif ($remoteAncestor.Code -eq 0) {
            Write-Fail "LOCAL_COMMITS_NOT_ON_REMOTE"
            return 1
        } else {
            Write-Fail "HISTORY_DIVERGED"
            return 1
        }
    }
    if ($IsDryRun) {
        Write-Host ("WORKTREE_UPDATE=" + $move)
        Write-Host "DRY_RUN_MOVE=NOT_APPLIED"
        Write-Host "MASTER_SPEC_UPDATE_SYNC=DRY_RUN"
        Write-Host "CLOUD_AGENT_WROTE_D_DRIVE=0"
        Write-Host "DESTINATION_WRITTEN=0"
        return 0
    }
    if ($move -eq "FAST_FORWARD") {
        $checkout = Invoke-Git $Root @("-c", "advice.detachedHead=false", "checkout", "--detach", $remoteSha)
        if ($checkout.Code -ne 0) {
            Write-Fail "CHECKOUT_FAILED"
            return 1
        }
        $headAfter = Invoke-Git $Root @("rev-parse", "HEAD")
        if ($headAfter.Code -ne 0 -or $headAfter.Text -ne $remoteSha) {
            Write-Fail "HEAD_MISMATCH"
            return 1
        }
        $again = Test-WorktreePorcelain $Root
        if ($again -ne "CLEAN") {
            Write-Fail ("WORKTREE_" + $again)
            return 1
        }
    }
    Write-Host ("WORKTREE_UPDATE=" + $move)
    $sources = Test-RequiredSources $Root
    if ($sources -ne "OK") {
        Write-Fail $sources
        return 1
    }
    $copyCode = Invoke-CopyScript $Root $DestinationPath
    if ($copyCode -ne 0) {
        Write-Fail "SYNC_FAILED"
        return 1
    }
    $dest = $DestinationPath
    if ([string]::IsNullOrWhiteSpace($dest)) {
        $manifest = Get-Manifest $Root
        if ($null -eq $manifest) {
            Write-Fail "MANIFEST_MISSING"
            return 1
        }
        $dest = [string]$manifest.destination
    }
    return (Confirm-Destination $Root $dest $remoteSha)
}

function New-FixtureFiles([string]$Root, [string]$Branch) {
    $docs = Join-ChildPath (Join-ChildPath $Root "docs") "100oku"
    New-Item -ItemType Directory -Path $docs -Force | Out-Null
    $manifest = @{
        role = "repo_working_copy"
        destination = "D:\100oku-selftest-not-used"
        cloud_agent_can_write_destination = $false
        remote_branch = $Branch
        required = @(
            "docs/100oku/MASTER_SPEC.md",
            "docs/100oku/CURRENT_STATUS.md",
            "docs/100oku/CHANGELOG.md",
            "docs/100oku/HANDOVER.md"
        )
        optional_docx_dir = "docs/100oku"
    }
    $utf8 = New-Object System.Text.UTF8Encoding $false
    [IO.File]::WriteAllText((Join-ChildPath $docs "SYNC_MANIFEST.json"), (($manifest | ConvertTo-Json -Depth 5) + [Environment]::NewLine), $utf8)
    $names = @(
        "MASTER_SPEC.md",
        "CURRENT_STATUS.md",
        "CHANGELOG.md",
        "HANDOVER.md"
    )
    foreach ($name in $names) {
        [IO.File]::WriteAllText((Join-ChildPath $docs $name), ("fixture " + $name + " " + [Guid]::NewGuid().ToString("N") + [Environment]::NewLine), $utf8)
    }
}

function Invoke-GitCommit([string]$Root, [string]$Message) {
    $add = Invoke-Git $Root @("add", "--", ".")
    if ($add.Code -ne 0) { return $false }
    $commit = & git -C $Root -c user.email="sync-selftest@example.com" -c user.name="sync-selftest" -c commit.gpgsign=false commit -q -m $Message 2>&1
    if ($LASTEXITCODE -ne 0) { return $false }
    return $true
}

function Invoke-SelfTest {
    $temp = Join-ChildPath ([IO.Path]::GetTempPath()) ("master-spec-update-" + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $temp -Force | Out-Null
    $branch = "cursor/fixture-sync-d483"
    try {
        $bare = Join-ChildPath $temp "remote.git"
        $seed = Join-ChildPath $temp "seed"
        $clone = Join-ChildPath $temp "clone"
        $dedicated = Join-ChildPath $temp "dedicated"
        $dest = Join-ChildPath $temp "dest"
        & git init -q --bare $bare 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { return 1 }
        & git init -q $seed 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { return 1 }
        New-FixtureFiles $seed $branch
        if (-not (Invoke-GitCommit $seed "base")) { return 1 }
        $base = (Invoke-Git $seed @("rev-parse", "HEAD")).Text
        & git -C $seed branch -M $branch 2>&1 | Out-Null
        & git -C $seed remote add origin $bare 2>&1 | Out-Null
        & git -C $seed push -q origin ("HEAD:refs/heads/" + $branch) 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { return 1 }
        & git --git-dir $bare symbolic-ref HEAD ("refs/heads/" + $branch) 2>&1 | Out-Null
        & git clone -q -b $branch $bare $clone 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { return 1 }
        & git -C $clone worktree add --detach $dedicated $base 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { return 1 }

        $dirtyDest = Join-ChildPath $temp "dirty-dest"
        [IO.File]::WriteAllText((Join-ChildPath $dedicated "notes.txt"), "local")
        $dirtyCode = Invoke-UpdateAndSync $dedicated $branch $dirtyDest $false
        if ($dirtyCode -eq 0) { return 1 }
        if (Test-Path -LiteralPath $dirtyDest) { return 1 }
        $dirtyHead = (Invoke-Git $dedicated @("rev-parse", "HEAD")).Text
        if ($dirtyHead -ne $base) { return 1 }
        Remove-Item -LiteralPath (Join-ChildPath $dedicated "notes.txt") -Force
        Write-Host "CASE=DIRTY"

        $fetchDest = Join-ChildPath $temp "fetch-dest"
        & git -C $dedicated remote set-url origin (Join-ChildPath $temp "missing-remote") 2>&1 | Out-Null
        $fetchCode = Invoke-UpdateAndSync $dedicated $branch $fetchDest $false
        if ($fetchCode -eq 0) { return 1 }
        if (Test-Path -LiteralPath $fetchDest) { return 1 }
        if ((Invoke-Git $dedicated @("rev-parse", "HEAD")).Text -ne $base) { return 1 }
        & git -C $dedicated remote set-url origin $bare 2>&1 | Out-Null
        Write-Host "CASE=FETCH_FAIL"

        [IO.File]::AppendAllText((Join-ChildPath (Join-ChildPath (Join-ChildPath $dedicated "docs") "100oku") "HANDOVER.md"), "local-only`n")
        if (-not (Invoke-GitCommit $dedicated "local-only")) { return 1 }
        $localHead = (Invoke-Git $dedicated @("rev-parse", "HEAD")).Text
        $localDest = Join-ChildPath $temp "local-dest"
        $localCode = Invoke-UpdateAndSync $dedicated $branch $localDest $false
        if ($localCode -eq 0) { return 1 }
        if (Test-Path -LiteralPath $localDest) { return 1 }
        if ((Invoke-Git $dedicated @("rev-parse", "HEAD")).Text -ne $localHead) { return 1 }
        & git -C $dedicated reset --hard $base 2>&1 | Out-Null
        Write-Host "CASE=LOCAL_COMMITS"

        [IO.File]::AppendAllText((Join-ChildPath (Join-ChildPath (Join-ChildPath $seed "docs") "100oku") "CHANGELOG.md"), "sibling`n")
        if (-not (Invoke-GitCommit $seed "sibling")) { return 1 }
        & git -C $seed push -q origin ("HEAD:refs/heads/" + $branch) 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { return 1 }
        [IO.File]::AppendAllText((Join-ChildPath (Join-ChildPath (Join-ChildPath $dedicated "docs") "100oku") "HANDOVER.md"), "other`n")
        if (-not (Invoke-GitCommit $dedicated "other")) { return 1 }
        $divergedHead = (Invoke-Git $dedicated @("rev-parse", "HEAD")).Text
        $divergedDest = Join-ChildPath $temp "diverged-dest"
        $divergedCode = Invoke-UpdateAndSync $dedicated $branch $divergedDest $false
        if ($divergedCode -eq 0) { return 1 }
        if (Test-Path -LiteralPath $divergedDest) { return 1 }
        if ((Invoke-Git $dedicated @("rev-parse", "HEAD")).Text -ne $divergedHead) { return 1 }
        & git -C $dedicated reset --hard $base 2>&1 | Out-Null
        Write-Host "CASE=DIVERGED"

        $dryCode = Invoke-UpdateAndSync $dedicated $branch $dest $true
        if ($dryCode -ne 0) { return 1 }
        if ((Invoke-Git $dedicated @("rev-parse", "HEAD")).Text -ne $base) { return 1 }
        if (Test-Path -LiteralPath $dest) { return 1 }
        Write-Host "CASE=DRY_RUN"

        $forwardCode = Invoke-UpdateAndSync $dedicated $branch $dest $false
        if ($forwardCode -ne 0) { return 1 }
        $remoteTip = (Invoke-Git $seed @("rev-parse", "HEAD")).Text
        if ((Invoke-Git $dedicated @("rev-parse", "HEAD")).Text -ne $remoteTip) { return 1 }
        $last = (Read-Utf8Text (Join-ChildPath $dest "LAST_SYNC.json")) | ConvertFrom-Json
        if ($last.result -ne "PASS") { return 1 }
        if ([string]$last.source_commit -ne $remoteTip) { return 1 }
        if ($last.cloud_agent_wrote_destination -ne $false) { return 1 }
        Write-Host "CASE=FAST_FORWARD"

        $sameCode = Invoke-UpdateAndSync $dedicated $branch $dest $false
        if ($sameCode -ne 0) { return 1 }
        if ((Invoke-Git $dedicated @("rev-parse", "HEAD")).Text -ne $remoteTip) { return 1 }
        $archiveRoot = Join-ChildPath $dest "archive"
        $archives = @(Get-ChildItem -LiteralPath $archiveRoot -Directory -ErrorAction SilentlyContinue)
        if ($archives.Count -lt 1) { return 1 }
        Write-Host "CASE=UNCHANGED"

        $missingSeed = Join-ChildPath $temp "missing-seed"
        & git clone -q $bare $missingSeed 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { return 1 }
        Remove-Item -LiteralPath (Join-ChildPath (Join-ChildPath (Join-ChildPath $missingSeed "docs") "100oku") "CURRENT_STATUS.md") -Force
        if (-not (Invoke-GitCommit $missingSeed "drop-file")) { return 1 }
        & git -C $missingSeed push -q origin ("HEAD:refs/heads/" + $branch) 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { return 1 }
        $beforeMissing = Get-Sha256Hex (Join-ChildPath $dest "CURRENT_STATUS.md")
        $missingDest = $dest
        $missingCode = Invoke-UpdateAndSync $dedicated $branch $missingDest $false
        if ($missingCode -eq 0) { return 1 }
        $afterMissing = Get-Sha256Hex (Join-ChildPath $dest "CURRENT_STATUS.md")
        if ($afterMissing -ne $beforeMissing) { return 1 }
        Write-Host "CASE=MISSING"

        Write-Host "UPDATE_SYNC_SELFTEST=PASS"
        Write-Host "SELFTEST_WROTE_D_DRIVE=0"
        Write-Host "CLOUD_AGENT_WROTE_D_DRIVE=0"
        return 0
    } finally {
        if (Test-Path -LiteralPath $temp) {
            Remove-Item -LiteralPath $temp -Recurse -Force
        }
    }
}

$resolvedRoot = Get-DefaultRepoRoot
if ($SelfTest) {
    $selfCode = Invoke-SelfTest
    exit $selfCode
}
$resolvedBranch = Resolve-Branch $resolvedRoot $RemoteBranch
$updateCode = Invoke-UpdateAndSync $resolvedRoot $resolvedBranch $Destination ([bool]$DryRun)
exit $updateCode
