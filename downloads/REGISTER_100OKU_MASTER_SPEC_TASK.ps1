param(
    [string]$RepoRoot = "",
    [string]$RemoteBranch = "cursor/master-spec-fetch-sync-d483",
    [switch]$Register,
    [switch]$GuardSelfTest
)

# Print the daily 16:45 JST registration. Do not register unless -Register is present.
# The Owner bootstrap writes downloads/SAFE_REGISTER_100OKU_MASTER_SPEC_TASK.ps1 outside
# the worktree and runs that file. It calls this script with -Register only after the
# worktree checks pass. Do not pass a long inline -Command.
# This script does not start or stop Excel, MarketSpeed II, the Collector, the Gateway, or AI SHADOW.
# It does not submit orders. real_submit_allowed is unchanged.
$ErrorActionPreference = "Stop"

function Get-DefaultRepoRoot {
    if (-not [string]::IsNullOrWhiteSpace($RepoRoot)) { return $RepoRoot }
    return (Split-Path -Parent $PSScriptRoot)
}

function Invoke-RegisterGit([string]$Root, [string[]]$GitArgs) {
    # Exit code decides success. Git may write a normal note to stderr.
    $previousErrorAction = $ErrorActionPreference
    $previousNative = $PSNativeCommandUseErrorActionPreference
    $ErrorActionPreference = "Continue"
    $PSNativeCommandUseErrorActionPreference = $false
    $stdoutLines = New-Object System.Collections.Generic.List[string]
    $stderrLines = New-Object System.Collections.Generic.List[string]
    $code = 1
    try {
        $merged = & git -C $Root @GitArgs 2>&1
        $code = $LASTEXITCODE
        if ($null -ne $merged) {
            foreach ($item in @($merged)) {
                if ($item -is [System.Management.Automation.ErrorRecord]) {
                    [void]$stderrLines.Add([string]$item)
                } else {
                    [void]$stdoutLines.Add([string]$item)
                }
            }
        }
    } finally {
        $ErrorActionPreference = $previousErrorAction
        $PSNativeCommandUseErrorActionPreference = $previousNative
    }
    return [pscustomobject]@{
        Code = $code
        Text = (($stdoutLines -join [Environment]::NewLine).Trim())
        Stderr = (($stderrLines -join [Environment]::NewLine).Trim())
    }
}

function Invoke-RegisterGuard([string]$Root, [string]$Branch) {
    $env:GIT_TERMINAL_PROMPT = "0"
    $env:GCM_INTERACTIVE = "Never"
    if ([string]::IsNullOrWhiteSpace($Branch) -or $Branch.IndexOf(" ") -ge 0 -or $Branch.IndexOf("..") -ge 0) {
        $script:LastRegisterAbort = "REMOTE_BRANCH_MISSING"
        Write-Host "REGISTER_ABORT=REMOTE_BRANCH_MISSING"
        return 1
    }
    $refspec = "refs/heads/" + $Branch + ":refs/remotes/origin/" + $Branch
    $fetch = Invoke-RegisterGit $Root @("fetch", "origin", $refspec)
    if ($fetch.Code -ne 0) {
        $script:LastRegisterAbort = "FETCH_FAILED"
        Write-Host "REGISTER_ABORT=FETCH_FAILED"
        return 1
    }
    $status = Invoke-RegisterGit $Root @("status", "--porcelain", "--untracked-files=normal")
    if ($status.Code -ne 0) {
        $script:LastRegisterAbort = "WORKTREE_UNREADABLE"
        Write-Host "REGISTER_ABORT=WORKTREE_UNREADABLE"
        return 1
    }
    if (-not [string]::IsNullOrWhiteSpace($status.Text)) {
        $script:LastRegisterAbort = "WORKTREE_DIRTY"
        Write-Host "REGISTER_ABORT=WORKTREE_DIRTY"
        return 1
    }
    $head = Invoke-RegisterGit $Root @("rev-parse", "HEAD")
    $remoteRef = "refs/remotes/origin/" + $Branch
    $remote = Invoke-RegisterGit $Root @("rev-parse", $remoteRef)
    if ($head.Code -ne 0 -or $remote.Code -ne 0 -or [string]::IsNullOrWhiteSpace($head.Text) -or [string]::IsNullOrWhiteSpace($remote.Text)) {
        $script:LastRegisterAbort = "REMOTE_COMMIT_MISSING"
        Write-Host "REGISTER_ABORT=REMOTE_COMMIT_MISSING"
        return 1
    }
    $headSha = $head.Text
    $remoteSha = $remote.Text
    $ancestor = Invoke-RegisterGit $Root @("merge-base", "--is-ancestor", $headSha, $remoteSha)
    if ($ancestor.Code -ne 0) {
        $localOnly = Invoke-RegisterGit $Root @("merge-base", "--is-ancestor", $remoteSha, $headSha)
        if ($localOnly.Code -eq 0) {
            $script:LastRegisterAbort = "LOCAL_COMMITS_NOT_ON_REMOTE"
            Write-Host "REGISTER_ABORT=LOCAL_COMMITS_NOT_ON_REMOTE"
        } else {
            $script:LastRegisterAbort = "HISTORY_DIVERGED"
            Write-Host "REGISTER_ABORT=HISTORY_DIVERGED"
        }
        return 1
    }
    $checkout = Invoke-RegisterGit $Root @("-c", "advice.detachedHead=false", "checkout", "--quiet", "--detach", $remoteSha)
    if ($checkout.Code -ne 0) {
        $script:LastRegisterAbort = "CHECKOUT_FAILED"
        Write-Host "REGISTER_ABORT=CHECKOUT_FAILED"
        return 1
    }
    $after = Invoke-RegisterGit $Root @("rev-parse", "HEAD")
    $again = Invoke-RegisterGit $Root @("status", "--porcelain", "--untracked-files=normal")
    if ($after.Code -ne 0 -or $after.Text -ne $remoteSha -or $again.Code -ne 0 -or -not [string]::IsNullOrWhiteSpace($again.Text)) {
        $script:LastRegisterAbort = "HEAD_MISMATCH"
        Write-Host "REGISTER_ABORT=HEAD_MISMATCH"
        return 1
    }
    $script:LastRegisterAbort = ""
    Write-Host "REGISTER_CHECK=PASS"
    Write-Host ("REGISTER_HEAD=" + $remoteSha)
    return 0
}

