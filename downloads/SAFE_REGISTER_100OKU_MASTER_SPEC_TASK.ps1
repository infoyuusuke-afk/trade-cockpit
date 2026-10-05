param(
    [string]$RepoRoot = "",
    [string]$RemoteBranch = "cursor/master-spec-fetch-sync-d483",
    [switch]$SelfTest
)

# First registration of the 16:45 master-spec task.
# The Owner does not run this file from the detached worktree. A one-line cmd bootstrap
# fetches the branch, writes this blob outside the worktree, then runs that file.
# OWNER_BOOTSTRAP_COMMAND
# cmd /c "git -C C:\Users\yusuk\code\trade-cockpit-100oku-master-sync fetch origin refs/heads/cursor/master-spec-fetch-sync-d483:refs/remotes/origin/cursor/master-spec-fetch-sync-d483 && git -C C:\Users\yusuk\code\trade-cockpit-100oku-master-sync show refs/remotes/origin/cursor/master-spec-fetch-sync-d483:downloads/SAFE_REGISTER_100OKU_MASTER_SPEC_TASK.ps1 > C:\Users\yusuk\code\SAFE_REGISTER_100OKU_MASTER_SPEC_TASK.ps1 && powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\Users\yusuk\code\SAFE_REGISTER_100OKU_MASTER_SPEC_TASK.ps1 -RepoRoot C:\Users\yusuk\code\trade-cockpit-100oku-master-sync"
# This script does not copy files to D: and does not start or stop Excel, MarketSpeed II,
# the Collector, the Gateway, or AI SHADOW. It does not submit orders.
# real_submit_allowed is unchanged.
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

function Get-SafeRepoRoot {
    if (-not [string]::IsNullOrWhiteSpace($RepoRoot)) { return $RepoRoot }
    return (Split-Path -Parent $PSScriptRoot)
}