function Invoke-RegisterCommit([string]$Root, [string]$Message) {
    $add = Invoke-RegisterGit $Root @("add", "--", ".")
    if ($add.Code -ne 0) { return $false }
    & git -C $Root -c user.email="sync-selftest@example.com" -c user.name="sync-selftest" -c commit.gpgsign=false commit -q -m $Message 2>&1 | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Invoke-RegisterGuardSelfTest {
    $temp = [IO.Path]::Combine([IO.Path]::GetTempPath(), ("register-guard-" + [Guid]::NewGuid().ToString("N")))
    New-Item -ItemType Directory -Path $temp -Force | Out-Null
    $branch = "cursor/fixture-sync-d483"
    try {
        $bare = [IO.Path]::Combine($temp, "remote.git")
        $seed = [IO.Path]::Combine($temp, "seed")
        $clone = [IO.Path]::Combine($temp, "clone")
        $dedicated = [IO.Path]::Combine($temp, "dedicated")
        & git init -q --bare $bare 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { return 1 }
        & git init -q $seed 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { return 1 }
        [IO.File]::WriteAllText([IO.Path]::Combine($seed, "note.txt"), "base")
        if (-not (Invoke-RegisterCommit $seed "base")) { return 1 }
        $base = (Invoke-RegisterGit $seed @("rev-parse", "HEAD")).Text
        & git -C $seed branch -M $branch 2>&1 | Out-Null
        & git -C $seed remote add origin $bare 2>&1 | Out-Null
        & git -C $seed push -q origin ("HEAD:refs/heads/" + $branch) 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { return 1 }
        & git --git-dir $bare symbolic-ref HEAD ("refs/heads/" + $branch) 2>&1 | Out-Null
        & git clone -q -b $branch $bare $clone 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { return 1 }
        & git -C $clone worktree add --detach $dedicated $base 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { return 1 }
        [IO.File]::AppendAllText([IO.Path]::Combine($dedicated, "note.txt"), "local")
        if (-not (Invoke-RegisterCommit $dedicated "local-only")) { return 1 }
        $localHead = (Invoke-RegisterGit $dedicated @("rev-parse", "HEAD")).Text
        $local = Invoke-RegisterGuard $dedicated $branch
        if ($local -eq 0 -or $script:LastRegisterAbort -ne "LOCAL_COMMITS_NOT_ON_REMOTE") { return 1 }
        if ((Invoke-RegisterGit $dedicated @("rev-parse", "HEAD")).Text -ne $localHead) { return 1 }
        & git -C $dedicated reset --hard $base 2>&1 | Out-Null
        Write-Host "CASE=LOCAL_COMMITS"

        [IO.File]::AppendAllText([IO.Path]::Combine($seed, "note.txt"), "forward")
        if (-not (Invoke-RegisterCommit $seed "forward")) { return 1 }
        & git -C $seed push -q origin ("HEAD:refs/heads/" + $branch) 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { return 1 }

        [IO.File]::WriteAllText([IO.Path]::Combine($dedicated, "extra.txt"), "dirty")
        $dirty = Invoke-RegisterGuard $dedicated $branch
        if ($dirty -eq 0 -or $script:LastRegisterAbort -ne "WORKTREE_DIRTY") { return 1 }
        if ((Invoke-RegisterGit $dedicated @("rev-parse", "HEAD")).Text -ne $base) { return 1 }
        Remove-Item -LiteralPath ([IO.Path]::Combine($dedicated, "extra.txt")) -Force
        Write-Host "CASE=DIRTY"

        & git -C $dedicated remote set-url origin ([IO.Path]::Combine($temp, "missing-remote")) 2>&1 | Out-Null
        $fetch = Invoke-RegisterGuard $dedicated $branch
        if ($fetch -eq 0 -or $script:LastRegisterAbort -ne "FETCH_FAILED") { return 1 }
        if ((Invoke-RegisterGit $dedicated @("rev-parse", "HEAD")).Text -ne $base) { return 1 }
        & git -C $dedicated remote set-url origin $bare 2>&1 | Out-Null
        Write-Host "CASE=FETCH_FAIL"

        [IO.File]::AppendAllText([IO.Path]::Combine($seed, "note.txt"), "sibling")
        if (-not (Invoke-RegisterCommit $seed "sibling")) { return 1 }
        & git -C $seed push -q origin ("HEAD:refs/heads/" + $branch) 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { return 1 }
        [IO.File]::AppendAllText([IO.Path]::Combine($dedicated, "note.txt"), "other")
        if (-not (Invoke-RegisterCommit $dedicated "other")) { return 1 }
        $divergedHead = (Invoke-RegisterGit $dedicated @("rev-parse", "HEAD")).Text
        $diverged = Invoke-RegisterGuard $dedicated $branch
        if ($diverged -eq 0 -or $script:LastRegisterAbort -ne "HISTORY_DIVERGED") { return 1 }
        if ((Invoke-RegisterGit $dedicated @("rev-parse", "HEAD")).Text -ne $divergedHead) { return 1 }
        & git -C $dedicated reset --hard $base 2>&1 | Out-Null
        Write-Host "CASE=DIVERGED"

        $tip = (Invoke-RegisterGit $seed @("rev-parse", "HEAD")).Text
        $moved = Invoke-RegisterGuard $dedicated $branch
        if ($moved -ne 0 -or $script:LastRegisterAbort -ne "") { return 1 }
        if ((Invoke-RegisterGit $dedicated @("rev-parse", "HEAD")).Text -ne $tip) { return 1 }
        Write-Host "CASE=FAST_FORWARD"

        $same = Invoke-RegisterGuard $dedicated $branch
        if ($same -ne 0) { return 1 }
        if ((Invoke-RegisterGit $dedicated @("rev-parse", "HEAD")).Text -ne $tip) { return 1 }
        Write-Host "CASE=UNCHANGED"
        Write-Host "REGISTER_GUARD_SELFTEST=PASS"
        Write-Host "SELFTEST_WROTE_D_DRIVE=0"
        return 0
    } finally {
        if (Test-Path -LiteralPath $temp) {
            Remove-Item -LiteralPath $temp -Recurse -Force
        }
    }
}

$root = Get-DefaultRepoRoot
$wrapper = [IO.Path]::Combine([IO.Path]::Combine($root, "downloads"), "UPDATE_AND_SYNC_100OKU_MASTER_SPEC.ps1")
$task = "TradeCockpit-100oku-MasterSpec-Sync"
# schtasks splits a /TR value on embedded quotes. These paths have no spaces.
# The task runs the fetch-then-sync wrapper, not a copy of a frozen worktree.
if ($root.IndexOf(" ") -ge 0 -or $root.IndexOf([char]34) -ge 0 -or $wrapper.IndexOf(" ") -ge 0 -or $wrapper.IndexOf([char]34) -ge 0) {
    Write-Host "TASK_REGISTER=FAIL"
    Write-Host "REASON=PATH_HAS_SPACE_OR_QUOTE"
    exit 1
}
$action = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File " + $wrapper + " -RepoRoot " + $root

Write-Host "TASK_NAME=$task"
Write-Host "TASK_TIME=16:45"
Write-Host "TASK_TIMEZONE_ASSUMPTION=LOCAL_CLOCK_IS_JST"
Write-Host "TASK_ACTION=$action"
Write-Host "CLOUD_AGENT_WROTE_D_DRIVE=0"

if ($GuardSelfTest) {
    $guardSelf = Invoke-RegisterGuardSelfTest
    exit $guardSelf
}

if (-not $Register) {
    Write-Host "TASK_REGISTER=NOT_RUN"
    exit 0
}

$guardCode = Invoke-RegisterGuard $root $RemoteBranch
if ($guardCode -ne 0) { exit $guardCode }

if (-not (Test-Path -LiteralPath $wrapper)) {
    Write-Host "TASK_REGISTER=FAIL"
    Write-Host "REASON=WRAPPER_MISSING"
    exit 1
}

$schtasks = Get-Command schtasks.exe -ErrorAction SilentlyContinue
if ($null -eq $schtasks) {
    Write-Host "TASK_REGISTER=FAIL"
    Write-Host "REASON=SCHTASKS_MISSING"
    exit 1
}

& schtasks.exe /Create /F /TN $task /SC DAILY /ST 16:45 /TR $action
if ($LASTEXITCODE -ne 0) {
    Write-Host "TASK_REGISTER=FAIL"
    exit $LASTEXITCODE
}
Write-Host "TASK_REGISTER=PASS"
exit 0