function Invoke-SafeGit([string]$Root, [string[]]$GitArgs) {
    # Windows PowerShell 5.1 turns git's normal stderr into NativeCommandError when
    # ErrorActionPreference is Stop. Exit code decides success. Stderr is evidence only.
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

function Invoke-SafeRegisterCheck([string]$Root, [string]$Branch) {
    $env:GIT_TERMINAL_PROMPT = "0"
    $env:GCM_INTERACTIVE = "Never"
    if ([string]::IsNullOrWhiteSpace($Branch) -or $Branch.IndexOf(" ") -ge 0 -or $Branch.IndexOf("..") -ge 0) {
        $script:LastSafeAbort = "REMOTE_BRANCH_MISSING"
        Write-Host "REGISTER_ABORT=REMOTE_BRANCH_MISSING"
        return 1
    }
    $refspec = "refs/heads/" + $Branch + ":refs/remotes/origin/" + $Branch
    $fetch = Invoke-SafeGit $Root @("fetch", "origin", $refspec)
    if ($fetch.Code -ne 0) {
        $script:LastSafeAbort = "FETCH_FAILED"
        Write-Host "REGISTER_ABORT=FETCH_FAILED"
        return 1
    }
    $status = Invoke-SafeGit $Root @("status", "--porcelain", "--untracked-files=normal")
    if ($status.Code -ne 0) {
        $script:LastSafeAbort = "WORKTREE_UNREADABLE"
        Write-Host "REGISTER_ABORT=WORKTREE_UNREADABLE"
        return 1
    }
    if (-not [string]::IsNullOrWhiteSpace($status.Text)) {
        $script:LastSafeAbort = "WORKTREE_DIRTY"
        Write-Host "REGISTER_ABORT=WORKTREE_DIRTY"
        return 1
    }
    $head = Invoke-SafeGit $Root @("rev-parse", "HEAD")
    $remoteRef = "refs/remotes/origin/" + $Branch
    $remote = Invoke-SafeGit $Root @("rev-parse", $remoteRef)
    if ($head.Code -ne 0 -or $remote.Code -ne 0 -or [string]::IsNullOrWhiteSpace($head.Text) -or [string]::IsNullOrWhiteSpace($remote.Text)) {
        $script:LastSafeAbort = "REMOTE_COMMIT_MISSING"
        Write-Host "REGISTER_ABORT=REMOTE_COMMIT_MISSING"
        return 1
    }
    $headSha = $head.Text
    $remoteSha = $remote.Text
    $ancestor = Invoke-SafeGit $Root @("merge-base", "--is-ancestor", $headSha, $remoteSha)
    if ($ancestor.Code -ne 0) {
        $localOnly = Invoke-SafeGit $Root @("merge-base", "--is-ancestor", $remoteSha, $headSha)
        if ($localOnly.Code -eq 0) {
            $script:LastSafeAbort = "LOCAL_COMMITS_NOT_ON_REMOTE"
            Write-Host "REGISTER_ABORT=LOCAL_COMMITS_NOT_ON_REMOTE"
        } else {
            $script:LastSafeAbort = "HISTORY_DIVERGED"
            Write-Host "REGISTER_ABORT=HISTORY_DIVERGED"
        }
        return 1
    }
    $checkout = Invoke-SafeGit $Root @("-c", "advice.detachedHead=false", "checkout", "--quiet", "--detach", $remoteSha)
    if ($checkout.Code -ne 0) {
        $script:LastSafeAbort = "CHECKOUT_FAILED"
        Write-Host "REGISTER_ABORT=CHECKOUT_FAILED"
        return 1
    }
    $after = Invoke-SafeGit $Root @("rev-parse", "HEAD")
    $again = Invoke-SafeGit $Root @("status", "--porcelain", "--untracked-files=normal")
    if ($after.Code -ne 0 -or $after.Text -ne $remoteSha -or $again.Code -ne 0 -or -not [string]::IsNullOrWhiteSpace($again.Text)) {
        $script:LastSafeAbort = "HEAD_MISMATCH"
        Write-Host "REGISTER_ABORT=HEAD_MISMATCH"
        return 1
    }
    $script:LastSafeAbort = ""
    Write-Host "REGISTER_CHECK=PASS"
    Write-Host ("REGISTER_HEAD=" + $remoteSha)
    return 0
}

function Invoke-RegisterScript([string]$Root, [string]$Branch) {
    $register = [System.IO.Path]::Combine($Root, "downloads", "REGISTER_100OKU_MASTER_SPEC_TASK.ps1")
    if (-not (Test-Path -LiteralPath $register)) {
        $script:LastSafeAbort = "REGISTER_SCRIPT_MISSING"
        Write-Host "REGISTER_ABORT=REGISTER_SCRIPT_MISSING"
        return 1
    }
    $shell = ""
    if (-not [string]::IsNullOrWhiteSpace($env:SystemRoot)) {
        $win = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
        if (Test-Path -LiteralPath $win) { $shell = $win }
    }
    if ([string]::IsNullOrWhiteSpace($shell)) {
        $found = Get-Command pwsh -ErrorAction SilentlyContinue
        if ($null -ne $found) { $shell = [string]$found.Source }
    }
    if ([string]::IsNullOrWhiteSpace($shell)) {
        $self = Join-Path $PSHOME "pwsh"
        if (Test-Path -LiteralPath $self) { $shell = $self }
    }
    if ([string]::IsNullOrWhiteSpace($shell)) {
        $script:LastSafeAbort = "SHELL_MISSING"
        Write-Host "REGISTER_ABORT=SHELL_MISSING"
        return 1
    }
    $previousErrorAction = $ErrorActionPreference
    $previousNative = $PSNativeCommandUseErrorActionPreference
    $ErrorActionPreference = "Continue"
    $PSNativeCommandUseErrorActionPreference = $false
    try {
        $child = & $shell -NoProfile -ExecutionPolicy Bypass -File $register -Register -RepoRoot $Root -RemoteBranch $Branch 2>&1
        $childCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorAction
        $PSNativeCommandUseErrorActionPreference = $previousNative
    }
    if ($null -ne $child) {
        $childLines = New-Object System.Collections.Generic.List[string]
        foreach ($item in @($child)) { [void]$childLines.Add([string]$item) }
        Write-Host (($childLines -join [Environment]::NewLine))
    }
    return $childCode
}

function New-SelfTestRepo {
    $base = Join-Path ([System.IO.Path]::GetTempPath()) ("safe-register-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $base | Out-Null
    $bare = Join-Path $base "remote.git"
    $work = Join-Path $base "work"
    & git init -q --bare $bare
    if ($LASTEXITCODE -ne 0) { throw "git init bare failed" }
    & git init -q $work
    if ($LASTEXITCODE -ne 0) { throw "git init work failed" }
    & git -C $work remote add origin $bare
    if ($LASTEXITCODE -ne 0) { throw "git remote add failed" }
    return [pscustomobject]@{ Base = $base; Bare = $bare; Work = $work }
}

function Add-SelfTestCommit([string]$Work, [string]$RelativePath, [string]$Content, [string]$Message) {
    $full = Join-Path $Work $RelativePath
    $parent = Split-Path -Parent $full
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    [System.IO.File]::WriteAllText($full, $Content)
    & git -C $Work add -- $RelativePath
    if ($LASTEXITCODE -ne 0) { throw "git add failed" }
    & git -C $Work -c user.email=sync-selftest@example.com -c user.name=sync-selftest -c commit.gpgsign=false commit -q -m $Message
    if ($LASTEXITCODE -ne 0) { throw "git commit failed" }
}

function Push-SelfTestBranch([string]$Work, [string]$Bare, [string]$Branch) {
    & git -C $Work push -q origin ("HEAD:refs/heads/" + $Branch)
    if ($LASTEXITCODE -ne 0) { throw "git push failed" }
    & git --git-dir $Bare symbolic-ref HEAD ("refs/heads/" + $Branch)
    if ($LASTEXITCODE -ne 0) { throw "git symbolic-ref failed" }
}

function Get-SelfTestHead([string]$Work) {
    $parsed = Invoke-SafeGit $Work @("rev-parse", "HEAD")
    if ($parsed.Code -ne 0) { throw "git rev-parse failed" }
    return $parsed.Text
}

function Remove-SelfTestRepo($Pair) {
    if ($null -eq $Pair) { return }
    Remove-Item -LiteralPath $Pair.Base -Recurse -Force -ErrorAction SilentlyContinue
}

function Get-RegisterStub {
    $lines = @(
        'param([string]$RepoRoot = "", [string]$RemoteBranch = "", [switch]$Register)',
        '$stamp = Join-Path $RepoRoot "register-called.txt"',
        '[System.IO.File]::WriteAllText($stamp, "called")',
        'Write-Host "TASK_ACTION=powershell.exe -File C:\repo\downloads\UPDATE_AND_SYNC_100OKU_MASTER_SPEC.ps1 -RepoRoot C:\repo"',
        'Write-Host "TASK_REGISTER=PASS"',
        'exit 0'
    )
    return ($lines -join [Environment]::NewLine)
}

function Assert-NotRegistered([string]$Work, [string]$ExpectedHead, [string]$Label) {
    $head = Get-SelfTestHead $Work
    if ($head -ne $ExpectedHead) { throw ($Label + " moved HEAD") }
    $stamp = Join-Path $Work "register-called.txt"
    if (Test-Path -LiteralPath $stamp) { throw ($Label + " called register") }
    Write-Host ("CASE=" + $Label)
    Write-Host "REGISTER_CALLED=0"
}

function Invoke-SafeRegisterSelfTest {
    $branch = "cursor/master-spec-fetch-sync-d483"
    $stub = Get-RegisterStub
    $pair = $null
    try {
        $pair = New-SelfTestRepo
        Add-SelfTestCommit $pair.Work "note.txt" "base" "base"
        Push-SelfTestBranch $pair.Work $pair.Bare $branch
        $base = Get-SelfTestHead $pair.Work
        Add-SelfTestCommit $pair.Work "downloads/REGISTER_100OKU_MASTER_SPEC_TASK.ps1" $stub "stub"
        Push-SelfTestBranch $pair.Work $pair.Bare $branch
        & git -C $pair.Work reset --hard $base
        if ($LASTEXITCODE -ne 0) { throw "reset failed" }
        [System.IO.File]::WriteAllText((Join-Path $pair.Work "extra.txt"), "dirty")
        $code = Invoke-SafeRegisterCheck $pair.Work $branch
        if ($code -eq 0 -or $script:LastSafeAbort -ne "WORKTREE_DIRTY") { throw "dirty case did not abort" }
        Assert-NotRegistered $pair.Work $base "DIRTY"
        Remove-SelfTestRepo $pair

        $pair = New-SelfTestRepo
        Add-SelfTestCommit $pair.Work "note.txt" "base" "base"
        Push-SelfTestBranch $pair.Work $pair.Bare $branch
        Add-SelfTestCommit $pair.Work "local.txt" "local" "local"
        $local = Get-SelfTestHead $pair.Work
        $code = Invoke-SafeRegisterCheck $pair.Work $branch
        if ($code -eq 0 -or $script:LastSafeAbort -ne "LOCAL_COMMITS_NOT_ON_REMOTE") { throw "local case did not abort" }
        Assert-NotRegistered $pair.Work $local "LOCAL_ONLY"
        Remove-SelfTestRepo $pair

        $pair = New-SelfTestRepo
        Add-SelfTestCommit $pair.Work "note.txt" "base" "base"
        Push-SelfTestBranch $pair.Work $pair.Bare $branch
        Add-SelfTestCommit $pair.Work "local.txt" "local" "local"
        $local = Get-SelfTestHead $pair.Work
        $other = Join-Path $pair.Base "other"
        & git clone -q -b $branch $pair.Bare $other
        if ($LASTEXITCODE -ne 0) { throw "clone failed" }
        Add-SelfTestCommit $other "remote.txt" "remote" "remote"
        Push-SelfTestBranch $other $pair.Bare $branch
        $code = Invoke-SafeRegisterCheck $pair.Work $branch
        if ($code -eq 0 -or $script:LastSafeAbort -ne "HISTORY_DIVERGED") { throw "diverged case did not abort" }
        Assert-NotRegistered $pair.Work $local "DIVERGED"
        Remove-SelfTestRepo $pair

        $pair = New-SelfTestRepo
        Add-SelfTestCommit $pair.Work "note.txt" "base" "base"
        Push-SelfTestBranch $pair.Work $pair.Bare $branch
        $base = Get-SelfTestHead $pair.Work
        & git -C $pair.Work remote set-url origin (Join-Path $pair.Base "missing.git")
        if ($LASTEXITCODE -ne 0) { throw "set-url failed" }
        $code = Invoke-SafeRegisterCheck $pair.Work $branch
        if ($code -eq 0 -or $script:LastSafeAbort -ne "FETCH_FAILED") { throw "fetch case did not abort" }
        Assert-NotRegistered $pair.Work $base "FETCH_FAILED"
        Remove-SelfTestRepo $pair

        $pair = New-SelfTestRepo
        Add-SelfTestCommit $pair.Work "note.txt" "base" "base"
        Push-SelfTestBranch $pair.Work $pair.Bare $branch
        $base = Get-SelfTestHead $pair.Work
        Add-SelfTestCommit $pair.Work "downloads/REGISTER_100OKU_MASTER_SPEC_TASK.ps1" $stub "stub"
        Push-SelfTestBranch $pair.Work $pair.Bare $branch
        $tip = Get-SelfTestHead $pair.Work
        & git -C $pair.Work reset --hard $base
        if ($LASTEXITCODE -ne 0) { throw "reset failed" }
        & git -C $pair.Work checkout -q --detach $base
        if ($LASTEXITCODE -ne 0) { throw "detach base failed" }
        $previousNative = $PSNativeCommandUseErrorActionPreference
        $PSNativeCommandUseErrorActionPreference = $true
        $noisy = Invoke-SafeGit $pair.Work @("-c", "advice.detachedHead=false", "checkout", "--detach", $tip)
        $PSNativeCommandUseErrorActionPreference = $previousNative
        if ($noisy.Code -ne 0) { throw "stderr was treated as failure" }
        if ($noisy.Text.Length -ne 0) { throw "stdout mixed with stderr" }
        if ($noisy.Stderr.IndexOf("Previous HEAD position was") -lt 0) { throw "stderr was not captured" }
        if ((Get-SelfTestHead $pair.Work) -ne $tip) { throw "noisy checkout did not move HEAD" }
        Write-Host "CASE=STDERR_OK"
        Write-Host "GIT_STDERR_CAPTURED=1"
        & git -C $pair.Work reset --hard $base
        if ($LASTEXITCODE -ne 0) { throw "reset after stderr case failed" }
        $code = Invoke-SafeRegisterCheck $pair.Work $branch
        if ($code -ne 0) { throw "fast-forward check failed" }
        $reg = Invoke-RegisterScript $pair.Work $branch
        if ($reg -ne 0) { throw "fast-forward register failed" }
        if ((Get-SelfTestHead $pair.Work) -ne $tip) { throw "fast-forward head mismatch" }
        if (-not (Test-Path -LiteralPath (Join-Path $pair.Work "register-called.txt"))) { throw "fast-forward did not call register" }
        Write-Host "CASE=FAST_FORWARD"
        Write-Host "REGISTER_CALLED=1"
        Remove-SelfTestRepo $pair

        $pair = New-SelfTestRepo
        Add-SelfTestCommit $pair.Work "note.txt" "base" "base"
        Add-SelfTestCommit $pair.Work "downloads/REGISTER_100OKU_MASTER_SPEC_TASK.ps1" $stub "stub"
        Push-SelfTestBranch $pair.Work $pair.Bare $branch
        $tip = Get-SelfTestHead $pair.Work
        $code = Invoke-SafeRegisterCheck $pair.Work $branch
        if ($code -ne 0) { throw "unchanged check failed" }
        $reg = Invoke-RegisterScript $pair.Work $branch
        if ($reg -ne 0) { throw "unchanged register failed" }
        if ((Get-SelfTestHead $pair.Work) -ne $tip) { throw "unchanged head mismatch" }
        if (-not (Test-Path -LiteralPath (Join-Path $pair.Work "register-called.txt"))) { throw "unchanged did not call register" }
        Write-Host "CASE=UNCHANGED"
        Write-Host "REGISTER_CALLED=1"
        Remove-SelfTestRepo $pair
        $pair = $null

        Write-Host "SAFE_REGISTER_SELFTEST=PASS"
        Write-Host "SELFTEST_WROTE_D_DRIVE=0"
    } catch {
        Write-Host "SAFE_REGISTER_SELFTEST=FAIL"
        Write-Host $_.Exception.Message
        exit 1
    } finally {
        Remove-SelfTestRepo $pair
    }
}

if ($SelfTest) {
    Invoke-SafeRegisterSelfTest
    exit 0
}

$root = Get-SafeRepoRoot
$check = Invoke-SafeRegisterCheck $root $RemoteBranch
if ($check -ne 0) { exit $check }
$registered = Invoke-RegisterScript $root $RemoteBranch
exit $registered
